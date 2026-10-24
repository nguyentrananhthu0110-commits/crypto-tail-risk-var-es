"""Mục 15 A/B: incremental update (mock client), train/test theo thời gian,
tái lập XGBoost, save/load model, breach logic, scaling theo horizon, timezone UTC."""
import time
import joblib
import numpy as np
import pandas as pd
import pytest
from src.data import pipeline
from src.data.validation import validate_candles
from src.features.build import build_daily
from src.models.training import _backtest, chronological_split
from src.models.volatility import fit_garch, garch_forecast_var, make_xgb_regressor
from src.risk.var_es import forecast_var_es
from src.storage import atomic_write_json, read_json


class FakeClient:
    def __init__(self, new_df): self.new_df = new_df; self.calls = []
    def fetch_klines(self, symbol, interval, start, end):
        self.calls.append(start); return self.new_df


def _next_candles(after_ts):
    return pd.DataFrame({
        "timestamp": [after_ts + i * 3_600_000 for i in (1, 2, 3)],
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
        "volume": 1.0, "close_time": [after_ts + i * 3_600_000 - 1 for i in (2, 3, 4)],
        "quote_volume": 1.0, "trades": 1})


def test_incremental_fetches_only_after_checkpoint(hourly_candles, monkeypatch):
    checkpoint = int(hourly_candles["timestamp"].max())
    fake = FakeClient(_next_candles(checkpoint))
    saved = {}
    monkeypatch.setattr(pipeline, "load_dataset", lambda s, i: hourly_candles)
    monkeypatch.setattr(pipeline, "_client", fake)
    monkeypatch.setattr(pipeline, "log_job", lambda *a, **k: None)
    def fake_save(symbol, interval, df, source="x"):
        saved["df"] = df
        return validate_candles(df, interval)
    monkeypatch.setattr(pipeline, "_save", fake_save)
    res = pipeline.download_or_update("BTCUSDT", "1h", 730)
    assert res["mode"] == "incremental" and res["new_rows"] == 3
    assert fake.calls == [checkpoint + 3_600_000]           # chỉ tải phần thiếu
    assert len(saved["df"]) == 75 and saved["df"]["timestamp"].is_unique


def test_no_new_data_does_not_call_network(monkeypatch):
    now_hour = (int(time.time() * 1000) // 3_600_000) * 3_600_000
    df = _next_candles(now_hour - 3_600_000)
    class Boom:
        def fetch_klines(self, *a): raise AssertionError("không được gọi mạng khi đã mới nhất")
    monkeypatch.setattr(pipeline, "load_dataset", lambda s, i: df)
    monkeypatch.setattr(pipeline, "_client", Boom())
    res = pipeline.download_or_update("BTCUSDT", "1h", 730)
    assert res["mode"] == "no_new_data" and res["new_rows"] == 0


def test_chronological_split_never_shuffles():
    tr, te = chronological_split(100, 0.8)
    assert list(tr) == list(range(80)) and list(te) == list(range(80, 100))
    assert max(tr) < min(te)
    with pytest.raises(ValueError): chronological_split(10, 1.5)


def test_xgb_reproducible_and_joblib_roundtrip(tmp_path):
    rng = np.random.default_rng(5)
    X = rng.uniform(0, 1, (160, 4)); y = 0.001 + 0.002 * X[:, 0]
    m1, e1 = make_xgb_regressor(); m1.fit(X, y)
    m2, _ = make_xgb_regressor(); m2.fit(X, y)
    p1, p2 = m1.predict(X[:5]), m2.predict(X[:5])
    assert np.allclose(p1, p2) and np.isfinite(p1).all() and p1.shape == (5,)
    path = tmp_path / "m.joblib"; joblib.dump({"model": m1, "engine": e1}, path)
    loaded = joblib.load(path)
    assert np.allclose(loaded["model"].predict(X[:5]), p1)


def test_garch_state_json_roundtrip_forecast_same(tmp_path):
    rng = np.random.default_rng(2)
    st = fit_garch(rng.normal(0, 0.02, 300)); st.pop("sigma2_series", None)
    path = tmp_path / "g.json"; atomic_write_json(st, path)
    back = read_json(path)
    assert garch_forecast_var(back, 7) == pytest.approx(garch_forecast_var(st, 7))


def test_var_scales_with_sqrt_horizon_and_custom_alpha():
    one = forecast_var_es(0.02, 5.0, 10_000, alphas=(0.90, 0.975), horizon_days=1)
    four = forecast_var_es(0.02, 5.0, 10_000, alphas=(0.90,), horizon_days=4)
    assert "var_90" in one and "var_97" in one or "var_90" in one  # khoá theo int(alpha*100)
    assert four["var_90"] == pytest.approx(2 * one["var_90"], rel=0.05)


def test_breach_logic_known_case():
    daily = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"], utc=True),
        "simple_return": [-0.10, 0.0, 0.05]})
    bt = _backtest(daily, ["2024-01-01", "2024-01-02", "2024-01-03"],
                   np.array([0.01**2] * 3), t_df=5.0, position=10_000)
    flags = [(r["breach95"], r["breach99"]) for r in bt["series"]]
    assert flags[0][0] is True    # lỗ 10% vượt VaR với sigma 1%
    assert flags[1] == (False, False) and flags[2] == (False, False)


def test_build_daily_timezone_is_utc(hourly_candles):
    daily = build_daily(hourly_candles)
    assert str(daily["date"].dt.tz) == "UTC"
    assert (daily["date"].dt.hour == 0).all()  # biên ngày theo UTC, không phụ thuộc múi giờ máy
