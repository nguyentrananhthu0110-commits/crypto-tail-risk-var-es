"""Incremental update: chỉ tải phần thiếu từ checkpoint. Chính sách retrain mặc định:
chỉ huấn luyện lại khi có >= CRI retrain_min_new_days ngày dữ liệu mới hoặc --retrain."""
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from src.config import CONFIG
from src.data.pipeline import load_dataset, prepare_symbol_data
from src.models.training import load_forecast, train_symbol
from src.utils.logging_setup import get_logger

log = get_logger("cri.update")

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=CONFIG["symbols"])
    ap.add_argument("--retrain", action="store_true", help="Huấn luyện lại bất kể chính sách")
    args = ap.parse_args()
    try:
        for s in args.symbols:
            s = s.upper()
            results = prepare_symbol_data(s)
            new_daily = next((r["new_rows"] for r in results if r["interval"] == "1d"), 0)
            fc = load_forecast(s)
            need = args.retrain or fc is None or new_daily >= CONFIG["retrain_min_new_days"]
            log.info("%s: +%d nến ngày mới -> retrain=%s", s, new_daily, need)
            if need:
                train_symbol(s); log.info("%s: đã huấn luyện lại", s)
            else:
                # Có dữ liệu giờ mới nhưng chưa đủ ngày: vẫn làm mới forecast artifacts bằng train nhanh?
                # Không: giữ forecast cũ kèm timestamp cũ (trung thực), người dùng có thể --retrain.
                log.info("%s: giữ nguyên model/forecast đã lưu (chưa đạt ngưỡng %d ngày mới). Dùng --retrain để ép.",
                         s, CONFIG["retrain_min_new_days"])
        log.info("CẬP NHẬT HOÀN TẤT")
        return 0
    except Exception as e:
        log.error("THẤT BẠI: %s", e); return 1

if __name__ == "__main__":
    raise SystemExit(main())
