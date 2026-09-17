"""直接验证 /auth/config 的 dev_prefill 收敛逻辑（绕开本地 pytest fixture 问题）。

用途：本地 Windows 上 Test/backend/test_auth.py 的 auth_client fixture 在 pytest 9.1.1
下 setup 阶段统一报错（所有历史用例一起失败），因此用本脚本以最小复现验证：
  - 回环对端 → 下发 dev_prefill / dev_write_api_key
  - 非回环对端 → 两者均为 null
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]  # Test/debug/<file> -> 仓库根
_BACKEND_ROOT = REPO / "Code" / "backend"
_GEE_SRC = _BACKEND_ROOT / "app" / "gee" / "core" / "src"
# 与 Test/backend/conftest.py 的 sys.path 约定保持一致：
#   Code/backend / Code / GEE src → 前置（使 `import app.*`、`shared`、`webgis_gee` 可用）
for _p in (_BACKEND_ROOT, REPO / "Code", _GEE_SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
# 算法 provider 根用 append：Code 根的 algorithms（含 __path__ 合并垫片）必须优先，
# 否则 provider 本地同名包会遮蔽（conftest 的 B-N7/B-N8 结论）。
_ALGO_ROOT = REPO / "Code" / "algorithms" / "providers" / "Python"
if str(_ALGO_ROOT) not in sys.path:
    sys.path.append(str(_ALGO_ROOT))

tmp = Path(tempfile.mkdtemp(prefix="devprefill-"))
os.environ.update(
    {
        "BACKEND_ENV": "development",
        "BACKEND_USER_AUTH_ENABLED": "true",
        "BACKEND_ADMIN_USERNAME": "admin",
        "BACKEND_ADMIN_PASSWORD": "Dev-Prefill-Pw-9f2!",
        "BACKEND_DEV_AUTH_PREFILL": "true",
        "BACKEND_DEV_DEFAULT_API_KEY": "cgda-dev-write-key",
        "BACKEND_DATA_ROOT": str(tmp / "data"),
        "BACKEND_OUTPUT_ROOT": str(tmp / "out"),
        "BACKEND_WORKFLOW_STATE_DIR": str(tmp / "state"),
    }
)

from fastapi.testclient import TestClient  # noqa: E402

import app.core.config as cfg_mod  # noqa: E402
from app.api.routers import auth_router  # noqa: E402
from app.services import user_repository as ur_mod  # noqa: E402
from app.services.user_repository import UserRepository  # noqa: E402

ur_mod._repo = UserRepository(tmp / "state" / "users.sqlite3")
patched = replace(
    cfg_mod.settings,
    environment="development",
    dev_auth_prefill=True,
    admin_username="admin",
    admin_password="Dev-Prefill-Pw-9f2!",
    dev_default_api_key="cgda-dev-write-key",
)
cfg_mod.settings = patched
auth_router.settings = patched

from app.main import create_app  # noqa: E402

app = create_app()

for peer in ["127.0.0.1", "::1", "127.5.5.5", "172.17.0.1", "192.168.1.50", "203.0.113.7", "unknown"]:
    auth_router._direct_client_host = lambda _r, p=peer: p
    with TestClient(app) as client:
        resp = client.get("/auth/config")
    body = resp.json()
    prefill = body.get("dev_prefill")
    shown = "null" if prefill is None else f"{{username={prefill['username']}, password=<{len(prefill['password'])} chars>}}"
    print(f"peer={peer:<14} HTTP {resp.status_code}  dev_prefill={shown}  key={body.get('dev_write_api_key')!r}")
