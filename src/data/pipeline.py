"""Data pipeline: first-time setup / incremental update / normal launch đều đi qua đây.

- First-time: tải đủ lịch sử cấu hình.
- Incremental: chỉ tải từ checkpoint (nến đã đóng cuối cùng) + 1 interval.
- Cập nhật thất bại -> file cũ còn nguyên (atomic write), manifest không đổi.
"""
from __future__ import annotations
import time
import pandas as pd
from src.config import CONFIG, INTERVAL_MS, dataset_path
from src.data.binance_client import BinanceClient
from src.data.validation import clean_candles, validate_candles
from src.storage import atomic_write_parquet, log_job, parquet_state, read_parquet, upsert_dataset, utcnow_iso
from src.utils.logging_setup import get_logger

log = get_logger("cri.pipeline")
_client = BinanceClient()

def load_dataset(symbol: str, interval: str) -> pd.DataFrame | None:
    return read_parquet(dataset_path(symbol, interval))

def dataset_quality(symbol: str, interval: str) -> dict:
    """Báo cáo chất lượng dataset đã lưu cho tầng Advanced. Phân biệt missing/corrupt/ok."""
    state, df = parquet_state(dataset_path(symbol, interval))
    base = {"symbol": symbol.upper(), "interval": interval, "file_state": state}
    if state != "ok" or df is None or df.empty:
        return {**base, "ok": False, "rows": 0,
                "note": ("Chưa có file dataset" if state == "missing"
                         else "File dataset không đọc được (hỏng). Hãy chạy prepare_data.cmd --full để tải lại có chủ đích."
                         if state == "corrupt" else "Dataset rỗng")}
    rep = validate_candles(df, interval)
    stale_days = round(max(0.0, (time.time() * 1000 - rep["end_ms"]) / 86_400_000), 1)
    stale_listing = stale_days > 7.0
    return {**base, **rep, "ok": bool(rep["ok"] and not stale_listing),
            "stale_days": stale_days, "stale_listing": stale_listing,
            "stale_note": (f"Cảnh báo: nến mới nhất đã cũ {stale_days} ngày (có thể cặp đã ngừng giao dịch trên sàn)."
                           if stale_listing else None),
            "start_utc": pd.to_datetime(rep["start_ms"], unit="ms", utc=True).isoformat(),
            "end_utc": pd.to_datetime(rep["end_ms"], unit="ms", utc=True).isoformat(),
            "gaps": rep["gaps"][:10]}

def _save(symbol, interval, df, source="binance_public_rest"):
    df = clean_candles(df)
    rep = validate_candles(df, interval)
    atomic_write_parquet(df, dataset_path(symbol, interval))
    upsert_dataset(symbol, interval, source, rep["start_ms"], rep["end_ms"], rep["rows"],
                   CONFIG["feature_version"], CONFIG["model_version"],
                   status="ready" if rep["ok"] else "ready_with_warnings")
    return rep

def download_or_update(symbol: str, interval: str, history_days: int, force_full: bool = False) -> dict:
    symbol = symbol.upper(); started = utcnow_iso(); step = INTERVAL_MS[interval]
    now_ms = int(time.time() * 1000)
    existing = None if force_full else load_dataset(symbol, interval)
    try:
        if existing is not None and not existing.empty:
            checkpoint = int(existing["timestamp"].max())
            start = checkpoint + step
            if start >= now_ms - step:  # đã cập nhật tới nến đóng gần nhất
                rep = validate_candles(existing, interval)
                log.info("%s %s: đã mới nhất (checkpoint %s)", symbol, interval, checkpoint)
                return {"symbol": symbol, "interval": interval, "mode": "no_new_data",
                        "rows": rep["rows"], "new_rows": 0, "validation": rep}
            log.info("%s %s: incremental từ %s (đã có %d nến)", symbol, interval, start, len(existing))
            new = _client.fetch_klines(symbol, interval, start, now_ms)
            merged = clean_candles(pd.concat([existing, new], ignore_index=True)) if not new.empty else existing
            rep = _save(symbol, interval, merged)
            # Nếu phát hiện gap: thử nạp lại đúng vùng thiếu một lần (không backfill tương lai)
            if rep["gap_count"] > 0:
                log.warning("%s %s: %d gap, thử nạp lại vùng thiếu", symbol, interval, rep["gap_count"])
                fill = _client.fetch_klines(symbol, interval, rep["gaps"][0], rep["gaps"][-1] + step)
                if not fill.empty:
                    merged = clean_candles(pd.concat([merged, fill], ignore_index=True))
                    rep = _save(symbol, interval, merged)
            res = {"symbol": symbol, "interval": interval, "mode": "incremental",
                   "rows": rep["rows"], "new_rows": int(len(merged) - len(existing)), "validation": rep}
        else:
            start = now_ms - history_days * 86_400_000
            log.info("%s %s: tải ban đầu %d ngày", symbol, interval, history_days)
            df = _client.fetch_klines(symbol, interval, start, now_ms)
            if df.empty:
                raise RuntimeError("Binance trả về rỗng")
            rep = _save(symbol, interval, df)
            res = {"symbol": symbol, "interval": interval, "mode": "initial",
                   "rows": rep["rows"], "new_rows": rep["rows"], "validation": rep}
        log_job("download", symbol, "success", str(res), started)
        log.info("%s %s: xong - %s", symbol, interval, res)
        return res
    except Exception as e:
        log_job("download", symbol, "failed", str(e), started)
        log.error("%s %s: thất bại, giữ nguyên dữ liệu cũ. %s", symbol, interval, e)
        raise

def prepare_symbol_data(symbol: str, force_full: bool = False) -> list[dict]:
    out = []
    out.append(download_or_update(symbol, "1h", CONFIG["history_days_hourly"], force_full))
    out.append(download_or_update(symbol, "1d", CONFIG["history_days_daily"], force_full))
    return out


def purge_symbol_artifacts(symbol: str) -> dict:
    """Xóa toàn bộ file dữ liệu, mô hình, manifest SQLite và dòng backtest của mã bị sàn xóa/hủy giao dịch."""
    from src.config import FEATURES_DIR, MODEL_META_DIR, PROCESSED_DIR, PROJECT_ROOT, RAW_DIR, SAVED_DIR
    from src.storage import delete_symbol_records
    sym = symbol.strip().upper()
    removed_files: list[str] = []
    for folder in (RAW_DIR, PROCESSED_DIR, FEATURES_DIR, SAVED_DIR, MODEL_META_DIR):
        if not folder.exists():
            continue
        for p in folder.glob(f"{sym}_*"):
            if p.is_file():
                p.unlink()
                removed_files.append(str(p.relative_to(PROJECT_ROOT)))
    reports_dir = PROJECT_ROOT / "outputs" / "reports"
    if reports_dir.exists():
        for p in reports_dir.glob(f"*{sym}*.pdf"):
            if p.is_file():
                p.unlink()
                removed_files.append(str(p.relative_to(PROJECT_ROOT)))
    delete_symbol_records(sym)
    try:
        from src.backtest.run_backtest import remove_symbols_from_backtest_tables
        remove_symbols_from_backtest_tables([sym])
    except Exception as e:
        log.warning("Không dọn được bảng backtest cho %s: %s", sym, e)
    log.info("Đã xóa sạch coin ngừng giao dịch %s (%d files)", sym, len(removed_files))
    return {"symbol": sym, "removed_files": removed_files}


def _discover_stored_symbols() -> set[str]:
    """Tìm mọi mã <SYM>USDT đang có file dữ liệu/mô hình hoặc bản ghi SQLite trên đĩa."""
    from src.config import FEATURES_DIR, MODEL_META_DIR, PROCESSED_DIR, RAW_DIR, SAVED_DIR
    from src.storage import get_datasets, get_models
    found: set[str] = set()
    for folder in (RAW_DIR, PROCESSED_DIR, FEATURES_DIR, SAVED_DIR, MODEL_META_DIR):
        if not folder.exists():
            continue
        for p in folder.iterdir():
            if not p.is_file() or "_" not in p.name:
                continue
            prefix = p.name.split("_", 1)[0].upper()
            if prefix.endswith("USDT"):
                found.add(prefix)
    for row in get_datasets():
        if row.get("symbol"):
            found.add(str(row["symbol"]).upper())
    for row in get_models():
        if row.get("symbol"):
            found.add(str(row["symbol"]).upper())
    return found


def sync_active_symbols(
    check_exchange: bool = True,
    persist_config: bool = True,
    client: BinanceClient | None = None,
) -> dict:
    """Đồng bộ danh sách coin theo trạng thái giao dịch thực tế trên Binance Spot tại thời điểm chạy:
    - Nếu sàn hủy niêm yết / ngừng giao dịch (status != 'TRADING'), tự động xóa mã đó khỏi config.json
      và dọn sạch toàn bộ dữ liệu, model, SQLite, bảng backtest & hình ảnh liên quan.
    - Nếu mất mạng tạm thời (offline), giữ nguyên danh sách hiện có (không xóa nhầm) nhưng vẫn dọn các file mồ côi
      không nằm trong config.json.
    """
    from src.config import save_symbols
    from src.data.binance_client import BinanceError

    cli = client or _client
    current_cfg = [s.upper() for s in CONFIG["symbols"]]
    delisted: list[str] = []
    exchange_checked = False

    if check_exchange:
        try:
            active_on_exchange = cli.fetch_active_spot_symbols()
            if len(active_on_exchange) >= 50:  # đảm bảo phản hồi hợp lệ, không rỗng bất thường
                exchange_checked = True
                delisted = [s for s in current_cfg if s not in active_on_exchange]
                if delisted:
                    kept = [s for s in current_cfg if s in active_on_exchange]
                    if kept:
                        if persist_config:
                            save_symbols(kept)
                        else:
                            CONFIG["symbols"][:] = kept
                        current_cfg = list(CONFIG["symbols"])
                    log.warning("Phát hiện %d coin đã bị xóa/ngừng giao dịch trên Binance Spot -> xóa khỏi hệ thống: %s",
                                len(delisted), ", ".join(delisted))
        except (BinanceError, Exception) as e:
            log.warning("Không kiểm tra được exchangeInfo từ Binance (giữ nguyên danh sách hiện tại): %s", e)

    cfg_set = set(current_cfg)
    stored = _discover_stored_symbols()
    orphans = sorted(s for s in stored if s not in cfg_set and s not in set(delisted))

    for sym in sorted(set(delisted) | set(orphans)):
        purge_symbol_artifacts(sym)

    return {
        "exchange_checked": exchange_checked,
        "active": list(CONFIG["symbols"]),
        "removed_delisted": sorted(delisted),
        "removed_orphans": orphans,
    }
