"""Backtest VaR/ES cho 4 mô hình volatility trên CÙNG một tập test out-of-sample + mẫu dài rolling.

Cách chạy (từ thư mục gốc của repo):
    python -m src.backtest.run_backtest
    python -m src.backtest.run_backtest --long-csv data/raw/Data_daily_BTC_ETH_2017-2026.csv

Đầu vào  : models/metadata/<SYMBOL>_performance.json  (σ dự báo ngoài mẫu của 4 mô hình)
           models/metadata/<SYMBOL>_forecast.json     (khoảng train/test & t_df_train_only)
           data/processed/<SYMBOL>_daily.parquet      (lợi suất ngày thực tế)
           data/raw/<SYMBOL>_1d.parquet               (chuỗi nến ngày dài hạn cho mẫu dài 35 coin)
Đầu ra   : outputs/tables/backtest_*.csv, outputs/figures/backtest_*.png

Quy ước (khớp src/risk/var_es.py):
- LOSS = -simple_return (số dương = lỗ), tính theo % vị thế.
- VaR_a = phân vị a của LOSS; ES_a = E[LOSS | LOSS >= VaR_a]. Horizon 1 ngày, mu = 0.
- Phân phối: Student-t chuẩn hoá (phương sai 1) nhân σ dự báo của từng mô hình.
- Bậc tự do t cho mọi backtest được ước lượng CHỈ trên giai đoạn train (t_df_train_only -> không rò rỉ).
"""
from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from src.models.volatility import diebold_mariano
from src.risk.var_es import christoffersen_test, kupiec_test

ROOT = Path(__file__).resolve().parents[2]
META = ROOT / "models" / "metadata"
PROCESSED = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw"
TABLES = ROOT / "outputs" / "tables"
FIGURES = ROOT / "outputs" / "figures"


def discover_symbols():
    """Mọi symbol đã có performance.json + forecast.json + daily parquet (không gắn cứng BTC/ETH)."""
    out = []
    for p in sorted(META.glob("*_performance.json")):
        sym = p.name.replace("_performance.json", "")
        if (META / f"{sym}_forecast.json").exists() and (PROCESSED / f"{sym}_daily.parquet").exists():
            out.append(sym)
    return tuple(out)


SYMBOLS = discover_symbols()
MODELS = ("historical_22d", "garch_1_1", "har_rv", "xgboost")
LABELS = {"historical_22d": "Historical 22d", "garch_1_1": "GARCH(1,1)",
          "har_rv": "HAR-RV", "xgboost": "XGBoost"}
ALPHAS = (0.95, 0.99)
NU_MIN, NU_MAX = 2.5, 100.0  # cùng giới hạn với src/risk/var_es.py


# ---------------------------------------------------------------- phân phối
def t_var_es(sigma, nu, alpha):
    """VaR và ES (tỷ lệ lỗ, số dương) khi lợi suất = sigma * eps, eps ~ Student-t chuẩn hoá phương sai 1.

    ES dùng công thức đóng (không Monte Carlo):  ES = sigma*s * f(q)/(1-a) * (nu+q^2)/(nu-1).
    """
    sigma = np.asarray(sigma, float)
    nu = np.clip(np.asarray(nu, float), NU_MIN, NU_MAX)
    s = np.sqrt((nu - 2.0) / nu)
    q = stats.t.ppf(alpha, nu)
    var = sigma * s * q
    es = sigma * s * stats.t.pdf(q, nu) / (1.0 - alpha) * (nu + q ** 2) / (nu - 1.0)
    return var, es


def normal_var_es(sigma, alpha):
    sigma = np.asarray(sigma, float)
    z = stats.norm.ppf(alpha)
    return sigma * z, sigma * stats.norm.pdf(z) / (1.0 - alpha)


def pinball(loss, var, alpha):
    loss, var = np.asarray(loss, float), np.asarray(var, float)
    return np.where(loss >= var, alpha * (loss - var), (1 - alpha) * (var - loss))


# ---------------------------------------------------------------- kiểm định
def basel_zone(breaches: int, n: int, p: float = 0.01) -> str:
    """Traffic light mở rộng theo xác suất nhị thức cho n bất kỳ.
    Xanh: P(X<=x) < 95% ; Vàng: < 99,99% ; Đỏ: còn lại. (Với n=250: xanh 0-4, vàng 5-9, đỏ >=10.)"""
    cum = stats.binom.cdf(int(breaches), int(n), p)
    return "Xanh" if cum < 0.95 else ("Vàng" if cum < 0.9999 else "Đỏ")


def z2_test(loss, var, es, sigma, nu, alpha, dist="t", nsim=20000, seed=42):
    """Acerbi–Székely (2014) Z2: Z2 = sum(I_t * L_t / ES_t) / (T*(1-a)) - 1.
    H0: ES đúng (Z2=0). H1: ES bị ƯỚC LƯỢNG THẤP (Z2>0). p-value một phía bằng mô phỏng
    dưới chính phân phối của mô hình (seed cố định -> tái lập)."""
    loss, var, es = (np.asarray(x, float) for x in (loss, var, es))
    T = len(loss)
    I = loss > var
    if I.sum() == 0:
        return {"z2": None, "p_value": None, "status": "không có vi phạm -> không kiểm định được"}
    z2 = float(np.sum(I * loss / es) / (T * (1 - alpha)) - 1.0)
    rng = np.random.default_rng(seed)
    sigma = np.asarray(sigma, float)
    nu_a = np.clip(np.broadcast_to(np.asarray(nu, float), (T,)), NU_MIN, NU_MAX)
    chunk, count = 2000, 0
    done = 0
    while done < nsim:
        m = min(chunk, nsim - done)
        if dist == "t":
            eps = rng.standard_t(nu_a, size=(m, T)) * np.sqrt((nu_a - 2) / nu_a)
        else:
            eps = rng.standard_normal((m, T))
        L = sigma * eps
        zs = np.sum((L > var) * L / es, axis=1) / (T * (1 - alpha)) - 1.0
        count += int(np.sum(zs >= z2))
        done += m
    return {"z2": z2, "p_value": float((count + 1) / (nsim + 1)), "status": "ok"}


def evaluate(symbol, model, dates, loss, sigma, nu, dist="t", nsim=20000, extra_meta: dict | None = None):
    """Tính VaR/ES từng ngày + toàn bộ kiểm định. Trả (dòng tóm tắt, bảng theo ngày)."""
    loss, sigma = np.asarray(loss, float), np.asarray(sigma, float)
    T = len(loss)
    daily = pd.DataFrame({"symbol": symbol, "model": model, "date": list(dates),
                          "loss_pct": np.round(100 * loss, 6), "sigma_pct": np.round(100 * sigma, 6)})
    rows = []
    for a in ALPHAS:
        tag = int(round(a * 100))
        var, es = t_var_es(sigma, nu, a) if dist == "t" else normal_var_es(sigma, a)
        breach = loss > var
        daily[f"var{tag}_pct"], daily[f"es{tag}_pct"] = np.round(100 * var, 6), np.round(100 * es, 6)
        daily[f"breach{tag}"] = breach.astype(int)
        k = int(breach.sum())
        ku = kupiec_test(k, T, a)
        ch = christoffersen_test(breach.astype(int), a)
        z2 = z2_test(loss, var, es, sigma, nu, a, dist=dist, nsim=nsim)
        pl = pinball(loss, var, a)
        daily[f"pinball{tag}"] = np.round(pl, 8)
        breach_dates = [str(x) for x in np.asarray(dates)[breach]]
        breach_dates_str = (
            ", ".join(breach_dates[:8]) + (f" (+{k - 8} ngày)" if k > 8 else "")
            if k else ""
        )
        row = {
            "symbol": symbol, "model": model, "mức_tin_cậy": f"{tag}%", "n": T,
            "vi_phạm": k, "kỳ_vọng": round(T * (1 - a), 2), "tỷ_lệ_vi_phạm_%": round(100 * k / T, 2),
            "kupiec_p": ku.get("p_value"),
            "christoffersen_cc_p": ch.get("p_value_conditional_coverage") if k >= 5 else None,
            "christoffersen_cc_note": ("ok" if (k >= 5 and ch.get("status") == "ok")
                                       else f"không đủ dữ liệu ({k} vi phạm < 5)"),
            "sức_mạnh_kiểm_định": power_note(T, a, k),
            "pinball_loss": float(np.mean(pl)),
            "VaR_trung_bình_%": float(100 * np.mean(var)),
            "ES_dự_báo_trung_bình_%_ngày_vi_phạm": float(100 * np.mean(es[breach])) if k else None,
            "lỗ_thực_tế_trung_bình_%_ngày_vi_phạm": float(100 * np.mean(loss[breach])) if k else None,
            "ngày_vi_phạm": breach_dates_str,
            "ES_Z2": z2["z2"], "ES_Z2_p": z2["p_value"],
            "Basel": basel_zone(k, T) if tag == 99 else "",
        }
        if extra_meta:
            row.update(extra_meta)
        rows.append(row)
    return rows, daily


def power_note(n_days: int, alpha: float, breaches: int) -> str:
    """Cảnh báo sức mạnh kiểm định theo cỡ mẫu."""
    exp = n_days * (1 - alpha)
    if exp < 5:
        return (f"YẾU: chỉ kỳ vọng {exp:.1f} vi phạm/{n_days} ngày -> 'không bác bỏ' "
                f"không chứng minh mô hình tốt; cần mẫu dài hơn")
    if exp < 10:
        return f"TRUNG BÌNH: kỳ vọng {exp:.1f} vi phạm/{n_days} ngày"
    return f"ok: kỳ vọng {exp:.1f} vi phạm/{n_days} ngày"


def dm_vs_benchmark(daily: pd.DataFrame, benchmark="historical_22d") -> pd.DataFrame:
    """Diebold–Mariano trên pinball loss, mỗi mô hình so với benchmark. Âm = mô hình tốt hơn benchmark."""
    out = []
    for sym, g in daily.groupby("symbol"):
        base = g[g.model == benchmark].sort_values("date")
        if base.empty:
            continue
        for m, h in g.groupby("model"):
            if m == benchmark:
                continue
            h = h.sort_values("date")
            for tag in (95, 99):
                r = diebold_mariano(h[f"pinball{tag}"].to_numpy(), base[f"pinball{tag}"].to_numpy())
                out.append({"symbol": sym, "model": m, "benchmark": benchmark, "mức_tin_cậy": f"{tag}%",
                            "DM_stat": r["statistic"], "p_value": r["p_value"]})
    return pd.DataFrame(out)


# ---------------------------------------------------------------- phần chính: 4 mô hình (tập ngắn 35 coin)
def _atomic_to_csv(df: pd.DataFrame, path: Path) -> None:
    """Ghi CSV nguyên tử qua file tạm để API đang mở không bao giờ đọc phải file ghi dở."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    tmp.replace(path)


def _merge_symbol_rows(existing_path: Path, new_df: pd.DataFrame, updated_syms: set[str]) -> pd.DataFrame:
    """Thay thế đúng các dòng của `updated_syms` trong bảng cũ (nếu có), giữ nguyên các mã còn lại."""
    if not existing_path.exists():
        return new_df
    try:
        old_df = pd.read_csv(existing_path, encoding="utf-8-sig")
    except Exception:
        return new_df
    if "symbol" not in old_df.columns:
        return new_df
    kept = old_df[~old_df["symbol"].astype(str).isin(updated_syms)]
    if kept.empty:
        return new_df
    if new_df.empty:
        return kept.reset_index(drop=True)
    return pd.concat([kept, new_df], ignore_index=True)


def load_test_inputs(symbol):
    perf = json.loads((META / f"{symbol}_performance.json").read_text(encoding="utf-8"))
    fc = json.loads((META / f"{symbol}_forecast.json").read_text(encoding="utf-8"))
    daily = pd.read_parquet(PROCESSED / f"{symbol}_daily.parquet")
    daily["d"] = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m-%d")
    return perf, fc, daily


def run_main(nsim=20000, plot: bool = True, symbols: list[str] | tuple[str, ...] | None = None):
    discovered = discover_symbols()
    if symbols is None:
        target_syms = discovered
        full_replace = True
    else:
        req = {s.upper() for s in symbols}
        target_syms = tuple(s for s in discovered if s in req)
        full_replace = set(target_syms) == set(discovered)
    if not target_syms:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    all_rows, all_daily, nu_rows = [], [], []
    for sym in target_syms:
        perf, fc, daily = load_test_inputs(sym)
        dates = perf["dates"]
        idx = {d: i for i, d in enumerate(daily["d"])}
        loss = -daily["simple_return"].to_numpy()[[idx[d] for d in dates]]
        train_end = fc["train_period"]["end"]
        first_test_idx = idx[dates[0]]
        r_train = daily["simple_return"].iloc[:first_test_idx].dropna().to_numpy()
        # MỘT NGUỒN DUY NHẤT: lấy t_df_train_only đã lưu trong forecast.json (chỉ trước kỳ test -> không rò rỉ).
        risk_meta = fc.get("risk", {})
        nu_train = risk_meta.get("t_df_train_only")
        nu_source = "artifact (t_df_train_only)"
        if nu_train is None:
            nu_train = float(np.clip(stats.t.fit(r_train)[0], NU_MIN, NU_MAX))
            nu_source = "tự fit lại từ tập train"
        nu_full = risk_meta.get("t_df_live") or float(
            np.clip(stats.t.fit(daily["simple_return"].dropna().to_numpy())[0], NU_MIN, NU_MAX)
        )
        nu_rows.append({
            "symbol": sym,
            "nu_train_only(dùng)": float(nu_train),
            "nu_toàn_mẫu(live_tham_chiếu)": float(nu_full),
            "train_end": train_end,
            "test_start": str(dates[0]),
            "test_end": str(dates[-1]),
            "n_test": len(dates),
            "nguồn_ν": nu_source,
        })
        meta = {"từ_ngày": str(dates[0]), "đến_ngày": str(dates[-1])}
        for m in MODELS:
            sigma = np.array([np.nan if v is None else v for v in perf["forecasts_vol_daily"][m]], float)
            rows, d = evaluate(sym, m, dates, loss, sigma, nu_train, "t", nsim, extra_meta=meta)
            all_rows += rows
            all_daily.append(d)
    summary_new = pd.DataFrame(all_rows)
    daily_new = pd.concat(all_daily, ignore_index=True)
    dm_new = dm_vs_benchmark(daily_new)
    nu_new = pd.DataFrame(nu_rows)

    if plot:
        plot_main(daily_new)

    if full_replace:
        summary, daily, dm, nu_tbl = summary_new, daily_new, dm_new, nu_new
    else:
        upd = set(target_syms)
        summary = _merge_symbol_rows(TABLES / "backtest_summary.csv", summary_new, upd)
        daily = _merge_symbol_rows(TABLES / "backtest_daily.csv", daily_new, upd)
        dm = _merge_symbol_rows(TABLES / "backtest_dm_pinball.csv", dm_new, upd)
        nu_tbl = _merge_symbol_rows(TABLES / "backtest_nu.csv", nu_new, upd)

    _atomic_to_csv(summary, TABLES / "backtest_summary.csv")
    _atomic_to_csv(daily, TABLES / "backtest_daily.csv")
    _atomic_to_csv(dm, TABLES / "backtest_dm_pinball.csv")
    _atomic_to_csv(nu_tbl, TABLES / "backtest_nu.csv")
    return summary, dm, nu_tbl


def plot_main(daily):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("(bỏ qua hình: chưa cài matplotlib -> pip install matplotlib)")
        return
    FIGURES.mkdir(parents=True, exist_ok=True)
    for sym, g in daily.groupby("symbol"):
        fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
        for ax, tag in zip(axes, (95, 99)):
            base = g[g.model == MODELS[0]].sort_values("date")
            x = pd.to_datetime(base["date"])
            ax.plot(x, base["loss_pct"], color="0.55", lw=1, label="Tổn thất thực tế")
            for m in MODELS:
                h = g[g.model == m].sort_values("date")
                ax.plot(pd.to_datetime(h["date"]), h[f"var{tag}_pct"], lw=1.3, label=f"VaR{tag} {LABELS[m]}")
            ax.set_ylabel("% vị thế"); ax.set_title(f"{sym} - VaR {tag}% 1 ngày vs tổn thất thực tế")
            ax.legend(fontsize=7, ncol=3)
        fig.tight_layout()
        fig.savefig(FIGURES / f"backtest_{sym}.png", dpi=140)
        plt.close(fig)


# ---------------------------------------------------------------- phần mẫu dài rolling (2017-nay CSV + 1d parquet 35 coin)
def garch_rolling(r_pct, window=1000, refit=20):
    """GARCH(1,1)-t rolling: refit mỗi `refit` ngày trên `window` ngày gần nhất; giữa các lần refit
    cập nhật σ² bằng tham số cố định + lợi suất đã quan sát. Chỉ dùng dữ liệu đến t-1 cho ngày t.
    r_pct: log return đơn vị %. Trả (sigma_pct, nu, chỉ số bắt đầu)."""
    from arch import arch_model
    n = len(r_pct)
    sigma = np.full(n, np.nan); nu = np.full(n, np.nan)
    mu = om = al = be = nu_i = 0.0
    for i in range(window, n):
        if (i - window) % refit == 0:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = arch_model(r_pct[i - window:i], mean="Constant", vol="Garch", p=1, q=1,
                                 dist="t", rescale=False).fit(disp="off", show_warning=False)
            p = res.params
            mu, om, al, be = float(p["mu"]), float(p["omega"]), float(p["alpha[1]"]), float(p["beta[1]"])
            nu_i = float(np.clip(p["nu"], NU_MIN, NU_MAX))
            s2_prev = float(res.conditional_volatility[-1] ** 2)
            e_prev = float(res.resid[-1])
            s2 = max(om + al * e_prev ** 2 + be * s2_prev, 1e-8)
        else:
            e_prev = r_pct[i - 1] - mu
            s2 = max(om + al * e_prev ** 2 + be * s2, 1e-8)
        sigma[i], nu[i] = np.sqrt(s2), nu_i
    return sigma, nu, window


def hist_sigma(r_pct, window=1000, lookback=22):
    """σ benchmark 'Historical 22d': căn trung bình bình phương lợi suất 22 ngày gần nhất (mu=0). Chỉ dùng đến t-1."""
    n = len(r_pct)
    sg = np.full(n, np.nan)
    for i in range(window, n):
        sg[i] = np.sqrt(np.mean(r_pct[i - lookback:i] ** 2))
    return sg


def ewma_sigma(r_pct, window=1000, lam=0.94, warmup=30):
    """σ benchmark EWMA/RiskMetrics: s2_t = lam*s2_{t-1} + (1-lam)*r_{t-1}^2. Chỉ dùng đến t-1."""
    n = len(r_pct)
    s2 = np.mean(r_pct[:warmup] ** 2)
    sg = np.full(n, np.nan)
    for i in range(1, n):
        s2 = lam * s2 + (1 - lam) * r_pct[i - 1] ** 2
        if i >= window:
            sg[i] = np.sqrt(s2)
    return sg


LONG_MODELS = ("GARCH-t (rolling)", "EWMA-t (RiskMetrics)", "Historical 22d-t", "GARCH-chuẩn (đối chứng đuôi mỏng)")


def _eval_long_series(short_sym: str, dates_all, r_pct: np.ndarray, window: int, refit: int, nsim: int, source_label: str):
    sg_garch, nu, start = garch_rolling(r_pct, window, refit)
    sigmas = {"GARCH-t (rolling)": (sg_garch, "t"),
              "EWMA-t (RiskMetrics)": (ewma_sigma(r_pct, window), "t"),
              "Historical 22d-t": (hist_sigma(r_pct, window), "t"),
              "GARCH-chuẩn (đối chứng đuôi mỏng)": (sg_garch, "normal")}
    sl = slice(start, None)
    dates = np.asarray(dates_all)[sl]
    loss = -np.expm1(r_pct[sl] / 100.0)  # log return % -> simple return -> loss
    meta = {"cửa_sổ_train": int(window), "từ_ngày": str(dates[0]), "đến_ngày": str(dates[-1]), "nguồn_dữ_liệu": source_label}
    rows, dailies = [], []
    for name in LONG_MODELS:
        sg, dist = sigmas[name]
        rr, dd = evaluate(short_sym, name, dates, loss, sg[sl] / 100.0, nu[sl], dist, nsim, extra_meta=meta)
        rows += rr; dailies.append(dd)
    return rows, dailies


def _load_long_series_for_symbol(
    full_sym: str,
    csv_path: str | Path | None = None,
    window: int = 1000,
    csv_cache: pd.DataFrame | None = None,
    extend_csv_with_parquet: bool = True,
):
    """Chuẩn bị chuỗi (short_sym, dates_all, r_pct, win, source_label) cho mẫu dài rolling.
    - Với BTCUSDT / ETHUSDT: lấy chuỗi gốc từ CSV 2017–2026 (nếu có) VÀ tự động nối tiếp các ngày đóng cửa mới
      nhất sau ngày cuối của CSV từ `data/raw/<SYMBOL>_1d.parquet` (tính log-return nội tại trong Parquet để
      không có bước nhảy tỷ giá USD/USDT tại điểm nối). Nhờ đó mỗi ngày bấm Cập nhật / Nạp dữ liệu, mẫu dài
      của BTC và ETH đều tự động tiến thêm ngày mới y như 33 altcoin còn lại.
    - Với các coin còn lại: đọc trực tiếp từ `data/raw/<SYMBOL>_1d.parquet`.
    """
    full_sym = full_sym.upper()
    short_sym = full_sym.replace("USDT", "")
    p_1d = RAW / f"{full_sym}_1d.parquet"

    if short_sym in ("BTC", "ETH") and csv_cache is not None:
        col = "btc_log_return" if short_sym == "BTC" else "eth_log_return"
        dates_csv = csv_cache["date_str"].to_numpy()
        r_csv = csv_cache[col].to_numpy(float)
        if extend_csv_with_parquet and p_1d.exists():
            try:
                df1d = pd.read_parquet(p_1d).sort_values("timestamp").reset_index(drop=True)
                df1d["log_ret_pct"] = 100.0 * np.log(df1d["close"] / df1d["close"].shift(1))
                df1d["date_str"] = pd.to_datetime(df1d["timestamp"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
                newer = df1d[df1d["date_str"] > str(dates_csv[-1])].dropna(subset=["log_ret_pct"])
                if not newer.empty:
                    dates_merged = np.concatenate([dates_csv, newer["date_str"].to_numpy()])
                    r_merged = np.concatenate([r_csv, newer["log_ret_pct"].to_numpy(float)])
                    return short_sym, dates_merged, r_merged, window, "CSV 2017–2026 + Binance 1d"
            except Exception:
                pass
        return short_sym, dates_csv, r_csv, window, "CSV 2017–2026"

    if not p_1d.exists():
        return None
    df1d = pd.read_parquet(p_1d).sort_values("timestamp").reset_index(drop=True)
    if len(df1d) < 620:
        return None
    df1d["log_ret_pct"] = 100.0 * np.log(df1d["close"] / df1d["close"].shift(1))
    df1d = df1d.dropna(subset=["log_ret_pct"]).reset_index(drop=True)
    # Ưu tiên cửa sổ 1.000 ngày khi đủ dài (>=1.250 ngày -> >=250 ngày OOS); coin niêm yết mới dùng cửa sổ 500 ngày.
    win = window if len(df1d) >= window + 250 else 500
    if len(df1d) < win + 150:
        return None
    dates_1d = pd.to_datetime(df1d["timestamp"], unit="ms", utc=True).dt.strftime("%Y-%m-%d").to_numpy()
    r_1d = df1d["log_ret_pct"].to_numpy(float)
    return short_sym, dates_1d, r_1d, win, "Binance 1d lịch sử"


def run_long(
    csv_path: str | Path | None = None,
    window=1000,
    refit=20,
    nsim=4000,
    include_parquet: bool = False,
    symbols: list[str] | tuple[str, ...] | None = None,
    only_if_stale: bool = False,
):
    """Backtest dài hạn rolling cho BTC/ETH (từ CSV 2017-nay nối tiếp Binance 1d mới nhất) và mở rộng sang
    toàn bộ coin từ <SYMBOL>_1d.parquet khi include_parquet=True (hoặc truyền `symbols`).
    Khi `only_if_stale=True`, chỉ tính lại các đồng coin có ngày đóng cửa mới hơn bảng đã lưu -> cập nhật hàng ngày cực nhanh.
    """
    default_csv = RAW / "Data_daily_BTC_ETH_2017-2026.csv"
    eff_csv = Path(csv_path) if csv_path is not None else (default_csv if default_csv.exists() else None)
    csv_cache = None
    if eff_csv is not None and eff_csv.exists():
        d = pd.read_csv(eff_csv, encoding="utf-8-sig")
        d["date"] = pd.to_datetime(d["date_utc"], format="%m/%d/%Y")
        d = d.iloc[1:].reset_index(drop=True)  # dòng đầu không có giá hôm trước trong file
        d["date_str"] = d["date"].dt.strftime("%Y-%m-%d")
        csv_cache = d

    discovered = discover_symbols()
    if symbols is not None:
        target_full = tuple(s.upper() for s in symbols)
        full_replace = False
    elif include_parquet:
        target_full = discovered if discovered else ("BTCUSDT", "ETHUSDT")
        full_replace = not only_if_stale
    else:
        target_full = ("BTCUSDT", "ETHUSDT")
        full_replace = not only_if_stale

    existing_summary = None
    summary_path = TABLES / "backtest_long_summary.csv"
    if only_if_stale and summary_path.exists():
        try:
            existing_summary = pd.read_csv(summary_path, encoding="utf-8-sig")
        except Exception:
            existing_summary = None

    rows, dailies, updated_short = [], [], set()
    for full_sym in target_full:
        loaded = _load_long_series_for_symbol(full_sym, eff_csv, window, csv_cache, extend_csv_with_parquet=True)
        if loaded is None:
            continue
        short_sym, dates_all, r_pct, win, src_label = loaded
        expected_end = str(dates_all[-1])
        expected_n = len(dates_all) - win

        if only_if_stale and existing_summary is not None and "symbol" in existing_summary.columns:
            sub = existing_summary[existing_summary["symbol"].astype(str) == short_sym]
            if (
                len(sub) == len(LONG_MODELS) * len(ALPHAS)
                and "đến_ngày" in sub.columns
                and all(str(x) == expected_end for x in sub["đến_ngày"])
                and all(int(x) == expected_n for x in sub["n"])
            ):
                continue  # Đã khớp ngày đóng cửa mới nhất -> giữ nguyên kết quả đã lưu

        rr, dd = _eval_long_series(short_sym, dates_all, r_pct, win, refit, nsim, src_label)
        rows += rr
        dailies += dd
        updated_short.add(short_sym)

    if not updated_short:
        if summary_path.exists():
            s_old = pd.read_csv(summary_path, encoding="utf-8-sig")
            dm_p = TABLES / "backtest_long_dm_pinball.csv"
            dm_old = pd.read_csv(dm_p, encoding="utf-8-sig") if dm_p.exists() else pd.DataFrame()
            return s_old, dm_old
        return pd.DataFrame(), pd.DataFrame()

    summary_new = pd.DataFrame(rows)
    daily_new = pd.concat(dailies, ignore_index=True)
    dm_new = dm_vs_benchmark(daily_new, benchmark="Historical 22d-t")

    if full_replace:
        summary, daily, dm = summary_new, daily_new, dm_new
    else:
        summary = _merge_symbol_rows(TABLES / "backtest_long_summary.csv", summary_new, updated_short)
        daily = _merge_symbol_rows(TABLES / "backtest_long_daily.csv", daily_new, updated_short)
        dm = _merge_symbol_rows(TABLES / "backtest_long_dm_pinball.csv", dm_new, updated_short)

    _atomic_to_csv(summary, TABLES / "backtest_long_summary.csv")
    _atomic_to_csv(daily, TABLES / "backtest_long_daily.csv")
    _atomic_to_csv(dm, TABLES / "backtest_long_dm_pinball.csv")
    return summary, dm


def remove_symbols_from_backtest_tables(symbols: list[str]) -> None:
    """Xóa sạch dòng của các coin đã hủy niêm yết khỏi toàn bộ 7 bảng CSV backtest và hình PNG."""
    if not symbols:
        return
    drop_keys: set[str] = set()
    for s in symbols:
        su = str(s).strip().upper()
        if su:
            drop_keys.add(su)
            drop_keys.add(su.replace("USDT", ""))
            fig = FIGURES / f"backtest_{su}.png"
            if fig.exists():
                fig.unlink()
    table_names = (
        "backtest_summary.csv", "backtest_daily.csv", "backtest_dm_pinball.csv", "backtest_nu.csv",
        "backtest_long_summary.csv", "backtest_long_daily.csv", "backtest_long_dm_pinball.csv",
    )
    for name in table_names:
        path = TABLES / name
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path, encoding="utf-8-sig")
        except Exception:
            continue
        if "symbol" in df.columns:
            kept = df[~df["symbol"].astype(str).isin(drop_keys)].reset_index(drop=True)
            if len(kept) != len(df):
                _atomic_to_csv(kept, path)


def refresh_extended_backtest(
    symbols: list[str] | tuple[str, ...] | None = None,
    nsim_short: int = 5000,
    nsim_long: int = 4000,
    plot: bool = True,
    force_long: bool = False,
    refresh_short: bool = True,
    refresh_long_flag: bool = True,
):
    """Làm mới đồng bộ cả bảng tập ngắn (4 mô hình) và mẫu dài rolling theo ngày mới nhất.
    Được gọi tự động từ nút 2) Nạp dữ liệu & huấn luyện, nút 4) Cập nhật dữ liệu và các nút trên trình duyệt.
    """
    if refresh_short:
        run_main(nsim=nsim_short, plot=plot, symbols=symbols)
    if refresh_long_flag:
        run_long(
            csv_path=None,
            window=1000,
            refit=20,
            nsim=nsim_long,
            include_parquet=True,
            symbols=symbols,
            only_if_stale=not force_long,
        )


# ---------------------------------------------------------------- CLI
def _show(df, cols=None):
    with pd.option_context("display.width", 250, "display.max_columns", 50, "display.float_format", "{:.4g}".format):
        print(df if cols is None else df[cols])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--long-csv", help="Đường dẫn CSV 2017-nay để chạy phần dài hạn (kèm 1d parquet cho các coin còn lại)")
    ap.add_argument("--all-long", action="store_true", help="Chạy mẫu dài cho toàn bộ 35 coin (tự dùng CSV nếu có + 1d parquet)")
    ap.add_argument("--nsim", type=int, default=20000, help="Số mô phỏng cho kiểm định ES Z2")
    ap.add_argument("--no-plot", action="store_true", help="Bỏ qua vẽ hình PNG")
    a = ap.parse_args()
    print("=== Backtest VaR/ES: 4 mô hình, cùng tập test ===")
    summary, dm, nu = run_main(a.nsim, plot=not a.no_plot)
    print(f"\nĐã tính tập ngắn cho {nu['symbol'].nunique()} coin.")
    default_csv = RAW / "Data_daily_BTC_ETH_2017-2026.csv"
    if a.long_csv or a.all_long:
        csv_to_use = a.long_csv or (default_csv if default_csv.exists() else None)
        print("\n=== PHẦN DÀI HẠN: GARCH-t / EWMA / Historical rolling ===")
        long, long_dm = run_long(csv_to_use, include_parquet=True)
        print(f"Đã tính mẫu dài cho {long['symbol'].nunique()} coin.")
    print(f"\nĐã ghi bảng vào {TABLES} và hình vào {FIGURES}")


if __name__ == "__main__":
    main()
