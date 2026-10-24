"""Launcher phải phát hiện .venv hỏng (Python gốc không còn) và tự dựng lại."""
import importlib.machinery
import importlib.util
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_gui():
    loader = importlib.machinery.SourceFileLoader("start_here_gui", str(ROOT / "START_HERE.pyw"))
    spec = importlib.util.spec_from_loader("start_here_gui", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _fake_broken_venv(tmp_path):
    gui = load_gui()
    vpy = gui.venv_python(tmp_path)
    vpy.parent.mkdir(parents=True)
    vpy.write_text("#!/nonexistent/python\n")
    if os.name != "nt":
        vpy.chmod(0o755)
    return gui


def test_missing_venv_is_not_healthy(tmp_path):
    gui = load_gui()
    assert gui.venv_healthy(tmp_path) is False
    assert gui.setup_commands(tmp_path)[0][1][1:3] == ["-m", "venv"]


def test_broken_venv_is_detected_and_recreated(tmp_path):
    gui = _fake_broken_venv(tmp_path)
    assert gui.venv_healthy(tmp_path) is False
    label, cmd = gui.setup_commands(tmp_path)[0]
    assert "--clear" in cmd and cmd[1:3] == ["-m", "venv"]
