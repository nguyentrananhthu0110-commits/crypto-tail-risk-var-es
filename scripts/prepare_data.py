"""First-time setup: tải lịch sử -> features -> huấn luyện baseline -> lưu artifacts.
Chạy lại vẫn an toàn (incremental nếu đã có dữ liệu), trừ khi dùng --full."""
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config import CONFIG
from src.data.pipeline import prepare_symbol_data, sync_active_symbols
from src.models.training import train_symbol
from src.utils.logging_setup import get_logger

log = get_logger("cri.prepare")

def main() -> int:
    ap = argparse.ArgumentParser(description="Chuẩn bị dữ liệu & huấn luyện ban đầu")
    ap.add_argument("--symbols", nargs="+", default=None)
    ap.add_argument("--full", action="store_true", help="Tải lại toàn bộ lịch sử (ghi đè có chủ đích)")
    ap.add_argument("--skip-train", action="store_true")
    args = ap.parse_args()
    try:
        sync_res = sync_active_symbols(check_exchange=True, persist_config=True)
        if sync_res["removed_delisted"] or sync_res["removed_orphans"]:
            log.info("Đã dọn dẹp coin ngừng giao dịch/dư thừa: delisted=%s, orphans=%s",
                     sync_res["removed_delisted"], sync_res["removed_orphans"])
        active_set = set(CONFIG["symbols"])
        target_symbols = (
            [s.upper() for s in args.symbols if not sync_res["exchange_checked"] or s.upper() in active_set]
            if args.symbols else list(CONFIG["symbols"])
        )
        for s in target_symbols:
            log.info("=== %s: dữ liệu ===", s.upper())
            for r in prepare_symbol_data(s.upper(), force_full=args.full):
                log.info("  %s %s: %s, %d nến (+%d mới), gaps=%d", r["symbol"], r["interval"],
                         r["mode"], r["rows"], r["new_rows"], r["validation"]["gap_count"])
        if not args.skip_train:
            for s in target_symbols:
                log.info("=== %s: huấn luyện GARCH/HAR-RV/XGBoost ===", s.upper())
                f = train_symbol(s.upper())
                log.info("  Xong. Mô hình được chọn: %s | Vol dự báo năm-hoá: %.1f%% | Regime: %s",
                         f["selected_model"], f["forecast_vol_annualized_pct"], f["regime"]["label_vi"])
            try:
                from src.backtest.run_backtest import refresh_extended_backtest
                log.info("=== Cập nhật bảng backtest mở rộng (cả tập ngắn & mẫu dài rolling) ===")
                refresh_extended_backtest(
                    symbols=[s.upper() for s in target_symbols],
                    nsim_short=5000,
                    nsim_long=4000,
                    plot=True,
                    force_long=bool(args.full),
                )
            except Exception as bt_err:
                log.warning("Không cập nhật được bảng backtest mở rộng: %s", bt_err)
        log.info("HOÀN TẤT. Giờ có thể chạy run_app.cmd")
        return 0
    except Exception as e:
        log.error("THẤT BẠI: %s", e)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
