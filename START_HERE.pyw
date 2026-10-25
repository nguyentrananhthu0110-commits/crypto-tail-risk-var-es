"""Crypto Risk Intelligence — trình khởi chạy đồ họa cho Windows, KHÔNG cần CMD.

Cách dùng: giải nén ZIP, double-click START_HERE.pyw.
Nếu Windows mở file bằng trình soạn thảo thay vì chạy, nhấp chuột phải ->
Open with -> Python (hoặc chạy `pyw START_HERE.pyw` / `py START_HERE.pyw`).

File này chỉ dùng thư viện chuẩn của Python. Nó có thể:
1) tạo .venv và cài dependencies, 2) nạp dữ liệu Binance + huấn luyện,
3) cập nhật incremental, 4) mở/dừng ứng dụng web.
Bản ZIP đã đóng gói sẵn dữ liệu và mô hình tham chiếu; vì vậy lần đầu bạn có thể chỉ cần
bước 1 rồi bấm "Mở ứng dụng", sau đó nạp/cập nhật dữ liệu ngay trong trình duyệt.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from queue import Empty, Queue

ROOT = Path(__file__).resolve().parent


def console_python(executable: str | Path | None = None) -> Path:
    """Nếu GUI được mở bằng pythonw.exe, ưu tiên python.exe cùng thư mục để chạy tiến trình con."""
    exe = Path(executable or sys.executable)
    if exe.name.lower() == "pythonw.exe":
        candidate = exe.with_name("python.exe")
        if candidate.exists():
            return candidate
    return exe


def venv_python(root: Path = ROOT) -> Path:
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def venv_healthy(root: Path = ROOT) -> bool:
    """True nếu .venv tồn tại VÀ python của nó chạy được.

    .venv gắn cứng với đường dẫn Python lúc tạo; nếu bị copy từ máy khác hoặc Python gốc
    đã bị gỡ thì python.exe vẫn "tồn tại" nhưng không chạy được (lỗi "did not find executable").
    """
    vpy = venv_python(root)
    if not vpy.exists():
        return False
    try:
        import subprocess
        kwargs = {}
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        r = subprocess.run([str(vpy), "-c", "import sys, venv"], cwd=str(root), timeout=30,
                           capture_output=True, **kwargs)
        return r.returncode == 0
    except Exception:
        return False


def bundled_ready(root: Path = ROOT) -> bool:
    needed = [
        root / "models" / "metadata" / "BTCUSDT_forecast.json",
        root / "models" / "metadata" / "ETHUSDT_forecast.json",
        root / "data" / "raw" / "BTCUSDT_1h.parquet",
        root / "data" / "raw" / "ETHUSDT_1h.parquet",
    ]
    return all(p.exists() and p.stat().st_size > 0 for p in needed)


def app_host_port(root: Path = ROOT) -> tuple[str, int]:
    try:
        cfg = json.loads((root / "config" / "config.json").read_text(encoding="utf-8"))
        return "127.0.0.1", int(cfg.get("port", 8765))
    except Exception:
        return "127.0.0.1", 8765


def setup_commands(root: Path = ROOT, system_python: Path | None = None) -> list[tuple[str, list[str]]]:
    sys_py = str(system_python or console_python())
    vpy = str(venv_python(root))
    cmds: list[tuple[str, list[str]]] = []
    if not venv_python(root).exists():
        cmds.append(("Tạo môi trường ảo .venv", [sys_py, "-m", "venv", ".venv"]))
    elif not venv_healthy(root):
        # .venv hỏng (trỏ tới Python không còn tồn tại): dựng lại bằng Python hiện tại.
        # --clear xoá sạch nội dung cũ của .venv trước khi tạo mới.
        cmds.append(("Phát hiện .venv hỏng — tạo lại bằng Python hiện tại",
                     [sys_py, "-m", "venv", "--clear", ".venv"]))
    cmds.extend([
        ("Nâng cấp pip", [vpy, "-m", "pip", "install", "--upgrade", "pip"]),
        ("Cài thư viện", [vpy, "-m", "pip", "install", "-r", "requirements.txt"]),
        ("Kiểm tra thư viện lõi", [vpy, "-c",
         "import fastapi, uvicorn, pandas, numpy, scipy, sklearn, pyarrow, requests, joblib; print('Core dependencies: OK')"]),
    ])
    return cmds


def script_command(script: str, root: Path = ROOT) -> list[str]:
    return [str(venv_python(root)), str(Path("scripts") / script)]


def server_command(root: Path = ROOT) -> list[str]:
    host, port = app_host_port(root)
    return [str(venv_python(root)), "-m", "uvicorn", "app.main:app",
            "--host", host, "--port", str(port), "--log-level", "info"]


def main() -> None:
    import subprocess
    import tkinter as tk
    from tkinter import messagebox, scrolledtext

    if sys.version_info < (3, 10):
        # Chưa tạo được cửa sổ một cách an toàn trên bản Python quá cũ.
        raise SystemExit("Cần Python 3.10 trở lên (khuyến nghị 3.11-3.13).")

    q: Queue = Queue()
    win = tk.Tk()
    win.title("Crypto Risk Intelligence — Khởi chạy không cần CMD")
    win.geometry("880x620")
    win.minsize(760, 520)
    win.configure(bg="#10141b")

    header = tk.Frame(win, bg="#10141b", padx=18, pady=14)
    header.pack(fill="x")
    tk.Label(header, text="Crypto Risk Intelligence", fg="#eef2f7", bg="#10141b",
             font=("Segoe UI", 18, "bold")).pack(anchor="w")
    status_text = (
        "Dữ liệu + mô hình đóng gói sẵn: CÓ — có thể chỉ cài thư viện rồi mở ứng dụng."
        if bundled_ready() else
        "Dữ liệu đóng gói sẵn: chưa có — hãy dùng nút Nạp dữ liệu sau khi cài thư viện."
    )
    tk.Label(header, text=status_text, fg="#9fb0c7", bg="#10141b",
             font=("Segoe UI", 10), wraplength=820, justify="left").pack(anchor="w", pady=(4, 0))

    btn_frame = tk.Frame(win, bg="#10141b", padx=18, pady=4)
    btn_frame.pack(fill="x")
    log = scrolledtext.ScrolledText(win, bg="#0b0f16", fg="#d6deeb", insertbackground="#d6deeb",
                                    font=("Consolas", 9), wrap="word", padx=10, pady=10)
    log.pack(fill="both", expand=True, padx=18, pady=(8, 14))

    buttons: dict[str, tk.Button] = {}
    server_proc = {"p": None}
    busy = {"v": False}

    def emit(text: str) -> None:
        q.put(text)

    def set_busy(value: bool) -> None:
        busy["v"] = value
        for name, btn in buttons.items():
            if name == "stop":
                btn.configure(state=("normal" if server_proc["p"] is not None else "disabled"))
            else:
                btn.configure(state=("disabled" if value else "normal"))

    def popen(cmd: list[str]):
        kwargs = {}
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        return subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", **kwargs)

    def require_venv() -> bool:
        if venv_healthy():
            return True
        if venv_python().exists():
            messagebox.showwarning(
                "Môi trường .venv bị hỏng",
                "Thư mục .venv trỏ tới một Python không còn tồn tại (thường do copy từ máy khác).\n"
                "Hãy bấm nút 1 “Cài đặt thư viện” — launcher sẽ tự dựng lại .venv.")
        else:
            messagebox.showwarning(
                "Chưa cài thư viện",
                "Hãy bấm nút 1 “Cài đặt thư viện” trước. Bước này chỉ cần làm một lần.")
        return False

    def run_commands(title: str, commands: list[tuple[str, list[str]]]) -> None:
        if busy["v"]:
            return
        set_busy(True)

        def worker() -> None:
            emit(f"\n===== {title} =====")
            try:
                for label, cmd in commands:
                    emit(f"\n--- {label} ---")
                    emit(" ".join(f'"{c}"' if " " in c else c for c in cmd))
                    proc = popen(cmd)
                    assert proc.stdout is not None
                    for line in proc.stdout:
                        emit(line.rstrip())
                    code = proc.wait()
                    if code != 0:
                        emit(f"\n[THẤT BẠI] {label}: mã lỗi {code}.")
                        emit("Hãy xem dòng lỗi phía trên và logs/app.log (nếu có). Dữ liệu cũ không bị xoá.")
                        q.put("__DONE_FAIL__")
                        return
                emit(f"\n[HOÀN TẤT] {title}")
                q.put("__DONE_OK__")
            except Exception as exc:  # noqa: BLE001
                emit(f"\n[THẤT BẠI] {exc}")
                q.put("__DONE_FAIL__")

        threading.Thread(target=worker, daemon=True).start()

    def drain2() -> None:
        try:
            while True:
                item = q.get_nowait()
                if item in ("__DONE_OK__", "__DONE_FAIL__"):
                    set_busy(False)
                    continue
                if item == "__SERVER_STOPPED__":
                    buttons["stop"].configure(state="disabled")
                    continue
                log.insert("end", item + "\n")
                log.see("end")
        except Empty:
            pass
        win.after(120, drain2)

    def do_setup() -> None:
        run_commands("Cài đặt thư viện (không tải dữ liệu)", setup_commands())

    def do_prepare() -> None:
        if require_venv():
            run_commands("Nạp dữ liệu Binance và huấn luyện mô hình",
                         [("Tải lịch sử, tạo features, huấn luyện, đánh giá", script_command("prepare_data.py"))])

    def do_update() -> None:
        if require_venv():
            run_commands("Cập nhật dữ liệu incremental",
                         [("Chỉ tải phần thiếu kể từ checkpoint", script_command("update_data.py"))])

    def wait_and_open(url: str) -> None:
        def worker() -> None:
            for _ in range(60):
                try:
                    with urllib.request.urlopen(url + "/api/health", timeout=2) as r:
                        if r.status == 200:
                            emit(f"[SẴN SÀNG] {url}")
                            webbrowser.open(url)
                            return
                except Exception:
                    time.sleep(0.5)
            emit("[LỖI] Server không phản hồi sau 30 giây. Xem log ở cửa sổ này.")
        threading.Thread(target=worker, daemon=True).start()

    def do_open_app() -> None:
        if not require_venv():
            return
        if server_proc["p"] is not None and server_proc["p"].poll() is None:
            host, port = app_host_port(); webbrowser.open(f"http://{host}:{port}"); return
        host, port = app_host_port(); url = f"http://{host}:{port}"
        proc = popen(server_command())
        server_proc["p"] = proc
        buttons["stop"].configure(state="normal")
        emit(f"\n===== Mở ứng dụng tại {url} =====")
        emit("Dữ liệu/mô hình đóng gói sẵn sẽ được dùng ngay. Nếu cần dữ liệu mới, dùng nút Cập nhật hoặc nút trong trình duyệt.")

        def pump() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                emit(line.rstrip())
            emit(f"[SERVER ĐÃ DỪNG] mã {proc.wait()}")
            server_proc["p"] = None
            q.put("__SERVER_STOPPED__")
        threading.Thread(target=pump, daemon=True).start()
        wait_and_open(url)

    def do_stop_app() -> None:
        proc = server_proc["p"]
        if proc is not None and proc.poll() is None:
            proc.terminate()
            emit("Đã gửi lệnh dừng server…")

    def on_close() -> None:
        do_stop_app()
        win.after(350, win.destroy)

    specs = [
        ("setup", "1) Cài đặt thư viện", do_setup),
        ("prepare", "2) Nạp dữ liệu & huấn luyện", do_prepare),
        ("open", "3) Mở ứng dụng", do_open_app),
        ("update", "4) Cập nhật dữ liệu", do_update),
        ("stop", "5) Dừng ứng dụng", do_stop_app),
    ]
    for col in range(3):
        btn_frame.grid_columnconfigure(col, weight=1, uniform="main_buttons")
    for i, (key, label, fn) in enumerate(specs):
        b = tk.Button(btn_frame, text=label, command=fn, font=("Segoe UI", 10, "bold"),
                      bg="#24324a", fg="#eef2f7", activebackground="#30435f", activeforeground="#ffffff",
                      relief="flat", padx=10, pady=8, cursor="hand2")
        b.grid(row=i // 3, column=i % 3, sticky="ew", padx=(0, 8), pady=(0, 8))
        buttons[key] = b
    buttons["stop"].configure(state="disabled")

    emit("Crypto Risk Intelligence — cách chạy không cần CMD")
    emit(f"Thư mục dự án: {ROOT}")
    emit(f"Python đang mở trình khởi chạy: {sys.version.split()[0]}")
    if venv_python().exists() and not venv_healthy():
        emit("[CẢNH BÁO] .venv hiện có bị hỏng (Python gốc không còn). Bấm 1) Cài đặt thư viện để tự dựng lại.")
    emit("Lần đầu: bấm 1) Cài đặt thư viện. Vì ZIP đã có dữ liệu/mô hình đóng gói sẵn, sau đó có thể bấm 3) Mở ứng dụng ngay.")
    emit("Khi muốn kéo dữ liệu mới thật từ Binance: bấm Cập nhật dữ liệu, hoặc dùng nút “Nạp dữ liệu & huấn luyện” ngay trong trình duyệt.")
    win.protocol("WM_DELETE_WINDOW", on_close)
    drain2()
    win.mainloop()


if __name__ == "__main__":
    main()
