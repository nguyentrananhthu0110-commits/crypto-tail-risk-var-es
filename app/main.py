"""FastAPI backend: REST cho chart/forecast/risk + static frontend.
- Giá realtime: trình duyệt kết nối thẳng Binance WebSocket công khai (data-stream.binance.vision).
- Backend REST: initial load, fallback khi WS mất, dữ liệu đã lưu & artifacts của model.
- Lỗi trả JSON thống nhất {detail:{code,message}}; không lộ stack trace.
"""
from __future__ import annotations
import sys, threading, time
from enum import Enum
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.config import CONFIG
from src.data.binance_client import BinanceClient, BinanceError
from src.data.pipeline import dataset_quality, load_dataset
from src.models.training import forecast_state, load_forecast, load_named, model_files_status, recompute_risk_for_position
from src.storage import get_datasets, get_last_jobs, get_models, utcnow_iso
from src.utils.logging_setup import get_logger

log = get_logger("cri.api")
app = FastAPI(title="Crypto Risk Intelligence", version="1.0.0", docs_url="/api/docs")
STATIC = Path(__file__).resolve().parent / "static"
client = BinanceClient()
_jobs: dict = {"prepare": {"running": False, "last": None}, "update": {"running": False, "last": None}, "retrain": {"running": False, "last": None}}
_lock = threading.Lock()

# Danh sách tài sản đọc từ config (không chỉ BTC/ETH) -> hiển thị trên bộ chọn & tìm kiếmCoin
SymbolEnum = Enum("SymbolEnum", {name: name for name in CONFIG["symbols"]}, type=str)
class IntervalEnum(str, Enum):
    m1 = "1m"; m5 = "5m"; m15 = "15m"; m30 = "30m"; h1 = "1h"; h4 = "4h"; d1 = "1d"

def err(status: int, code: str, message: str):
    return JSONResponse(status_code=status, content={"detail": {"code": code, "message": message}})

@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return err(422, "VALIDATION_ERROR", f"Tham số không hợp lệ: {exc.errors()[:2]}")

@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unhandled: %s", exc)
    return err(500, "INTERNAL_ERROR", "Đã xảy ra lỗi phía máy chủ. Xem logs/app.log để biết chi tiết.")

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "crypto-risk-intelligence", "server_time_utc": utcnow_iso()}

@app.get("/api/status")
def status(include_quality: bool = Query(False)):
    models = {}
    for s in CONFIG["symbols"]:
        state, f = forecast_state(s)
        files = model_files_status(s)
        if state == "corrupt":
            models[s] = {"status": "corrupted", "model_files": files,
                         "guidance": "Artifact dự báo không đọc được. Hãy huấn luyện lại (update_data.cmd --retrain) hoặc chạy lại prepare_data.cmd."}
        elif f:
            models[s] = {"status": "ready" if files["overall"] == "ok" else "ready_with_warnings",
                         "selected_model": f["selected_model"], "model_files": files,
                         "generated_at_utc": f["generated_at_utc"], "last_closed_day": f["last_closed_day"]}
        else:
            models[s] = {"status": "not_initialized", "model_files": files}
    out = {"server_time_utc": utcnow_iso(), "datasets": get_datasets(),
            "models": models, "saved_models": get_models(), "recent_jobs": get_last_jobs(8),
            "background_jobs": _jobs, "config": {"symbols": CONFIG["symbols"],
            "chart_intervals": CONFIG["chart_intervals"],
            "reference_position_usd": CONFIG["reference_position_usd"],
            "binance_ws_base": CONFIG["binance_ws_base"]}}
    if include_quality:  # chỉ tính khi tầng Advanced yêu cầu — tránh đọc Parquet trong polling
        out["data_quality"] = [dataset_quality(s, iv) for s in CONFIG["symbols"] for iv in ("1h", "1d")]
    return out

@app.get("/api/ticker")
def ticker(symbol: SymbolEnum = SymbolEnum.BTCUSDT):
    try:
        d = client.fetch_ticker_24h(symbol.value); d["stale"] = False; return d
    except BinanceError as e:
        df = load_dataset(symbol.value, "1h")
        if df is not None and not df.empty:
            last = df.iloc[-1]; prev = df.iloc[-25] if len(df) > 25 else df.iloc[0]
            return {"symbol": symbol.value, "price": float(last["close"]),
                    "change_pct_24h": float((last["close"]/prev["close"] - 1) * 100),
                    "high_24h": float(df.tail(24)["high"].max()), "low_24h": float(df.tail(24)["low"].min()),
                    "volume_24h": float(df.tail(24)["volume"].sum()), "quote_volume_24h": 0.0,
                    "open_24h": float(prev["close"]), "source": "local_dataset_fallback", "stale": True}
        return err(502, "UPSTREAM_UNAVAILABLE", f"Không lấy được ticker từ Binance ({e}). Kiểm tra kết nối mạng.")

@app.get("/api/ohlcv")
def ohlcv(symbol: SymbolEnum = SymbolEnum.BTCUSDT, interval: IntervalEnum = IntervalEnum.h1,
          limit: int = Query(500, ge=10, le=1000)):
    now_ms = int(time.time() * 1000)
    df, source, stale, upstream_msg = None, "binance_rest_recent", False, None
    try:
        df = client.fetch_recent(symbol.value, interval.value, limit, include_forming=True)
        if df is None or df.empty:
            upstream_msg = "Binance trả về rỗng"
    except BinanceError as e:
        upstream_msg = str(e)
    if upstream_msg is not None:  # upstream lỗi HOẶC rỗng -> fallback cục bộ, gắn cờ stale trung thực
        df = load_dataset(symbol.value, interval.value)
        if df is None or df.empty:
            return err(502, "UPSTREAM_UNAVAILABLE",
                       f"Không lấy được dữ liệu thị trường ({upstream_msg}) và chưa có dataset cục bộ cho {symbol.value} {interval.value}. Hãy thử lại, hoặc kiểm tra kết nối/dữ liệu đã lưu.")
        df = df.tail(limit); source, stale = "local_dataset_fallback", True
    from src.config import INTERVAL_MS
    step = INTERVAL_MS[interval.value]
    candles = [{"t": int(r.timestamp), "o": float(r.open), "h": float(r.high), "l": float(r.low),
                "c": float(r.close), "v": float(r.volume),
                "closed": bool(int(r.timestamp) + step - 1 < now_ms)} for r in df.itertuples()]
    return {"symbol": symbol.value, "interval": interval.value, "source": source, "stale": stale,
            "fetched_at_utc": utcnow_iso(), "candles": candles}

def _need_forecast(symbol: str):
    state, f = forecast_state(symbol)
    if state == "corrupt":
        return None, err(500, "MODEL_CORRUPTED",
                         f"Artifact mô hình của {symbol} không đọc được (có thể bị hỏng khi process bị tắt đột ngột). Hãy chạy update_data.cmd --retrain hoặc prepare_data.cmd để tạo lại có chủ đích.")
    if not f:
        return None, err(404, "MODEL_NOT_INITIALIZED",
                         f"Model cho {symbol} chưa được khởi tạo. Hãy chạy prepare_data.cmd (hoặc scripts/prepare_data.py).")
    return f, None

@app.get("/api/forecast")
def forecast(symbol: SymbolEnum = SymbolEnum.BTCUSDT,
             position_usd: float = Query(None, gt=0, le=1e12)):
    f, e = _need_forecast(symbol.value)
    if e: return e
    if position_usd and abs(position_usd - f["risk"]["reference_position_usd"]) > 1e-9:
        f = recompute_risk_for_position(f, position_usd)
    return f

@app.get("/api/performance")
def performance(symbol: SymbolEnum = SymbolEnum.BTCUSDT):
    d = load_named(symbol.value, "performance")
    return d if d else err(404, "MODEL_NOT_INITIALIZED", "Chưa có kết quả đánh giá. Hãy chạy prepare_data.cmd.")

@app.get("/api/backtest")
def backtest(symbol: SymbolEnum = SymbolEnum.BTCUSDT):
    d = load_named(symbol.value, "backtest")
    return d if d else err(404, "MODEL_NOT_INITIALIZED", "Chưa có kết quả backtest. Hãy chạy prepare_data.cmd.")

@app.get("/api/explain")
def explain(symbol: SymbolEnum = SymbolEnum.BTCUSDT):
    d = load_named(symbol.value, "explain")
    return d if d else err(404, "MODEL_NOT_INITIALIZED", "Chưa có thông tin giải thích mô hình.")

@app.get("/api/report")
def report(symbol: SymbolEnum = SymbolEnum.BTCUSDT):
    """PDF phan tich chuyen sau — tao dong tu artifacts da luu."""
    from src.report import build_pdf
    import tempfile
    tmp = Path(tempfile.gettempdir()) / f"CRI_Report_{symbol.value}.pdf"
    try:
        build_pdf(symbol.value, tmp)
    except FileNotFoundError as e:
        return err(404, "MODEL_NOT_INITIALIZED", str(e))
    except Exception as e:
        log.exception("Report build failed %s: %s", symbol.value, e)
        return err(500, "REPORT_ERROR", f"Khong tao duoc bao cao PDF: {e}")
    return FileResponse(str(tmp), media_type="application/pdf", filename=f"CRI_PhanTich_{symbol.value}.pdf")

def _run_job(kind: str, fn):
    with _lock:
        if _jobs[kind]["running"]:
            return False
        _jobs[kind] = {"running": True, "last": {"started_at_utc": utcnow_iso(), "status": "running"}}
    def target():
        try:
            fn(); _jobs[kind] = {"running": False, "last": {"finished_at_utc": utcnow_iso(), "status": "success"}}
        except Exception as exc:  # noqa: BLE001
            log.exception("Background %s failed", kind)
            _jobs[kind] = {"running": False, "last": {"finished_at_utc": utcnow_iso(), "status": "failed", "error": str(exc)}}
    threading.Thread(target=target, daemon=True).start()
    return True

def _prepare_all_symbols():
    """Nạp dữ liệu + huấn luyện toàn bộ ngay từ trình duyệt (không cần CMD/PowerShell)."""
    from src.data.pipeline import prepare_symbol_data
    from src.models.training import train_symbol
    for sym in CONFIG["symbols"]:
        try:
            log.info("Browser prepare: loading data for %s", sym)
            prepare_symbol_data(sym)
        except Exception as e:
            log.warning("Prepare %s failed (kept going): %s", sym, e)
    for sym in CONFIG["symbols"]:
        try:
            log.info("Browser prepare: training %s", sym)
            train_symbol(sym)
        except Exception as e:
            log.warning("Train %s failed (kept going): %s", sym, e)

@app.post("/api/admin/prepare")
def admin_prepare(symbol: SymbolEnum | None = None):
    """Nạp dữ liệu + huấn luyện. Nếu có symbol chỉ làm cho loại tiền đó, không thì toàn bộ danh sách config."""
    targets = [symbol.value] if symbol else list(CONFIG["symbols"])

    def job():
        from src.data.pipeline import prepare_symbol_data
        from src.models.training import train_symbol
        for s in targets:
            try:
                log.info("Browser prepare: loading data for %s", s)
                prepare_symbol_data(s)
            except Exception as e:
                log.warning("Prepare %s failed (kept going): %s", s, e)
        for s in targets:
            try:
                log.info("Browser prepare: training %s", s)
                train_symbol(s)
            except Exception as e:
                log.warning("Train %s failed (kept going): %s", s, e)

    ok = _run_job("prepare", job)
    label = symbol.value if symbol else ", ".join(targets)
    return {"accepted": ok,
            "message": f"Đang nạp dữ liệu và huấn luyện mô hình cho {label} ở nền. Bạn có thể tiếp tục xem biểu đồ trực tiếp." if ok else "Một tác vụ nạp dữ liệu đang chạy."}

@app.post("/api/admin/update")
def admin_update(symbol: SymbolEnum = SymbolEnum.BTCUSDT):
    from src.data.pipeline import prepare_symbol_data
    ok = _run_job("update", lambda: prepare_symbol_data(symbol.value))
    return {"accepted": ok, "message": "Đang cập nhật incremental..." if ok else "Một tác vụ cập nhật đang chạy."}

@app.post("/api/admin/retrain")
def admin_retrain(symbol: SymbolEnum = SymbolEnum.BTCUSDT):
    from src.models.training import train_symbol
    ok = _run_job("retrain", lambda: train_symbol(symbol.value))
    return {"accepted": ok, "message": "Đang huấn luyện lại ở nền..." if ok else "Tác vụ huấn luyện đang chạy."}

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")

app.mount("/static", StaticFiles(directory=STATIC), name="static")
