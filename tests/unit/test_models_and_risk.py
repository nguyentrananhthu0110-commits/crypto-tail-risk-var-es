"""B+C. Models & Risk: giá trị hữu hạn, tái lập được, quy ước dấu VaR/ES,
test-case đã biết đáp án cho Kupiec/QLIKE, trường hợp thiếu dữ liệu."""
import numpy as np
import pytest
from src.models.volatility import (HARModel, diebold_mariano, fit_garch, garch_forecast_var,
                                   mae, qlike, rmse)
from src.risk.var_es import (christoffersen_test, forecast_var_es, historical_var_es,
                             kupiec_test, parametric_t_var_es, quantile_loss)


def test_qlike_known_value():
    # RV = dự báo -> QLIKE = 0
    assert qlike([0.01, 0.02], [0.01, 0.02]) == pytest.approx(0.0, abs=1e-12)
    # ratio=2 -> 2 - ln2 - 1
    assert qlike([0.02], [0.01]) == pytest.approx(1 - np.log(2), rel=1e-9)


def test_mae_rmse_basic():
    assert mae([1, 2], [1, 4]) == 1.0
    assert rmse([1, 2], [1, 4]) == pytest.approx(np.sqrt(2))


def test_har_recovers_known_coefficients():
    rng = np.random.default_rng(0)
    n = 500
    d, w, m = rng.uniform(0, 1, n), rng.uniform(0, 1, n), rng.uniform(0, 1, n)
    y = 0.1 + 0.4 * d + 0.3 * w + 0.2 * m
    har = HARModel().fit(d, w, m, y)
    assert np.allclose(har.coef_, [0.1, 0.4, 0.3, 0.2], atol=1e-8)
    assert (har.predict_var(d, w, m) > 0).all()
    # save/load tròn trịa
    har2 = HARModel.from_dict(har.to_dict())
    assert np.allclose(har2.predict_var(d, w, m), har.predict_var(d, w, m))


def test_garch_fit_and_forecast_finite_positive():
    rng = np.random.default_rng(11)
    rets = rng.normal(0, 0.02, 400)
    state = fit_garch(rets)
    for k in ("omega", "alpha", "beta", "last_sigma2"):
        assert np.isfinite(state[k])
    assert state["omega"] > 0 and state["alpha"] >= 0 and state["beta"] >= 0
    total7, seq = garch_forecast_var(state, 7)
    assert len(seq) == 7 and all(v > 0 and np.isfinite(v) for v in seq)
    assert total7 == pytest.approx(sum(seq))


def test_dm_insufficient_and_identical():
    assert diebold_mariano([1, 2], [1, 2])["note"] == "insufficient_data"
    d = diebold_mariano(np.ones(40), np.ones(40))
    assert d["p_value"] is None  # std=0 -> không giả vờ có kết luận


def test_historical_var_es_sign_convention_known_case():
    # Lợi suất: 19 ngày 0%, 1 ngày -10% (n=20). LOSS trên 10k: mười chín số 0, một số 1000.
    rets = np.array([0.0] * 19 + [-0.10])
    out = historical_var_es(rets, 10_000)
    assert out["var_95"] >= 0 and out["es_95"] >= out["var_95"]  # ES không nhỏ hơn VaR
    assert out["es_99"] == pytest.approx(1000.0, rel=0.05)


def test_var_increases_with_volatility_and_confidence():
    lo = forecast_var_es(0.01, 5.0, 10_000)
    hi = forecast_var_es(0.03, 5.0, 10_000)
    assert hi["var_95"] > lo["var_95"] > 0
    assert lo["var_99"] > lo["var_95"] and lo["es_95"] > lo["var_95"]


def test_parametric_reproducible_with_seed():
    rng = np.random.default_rng(1)
    rets = rng.normal(0, 0.02, 300)
    a, b = parametric_t_var_es(rets, 10_000), parametric_t_var_es(rets, 10_000)
    assert a["var_95"] == b["var_95"] and a["es_99"] == b["es_99"]


def test_kupiec_at_expected_rate_high_pvalue():
    out = kupiec_test(breaches=5, n=100, alpha=0.95)  # đúng kỳ vọng 5%
    assert out["status"] == "ok" and out["p_value"] > 0.9
    bad = kupiec_test(breaches=25, n=100, alpha=0.95)
    assert bad["p_value"] < 0.01


def test_backtests_report_insufficient_data():
    assert kupiec_test(1, 10, 0.95)["status"] == "insufficient_data"
    assert christoffersen_test([0] * 60, 0.95)["status"] == "insufficient_data"  # 0 breach
    ok = christoffersen_test([0, 1] * 40, 0.95)
    assert ok["status"] == "ok" and 0 <= ok["p_value_conditional_coverage"] <= 1


def test_quantile_loss_perfect_forecast_is_zero():
    assert quantile_loss([100, 200], [100, 200], 0.95) == 0.0
