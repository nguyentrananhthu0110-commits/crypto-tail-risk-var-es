"""A. Data: liên tục, duplicate, gaps, OHLC, resample đúng ranh giới, leakage features."""
import numpy as np
import pandas as pd
from src.data.validation import clean_candles, resample_ohlcv, validate_candles
from src.features.build import build_daily, build_features


def test_validate_ok_continuous(hourly_candles):
    rep = validate_candles(hourly_candles, "1h")
    assert rep["ok"] and rep["gap_count"] == 0 and rep["rows"] == 72


def test_validate_detects_gap_duplicate_and_ohlc_violation(hourly_candles):
    df = hourly_candles.drop(index=5)                      # tạo 1 gap
    df = pd.concat([df, df.iloc[[10]]], ignore_index=True)  # duplicate
    df.loc[20, "high"] = df.loc[20, "low"] - 1              # high < low
    rep = validate_candles(df, "1h")
    assert rep["gap_count"] == 1 and rep["duplicates"] == 1 and rep["ohlc_violations"] >= 1
    assert rep["ok"] is False


def test_clean_dedupes_and_sorts(hourly_candles):
    df = pd.concat([hourly_candles.iloc[::-1], hourly_candles.iloc[[0]]], ignore_index=True)
    out = clean_candles(df)
    assert len(out) == 72 and out["timestamp"].is_monotonic_increasing


def test_resample_1h_to_4h_aggregation_rules(hourly_candles):
    out = resample_ohlcv(hourly_candles, "4h")
    assert len(out) == 18
    first4 = hourly_candles.iloc[:4]
    row = out.iloc[0]
    assert row["open"] == first4["open"].iloc[0]
    assert row["close"] == first4["close"].iloc[-1]
    assert row["high"] == first4["high"].max()
    assert row["low"] == first4["low"].min()
    assert np.isclose(row["volume"], first4["volume"].sum())
    assert row["timestamp"] % (4 * 3_600_000) == 0  # ranh giới UTC


def test_build_daily_rv_and_closed_days(hourly_candles):
    daily = build_daily(hourly_candles)
    assert len(daily) == 3 and (daily["n_hours"] >= 23).all()
    assert (daily["rv"].dropna() >= 0).all()
    assert np.allclose(daily["realized_vol"].dropna(), np.sqrt(daily["rv"].dropna()))


def test_feature_leakage_target_is_next_day(daily_series):
    d = daily_series.copy()
    d["log_return"] = np.log(d["close"] / d["close"].shift(1))
    d["simple_return"] = d["close"] / d["close"].shift(1) - 1
    f = build_features(d, None)
    ok = f.dropna(subset=["target_rv"])
    # target luôn là RV của ngày kế tiếp, không phải cùng ngày
    assert (pd.to_datetime(ok["target_date"]) > pd.to_datetime(ok["date"])).all()
    idx = ok.index[30]
    assert np.isclose(f.loc[idx, "target_rv"], f.loc[idx + 1, "rv"])
    assert np.isclose(f.loc[idx, "rv_lag1"], f.loc[idx, "rv"])  # feature chỉ dùng thông tin <= t
