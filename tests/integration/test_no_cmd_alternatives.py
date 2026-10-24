"""Phương án không cần CMD: endpoint nạp dữ liệu trong trình duyệt,
GUI START_HERE.pyw và các script PowerShell/VS Code tasks."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient
import app.main as main

ROOT = Path(__file__).resolve().parents[2]
client = TestClient(main.app, raise_server_exceptions=False)


def load_gui_module():
    loader = importlib.machinery.SourceFileLoader("start_here_gui", str(ROOT / "START_HERE.pyw"))
    spec = importlib.util.spec_from_loader("start_here_gui", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_browser_prepare_endpoint_accepts_background_job(monkeypatch):
    captured = {}
    def fake_run_job(kind, fn):
        captured["kind"] = kind; captured["callable"] = callable(fn); return True
    monkeypatch.setattr(main, "_run_job", fake_run_job)
    r = client.post("/api/admin/prepare")
    assert r.status_code == 200
    assert r.json()["accepted"] is True
    assert captured == {"kind": "prepare", "callable": True}


def test_gui_helpers_and_bundled_data_contract():
    gui = load_gui_module()
    assert gui.ROOT == ROOT
    assert gui.bundled_ready(ROOT) is True  # ZIP bàn giao phải mở được ngay sau khi cài thư viện
    assert gui.app_host_port(ROOT)[0] == "127.0.0.1"
    cmds = gui.setup_commands(ROOT)
    assert cmds and all(isinstance(c[1], list) and c[1] for c in cmds)
    assert gui.server_command(ROOT)[1:3] == ["-m", "uvicorn"]
    assert gui.script_command("prepare_data.py", ROOT)[-1].endswith("prepare_data.py")


def test_gui_source_is_stdlib_only_and_compiles():
    src = (ROOT / "START_HERE.pyw").read_text(encoding="utf-8")
    compile(src, "START_HERE.pyw", "exec")
    assert "import tkinter" in src and "scripts" in src and "prepare_data.py" in src
    # GUI không import thư viện ngoài ở cấp module (chuỗi kiểm tra cài đặt chạy ở process con thì được phép).
    for banned in ("\nimport fastapi", "\nimport pandas", "\nimport requests"):
        assert banned not in src


def test_powershell_alternatives_self_locate_without_cmd():
    for name in ("setup.ps1", "prepare_data.ps1", "update_data.ps1", "run_app.ps1"):
        body = (ROOT / name).read_text(encoding="utf-8")
        assert "MyInvocation.MyCommand.Path" in body
        assert ".venv" in body
        # Không được lén gọi ngược sang .cmd
        assert ".cmd\"" not in body and ".cmd'" not in body


def test_vscode_tasks_and_quickstart_exist():
    tasks = json.loads((ROOT / ".vscode" / "tasks.json").read_text(encoding="utf-8"))
    labels = [t["label"] for t in tasks["tasks"]]
    assert len(labels) == 4 and all(x.startswith("CRI:") for x in labels)
    guide = (ROOT / "00_BAT_DAU_TAI_DAY.txt").read_text(encoding="utf-8")
    assert "START_HERE.pyw" in guide and "PowerShell" in guide and "trinh duyet" in guide.lower()
