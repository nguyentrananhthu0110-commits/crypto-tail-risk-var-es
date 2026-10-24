#!/usr/bin/env bash
# Tương đương run_app.cmd cho Linux/macOS (Windows hãy dùng file .cmd).
set -euo pipefail
cd "$(dirname "$0")"
PY=".venv/bin/python"
[ -x "$PY" ] || { echo "Chưa có .venv. Hãy: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"; exit 1; }
"$PY" scripts/check_status.py --require-ready --check-port || { echo "Hãy chạy: $PY scripts/prepare_data.py"; exit 2; }
exec "$PY" scripts/launch.py
