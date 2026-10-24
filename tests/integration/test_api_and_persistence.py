"""A(phần lưu trữ)+D. Persistence sau restart, API hợp lệ/không hợp lệ, empty state.
Tests không gọi mạng: mock tại biên của app."""
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
import app.main as main
from src.data.binance_client import BinanceError
from src.storage import atomic_write_json, atomic_write_parquet, read_json, read_parquet

client = TestClient(main.app, raise_server_exceptions=False)


def test_atomic_parquet_roundtrip(tmp_path):
    df = pd.DataFrame({"timestamp": [1, 2], "close": [10.0, 11.0]})
    p = tmp_path / "x.parquet"
    atomic_write_parquet(df, p)
    back = read_parquet(p)
    assert back.equals(df)
    assert list(tmp_path.glob("*.tmp")) == [] and len(list(tmp_path.iterdir())) == 1


def test_atomic_json_roundtrip_and_corrupt_returns_none(tmp_path):
    p = tmp_path / "x.json"
    atomic_write_json({"a": 1, "b": "tiếng Việt"}, p)
    assert read_json(p) == {"a": 1, "b": "tiếng Việt"}
    p.write_text("{hỏng", encoding="utf-8")
    assert read_json(p) is None  # file hỏng -> None, không crash


def test_health_ok():
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_invalid_symbol_returns_422_structured():
    r = client.get("/api/ohlcv", params={"symbol": "UNKNOWNUSDT"})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "VALIDATION_ERROR"
    r2 = client.get("/api/forecast", params={"symbol": "BTCUSDT", "position_usd": -5})
    assert r2.status_code == 422


def test_forecast_empty_state_404_structured(monkeypatch):
    monkeypatch.setattr(main, "forecast_state", lambda s: ("missing", None))
    r = client.get("/api/forecast", params={"symbol": "BTCUSDT"})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "MODEL_NOT_INITIALIZED"


def test_ticker_falls_back_to_local_and_marks_stale(monkeypatch):
    def boom(self, symbol): raise BinanceError("upstream down", 503)
    monkeypatch.setattr(main.client, "fetch_ticker_24h", boom.__get__(main.client))
    n = 48
    fake = pd.DataFrame({"timestamp": np.arange(n), "open": 100.0, "high": 101.0,
                         "low": 99.0, "close": np.linspace(100, 110, n), "volume": 1.0,
                         "close_time": np.arange(n), "quote_volume": 1.0, "trades": 1})
    monkeypatch.setattr(main, "load_dataset", lambda s, i: fake)
    r = client.get("/api/ticker", params={"symbol": "BTCUSDT"})
    assert r.status_code == 200
    body = r.json()
    assert body["stale"] is True and body["source"] == "local_dataset_fallback"
    assert body["price"] == pytest.approx(110.0)


def test_index_served():
    r = client.get("/")
    assert r.status_code == 200 and "Crypto Risk Intelligence" in r.text
