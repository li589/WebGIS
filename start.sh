#!/usr/bin/env bash
# ============================================================
#  CGDA 一键启动 (Linux / macOS)
#  调用跨平台 Python 启动器 launch.py
#
#  用法:
#    ./start.sh                         → start all
#    ./start.sh start [component] ...
#    ./start.sh stop|status|restart|logs|flush|sync ...
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
    echo "[ERROR] Python 未找到，请确保 python3 在 PATH 中"
    exit 1
fi

if [ "$#" -eq 0 ]; then
    set -- start
fi

exec "$PYTHON" "${SCRIPT_DIR}/launch.py" "$@"
