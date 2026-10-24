"""Huấn luyện toàn bộ baseline trên train (chronological split), đánh giá OOS thật,
lưu model + metadata + forecast/backtest artifacts để dashboard load lại ngay.

Artifacts mỗi symbol (models/metadata/<SYMBOL>_*.json, models/saved/...):
- forecast.json  : dự báo mới nhất + VaR/ES 3 phương pháp + regime + diễn giải
- performance.json: chuỗi OOS actual-vs-forecast + metrics + Diebold-Mariano
- backtest.json   : breach timeline + Kupiec/Christoffersen + quantile loss
- explain.json    : feature importance (permutation) + tham số mô hình
"""
from __future__ import annotations
import joblib
import numpy as np
import pandas as pd
from src.config import CONFIG, MODEL_META_DIR, SAVED_DIR
from src.data.pipeline import load_dataset
from src.features.build import FEATURE_COLS, FEATURE_SCHEMA, compute_and_save
from src.models.volatility import (HARModel, diebold_mariano, fit_garch, garch_forecast_var,
                                   mae, make_xgb_regressor, permutation_importance, qlike, rmse)
from src.risk import regime as regime_mod
from src.risk.var_es import (christoffersen_test, fit_student_t, forecast_var_es,
                             historical_var_es, kupiec_test, parametric_t_var_es, quantile_loss)
from src.storage import atomic_write_json, log_job, upsert_model, utcnow_iso
from src.utils.logging_setup import get_logger

log = get_logger("cri.training")
ANN = np.sqrt(365)  # crypto giao dịch 365 ngày/năm

def _metrics(actual_var, fc_var) -> dict:
    a = np.sqrt(np.clip(np.asarray(actual_var, float), 0, None))
    f = np.sqrt(np.clip(np.asarray(fc_var, float), 1e-12, None))
    return {"mae_vol": mae(a, f), "rmse_vol": rmse(a, f), "qlike": qlike(actual_var, fc_var),
            "n": int(len(a))}

def chronological_split(n: int, train_ratio: float) -> tuple[range, range]:
    """Chia train/test THEO THỜI GIAN (không bao giờ xáo trộn ngẫu nhiên -> tránh rò rỉ)."""
    if n < 2 or not (0 < train_ratio < 1):
        raise ValueError("n và train_ratio không hợp lệ cho chronological split")
    cut = int(n * train_ratio)
    cut = min(max(cut, 1), n - 1)
    return range(0, cut), range(cut, n)

def _safe(v):
    return None if v is None or (isinstance(v, float) and not np.isfinite(v)) else float(v)

def train_symbol(symbol: str, position_usd: float | None = None) -> dict:
    symbol = symbol.upper(); started = utcnow_iso()
    position = float(position_usd or CONFIG["reference_position_usd"])
    hourly = load_dataset(symbol, "1h")
    if hourly is None or len(hourly) < 24 * 90:
        raise RuntimeError(f"{symbol}: chưa đủ dữ liệu 1h để huấn luyện (cần >=90 ngày). Hãy chạy prepare_data.")
    others = [s for s in CONFIG["symbols"] if s != symbol]
    hourly_other = load_dataset(others[0], "1h") if others else None
    daily, feats = compute_and_save(symbol, hourly, hourly_other)

    df = feats.dropna(subset=FEATURE_COLS + ["target_rv"]).reset_index(drop=True)
    if len(df) < 120:
        raise RuntimeError(f"{symbol}: chỉ có {len(df)} quan sát ngày hợp lệ (cần >=120).")
    tr_idx, te_idx = chronological_split(len(df), CONFIG["train_ratio"])
    train, test = df.iloc[list(tr_idx)], df.iloc[list(te_idx)]
    ytr_rv, yte_rv = train["target_rv"].to_numpy(), test["target_rv"].to_numpy()
    dates_test = [pd.Timestamp(d).strftime("%Y-%m-%d") for d in test["target_date"]]

    # --- Historical baseline: trung bình RV 22 ngày (feature rv_m) ---
    fc_hist = test["rv_m"].to_numpy()

    # --- HAR-RV ---
    har = HARModel().fit(train["rv_lag1"], train["rv_w"], train["rv_m"], ytr_rv)
    fc_har = har.predict_var(test["rv_lag1"].to_numpy(), test["rv_w"].to_numpy(), test["rv_m"].to_numpy())

    # --- GARCH(1,1) trên log-return ngày: OOS bằng expanding refit định kỳ ---
    rets_all = daily["log_return"].to_numpy()
    daily_dates = [pd.Timestamp(d).strftime("%Y-%m-%d") for d in daily["date"]]
    # Ánh xạ ngày target của test -> chỉ số trong daily để lấy dự báo GARCH 1-bước
    date_to_idx = {d: i for i, d in enumerate(daily_dates)}
    first_test_idx = date_to_idx[dates_test[0]]
    garch_fc_all = _garch_oos(rets_all, first_test_idx)
    fc_garch = np.array([garch_fc_all[date_to_idx[d]] for d in dates_test])
    garch_state = fit_garch(rets_all[np.isfinite(rets_all)])  # fit cuối trên toàn bộ dữ liệu đã có cho dự báo tới
    garch_state.pop("sigma2_series", None)

    # --- XGBoost: target RV (phương sai) ---
    xgb, xgb_engine = make_xgb_regressor()
    xgb.fit(train[FEATURE_COLS].to_numpy(), ytr_rv)
    fc_xgb = np.clip(xgb.predict(test[FEATURE_COLS].to_numpy()), 1e-12, None)
    imp = permutation_importance(xgb, test[FEATURE_COLS].to_numpy(), yte_rv, FEATURE_COLS)

    forecasts_var = {"historical_22d": fc_hist, "garch_1_1": fc_garch, "har_rv": fc_har, "xgboost": fc_xgb}
    metrics = {k: _metrics(yte_rv, v) for k, v in forecasts_var.items()}
    best_model = min(metrics, key=lambda k: metrics[k]["qlike"])
    # Diebold-Mariano: best vs từng mô hình còn lại (tổn thất bình phương trên phương sai)
    dm = {}
    for k, v in forecasts_var.items():
        if k == best_model: continue
        dm[f"{best_model}_vs_{k}"] = diebold_mariano((yte_rv - forecasts_var[best_model]) ** 2,
                                                     (yte_rv - v) ** 2)

    # --- Dự báo cho ngày kế tiếp từ quan sát đầy đủ gần nhất ---
    last = feats.dropna(subset=FEATURE_COLS).iloc[-1]
    var_1d = {
        "historical_22d": float(last["rv_m"]),
        "har_rv": float(har.predict_var(float(last["rv_lag1"]), float(last["rv_w"]), float(last["rv_m"]))[0]),
        "xgboost": float(np.clip(xgb.predict(last[FEATURE_COLS].to_numpy().reshape(1, -1))[0], 1e-12, None)),
    }
    total7, seq7 = garch_forecast_var(garch_state, 7)
    var_1d["garch_1_1"] = seq7[0]
    vol_1d = {k: float(np.sqrt(v)) for k, v in var_1d.items()}
    best_vol = vol_1d[best_model]
    vol_7d_best = float(np.sqrt(total7)) if best_model == "garch_1_1" else float(best_vol * np.sqrt(7))

    # --- Risk: VaR/ES ---
    train_vol = np.sqrt(np.clip(train["rv_lag1"].to_numpy(), 0, None))
    thresholds = regime_mod.fit_thresholds(train_vol)
    reg = regime_mod.classify(best_vol, thresholds, train_vol)
    rets_simple_train = daily["simple_return"].dropna().to_numpy()[-250:]
    t_fit = fit_student_t(daily["simple_return"].dropna().to_numpy())
    risk = {
        "reference_position_usd": position, "horizon_days": 1, "selected_model": best_model,
        "selection_rule": "QLIKE out-of-sample thấp nhất trên tập test theo thứ tự thời gian",
        "forecast_based": forecast_var_es(best_vol, t_fit["df"], position),
        "historical_simulation": historical_var_es(rets_simple_train, position),
        "parametric_student_t": parametric_t_var_es(daily["simple_return"].dropna().to_numpy(), position),
        "convention": "LOSS = -simple_return x position (số dương = lỗ). VaR là ngưỡng lỗ, không phải lỗ tối đa.",
    }
    for m in ("forecast_based", "historical_simulation", "parametric_student_t"):
        for a in (95, 99):
            risk[m][f"var_{a}_pct"] = _safe(risk[m][f"var_{a}"] / position * 100)
            risk[m][f"es_{a}_pct"] = _safe(risk[m][f"es_{a}"] / position * 100)

    # --- Backtest OOS với VaR forecast-based của mô hình được chọn ---
    backtest = _backtest(daily, dates_test, forecasts_var[best_model], t_fit["df"], position)

    forecast = {
        "symbol": symbol, "status": "ready", "generated_at_utc": utcnow_iso(),
        "model_version": CONFIG["model_version"], "feature_version": CONFIG["feature_version"],
        "train_period": {"start": str(pd.Timestamp(train["date"].iloc[0]).date()),
                         "end": str(pd.Timestamp(train["date"].iloc[-1]).date()), "n_train": int(len(train))},
        "test_period": {"start": dates_test[0], "end": dates_test[-1], "n_test": int(len(test))},
        "last_closed_day": str(pd.Timestamp(last["date"]).date()),
        "horizon_days": 1, "selected_model": best_model,
        "forecast_vol_daily": best_vol, "forecast_vol_annualized_pct": _safe(best_vol * ANN * 100),
        "forecast_vol_7d": vol_7d_best,
        "forecast_7d_note": ("Tổng phương sai 7 ngày từ đường cong GARCH" if best_model == "garch_1_1"
                             else "vol 1 ngày x sqrt(7) (giả định độc lập, chỉ để tham chiếu quy mô)"),
        "models_vol_daily": vol_1d,
        "models_vol_annualized_pct": {k: _safe(v * ANN * 100) for k, v in vol_1d.items()},
        "current_realized_vol_daily": _safe(np.sqrt(float(last["rv_lag1"]))),
        "current_realized_vol_annualized_pct": _safe(np.sqrt(float(last["rv_lag1"])) * ANN * 100),
        "regime": reg, "risk": risk, "metrics_oos": metrics,
        "interpretation": _interpret(symbol, reg, risk, best_model, metrics, position),
        "limitations": [
            "Dự báo volatility không dự báo hướng giá tăng/giảm.",
            "VaR/ES dựa trên phân phối quá khứ/mô hình tham số; cú sốc chưa từng xuất hiện có thể vượt xa ước lượng.",
            "RV ngày tính từ lợi suất 1h, không dùng dữ liệu tick; microstructure noise có thể ảnh hưởng.",
            "Mô hình được chọn theo QLIKE out-of-sample trong cửa sổ test hiện tại; thứ hạng có thể đổi khi dữ liệu mới đến.",
        ],
    }
    performance = {
        "symbol": symbol, "dates": dates_test,
        "actual_vol_daily": [ _safe(x) for x in np.sqrt(np.clip(yte_rv, 0, None))],
        "forecasts_vol_daily": {k: [_safe(x) for x in np.sqrt(np.clip(v, 0, None))] for k, v in forecasts_var.items()},
        "metrics": metrics, "selected_model": best_model, "diebold_mariano": dm,
        "note": "Tập test theo thứ tự thời gian, chưa dùng để fit tham số (GARCH refit mở rộng chỉ dùng dữ liệu quá khứ).",
    }
    explain = {
        "symbol": symbol,
        "feature_importance": imp, "feature_schema": FEATURE_SCHEMA,
        "importance_method": "Permutation importance trên tập test (mức tăng RMSE khi xáo trộn feature). Không phải bằng chứng nhân quả.",
        "garch": {k: garch_state.get(k) for k in ("engine","mu","omega","alpha","beta","nu","unconditional_var")},
        "har": har.to_dict(), "xgboost_engine": xgb_engine,
        "xgboost_params": {k: str(v) for k, v in xgb.get_params().items()} if hasattr(xgb, "get_params") else {},
    }

    # --- Lưu bền vững ---
    joblib.dump({"model": xgb, "engine": xgb_engine, "features": FEATURE_COLS}, SAVED_DIR / f"{symbol}_xgboost.joblib")
    atomic_write_json(har.to_dict(), SAVED_DIR / f"{symbol}_har.json")
    atomic_write_json(garch_state, SAVED_DIR / f"{symbol}_garch.json")
    atomic_write_json(forecast, MODEL_META_DIR / f"{symbol}_forecast.json")
    atomic_write_json(performance, MODEL_META_DIR / f"{symbol}_performance.json")
    atomic_write_json(backtest, MODEL_META_DIR / f"{symbol}_backtest.json")
    atomic_write_json(explain, MODEL_META_DIR / f"{symbol}_explain.json")
    for mt, fp in (("har_rv", SAVED_DIR/f"{symbol}_har.json"), ("garch_1_1", SAVED_DIR/f"{symbol}_garch.json"),
                   ("xgboost", SAVED_DIR/f"{symbol}_xgboost.joblib"), ("historical_22d", "in_memory_rule")):
        upsert_model(symbol, mt, forecast["train_period"]["start"], forecast["train_period"]["end"], 1,
                     str(fp), metrics.get(mt, {}), CONFIG["model_version"], FEATURE_SCHEMA)
    log_job("train", symbol, "success", f"best={best_model} metrics={metrics}", started)
    log.info("%s: huấn luyện xong. Best=%s QLIKE=%s", symbol, best_model,
             {k: round(v['qlike'], 4) for k, v in metrics.items()})
    return forecast

def _garch_oos(returns, start_idx):
    from src.models.volatility import garch_oos_forecasts
    rets = np.nan_to_num(np.asarray(returns, float), nan=0.0)
    return garch_oos_forecasts(rets, start_idx, refit_every=20)

def _backtest(daily, dates_test, fc_var_best, t_df, position):
    daily = daily.copy()
    daily["date_str"] = [pd.Timestamp(d).strftime("%Y-%m-%d") for d in daily["date"]]
    idx = {d: i for i, d in enumerate(daily["date_str"])}
    rows, ind95, ind99, var95s, losses = [], [], [], [], []
    from scipy import stats as _st
    dfree = float(np.clip(t_df, 2.5, 100))
    for d, fv in zip(dates_test, fc_var_best):
        r = float(daily.iloc[idx[d]]["simple_return"])
        loss = -r * position
        sigma = float(np.sqrt(max(fv, 1e-12)))
        scale = sigma * np.sqrt((dfree - 2) / dfree)
        v95 = float(-_st.t.ppf(0.05, dfree) * scale * position)
        v99 = float(-_st.t.ppf(0.01, dfree) * scale * position)
        b95, b99 = int(loss > v95), int(loss > v99)
        ind95.append(b95); ind99.append(b99); var95s.append(v95); losses.append(loss)
        rows.append({"date": d, "loss_usd": _safe(loss), "var95_usd": _safe(v95), "var99_usd": _safe(v99),
                     "breach95": bool(b95), "breach99": bool(b99), "forecast_vol_daily": _safe(sigma)})
    return {
        "method": "VaR forecast-based (mô hình được chọn bởi QLIKE) trên tập test out-of-sample",
        "reference_position_usd": position, "series": rows,
        "summary_95": {"n": len(rows), "breaches": int(sum(ind95)), "breach_rate": _safe(np.mean(ind95)),
                       "quantile_loss": _safe(quantile_loss(losses, var95s, 0.95)),
                       "kupiec": kupiec_test(int(sum(ind95)), len(rows), 0.95),
                       "christoffersen": christoffersen_test(ind95, 0.95)},
        "summary_99": {"n": len(rows), "breaches": int(sum(ind99)), "breach_rate": _safe(np.mean(ind99)),
                       "kupiec": kupiec_test(int(sum(ind99)), len(rows), 0.99),
                       "christoffersen": christoffersen_test(ind99, 0.99)},
    }

def _interpret(symbol, reg, risk, best_model, metrics, position) -> dict:
    fb = risk["forecast_based"]
    pct = reg.get("percentile_vs_train")
    pct_txt = f" Cao hơn khoảng {pct:.0f}% số ngày trong giai đoạn huấn luyện." if pct is not None else ""
    market = (f"Volatility dự báo của {symbol.replace('USDT','/USDT')} đang ở mức {reg['label_vi'].lower()} "
              f"theo phân vị của tập huấn luyện.{pct_txt} Điều này cho biết quy mô dao động có thể xảy ra, "
              f"không cho biết giá sẽ tăng hay giảm.")
    risk_txt = (f"VaR 95% 1 ngày khoảng {fb['var_95']:,.0f} USD trên vị thế tham chiếu {position:,.0f} USD: theo mô hình, "
                f"mức lỗ vượt ngưỡng này có xác suất đuôi khoảng 5% trong một ngày. Đây không phải mức lỗ tối đa. "
                f"Expected Shortfall 95% khoảng {fb['es_95']:,.0f} USD là mức lỗ trung bình có điều kiện trong nhóm 5% kết quả tệ nhất.")
    model_txt = (f"Mô hình được dùng cho VaR là {best_model} vì có QLIKE out-of-sample thấp nhất "
                 f"({metrics[best_model]['qlike']:.3f}) trong kỳ kiểm tra hiện tại.")
    return {"market_summary": market, "risk_summary": risk_txt, "model_summary": model_txt,
            "what_could_be_wrong": [
                "Tin tức/sự kiện thanh khoản cực đoan ngoài mẫu lịch sử có thể làm realized vol vượt xa dự báo.",
                "Phân phối Student-t giả định đuôi đối xứng; thực tế đuôi giảm có thể nặng hơn.",
                "Nếu dữ liệu mới chưa được cập nhật (stale), dự báo phản ánh trạng thái cũ, không phải hiện tại.",
            ]}

def model_files_status(symbol: str, deep: bool = False) -> dict:
    """Kiểm tra tính toàn vẹn file model đã lưu.

    deep=True thực sự joblib.load XGBoost (chỉ dùng ở check_status/test, không dùng khi polling UI).
    Trạng thái từng file: ok | missing | corrupt | empty.
    """
    from src.storage import json_state
    s = symbol.upper(); files = {}
    for name in ("garch", "har"):
        state, _ = json_state(SAVED_DIR / f"{s}_{name}.json")
        files[name] = state
    xgb_path = SAVED_DIR / f"{s}_xgboost.joblib"
    if not xgb_path.exists():
        files["xgboost"] = "missing"
    elif xgb_path.stat().st_size == 0:
        files["xgboost"] = "empty"
    elif deep:
        try:
            obj = joblib.load(xgb_path)
            files["xgboost"] = "ok" if isinstance(obj, dict) and "model" in obj else "corrupt"
        except Exception:
            files["xgboost"] = "corrupt"
    else:
        files["xgboost"] = "ok"
    overall = "ok" if all(v == "ok" for v in files.values()) else ("corrupt" if "corrupt" in files.values() or "empty" in files.values() else "missing")
    return {"overall": overall, "files": files, "deep_checked": bool(deep)}

def forecast_state(symbol: str) -> tuple[str, dict | None]:
    """missing | corrupt | ok cho artifact forecast — để hướng dẫn cách sửa đúng."""
    from src.storage import json_state
    return json_state(MODEL_META_DIR / f"{symbol.upper()}_forecast.json")

def load_forecast(symbol: str) -> dict | None:
    from src.storage import read_json
    return read_json(MODEL_META_DIR / f"{symbol.upper()}_forecast.json")
def load_named(symbol: str, name: str) -> dict | None:
    from src.storage import read_json
    return read_json(MODEL_META_DIR / f"{symbol.upper()}_{name}.json")

def recompute_risk_for_position(forecast: dict, position_usd: float) -> dict:
    """Tái tính nhanh VaR/ES khi người dùng đổi quy mô vị thế (VaR tỉ lệ tuyến tính với vị thế)."""
    import copy
    f = copy.deepcopy(forecast); base = f["risk"]["reference_position_usd"]; ratio = position_usd / base
    for m in ("forecast_based", "historical_simulation", "parametric_student_t"):
        for a in (95, 99):
            f["risk"][m][f"var_{a}"] *= ratio; f["risk"][m][f"es_{a}"] *= ratio
    f["risk"]["reference_position_usd"] = float(position_usd)
    return f
