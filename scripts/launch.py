"""Launcher: khởi động uvicorn, chờ /api/health, mở trình duyệt, Ctrl+C -> tắt sạch process con."""
import os, signal, subprocess, sys, time, webbrowser
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.config import CONFIG

def main() -> int:
    host, port = CONFIG["host"], CONFIG["port"]
    url = f"http://{host}:{port}"
    cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", host, "--port", str(port), "--log-level", "info"]
    print(f"[Crypto Risk Intelligence] Đang khởi động tại {url} ...")
    popen_kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {}
    proc = subprocess.Popen(cmd, cwd=str(ROOT), **popen_kw)
    try:
        import urllib.request
        for _ in range(60):
            if proc.poll() is not None:
                print("[LỖI] Server thoát sớm. Xem log phía trên và logs/app.log"); return int(proc.returncode or 1)
            try:
                with urllib.request.urlopen(f"{url}/api/health", timeout=2) as r:
                    if r.status == 200: break
            except Exception:
                time.sleep(0.5)
        else:
            print("[LỖI] Server không phản hồi sau 30s."); proc.terminate(); return 1
        print(f"[SẴN SÀNG] Mở: {url}  (Ctrl+C để dừng)")
        if not os.environ.get("CRI_NO_BROWSER"):
            webbrowser.open(url)
        proc.wait()
        return int(proc.returncode or 0)
    except KeyboardInterrupt:
        print("\n[Đang dừng ứng dụng...]")
        proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
        try: proc.wait(timeout=10)
        except subprocess.TimeoutExpired: proc.kill()
        return 0

if __name__ == "__main__":
    raise SystemExit(main())
