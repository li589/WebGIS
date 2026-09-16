#!/usr/bin/env bash
# ============================================================
#  CGDA 一键停止 (Linux / macOS)
#  强制使用 Env/Python312（与 start.sh 一致）
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
  exit 1
fi

echo "[INFO] Python: $ENV_PY"
exec "$ENV_PY" "${SCRIPT_DIR}/launch.py" stop
