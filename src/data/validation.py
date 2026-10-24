"""Kiểm định chất lượng nến OHLCV và tổng hợp timeframe đúng ranh giới thời gian UTC."""
from __future__ import annotations
import numpy as np
import pandas as pd
from src.config import INTERVAL_MS

def validate_candles(df: pd.DataFrame, interval: str) -> dict:
    """Trả báo cáo chất lượng; không tự ý sửa dữ liệu."""
    rep = {"rows": int(len(df)), "duplicates": 0, "gaps": [], "gap_count": 0,
           "ohlc_violations": 0, "non_positive_prices": 0, "negative_volume": 0, "ok": True}
    if df.empty:
        rep["ok"] = False; return rep
    rep["duplicates"] = int(df.duplicated(subset=["timestamp"]).sum())
    rep["non_positive_prices"] = int((df[["open","high","low","close"]] <= 0).any(axis=1).sum())
    rep["negative_volume"] = int((df["volume"] < 0).sum())
    tol = 1e-9
    bad = (df["high"] + tol < df[["open","close"]].max(axis=1)) | (df["low"] - tol > df[["open","close"]].min(axis=1)) \
          | (df["high"] + tol < df["low"])
    rep["ohlc_violations"] = int(bad.sum())
    step = INTERVAL_MS[interval]
    ts = np.sort(df["timestamp"].to_numpy())
    expected = np.arange(ts[0], ts[-1] + step, step)
    missing = np.setdiff1d(expected, ts)
    rep["gap_count"] = int(len(missing))
    if len(missing):
        rep["gaps"] = [int(x) for x in missing[:50]]
    rep["ok"] = (rep["duplicates"] == 0 and rep["ohlc_violations"] == 0
                 and rep["non_positive_prices"] == 0 and rep["negative_volume"] == 0)
    rep["start_ms"], rep["end_ms"] = int(ts[0]), int(ts[-1])
    return rep

def clean_candles(df: pd.DataFrame) -> pd.DataFrame:
    """Chỉ khử trùng lặp & sắp xếp; giữ hàng vi phạm để validation báo cáo (không âm thầm sửa)."""
    if df.empty: return df
    return (df.drop_duplicates(subset=["timestamp"], keep="last")
              .sort_values("timestamp").reset_index(drop=True))

def resample_ohlcv(df: pd.DataFrame, target_interval: str) -> pd.DataFrame:
    """Tổng hợp nến nhỏ -> nến lớn theo ranh giới UTC: open=first, high=max, low=min,
    close=last, volume=sum. Không bao giờ chỉ đổi nhãn timeframe."""
    if df.empty: return df.copy()
    step = INTERVAL_MS[target_interval]
    d = df.copy()
    d["bucket"] = (d["timestamp"] // step) * step
    agg = (d.groupby("bucket")
             .agg(open=("open","first"), high=("high","max"), low=("low","min"),
                  close=("close","last"), volume=("volume","sum"),
                  quote_volume=("quote_volume","sum") if "quote_volume" in d else ("volume","sum"),
                  trades=("trades","sum") if "trades" in d else ("volume","size"))
             .reset_index().rename(columns={"bucket":"timestamp"}))
    agg["close_time"] = agg["timestamp"] + step - 1
    return agg.sort_values("timestamp").reset_index(drop=True)
