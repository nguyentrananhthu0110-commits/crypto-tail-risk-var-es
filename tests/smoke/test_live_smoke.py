"""Smoke test với nguồn THẬT — chỉ chạy thủ công khi đặt CRI_LIVE_TEST=1.
Chạy:  $env:CRI_LIVE_TEST=1; python -m pytest tests/test_live_smoke.py -v   (PowerShell)
"""
import os
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CRI_LIVE_TEST") != "1",
                                reason="Đặt CRI_LIVE_TEST=1 để chạy smoke test mạng thật")

def test_binance_public_reachable_and_sane():
    from src.data.binance_client import BinanceClient
    c = BinanceClient()
    t = c.fetch_ticker_24h("BTCUSDT")
    assert t["price"] > 0
    df = c.fetch_recent("BTCUSDT", "1h", 30, include_forming=False)
    assert len(df) >= 25
    from src.data.validation import validate_candles
    assert validate_candles(df, "1h")["ok"]
