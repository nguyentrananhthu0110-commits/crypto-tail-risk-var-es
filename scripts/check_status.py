"""Kiểm tra dữ liệu/model đã sẵn sàng chưa. Exit 0 = ready, 2 = chưa chuẩn bị, 3 = port bận."""
import argparse, socket, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config import CONFIG
from src.data.pipeline import dataset_quality
from src.models.training import forecast_state, model_files_status
from src.storage import get_datasets, get_last_jobs

def port_free(host, port):
    with socket.socket() as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) != 0

def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--require-ready", action="store_true")
    ap.add_argument("--check-port", action="store_true")
    ap.add_argument("--deep", action="store_true", help="Thực sự load thử file model XGBoost và kiểm tra chất lượng Parquet")
    args = ap.parse_args()
    ds = get_datasets()
    print("DATASETS:")
    for d in ds:
        print(f"  {d['symbol']} {d['interval']}: {d['rows']} dòng, cập nhật {d['last_update_utc']}, status={d['status']}")
    ready = True
    print("MODELS:")
    for s in CONFIG["symbols"]:
        state, f = forecast_state(s)
        files = model_files_status(s, deep=args.deep)
        if state == "corrupt":
            print(f"  {s}: CORRUPTED — artifact dự báo không đọc được. Chạy update_data.cmd --retrain"); ready = False
        elif f:
            warn = "" if files["overall"] == "ok" else f" [CANH BAO file model: {files}]"
            print(f"  {s}: ready, selected={f['selected_model']}, generated={f['generated_at_utc']}, files={files['overall']}{warn}")
            if files["overall"] == "corrupt": ready = False
        else: print(f"  {s}: CHƯA CÓ MODEL"); ready = False
    if args.deep:
        print("DATA QUALITY (deep):")
        for s in CONFIG["symbols"]:
            for iv in ("1h", "1d"):
                q = dataset_quality(s, iv)
                print(f"  {s} {iv}: file={q['file_state']} ok={q['ok']} rows={q['rows']} gaps={q.get('gap_count', '-')} dup={q.get('duplicates', '-')}")
                if q["file_state"] == "corrupt": ready = False
    if args.check_port and not port_free(CONFIG["host"], CONFIG["port"]):
        print(f"PORT {CONFIG['port']} đang bị chiếm (có thể app đã chạy, hoặc đổi CRI_PORT)."); return 3
    if args.require_ready and not ready:
        print("Chưa chuẩn bị dữ liệu. Hãy chạy prepare_data.cmd trước."); return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
