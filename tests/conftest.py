import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import pytest

@pytest.fixture
def hourly_candles():
    """3 ngày nến 1h hợp lệ, timestamp UTC liên tục."""
    rng = np.random.default_rng(7)
    n = 72
    start = 1_704_067_200_000  # 2024-01-01 00:00 UTC
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    op = np.concatenate([[100.0], close[:-1]])
    hi = np.maximum(op, close) * 1.001
    lo = np.minimum(op, close) * 0.999
    return pd.DataFrame({
        "timestamp": start + np.arange(n) * 3_600_000,
        "open": op, "high": hi, "low": lo, "close": close,
        "volume": rng.uniform(1, 10, n), "close_time": start + np.arange(n) * 3_600_000 + 3_599_999,
        "quote_volume": rng.uniform(100, 1000, n), "trades": 10,
    })

@pytest.fixture
def daily_series():
    rng = np.random.default_rng(3)
    n = 300
    rets = rng.normal(0, 0.02, n)
    close = 100 * np.exp(np.cumsum(rets))
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
        "open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
        "volume": rng.uniform(100, 500, n), "quote_volume": 1e6,
        "n_hours": 24, "rv": np.abs(rng.normal(0.0004, 0.0003, n)),
    })
