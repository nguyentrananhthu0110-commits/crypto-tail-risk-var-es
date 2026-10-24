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
    return {**base, **rep,
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
