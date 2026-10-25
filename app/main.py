"""FastAPI backend: REST cho chart/forecast/risk + static frontend.
- Giá realtime: trình duyệt kết nối thẳng Binance WebSocket công khai (data-stream.binance.vision).
- Backend REST: initial load, fallback khi WS mất, dữ liệu đã lưu & artifacts của model.
- Lỗi trả JSON thống nhất {detail:{code,message}}; không lộ stack trace.
"""
from __future__ import annotations
import math, sys, threading, time
from enum import Enum
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from fastapi import Depends, FastAPI, Query, Request
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

class IntervalEnum(str, Enum):
    m1 = "1m"; m5 = "5m"; m15 = "15m"; m30 = "30m"; h1 = "1h"; h4 = "4h"; d1 = "1d"

def _valid_symbol(symbol: str = Query("BTCUSDT")) -> str:
    """Kiểm tra symbol trực tiếp trên CONFIG['symbols'] hiện hành (tự động loại các mã đã bị sàn xóa)."""
    sym = str(symbol).strip().upper()
    if sym not in CONFIG["symbols"]:
        raise RequestValidationError([{
            "loc": ("query", "symbol"),
            "msg": f"Mã '{symbol}' không nằm trong danh sách còn giao dịch trên sàn.",
            "type": "value_error",
        }])
    return sym

def _optional_valid_symbol(symbol: str | None = Query(None)) -> str | None:
    if symbol is None:
        return None
    return _valid_symbol(symbol)

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
def ticker(symbol: str = Depends(_valid_symbol)):
    try:
        d = client.fetch_ticker_24h(symbol); d["stale"] = False; return d
    except BinanceError as e:
        df = load_dataset(symbol, "1h")
        if df is not None and not df.empty:
            last = df.iloc[-1]; prev = df.iloc[-25] if len(df) > 25 else df.iloc[0]
            return {"symbol": symbol, "price": float(last["close"]),
                    "change_pct_24h": float((last["close"]/prev["close"] - 1) * 100),
                    "high_24h": float(df.tail(24)["high"].max()), "low_24h": float(df.tail(24)["low"].min()),
                    "volume_24h": float(df.tail(24)["volume"].sum()), "quote_volume_24h": 0.0,
                    "open_24h": float(prev["close"]), "source": "local_dataset_fallback", "stale": True}
        return err(502, "UPSTREAM_UNAVAILABLE", f"Không lấy được ticker từ Binance ({e}). Kiểm tra kết nối mạng.")

@app.get("/api/ohlcv")
def ohlcv(symbol: str = Depends(_valid_symbol), interval: IntervalEnum = IntervalEnum.h1,
          limit: int = Query(500, ge=10, le=1000)):
    now_ms = int(time.time() * 1000)
    df, source, stale, upstream_msg = None, "binance_rest_recent", False, None
    try:
        df = client.fetch_recent(symbol, interval.value, limit, include_forming=True)
        if df is None or df.empty:
            upstream_msg = "Binance trả về rỗng"
    except BinanceError as e:
        upstream_msg = str(e)
    if upstream_msg is not None:  # upstream lỗi HOẶC rỗng -> fallback cục bộ, gắn cờ stale trung thực
        df = load_dataset(symbol, interval.value)
        if df is None or df.empty:
            return err(502, "UPSTREAM_UNAVAILABLE",
                       f"Không lấy được dữ liệu thị trường ({upstream_msg}) và chưa có dataset cục bộ cho {symbol} {interval.value}. Hãy thử lại, hoặc kiểm tra kết nối/dữ liệu đã lưu.")
        df = df.tail(limit); source, stale = "local_dataset_fallback", True
    from src.config import INTERVAL_MS
    step = INTERVAL_MS[interval.value]
    candles = [{"t": int(r.timestamp), "o": float(r.open), "h": float(r.high), "l": float(r.low),
                "c": float(r.close), "v": float(r.volume),
                "closed": bool(int(r.timestamp) + step - 1 < now_ms)} for r in df.itertuples()]
    return {"symbol": symbol, "interval": interval.value, "source": source, "stale": stale,
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
def forecast(symbol: str = Depends(_valid_symbol),
             position_usd: float = Query(None, gt=0, le=1e12)):
    f, e = _need_forecast(symbol)
    if e: return e
    if position_usd and abs(position_usd - f["risk"]["reference_position_usd"]) > 1e-9:
        f = recompute_risk_for_position(f, position_usd)
    return f

@app.get("/api/performance")
def performance(symbol: str = Depends(_valid_symbol)):
    d = load_named(symbol, "performance")
    return d if d else err(404, "MODEL_NOT_INITIALIZED", "Chưa có kết quả đánh giá. Hãy chạy prepare_data.cmd.")

@app.get("/api/backtest")
def backtest(symbol: str = Depends(_valid_symbol)):
    d = load_named(symbol, "backtest")
    return d if d else err(404, "MODEL_NOT_INITIALIZED", "Chưa có kết quả backtest. Hãy chạy prepare_data.cmd.")

_TABLES = Path(__file__).resolve().parents[1] / "outputs" / "tables"

def _read_table(name: str, symbol: str):
    """Đọc bảng backtest mở rộng theo symbol; NaN -> None (JSON hợp lệ). Trả None nếu chưa có file/symbol."""
    path = _TABLES / name
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return None
    key = symbol.replace("USDT", "") if "symbol" in df.columns and symbol not in set(df["symbol"]) else symbol
    df = df[df["symbol"] == key] if "symbol" in df.columns else df
    if df.empty:
        return None
    rows = df.to_dict(orient="records")
    return [{k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k, v in r.items()} for r in rows]

@app.get("/api/backtest-extended")
def backtest_extended(symbol: str = Depends(_valid_symbol)):
    """Backtest mở rộng (src/backtest/run_backtest.py): Kupiec/Christoffersen/Basel/ES-Z2/DM, ν chỉ từ train."""
    out = {"symbol": symbol,
           "test_window": _read_table("backtest_summary.csv", symbol),
           "test_window_dm": _read_table("backtest_dm_pinball.csv", symbol),
           "nu": _read_table("backtest_nu.csv", symbol),
           "long": _read_table("backtest_long_summary.csv", symbol),
           "long_dm": _read_table("backtest_long_dm_pinball.csv", symbol)}
    if not out["test_window"] and not out["long"]:
        return err(404, "BACKTEST_EXTENDED_NOT_FOUND",
                   "Chưa có bảng backtest mở rộng cho mã này. Chạy: python -m src.backtest.run_backtest")
    return out

@app.get("/api/explain")
def explain(symbol: str = Depends(_valid_symbol)):
    d = load_named(symbol, "explain")
    return d if d else err(404, "MODEL_NOT_INITIALIZED", "Chưa có thông tin giải thích mô hình.")

@app.get("/api/report")
def report(symbol: str = Depends(_valid_symbol)):
    """PDF phan tich chuyen sau — tao dong tu artifacts da luu."""
    from src.report import build_pdf
    import tempfile
    tmp = Path(tempfile.gettempdir()) / f"CRI_Report_{symbol}.pdf"
    try:
        build_pdf(symbol, tmp)
    except FileNotFoundError as e:
        return err(404, "MODEL_NOT_INITIALIZED", str(e))
    except Exception as e:
        log.exception("Report build failed %s: %s", symbol, e)
        return err(500, "REPORT_ERROR", f"Khong tao duoc bao cao PDF: {e}")
    return FileResponse(str(tmp), media_type="application/pdf", filename=f"CRI_PhanTich_{symbol}.pdf")

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
    from src.data.pipeline import prepare_symbol_data, sync_active_symbols
    from src.models.training import train_symbol
    sync_active_symbols(check_exchange=True, persist_config=True)
    for sym in list(CONFIG["symbols"]):
        try:
            log.info("Browser prepare: loading data for %s", sym)
            prepare_symbol_data(sym)
        except Exception as e:
            log.warning("Prepare %s failed (kept going): %s", sym, e)
    for sym in list(CONFIG["symbols"]):
        try:
            log.info("Browser prepare: training %s", sym)
            train_symbol(sym)
        except Exception as e:
            log.warning("Train %s failed (kept going): %s", sym, e)

@app.post("/api/admin/prepare")
def admin_prepare(symbol: str | None = Depends(_optional_valid_symbol)):
    """Nạp dữ liệu + huấn luyện. Nếu có symbol chỉ làm cho loại tiền đó, không thì toàn bộ danh sách config."""
    requested = [symbol] if symbol else list(CONFIG["symbols"])

    def job():
        from src.data.pipeline import prepare_symbol_data, sync_active_symbols
        from src.models.training import train_symbol
        sync_active_symbols(check_exchange=True, persist_config=True)
        active_set = set(CONFIG["symbols"])
        targets = [s for s in requested if s in active_set] if symbol else list(CONFIG["symbols"])
        if not targets:
            log.warning("Browser prepare: mã %s đã ngừng giao dịch trên sàn và được xóa khỏi hệ thống.", requested)
            return
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
        try:
            from src.backtest.run_backtest import refresh_extended_backtest
            refresh_extended_backtest(symbols=targets, nsim_short=5000, nsim_long=4000, plot=True, force_long=False)
        except Exception as e:
            log.warning("Extended backtest refresh failed: %s", e)

    ok = _run_job("prepare", job)
    label = symbol if symbol else ", ".join(requested)
    return {"accepted": ok,
            "message": f"Đang nạp dữ liệu và huấn luyện mô hình cho {label} ở nền. Bạn có thể tiếp tục xem biểu đồ trực tiếp." if ok else "Một tác vụ nạp dữ liệu đang chạy."}

@app.post("/api/admin/update")
def admin_update(symbol: str = Depends(_valid_symbol)):
    from src.data.pipeline import prepare_symbol_data, sync_active_symbols
    from src.models.training import train_symbol
    def _update_job():
        sym = symbol
        sync_active_symbols(check_exchange=True, persist_config=True)
        if sym not in CONFIG["symbols"]:
            log.warning("Browser update: mã %s đã ngừng giao dịch trên sàn và được xóa khỏi hệ thống.", sym)
            return
        results = prepare_symbol_data(sym)
        new_daily = next((r["new_rows"] for r in results if r["interval"] == "1d"), 0)
        fc = load_forecast(sym)
        retrained = False
        if fc is None or new_daily >= CONFIG["retrain_min_new_days"]:
            train_symbol(sym)
            retrained = True
        try:
            from src.backtest.run_backtest import run_long, run_main
            if retrained:
                run_main(nsim=5000, plot=True, symbols=[sym])
            run_long(csv_path=None, window=1000, refit=20, nsim=4000,
                     include_parquet=True, symbols=[sym], only_if_stale=True)
        except Exception as e:
            log.warning("Extended backtest incremental refresh failed for %s: %s", sym, e)
    ok = _run_job("update", _update_job)
    return {"accepted": ok, "message": "Đang cập nhật dữ liệu & kiểm định theo ngày mới nhất..." if ok else "Một tác vụ cập nhật đang chạy."}

@app.post("/api/admin/retrain")
def admin_retrain(symbol: str = Depends(_valid_symbol)):
    from src.models.training import train_symbol
    def _retrain_and_bt():
        sym = symbol
        train_symbol(sym)
        try:
            from src.backtest.run_backtest import refresh_extended_backtest
            refresh_extended_backtest(symbols=[sym], nsim_short=5000, nsim_long=4000, plot=True, force_long=False)
        except Exception as e:
            log.warning("Extended backtest refresh failed: %s", e)
    ok = _run_job("retrain", _retrain_and_bt)
    return {"accepted": ok, "message": "Đang huấn luyện lại ở nền..." if ok else "Tác vụ huấn luyện đang chạy."}

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """Serve the CRI brand icon for browsers that request /favicon.ico directly."""
    ico = STATIC / "icons" / "favicon.ico"
    if ico.exists():
        return FileResponse(ico, media_type="image/x-icon")
    return FileResponse(STATIC / "icons" / "favicon-32.png", media_type="image/png")

app.mount("/static", StaticFiles(directory=STATIC), name="static")
