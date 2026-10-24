"""Mục 12+15D: model/dataset hỏng, upstream rỗng, data-quality ở tầng Advanced."""
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
import app.main as main
from src.data.binance_client import empty_candles
from src.storage import atomic_write_parquet, parquet_state

client = TestClient(main.app, raise_server_exceptions=False)


def test_forecast_corrupted_returns_structured_500(monkeypatch):
    monkeypatch.setattr(main, "forecast_state", lambda s: ("corrupt", None))
    r = client.get("/api/forecast", params={"symbol": "ETHUSDT"})
    assert r.status_code == 500
    body = r.json()
    assert body["detail"]["code"] == "MODEL_CORRUPTED"
    assert "retrain" in body["detail"]["message"]  # hướng dẫn cách sửa, không lộ stack trace
    assert "Traceback" not in str(body)


def test_ohlcv_empty_upstream_falls_back_and_marks_stale(monkeypatch):
    monkeypatch.setattr(main.client, "fetch_recent", lambda *a, **k: empty_candles())
    fake = pd.DataFrame({"timestamp": [1704067200000, 1704070800000], "open": 1.0, "high": 2.0,
                         "low": 0.5, "close": 1.5, "volume": 3.0, "close_time": [1, 2],
                         "quote_volume": 1.0, "trades": 1})
    monkeypatch.setattr(main, "load_dataset", lambda s, i: fake)
    r = client.get("/api/ohlcv", params={"symbol": "BTCUSDT", "interval": "1h", "limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["stale"] is True and body["source"] == "local_dataset_fallback" and len(body["candles"]) == 2


def test_ohlcv_empty_everywhere_returns_502(monkeypatch):
    monkeypatch.setattr(main.client, "fetch_recent", lambda *a, **k: empty_candles())
    monkeypatch.setattr(main, "load_dataset", lambda s, i: None)
    r = client.get("/api/ohlcv", params={"symbol": "BTCUSDT", "interval": "4h", "limit": 10})
    assert r.status_code == 502 and r.json()["detail"]["code"] == "UPSTREAM_UNAVAILABLE"


def test_status_quality_and_model_files_contract(monkeypatch):
    r = client.get("/api/status", params={"include_quality": "true"})
    assert r.status_code == 200
    body = r.json()
    expected = len(body.get("config", {}).get("symbols", [])) * 2
    assert len(body.get("data_quality", [])) == expected
    for q in body["data_quality"]:
        assert q["file_state"] in ("ok", "missing", "corrupt")
    for s, m in body["models"].items():
        assert m["status"] in ("ready", "ready_with_warnings", "not_initialized", "corrupted")
        assert "model_files" in m
    # Mặc định (polling) không tính quality để giữ nhẹ
    assert "data_quality" not in client.get("/api/status").json()


def test_parquet_state_distinguishes_corrupt(tmp_path):
    p = tmp_path / "bad.parquet"
    p.write_bytes(b"not a parquet file")
    assert parquet_state(p)[0] == "corrupt"
    assert parquet_state(tmp_path / "none.parquet")[0] == "missing"
    ok = tmp_path / "ok.parquet"
    atomic_write_parquet(pd.DataFrame({"a": [1]}), ok)
    assert parquet_state(ok)[0] == "ok"
