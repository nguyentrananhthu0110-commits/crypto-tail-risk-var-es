"""/api/backtest-extended: đọc bảng outputs/tables, NaN -> null, 404 có hướng dẫn khi chưa chạy backtest."""
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

import app.main as main

client = TestClient(main.app, raise_server_exceptions=False)


def _write(tables, name, df):
    df.to_csv(tables / name, index=False, encoding="utf-8-sig")


def test_extended_returns_json_safe_rows(tmp_path, monkeypatch):
    _write(tmp_path, "backtest_summary.csv", pd.DataFrame({
        "symbol": ["BTCUSDT", "ETHUSDT"], "model": ["garch_1_1"] * 2, "mức_tin_cậy": ["99%"] * 2,
        "christoffersen_cc_p": [np.nan, 0.4]}))
    monkeypatch.setattr(main, "_TABLES", tmp_path)
    r = client.get("/api/backtest-extended", params={"symbol": "BTCUSDT"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["test_window"]) == 1 and body["test_window"][0]["christoffersen_cc_p"] is None
    assert body["long"] is None and body["nu"] is None


def test_extended_maps_btcusdt_to_btc_in_long_tables(tmp_path, monkeypatch):
    _write(tmp_path, "backtest_long_summary.csv", pd.DataFrame({"symbol": ["BTC", "ETH"], "model": ["m", "m"], "n": [5, 5]}))
    monkeypatch.setattr(main, "_TABLES", tmp_path)
    body = client.get("/api/backtest-extended", params={"symbol": "ETHUSDT"}).json()
    assert [x["symbol"] for x in body["long"]] == ["ETH"]


def test_extended_404_with_instruction_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_TABLES", tmp_path)
    r = client.get("/api/backtest-extended", params={"symbol": "SOLUSDT"})
    assert r.status_code == 404
    d = r.json()["detail"]
    assert d["code"] == "BACKTEST_EXTENDED_NOT_FOUND" and "run_backtest" in d["message"]


def test_pdf_report_endpoint_generates_valid_extended_pdf():
    for sym in ("BTCUSDT", "ETHUSDT"):
        r = client.get("/api/report", params={"symbol": sym})
        assert r.status_code == 200
        assert "application/pdf" in r.headers.get("content-type", "")
        assert r.content.startswith(b"%PDF-") and len(r.content) > 30_000
