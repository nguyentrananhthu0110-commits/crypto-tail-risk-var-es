"""Incremental update: chỉ tải phần thiếu từ checkpoint. Chính sách retrain mặc định:
chỉ huấn luyện lại khi có >= CRI retrain_min_new_days ngày dữ liệu mới hoặc --retrain."""
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from src.config import CONFIG
from src.data.pipeline import load_dataset, prepare_symbol_data, sync_active_symbols
from src.models.training import load_forecast, train_symbol
from src.utils.logging_setup import get_logger

log = get_logger("cri.update")

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=None)
    ap.add_argument("--retrain", action="store_true", help="Huấn luyện lại bất kể chính sách")
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
        retrained_syms: list[str] = []
        for s in target_symbols:
            s = s.upper()
            results = prepare_symbol_data(s)
            new_daily = next((r["new_rows"] for r in results if r["interval"] == "1d"), 0)
            fc = load_forecast(s)
            need = args.retrain or fc is None or new_daily >= CONFIG["retrain_min_new_days"]
            log.info("%s: +%d nến ngày mới -> retrain=%s", s, new_daily, need)
            if need:
                train_symbol(s)
                retrained_syms.append(s)
                log.info("%s: đã huấn luyện lại", s)
            else:
                log.info("%s: giữ nguyên model/forecast đã lưu (chưa có nến ngày mới đóng cửa). Dùng --retrain để ép.",
                         s)
        try:
            from src.backtest.run_backtest import run_long, run_main
            log.info("=== Kiểm tra & cập nhật bảng backtest mở rộng (tập ngắn + mẫu dài theo ngày mới) ===")
            if retrained_syms:
                run_main(nsim=5000, plot=True, symbols=retrained_syms)
            run_long(
                csv_path=None,
                window=1000,
                refit=20,
                nsim=4000,
                include_parquet=True,
                symbols=target_symbols,
                only_if_stale=not bool(args.retrain),
            )
        except Exception as bt_err:
            log.warning("Không cập nhật được bảng backtest mở rộng: %s", bt_err)
        log.info("CẬP NHẬT HOÀN TẤT")
        return 0
    except Exception as e:
        log.error("THẤT BẠI: %s", e); return 1

if __name__ == "__main__":
    raise SystemExit(main())
