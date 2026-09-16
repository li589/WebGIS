#!/usr/bin/env bash
# ============================================================
#  CGDA 一键启动 (Linux / macOS)
#  优先使用仓库内 Env/Python312（与 Windows 本地约定一致）
#
#  用法:
#    ./start.sh                         → start all
#    ./start.sh start [component] ...
#    ./start.sh stop|status|restart|logs|flush|sync ...
# ============================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ENV_PY=""
for cand in \
  "${SCRIPT_DIR}/Env/Python312/bin/python" \
  "${SCRIPT_DIR}/Env/Python312/bin/python3" \
  "${SCRIPT_DIR}/Env/Python312/python"
do
  if [[ -x "$cand" ]]; then
    ENV_PY="$cand"
    break
  fi
done

if [[ -z "$ENV_PY" ]]; then
  echo "[ERROR] 未找到 Env/Python312 解释器。"
  echo "        本仓库本地联调约定使用 Env/Python312；请先准备该环境。"
  echo "        （若仅临时验证，可手动: python3 launch.py …，但不推荐）"
  exit 1
fi

echo "[INFO] Python: $ENV_PY"

if [[ "$#" -eq 0 ]]; then
  set -- start
fi

exec "$ENV_PY" "${SCRIPT_DIR}/launch.py" "$@"
