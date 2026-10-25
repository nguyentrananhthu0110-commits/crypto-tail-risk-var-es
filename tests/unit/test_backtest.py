"""Known-answer tests cho src/backtest/run_backtest.py."""
import numpy as np
from scipy import stats

from src.backtest.run_backtest import basel_zone, evaluate, t_var_es, z2_test


def test_t_es_closed_form_matches_monte_carlo():
    nu, sigma, a = 4.0, 0.03, 0.99
    var, es = t_var_es(sigma, nu, a)
    rng = np.random.default_rng(0)
    x = sigma * rng.standard_t(nu, 4_000_000) * np.sqrt((nu - 2) / nu)
    mc_var = np.quantile(x, a)
    mc_es = x[x >= mc_var].mean()
    assert abs(var - mc_var) / mc_var < 0.01
    assert abs(es - mc_es) / mc_es < 0.02
    assert es > var > 0


def test_variance_is_sigma_squared():
    nu, sigma = 5.0, 0.02
    s = np.sqrt((nu - 2) / nu)
    assert abs(stats.t.var(nu, scale=sigma * s) - sigma ** 2) < 1e-12


def test_basel_traffic_light_matches_official_n250():
    assert [basel_zone(k, 250) for k in (0, 4)] == ["Xanh", "Xanh"]
    assert [basel_zone(k, 250) for k in (5, 9)] == ["Vàng", "Vàng"]
    assert basel_zone(10, 250) == "Đỏ"


def test_z2_has_correct_size_under_null_and_detects_underestimated_tail():
    rng = np.random.default_rng(1)
    T, nu, sigma, a = 500, 4.0, 0.02, 0.975
    var, es = t_var_es(sigma, nu, a)
    pv = []
    for _ in range(60):
        loss = sigma * rng.standard_t(nu, T) * np.sqrt((nu - 2) / nu)
        pv.append(z2_test(loss, np.full(T, var), np.full(T, es), np.full(T, sigma), nu, a, nsim=500)["p_value"])
    assert np.mean(np.array(pv) < 0.05) < 0.15          # kích thước kiểm định xấp xỉ 5%
    # thực tế biến động gấp 1,6 lần mô hình dự báo -> tổn thất ở đuôi bị đánh giá thấp -> phải bị bác bỏ
    loss = 1.6 * sigma * rng.standard_t(nu, 1500) * np.sqrt((nu - 2) / nu)
    r = z2_test(loss, np.full(1500, var), np.full(1500, es), np.full(1500, sigma), nu, a, nsim=500)
    assert r["z2"] > 0 and r["p_value"] < 0.05


def test_evaluate_counts_breaches_and_uses_loss_sign():
    T = 200
    sigma = np.full(T, 0.02)
    dates = [f"2026-01-{(i % 28) + 1:02d}-{i}" for i in range(T)]
    loss = np.zeros(T); loss[10] = 0.5; loss[50] = 0.5   # 2 ngày lỗ rất lớn
    rows, daily = evaluate("X", "m", dates, loss, sigma, 4.0, "t", nsim=200)
    r99 = [r for r in rows if r["mức_tin_cậy"] == "99%"][0]
    assert r99["vi_phạm"] == 2 and daily["breach99"].sum() == 2
    assert r99["ngày_vi_phạm"] == f"{dates[10]}, {dates[50]}"
    assert r99["lỗ_thực_tế_trung_bình_%_ngày_vi_phạm"] == 50.0
    assert r99["ES_dự_báo_trung_bình_%_ngày_vi_phạm"] > 0


def test_unified_train_only_nu_across_live_risk_and_backtest():
    """Thống nhất dùng ν_train xuyên suốt forecast.json (forecast_based, parametric_student_t) và backtest.json."""
    import json
    from src.config import MODEL_META_DIR
    fc_files = sorted(MODEL_META_DIR.glob("*_forecast.json"))
    assert len(fc_files) >= 2
    for fp in fc_files:
        sym = fp.name.replace("_forecast.json", "")
        fc = json.loads(fp.read_text(encoding="utf-8"))
        bt = json.loads((MODEL_META_DIR / f"{sym}_backtest.json").read_text(encoding="utf-8"))
        r = fc["risk"]
        nu_tr = r["t_df_train_only"]
        assert abs(r["t_df_used"] - nu_tr) < 1e-12
        assert abs(r["forecast_based"]["t_df"] - nu_tr) < 1e-12
        assert abs(r["parametric_student_t"]["params"]["df"] - nu_tr) < 1e-12
        assert abs(bt["t_df_used"] - nu_tr) < 1e-12


# ------------------------------------------------------------------ bổ sung: benchmark dài hạn & không nhìn trước
def test_long_benchmarks_use_only_past_data():
    """σ_t của Historical/EWMA không được đổi khi ta thay lợi suất ở ngày t trở đi."""
    from src.backtest.run_backtest import ewma_sigma, hist_sigma
    rng = np.random.default_rng(5)
    r = rng.normal(0, 2.0, 400)
    t = 300
    r2 = r.copy(); r2[t:] = 50.0                       # "tương lai" bị phá hoàn toàn
    for fn in (hist_sigma, ewma_sigma):
        a, b = fn(r, window=100), fn(r2, window=100)
        assert np.allclose(a[:t + 1], b[:t + 1], equal_nan=True)   # σ_t chỉ phụ thuộc r đến t-1
        assert np.isnan(a[:100]).all() and np.isfinite(a[100:]).all()


def test_benchmarks_track_true_vol_level():
    from src.backtest.run_backtest import ewma_sigma, hist_sigma
    r = np.random.default_rng(6).normal(0, 3.0, 3000)
    for fn in (hist_sigma, ewma_sigma):
        s = fn(r, window=200)[200:]
        assert 2.4 < np.nanmean(s) < 3.4


def test_discover_symbols_requires_all_inputs(tmp_path, monkeypatch):
    import src.backtest.run_backtest as bt
    meta, proc = tmp_path / "m", tmp_path / "p"; meta.mkdir(); proc.mkdir()
    for s in ("AAA", "BBB"):
        (meta / f"{s}USDT_performance.json").write_text("{}")
    (meta / "AAAUSDT_forecast.json").write_text("{}"); (proc / "AAAUSDT_daily.parquet").write_text("x")
    monkeypatch.setattr(bt, "META", meta); monkeypatch.setattr(bt, "PROCESSED", proc)
    assert bt.discover_symbols() == ("AAAUSDT",)       # BBB thiếu forecast/parquet -> bị bỏ qua


def test_dm_vs_benchmark_sign_convention():
    import pandas as pd
    from src.backtest.run_backtest import dm_vs_benchmark
    rng = np.random.default_rng(8)
    n = 400
    base = np.abs(rng.normal(1, 0.2, n)) + 0.5
    rows = []
    for m, pl in (("bench", base), ("better", base - 0.3)):
        rows.append(pd.DataFrame({"symbol": "X", "model": m, "date": np.arange(n),
                                  "pinball95": pl, "pinball99": pl}))
    out = dm_vs_benchmark(pd.concat(rows), benchmark="bench")
    assert (out["DM_stat"] < 0).all() and (out["p_value"] < 0.01).all()   # âm = tốt hơn benchmark


def test_backtest_uses_train_only_nu():
    """_backtest phải dùng ν truyền vào (train-only) và ghi lại; ν nhỏ hơn -> đuôi dày hơn -> VaR99 lớn hơn."""
    import pandas as pd
    from src.models.training import _backtest
    n = 60
    daily = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=n, tz="UTC"),
                          "simple_return": np.random.default_rng(2).normal(0, 0.02, n)})
    dates = [d.strftime("%Y-%m-%d") for d in daily["date"][30:]]
    fv = np.full(len(dates), 0.02 ** 2)
    a = _backtest(daily, dates, fv, 3.0, 1000.0)
    b = _backtest(daily, dates, fv, 30.0, 1000.0)
    assert a["t_df_used"] == 3.0 and b["t_df_used"] == 30.0
    assert a["series"][0]["var99_usd"] > b["series"][0]["var99_usd"]


def test_xgb_log_rv_never_collapses_to_eps_on_spiky_altcoins():
    """XGBoost trên log(RV) + Duan smearing không bao giờ dự báo âm/sập về 1e-12 làm nổ QLIKE & ES-Z2."""
    from src.models.volatility import make_xgb_regressor, qlike
    rng = np.random.default_rng(42)
    X_tr = rng.uniform(0, 1, (300, 6))
    y_tr = 0.0008 + 0.002 * X_tr[:, 0]
    y_tr[[10, 50, 120]] = 0.25  # các phiên sập cực đoan (spike gấp >100 lần)
    X_te = np.zeros((50, 6))    # giai đoạn cực lặng sóng dễ khiến cây tuyến tính gốc dự báo âm
    y_te = np.full(50, 0.0009)
    m, eng = make_xgb_regressor()
    m.fit(X_tr, y_tr)
    pred = m.predict(X_te)
    assert "log_rv" in eng
    assert (pred > 1e-6).all()
    assert qlike(y_te, pred) < 5.0


def test_dataset_quality_flags_delisted_stale_candles(tmp_path, monkeypatch):
    import pandas as pd
    import src.data.pipeline as pl
    old_ms = 1_700_000_000_000  # quá khứ xa (>7 ngày trước)
    df = pd.DataFrame({
        "timestamp": [old_ms, old_ms + 86_400_000],
        "open": [10.0, 10.5], "high": [11.0, 11.2], "low": [9.5, 10.0],
        "close": [10.5, 10.8], "volume": [100.0, 120.0],
        "quote_volume": [1050.0, 1296.0], "close_time": [old_ms + 86_399_999, old_ms + 172_799_999],
        "trades": [10, 12],
    })
    p = tmp_path / "OLDUSDT_1d.parquet"
    df.to_parquet(p, index=False)
    monkeypatch.setattr(pl, "dataset_path", lambda s, i: p)
    q = pl.dataset_quality("OLDUSDT", "1d")
    assert q["stale_listing"] is True and q["ok"] is False and q["stale_days"] > 7


def test_long_series_stitches_newer_parquet_days_and_incremental_refresh(tmp_path, monkeypatch):
    """BTC/ETH mẫu dài tự nối thêm các ngày đóng cửa mới từ <SYMBOL>_1d.parquet sau ngày cuối CSV
    mà không bị bước nhảy tỷ giá USD/USDT, và only_if_stale bỏ qua khi chưa có ngày mới."""
    import pandas as pd
    import src.backtest.run_backtest as bt

    raw_dir = tmp_path / "raw"
    tables_dir = tmp_path / "tables"
    raw_dir.mkdir(); tables_dir.mkdir()
    monkeypatch.setattr(bt, "RAW", raw_dir)
    monkeypatch.setattr(bt, "TABLES", tables_dir)

    rng = np.random.default_rng(123)
    dates_csv = pd.date_range("2025-01-01", periods=220, tz="UTC")
    csv_df = pd.DataFrame({
        "date_utc": dates_csv.strftime("%m/%d/%Y"),
        "btc_close_usd": 50_000.0,
        "eth_close_usd": 2_500.0,
        "btc_log_return": rng.normal(0, 2.0, len(dates_csv)),
        "eth_log_return": rng.normal(0, 2.5, len(dates_csv)),
    })
    csv_path = raw_dir / "Data_daily_BTC_ETH_2017-2026.csv"
    csv_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    # Parquet có thêm 3 ngày mới sau ngày cuối của CSV, với mức giá USDT chênh 0.2% so với USD
    dates_pq = pd.date_range("2025-08-05", periods=7, tz="UTC")  # chồng lấn trước & vượt qua ngày cuối CSV (2025-08-08)
    closes = [50100.0, 50200.0, 50300.0, 50400.0, 51408.0, 50893.92, 51911.80]
    pq_df = pd.DataFrame({
        "timestamp": (dates_pq.view("int64") // 1_000_000),
        "open": closes, "high": closes, "low": closes, "close": closes,
        "volume": 100.0, "quote_volume": 1000.0,
        "close_time": (dates_pq.view("int64") // 1_000_000) + 86_399_999, "trades": 10,
    })
    pq_df.to_parquet(raw_dir / "BTCUSDT_1d.parquet", index=False)

    # Lần 1: chạy với window=120 -> phải nối thêm đúng 3 ngày (2025-08-09..2025-08-11)
    summary1, _ = bt.run_long(csv_path=csv_path, window=120, refit=40, nsim=100, symbols=["BTCUSDT"], only_if_stale=True)
    assert set(summary1["symbol"]) == {"BTC"}
    assert summary1["đến_ngày"].iloc[0] == "2025-08-11"
    assert int(summary1["n"].iloc[0]) == (219 + 3) - 120
    assert "Binance 1d" in summary1["nguồn_dữ_liệu"].iloc[0]

    # Lần 2: chưa có ngày mới -> only_if_stale=True bỏ qua tính toán lại ngay lập tức
    calls = []
    orig_eval = bt._eval_long_series
    monkeypatch.setattr(bt, "_eval_long_series", lambda *a, **k: calls.append(1) or orig_eval(*a, **k))
    bt.run_long(csv_path=csv_path, window=120, refit=40, nsim=100, symbols=["BTCUSDT"], only_if_stale=True)
    assert calls == []

    # Lần 3: ngày mới đóng cửa (2025-08-12) được nạp vào Parquet -> tự động tính tiếp lên n+1!
    next_ts = int(pq_df["timestamp"].iloc[-1]) + 86_400_000
    pq_df2 = pd.concat([pq_df, pd.DataFrame([{
        "timestamp": next_ts, "open": 52000.0, "high": 52500.0, "low": 51500.0, "close": 52430.92,
        "volume": 100.0, "quote_volume": 1000.0, "close_time": next_ts + 86_399_999, "trades": 10,
    }])], ignore_index=True)
    pq_df2.to_parquet(raw_dir / "BTCUSDT_1d.parquet", index=False)
    summary3, _ = bt.run_long(csv_path=csv_path, window=120, refit=40, nsim=100, symbols=["BTCUSDT"], only_if_stale=True)
    assert len(calls) == 1
    assert summary3["đến_ngày"].iloc[0] == "2025-08-12"
    assert int(summary3["n"].iloc[0]) == (219 + 4) - 120


def test_sync_active_symbols_purges_delisted_everywhere_and_preserves_offline(tmp_path, monkeypatch):
    """Khi một coin bị sàn hủy giao dịch (không còn status=='TRADING'), sync_active_symbols phải xóa sạch
    khỏi config.json, CONFIG['symbols'], data/, models/, SQLite và bảng CSV backtest; nếu mất mạng thì giữ an toàn."""
    import json
    import pandas as pd
    import src.config as cfg_mod
    import src.storage as st_mod
    import src.backtest.run_backtest as bt_mod
    import src.data.pipeline as pl_mod
    from src.data.binance_client import BinanceError

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"symbols": ["BTCUSDT", "ETHUSDT", "DEADUSDT"]}, indent=2), encoding="utf-8")
    orig_symbols = list(cfg_mod.CONFIG["symbols"])

    raw_d = tmp_path / "raw"; proc_d = tmp_path / "proc"; feat_d = tmp_path / "feat"
    saved_d = tmp_path / "saved"; meta_d = tmp_path / "model_meta"
    db_d = tmp_path / "db"; tables_d = tmp_path / "tables"; figs_d = tmp_path / "figs"
    for d in (raw_d, proc_d, feat_d, saved_d, meta_d, db_d, tables_d, figs_d):
        d.mkdir(parents=True, exist_ok=True)

    try:
        monkeypatch.setattr(cfg_mod, "CONFIG_PATH", cfg_path)
        monkeypatch.setattr(cfg_mod, "RAW_DIR", raw_d)
        monkeypatch.setattr(cfg_mod, "PROCESSED_DIR", proc_d)
        monkeypatch.setattr(cfg_mod, "FEATURES_DIR", feat_d)
        monkeypatch.setattr(cfg_mod, "SAVED_DIR", saved_d)
        monkeypatch.setattr(cfg_mod, "MODEL_META_DIR", meta_d)
        monkeypatch.setattr(cfg_mod, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(st_mod, "METADATA_DIR", db_d)
        monkeypatch.setattr(st_mod, "MANIFEST_DB", db_d / "manifest.sqlite")
        monkeypatch.setattr(bt_mod, "TABLES", tables_d)
        monkeypatch.setattr(bt_mod, "FIGURES", figs_d)
        cfg_mod.CONFIG["symbols"][:] = ["BTCUSDT", "ETHUSDT", "DEADUSDT"]

        # Tạo đủ artifacts giả lập cho BTCUSDT, DEADUSDT (bị hủy trên sàn) và ORPHANUSDT (file mồ côi)
        for sym in ("BTCUSDT", "DEADUSDT", "ORPHANUSDT"):
            (raw_d / f"{sym}_1d.parquet").write_bytes(b"pq")
            (saved_d / f"{sym}_xgb.joblib").write_bytes(b"jb")
            (meta_d / f"{sym}_forecast.json").write_text("{}", encoding="utf-8")
            (figs_d / f"backtest_{sym}.png").write_bytes(b"png")
            st_mod.upsert_dataset(sym, "1d", "test", 1, 2, 10)
        pd.DataFrame({"symbol": ["BTCUSDT", "DEADUSDT", "ORPHANUSDT"], "n": [10, 10, 10]}).to_csv(
            tables_d / "backtest_summary.csv", index=False, encoding="utf-8-sig"
        )
        pd.DataFrame({"symbol": ["BTC", "DEAD", "ORPHAN"], "n": [100, 100, 100]}).to_csv(
            tables_d / "backtest_long_summary.csv", index=False, encoding="utf-8-sig"
        )

        # 1) Offline: không xóa nhầm DEADUSDT trong config, nhưng vẫn dọn ORPHANUSDT mồ côi
        class OfflineClient:
            def fetch_active_spot_symbols(self):
                raise BinanceError("offline")

        res_off = pl_mod.sync_active_symbols(check_exchange=True, persist_config=True, client=OfflineClient())
        assert res_off["exchange_checked"] is False
        assert "DEADUSDT" in cfg_mod.CONFIG["symbols"]
        assert "ORPHANUSDT" in res_off["removed_orphans"]
        assert not (raw_d / "ORPHANUSDT_1d.parquet").exists()

        # 2) Online: Binance trả về >=50 cặp TRADING và KHÔNG còn DEADUSDT -> tự động xóa sạch mọi nơi!
        active_fake = {"BTCUSDT", "ETHUSDT"} | {f"COIN{i}USDT" for i in range(60)}
        class OnlineClient:
            def fetch_active_spot_symbols(self):
                return active_fake

        res_on = pl_mod.sync_active_symbols(check_exchange=True, persist_config=True, client=OnlineClient())
        assert res_on["exchange_checked"] is True
        assert res_on["removed_delisted"] == ["DEADUSDT"]
        assert cfg_mod.CONFIG["symbols"] == ["BTCUSDT", "ETHUSDT"]
        assert json.loads(cfg_path.read_text(encoding="utf-8"))["symbols"] == ["BTCUSDT", "ETHUSDT"]
        assert not (raw_d / "DEADUSDT_1d.parquet").exists()
        assert not (saved_d / "DEADUSDT_xgb.joblib").exists()
        assert not (meta_d / "DEADUSDT_forecast.json").exists()
        assert not (figs_d / "backtest_DEADUSDT.png").exists()
        assert "DEADUSDT" not in {r["symbol"] for r in st_mod.get_datasets()}
        assert list(pd.read_csv(tables_d / "backtest_summary.csv")["symbol"]) == ["BTCUSDT"]
        assert list(pd.read_csv(tables_d / "backtest_long_summary.csv")["symbol"]) == ["BTC"]
        # BTCUSDT vẫn còn nguyên vẹn!
        assert (raw_d / "BTCUSDT_1d.parquet").exists()
    finally:
        cfg_mod.CONFIG["symbols"][:] = orig_symbols
