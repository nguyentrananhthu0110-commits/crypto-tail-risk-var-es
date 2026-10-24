"""Feature engineering ở tần suất NGÀY (UTC) từ nến 1h đã đóng.

Realized variance ngày t: RV_t = Σ (log-return 1h trong ngày t)^2.
Mọi feature tại ngày t chỉ dùng thông tin <= t; target là RV_{t+1} (không rò rỉ tương lai).
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from src.config import FEATURES_DIR, PROCESSED_DIR
from src.storage import atomic_write_parquet

FEATURE_SCHEMA = {
    "rv_lag1": "RV ngày t (phương sai thực hiện)", "rv_lag2": "RV ngày t-1", "rv_lag3": "RV ngày t-2",
    "rv_w": "Trung bình RV 5 ngày tới t (HAR weekly)", "rv_m": "Trung bình RV 22 ngày tới t (HAR monthly)",
    "ret_lag1": "Log-return ngày t", "abs_ret_lag1": "|log-return ngày t|",
    "ret_sq_lag1": "Bình phương log-return ngày t", "range_lag1": "log(High/Low) ngày t",
    "log_volume_lag1": "log(1+volume ngày t)", "volume_chg_lag1": "Thay đổi log volume ngày t",
    "cross_rv_lag1": "RV ngày t của tài sản còn lại (BTC<->ETH)",
}
FEATURE_COLS = list(FEATURE_SCHEMA.keys())

def build_daily(hourly: pd.DataFrame) -> pd.DataFrame:
    d = hourly.copy()
    d["dt"] = pd.to_datetime(d["timestamp"], unit="ms", utc=True)
    d = d.sort_values("dt")
    d["log_ret_h"] = np.log(d["close"] / d["close"].shift(1))
    d["date"] = d["dt"].dt.floor("D")
    def _rv(g):
        r = g["log_ret_h"].dropna()
        return float(np.sum(r ** 2)) if len(r) >= 12 else np.nan  # ngày cần đủ giờ mới tính RV
    daily = d.groupby("date").apply(lambda g: pd.Series({
        "open": g["open"].iloc[0], "high": g["high"].max(), "low": g["low"].min(),
        "close": g["close"].iloc[-1], "volume": g["volume"].sum(),
        "quote_volume": g["quote_volume"].sum(), "n_hours": len(g), "rv": _rv(g),
    }), include_groups=False).reset_index()
    # Chỉ giữ ngày đã đóng đủ 24 giờ (tránh ngày đang hình thành lọt vào training)
    daily = daily[daily["n_hours"] >= 23].reset_index(drop=True)
    daily["log_return"] = np.log(daily["close"] / daily["close"].shift(1))
    daily["simple_return"] = daily["close"] / daily["close"].shift(1) - 1.0
    daily["realized_vol"] = np.sqrt(daily["rv"])  # độ lệch chuẩn ngày, dạng thập phân
    return daily

def build_features(daily_self: pd.DataFrame, daily_other: pd.DataFrame | None) -> pd.DataFrame:
    f = daily_self.copy()
    f["rv_lag1"], f["rv_lag2"], f["rv_lag3"] = f["rv"], f["rv"].shift(1), f["rv"].shift(2)
    f["rv_w"] = f["rv"].rolling(5).mean()
    f["rv_m"] = f["rv"].rolling(22).mean()
    f["ret_lag1"] = f["log_return"]; f["abs_ret_lag1"] = f["log_return"].abs()
    f["ret_sq_lag1"] = f["log_return"] ** 2
    f["range_lag1"] = np.log(f["high"] / f["low"])
    f["log_volume_lag1"] = np.log1p(f["volume"])
    f["volume_chg_lag1"] = f["log_volume_lag1"].diff()
    if daily_other is not None:
        other = daily_other[["date", "rv"]].rename(columns={"rv": "cross_rv_lag1"})
        f = f.merge(other, on="date", how="left")
    else:
        f["cross_rv_lag1"] = f["rv_lag1"]
    f["cross_rv_lag1"] = f["cross_rv_lag1"].fillna(f["rv_lag1"])
    f["target_rv"] = f["rv"].shift(-1)          # RV ngày t+1
    f["target_vol"] = np.sqrt(f["target_rv"])
    f["target_date"] = f["date"].shift(-1)
    return f

def compute_and_save(symbol: str, hourly_self, hourly_other) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily = build_daily(hourly_self)
    other_daily = build_daily(hourly_other) if hourly_other is not None and not hourly_other.empty else None
    feats = build_features(daily, other_daily)
    atomic_write_parquet(daily, PROCESSED_DIR / f"{symbol}_daily.parquet")
    atomic_write_parquet(feats, FEATURES_DIR / f"{symbol}_features.parquet")
    return daily, feats
