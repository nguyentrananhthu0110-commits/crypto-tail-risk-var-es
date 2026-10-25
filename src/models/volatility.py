"""Mô hình volatility: Historical/EWMA, GARCH(1,1), HAR-RV, XGBoost + metrics QLIKE/DM.

GARCH được lưu dưới dạng THAM số (omega, alpha, beta, mu, nu, state) thay vì object của
thư viện -> load lại ổn định giữa các phiên bản. Dùng `arch` nếu có; nếu không, tự ước
lượng MLE chuẩn bằng scipy (cùng định dạng state). Đơn vị: returns dạng thập phân.
"""
from __future__ import annotations
import warnings
import numpy as np
from scipy import optimize, stats

EPS = 1e-12

# ---------------- Metrics ----------------
def mae(a, f): return float(np.mean(np.abs(np.asarray(a) - np.asarray(f))))
def rmse(a, f): return float(np.sqrt(np.mean((np.asarray(a) - np.asarray(f)) ** 2)))

def qlike(rv_var, forecast_var) -> float:
    """Patton (2011): QLIKE = mean( RV/h - log(RV/h) - 1 ). Yêu cầu RV, h > 0."""
    rv = np.clip(np.asarray(rv_var, float), EPS, None); h = np.clip(np.asarray(forecast_var, float), EPS, None)
    ratio = rv / h
    return float(np.mean(ratio - np.log(ratio) - 1.0))

def diebold_mariano(loss1, loss2) -> dict:
    """DM test h=1 (hiệu chỉnh Harvey–Leybourne–Newbold). H0: hai dự báo ngang nhau."""
    d = np.asarray(loss1, float) - np.asarray(loss2, float)
    n = len(d)
    if n < 20 or np.std(d) == 0:
        return {"statistic": None, "p_value": None, "n": int(n), "note": "insufficient_data"}
    mean_d, var_d = d.mean(), d.var(ddof=1)
    dm = mean_d / np.sqrt(var_d / n)
    hln = dm * np.sqrt((n - 1) / n)  # h=1: hệ số HLN rút gọn
    p = 2 * (1 - stats.t.cdf(abs(hln), df=n - 1))
    return {"statistic": float(hln), "p_value": float(p), "n": int(n),
            "note": "two-sided, h=1, HLN small-sample correction; âm nghĩa là model 1 tổn thất thấp hơn"}

# ---------------- Historical / EWMA ----------------
def historical_forecast_var(rv_window: np.ndarray) -> float:
    return float(np.mean(rv_window))

def ewma_series(returns: np.ndarray, lam: float = 0.94) -> np.ndarray:
    var = np.empty(len(returns)); var[0] = returns[0] ** 2
    for i in range(1, len(returns)):
        var[i] = lam * var[i-1] + (1 - lam) * returns[i-1] ** 2  # dự báo cho i chỉ dùng quá khứ
    return var

# ---------------- GARCH(1,1) ----------------
def _garch_filter(returns, mu, omega, alpha, beta, init_var):
    n = len(returns); sigma2 = np.empty(n); sigma2[0] = init_var
    eps = returns - mu
    for i in range(1, n):
        sigma2[i] = omega + alpha * eps[i-1] ** 2 + beta * sigma2[i-1]
    return sigma2, eps

def fit_garch(returns: np.ndarray) -> dict:
    """Ưu tiên arch (Student-t). Fallback: MLE Gaussian tự cài đặt bằng scipy."""
    r = np.asarray(returns, float); r = r[np.isfinite(r)]
    engine = "arch_garch11_t"
    try:
        from arch import arch_model
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m = arch_model(r * 100, mean="Constant", vol="Garch", p=1, q=1, dist="t", rescale=False)
            res = m.fit(disp="off")
        p = res.params
        mu = float(p.get("mu", p.iloc[0])) / 100
        omega = float(p["omega"]) / 1e4; alpha = float(p["alpha[1]"]); beta = float(p["beta[1]"])
        nu = float(p["nu"]) if "nu" in p else 8.0
    except Exception:
        engine = "scipy_garch11_gaussian_mle"
        mu = float(np.mean(r)); init_var = float(np.var(r)) or 1e-4
        def nll(theta):
            om, al, be = theta
            if om <= 0 or al < 0 or be < 0 or al + be >= 0.999: return 1e10
            s2, eps = _garch_filter(r, mu, om, al, be, init_var)
            s2 = np.clip(s2, EPS, None)
            return float(0.5 * np.sum(np.log(2*np.pi*s2) + eps**2 / s2))
        out = optimize.minimize(nll, [init_var*0.05, 0.08, 0.88], method="Nelder-Mead",
                                options={"maxiter": 4000, "xatol": 1e-10, "fatol": 1e-8})
        omega, alpha, beta = [float(x) for x in out.x]; nu = 8.0
    init_var = float(np.var(r)) or 1e-4
    sigma2, eps = _garch_filter(r, mu, omega, alpha, beta, init_var)
    uncond = omega / max(1 - alpha - beta, 1e-6)
    return {"engine": engine, "mu": mu, "omega": omega, "alpha": alpha, "beta": beta,
            "nu": float(np.clip(nu, 2.5, 100)), "last_sigma2": float(sigma2[-1]),
            "last_eps": float(eps[-1]), "unconditional_var": float(uncond),
            "sigma2_series": sigma2.tolist()}

def garch_forecast_var(state: dict, horizon_days: int = 1) -> tuple[float, list[float]]:
    """Trả (tổng phương sai horizon ngày, chuỗi phương sai từng ngày)."""
    om, al, be = state["omega"], state["alpha"], state["beta"]
    first = om + al * state["last_eps"] ** 2 + be * state["last_sigma2"]
    seq, cur = [float(first)], float(first)
    uncond = state["unconditional_var"]
    for _ in range(1, horizon_days):
        cur = uncond + (al + be) * (cur - uncond)
        seq.append(float(cur))
    return float(np.sum(seq)), seq

def garch_oos_forecasts(returns: np.ndarray, train_end_idx: int, refit_every: int = 20) -> np.ndarray:
    """1-step OOS: refit định kỳ trên cửa sổ mở rộng; các bước giữa cập nhật state bằng return đã quan sát."""
    n = len(returns); fc = np.full(n, np.nan)
    state, s2 = None, None
    for i in range(train_end_idx, n):
        if state is None or (i - train_end_idx) % refit_every == 0:
            st = fit_garch(returns[:i]); state = st
            s2 = st["last_sigma2"]; last_eps = st["last_eps"]
            fc[i] = st["omega"] + st["alpha"] * last_eps**2 + st["beta"] * s2
        else:
            fc[i] = s2_next
        eps_i = returns[i] - state["mu"]
        s2_next = state["omega"] + state["alpha"] * eps_i**2 + state["beta"] * fc[i]
    return fc

# ---------------- HAR-RV ----------------
class HARModel:
    def __init__(self): self.coef_ = None  # [intercept, beta_d, beta_w, beta_m]
    def fit(self, rv_d, rv_w, rv_m, y):
        X = np.column_stack([np.ones(len(y)), rv_d, rv_w, rv_m])
        mask = np.isfinite(X).all(axis=1) & np.isfinite(y)
        self.coef_, *_ = np.linalg.lstsq(X[mask], np.asarray(y)[mask], rcond=None)
        return self
    def predict_var(self, rv_d, rv_w, rv_m):
        X = np.column_stack([np.ones(np.size(rv_d)), np.atleast_1d(rv_d), np.atleast_1d(rv_w), np.atleast_1d(rv_m)])
        return np.clip(X @ self.coef_, EPS, None)
    def to_dict(self): return {"coef": self.coef_.tolist(),
                               "terms": ["intercept","RV_day","RV_week(5d)","RV_month(22d)"]}
    @classmethod
    def from_dict(cls, d):
        m = cls(); m.coef_ = np.array(d["coef"], float); return m

# ---------------- XGBoost trên log(RV) (fallback: HistGradientBoosting) ----------------
class LogRVRegressor:
    """Huấn luyện cây tăng cường trên log(RV) để dự báo phương sai luôn dương tuyệt đối
    và không bị bóp méo bởi vài ngày biến động cực đoan (tránh dự báo âm bị cắt về 1e-12
    làm nổ QLIKE và ES-Z2). Dùng hệ số Duan (1983) smearing ước lượng CHỈ trên phần dư tập train
    để khử chệch Jensen khi đổi ngược exp(log_rv) -> E[RV | X]."""
    def __init__(self, base_model):
        self.base_model = base_model
        self.smear_ = 1.0
        self.min_var_ = 1e-8

    def fit(self, X, y_rv):
        X_arr = np.asarray(X, float)
        y_pos = np.clip(np.asarray(y_rv, float), 1e-10, None)
        self.min_var_ = float(max(np.quantile(y_pos, 0.01) * 0.05, 1e-8))
        log_y = np.log(y_pos)
        self.base_model.fit(X_arr, log_y)
        pred_train = np.asarray(self.base_model.predict(X_arr), float)
        resid = np.clip(log_y - pred_train, -5.0, 5.0)
        self.smear_ = float(np.clip(np.mean(np.exp(resid)), 0.8, 2.5))
        return self

    def predict(self, X):
        X_arr = np.asarray(X, float)
        log_pred = np.clip(np.asarray(self.base_model.predict(X_arr), float), -23.0, 4.0)
        return np.clip(np.exp(log_pred) * self.smear_, self.min_var_, None)

    def get_params(self, deep: bool = True) -> dict:
        base = self.base_model.get_params(deep=deep) if hasattr(self.base_model, "get_params") else {}
        return {**base, "target_transform": "log_rv_duan_smearing",
                "smear_factor": round(self.smear_, 6), "min_var_floor": self.min_var_}


def make_xgb_regressor():
    try:
        from xgboost import XGBRegressor
        base = XGBRegressor(n_estimators=300, max_depth=3, learning_rate=0.04, subsample=0.85,
                            colsample_bytree=0.85, reg_lambda=1.0, random_state=42, n_jobs=2)
        return LogRVRegressor(base), "xgboost_log_rv"
    except Exception:
        from sklearn.ensemble import HistGradientBoostingRegressor
        base = HistGradientBoostingRegressor(max_iter=300, max_depth=3, learning_rate=0.04,
                                             random_state=42)
        return LogRVRegressor(base), "sklearn_hist_gradient_boosting_log_rv_fallback"

def permutation_importance(model, X: np.ndarray, y: np.ndarray, names: list[str], seed: int = 42) -> list[dict]:
    """Giải thích bằng permutation importance (không suy diễn nhân quả). Ổn định khi SHAP không khả dụng."""
    rng = np.random.default_rng(seed)
    base = rmse(y, np.clip(model.predict(X), EPS, None))
    out = []
    for j, name in enumerate(names):
        Xp = X.copy(); Xp[:, j] = rng.permutation(Xp[:, j])
        inc = rmse(y, np.clip(model.predict(Xp), EPS, None)) - base
        out.append({"feature": name, "importance_rmse_increase": float(max(inc, 0.0))})
    total = sum(o["importance_rmse_increase"] for o in out) or 1.0
    for o in out: o["share"] = o["importance_rmse_increase"] / total
    return sorted(out, key=lambda x: -x["share"])
