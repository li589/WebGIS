#!/usr/bin/env bash
# ============================================================
#  CGDA 一键停止 (Linux / macOS)
#  调用跨平台 Python 启动器 launch.py stop
# ============================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    echo "[ERROR] Python 未找到"
    exit 1
fi

exec "$PYTHON" "${SCRIPT_DIR}/launch.py" stop
