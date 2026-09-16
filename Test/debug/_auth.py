"""调试脚本共享的鉴权凭据解析（Test/debug/*）。

背景：这些一次性诊断脚本曾把开发弱口令 ``cgda-dev-admin`` 硬编码在源码里
（与 ``Code/backend/.env`` 的 ``BACKEND_ADMIN_PASSWORD`` 同值）。口令轮换后
该字面量即失效，且把凭据留在仓库里本身就是泄漏面，故统一改由本模块解析。

解析优先级：
1. 环境变量 ``CGDA_ADMIN_USERNAME`` / ``CGDA_ADMIN_PASSWORD``（临时覆盖用）；
2. 仓库内 ``Code/backend/.env`` 的 ``BACKEND_ADMIN_USERNAME`` /
   ``BACKEND_ADMIN_PASSWORD``（该文件不入库，是凭据的唯一真源）；
3. 都取不到则抛错并提示如何配置，绝不回退到任何已知默认口令。

用法::

    from _auth import admin_password
    payload = {"username": "admin", "password": admin_password()}

``from _auth import ...`` 依赖 Python 把脚本所在目录放进 ``sys.path[0]``，
因此无论从哪个 cwd 执行 ``python Test/debug/xxx.py`` 都能导入。
"""

from __future__ import annotations

import os
from pathlib import Path

# Test/debug/_auth.py -> parents[0]=debug, [1]=Test, [2]=仓库根
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _REPO_ROOT / "Code" / "backend" / ".env"


def _read_env_file() -> dict[str, str]:
    """解析 Code/backend/.env（忽略注释与空行，容忍无引号值）。"""
    if not _ENV_FILE.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip("'\"")
    return values


def _resolve(key_env: str, key_dotenv: str, default: str = "") -> str:
    val = (os.environ.get(key_env) or "").strip()
    if val:
        return val
    val = (_read_env_file().get(key_dotenv) or "").strip()
    if val:
        return val
    if default:
        return default
    raise RuntimeError(
        f"未找到 {key_dotenv}：请在环境变量 {key_env} 或 {_ENV_FILE} 中配置。"
        "（调试脚本不再内置默认口令。）"
    )


def admin_username() -> str:
    return _resolve("CGDA_ADMIN_USERNAME", "BACKEND_ADMIN_USERNAME", "admin")


def admin_password() -> str:
    return _resolve("CGDA_ADMIN_PASSWORD", "BACKEND_ADMIN_PASSWORD")


#: 兼容直接取值的调用点
ADMIN_USERNAME = admin_username
ADMIN_PASSWORD = admin_password
