"""VaR / Expected Shortfall + backtesting.

Quy ước (ghi rõ, nhất quán toàn hệ thống):
- r = simple return ngày của giá đóng cửa; LOSS = -r * position_usd (USD, số dương = lỗ).
- VaR_alpha = phân vị alpha của phân phối LOSS; ES_alpha = E[LOSS | LOSS >= VaR_alpha].
- VaR là NGƯỠNG, không phải mức lỗ tối đa. Horizon mặc định 1 ngày.
- Phương pháp chính: forecast-based (vol dự báo x phân vị Student-t chuẩn hoá),
  đối chiếu Historical Simulation và Parametric Student-t (fit trên lợi suất lịch sử).
"""
from __future__ import annotations
import numpy as np
from scipy import stats

def _var_es_from_losses(losses: np.ndarray, alpha: float) -> tuple[float, float]:
    losses = np.asarray(losses, float); losses = losses[np.isfinite(losses)]
    var = float(np.quantile(losses, alpha))
    tail = losses[losses >= var]
    es = float(np.mean(tail)) if len(tail) else var
    return var, es

def historical_var_es(simple_returns, position_usd: float, alphas=(0.95, 0.99)) -> dict:
    losses = -np.asarray(simple_returns, float) * position_usd
    losses = losses[np.isfinite(losses)]
    out = {"method": "historical_simulation", "n_obs": int(len(losses)),
           "assumption": "Phân phối thực nghiệm của lợi suất quá khứ đại diện cho kỳ tới"}
    for a in alphas:
        v, e = _var_es_from_losses(losses, a)
        out[f"var_{int(a*100)}"] = v; out[f"es_{int(a*100)}"] = e
    return out

def fit_student_t(returns) -> dict:
    r = np.asarray(returns, float); r = r[np.isfinite(r)]
    df, loc, scale = stats.t.fit(r)
    return {"df": float(np.clip(df, 2.5, 100)), "loc": float(loc), "scale": float(max(scale, 1e-8))}

def _mc_var_es(rng, sampler, position_usd, alphas, n=200_000):
    losses = -sampler(n) * position_usd
    return {a: _var_es_from_losses(losses, a) for a in alphas}

def parametric_t_var_es(simple_returns, position_usd, alphas=(0.95, 0.99), seed=42) -> dict:
    t = fit_student_t(simple_returns); rng = np.random.default_rng(seed)
    res = _mc_var_es(rng, lambda n: stats.t.rvs(t["df"], loc=t["loc"], scale=t["scale"],
                                                size=n, random_state=rng), position_usd, alphas)
    out = {"method": "parametric_student_t", "params": t,
           "assumption": "Lợi suất ~ Student-t(df, loc, scale) fit trên cửa sổ lịch sử; ES bằng Monte Carlo seed cố định (200k mô phỏng)"}
    for a, (v, e) in res.items(): out[f"var_{int(a*100)}"] = v; out[f"es_{int(a*100)}"] = e
    return out

def forecast_var_es(forecast_vol_daily: float, t_df: float, position_usd: float,
                    alphas=(0.95, 0.99), horizon_days: int = 1, seed=42) -> dict:
    """VaR từ volatility dự báo; phân vị của Student-t đã chuẩn hoá để phương sai = sigma^2*horizon."""
    df = float(np.clip(t_df, 2.5, 100))
    sigma_h = forecast_vol_daily * np.sqrt(horizon_days)
    scale = sigma_h * np.sqrt((df - 2) / df)
    rng = np.random.default_rng(seed)
    out = {"method": "forecast_vol_student_t", "t_df": df, "sigma_daily": float(forecast_vol_daily),
           "horizon_days": horizon_days,
           "assumption": "Lợi suất kỳ tới = sigma_dự_báo x epsilon, epsilon ~ Student-t chuẩn hoá (phương sai 1). Mu=0."}
    for a in alphas:
        q = stats.t.ppf(1 - a, df) * scale          # phân vị đuôi trái của lợi suất (âm)
        var = float(-q * position_usd)
        sims = stats.t.rvs(df, scale=scale, size=200_000, random_state=rng)
        es = float(-np.mean(sims[sims <= q]) * position_usd) if np.any(sims <= q) else var
        out[f"var_{int(a*100)}"] = var; out[f"es_{int(a*100)}"] = es
    return out

# ---------------- Backtesting ----------------
def kupiec_test(breaches: int, n: int, alpha: float) -> dict:
    """Kupiec unconditional coverage LR test. p = 1-alpha là xác suất breach kỳ vọng."""
    if n < 30:
        return {"test": "Kupiec unconditional coverage", "status": "insufficient_data", "n": int(n)}
    p, x = 1 - alpha, int(breaches)
    ll_null = (n - x) * np.log(1 - p) + (x * np.log(p) if x > 0 else 0.0)
    phat = x / n
    ll_alt = ((n - x) * np.log(1 - phat) if x < n else 0.0) + (x * np.log(phat) if x > 0 else 0.0)
    lr = float(-2 * (ll_null - ll_alt))
    pval = float(1 - stats.chi2.cdf(lr, df=1))
    return {"test": "Kupiec unconditional coverage", "status": "ok", "n": int(n), "breaches": x,
            "expected_breaches": float(n * p), "lr_statistic": lr, "p_value": pval,
            "verdict": "Không bác bỏ H0 (tần suất breach tương thích)" if pval > 0.05
                       else "Bác bỏ H0 (tần suất breach không tương thích)"}

# Dưới ngưỡng này, bảng chuyển trạng thái gần như rỗng (n11 = 0) nên p-value luôn xấp xỉ 1
# -> "không bác bỏ" là giả tạo, không phải bằng chứng mô hình tốt. Phải báo rõ là thiếu dữ liệu.
MIN_BREACHES_INDEPENDENCE = 5


def christoffersen_test(breach_indicator, alpha: float) -> dict:
    b = np.asarray(breach_indicator, int); n = len(b)
    k = int(b.sum())
    if n < 50 or k < MIN_BREACHES_INDEPENDENCE:
        return {"test": "Christoffersen conditional coverage", "status": "insufficient_data",
                "n": int(n), "breaches": k, "required_breaches": MIN_BREACHES_INDEPENDENCE,
                "note": (f"Không đủ dữ liệu: cần >=50 quan sát và >= {MIN_BREACHES_INDEPENDENCE} vi phạm "
                         f"(hiện có {k}). Dưới ngưỡng này kiểm định độc lập không có lực thống kê.")}
    n00 = int(np.sum((b[:-1] == 0) & (b[1:] == 0))); n01 = int(np.sum((b[:-1] == 0) & (b[1:] == 1)))
    n10 = int(np.sum((b[:-1] == 1) & (b[1:] == 0))); n11 = int(np.sum((b[:-1] == 1) & (b[1:] == 1)))
    def _ll(n01_, n00_, n11_, n10_):
        pi01 = n01_ / max(n00_ + n01_, 1); pi11 = n11_ / max(n10_ + n11_, 1)
        ll = 0.0
        if n00_: ll += n00_ * np.log(max(1 - pi01, 1e-12))
        if n01_: ll += n01_ * np.log(max(pi01, 1e-12))
        if n10_: ll += n10_ * np.log(max(1 - pi11, 1e-12))
        if n11_: ll += n11_ * np.log(max(pi11, 1e-12))
        return ll
    pi = (n01 + n11) / max(n00 + n01 + n10 + n11, 1)
    ll_ind0 = 0.0
    for cnt, is_one in ((n00 + n10, 0), (n01 + n11, 1)):
        if cnt: ll_ind0 += cnt * np.log(max(pi if is_one else 1 - pi, 1e-12))
    lr_ind = float(-2 * (ll_ind0 - _ll(n01, n00, n11, n10)))
    kup = kupiec_test(int(b.sum()), n, alpha)
    lr_cc = (kup.get("lr_statistic") or 0.0) + lr_ind
    return {"test": "Christoffersen conditional coverage", "status": "ok", "n": int(n), "breaches": int(b.sum()),
            "transitions": {"n00": n00, "n01": n01, "n10": n10, "n11": n11},
            "lr_independence": lr_ind, "p_value_independence": float(1 - stats.chi2.cdf(lr_ind, 1)),
            "lr_conditional_coverage": float(lr_cc),
            "p_value_conditional_coverage": float(1 - stats.chi2.cdf(lr_cc, 2)),
            "verdict": "Không bác bỏ H0" if (1 - stats.chi2.cdf(lr_cc, 2)) > 0.05 else "Bác bỏ H0"}

def quantile_loss(actual_loss, var_forecast, alpha: float) -> float:
    """Pinball/quantile loss cho chuỗi VaR dự báo (thấp hơn = tốt hơn)."""
    y, q = np.asarray(actual_loss, float), np.asarray(var_forecast, float)
    return float(np.mean(np.where(y >= q, alpha * (y - q), (1 - alpha) * (q - y))))
