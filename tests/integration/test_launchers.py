"""Mục 13+15E: kiểm tra tĩnh các file CMD (không thực thi được .cmd trên Linux)
và kiểm tra hợp đồng mã thoát của check_status.py mà run_app.cmd dựa vào.
Việc chạy thật .cmd cần nghiệm thu trên Windows — xem outputs/reports/verification_report.md."""
import os, socket, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def read(name): return (ROOT / name).read_text(encoding="utf-8", errors="replace")

def test_all_launchers_exist_and_self_locate():
    for name in ("setup.cmd", "prepare_data.cmd", "update_data.cmd", "run_app.cmd"):
        body = read(name)
        assert 'cd /d "%~dp0"' in body, f"{name}: phải tự về thư mục dự án, chạy từ mọi cwd"
        assert "C:\\Users\\" not in body and "D:\\" not in body, f"{name}: không được hardcode đường dẫn máy cá nhân"

def test_setup_cmd_contract():
    b = read("setup.cmd")
    assert "-m venv" in b and "requirements.txt" in b
    assert "prepare_data" not in b.split("Buoc tiep theo")[0].split("pip install -r")[1]  # không âm thầm train trong setup

def test_prepare_and_update_contracts():
    prep, upd = read("prepare_data.cmd"), read("update_data.cmd")
    assert "scripts\\prepare_data.py" in prep and "ERRORLEVEL" in prep
    assert "scripts\\update_data.py" in upd and "%*" in upd  # cho phép --retrain

def test_run_app_contract():
    b = read("run_app.cmd")
    assert "activate.bat" in b                       # kích hoạt venv
    assert "--require-ready" in b and "--check-port" in b
    assert '"2"' in b and '"3"' in b                 # phân biệt chưa-prepare vs port bận
    assert "scripts\\launch.py" in b
    assert "CRI_NO_PAUSE" in b                       # pause có thể tắt cho tự động hoá
    assert "exit /b %EXITCODE%" in b                 # mã lỗi không bị pause che mất

def test_check_status_ready_exit_zero():
    r = subprocess.run([sys.executable, "scripts/check_status.py", "--require-ready"],
                       cwd=ROOT, capture_output=True, text=True, timeout=120)
    # Repo bàn giao đã prepare sẵn; nếu chạy trong repo trắng, mã 2 cũng là hợp đồng đúng.
    assert r.returncode in (0, 2), r.stdout + r.stderr
    if r.returncode == 0:
        assert "ready" in r.stdout

def test_check_status_port_occupied_exit_3():
    sock = None
    try:
        sock = socket.socket(); sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 8765)); sock.listen(1)
    except OSError:
        sock = None  # port đã có process khác chiếm (ví dụ server đang chạy) — vẫn phải ra exit 3
    try:
        env = {**os.environ, "CRI_HOST": "127.0.0.1", "CRI_PORT": "8765"}
        r = subprocess.run([sys.executable, "scripts/check_status.py", "--check-port"],
                           cwd=ROOT, capture_output=True, text=True, timeout=120, env=env)
        assert r.returncode == 3, r.stdout + r.stderr
    finally:
        if sock: sock.close()


def test_cmd_files_use_crlf_line_endings():
    # cmd.exe co the phan tich sai block/label neu file .cmd chi dung LF kieu Unix.
    for name in ("setup.cmd", "prepare_data.cmd", "update_data.cmd", "run_app.cmd"):
        b = (ROOT / name).read_bytes()
        assert b.count(b"\r\n") > 10, f"{name}: thieu CRLF"
        assert b.count(b"\n") == b.count(b"\r\n"), f"{name}: con LF tron"
