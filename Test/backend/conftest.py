"""pytest 共享配置：补齐 backend、Code、GEE src 目录，确保 app/shared/webgis_gee 模块都可导入。

并重定向 ``tmp_path`` 到项目内可写目录，规避 Windows ACL 限制：
默认 ``C:\\Users\\likr\\AppData\\Local\\Temp\\pytest-of-likr`` 在某些 Windows 环境下
有 ACL 限制（WinError 5），导致 ``tmp_path`` fixture 报 ``PermissionError``。
通过设置 ``PYTEST_DEBUG_TEMPROOT`` 环境变量到项目内 ``.pytest_tmp`` 子目录绕过。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ["ENVIRONMENT"] = "test"
os.environ["BACKEND_ENV"] = "test"
os.environ["BACKEND_WORKFLOW_EXECUTOR"] = "sync"

# 测试隔离防御：剔除超出 Windows 环境变量合法上限（32767 字符）的巨型变量
# （如 AI 会话注入的 ACC_PRODUCT_CONFIG_V3 ~481KB）。它会让
# ``unittest.mock.patch.dict(os.environ, ...)`` 退出时写回超限炸
# ``ValueError``，也会波及子进程 spawn（与 git 提交须 ``env -u`` 同源）。
for _oversized_env_key in [k for k, v in os.environ.items() if len(v) > 32760]:
    os.environ.pop(_oversized_env_key, None)

# 测试套件已从 Code/backend/tests/ 迁至 Test/backend/，路径需回归仓库根再定位。
# conftest 位于 <repo>/Test/backend/conftest.py → parents[2] = 仓库根。
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = _REPO_ROOT / "Code" / "backend"
_CODE_ROOT = _REPO_ROOT / "Code"
_ALGO_ROOT = _REPO_ROOT / "Code" / "algorithms" / "providers" / "Python"
_GEE_SRC = _BACKEND_ROOT / "app" / "gee" / "core" / "src"

# 去硬编码批 1：算法/后端不再默认 I:；测试注入 DATA_ROOT。
# 优先级：CGDA_TEST_DATA_ROOT（显式覆盖，部署机/CI 推荐）> 已设 BACKEND_DATA_ROOT
# > 实验室盘存在则复用（向后兼容）> 仓库内临时目录。
if not os.environ.get("BACKEND_DATA_ROOT", "").strip():
    _explicit_test_root = os.environ.get("CGDA_TEST_DATA_ROOT", "").strip()
    if _explicit_test_root:
        os.environ["BACKEND_DATA_ROOT"] = _explicit_test_root
    else:
        _lab_root = Path(r"I:\Geograph_DataSet")
        os.environ["BACKEND_DATA_ROOT"] = str(
            _lab_root
            if _lab_root.exists()
            else _BACKEND_ROOT / ".pytest_tmp" / "data_root"
        )

# 凭据类 SQLite（gee_credentials / research_data_settings / api_keys / users 等
# 全部从 gee_credentials_db_path.parent 派生）必须在 conftest 预导入 app.core.config
# 之前就指向隔离路径：模块级 apply_startup_overrides() 会用 deployment.config.json
# 强制覆写 BACKEND_DATA_ROOT（生产 I: 盘），且 Settings 为 frozen dataclass、
# 类默认值在导入时求值——app fixture 的 monkeypatch+Settings() 重建对
# _RUNTIME_ROOT 派生路径不生效。不设此键时，HTTP 层凭据测试
# （test_config_contracts.py F6 PUT portal-credentials）会写生产 DB
# （2026-08-19 事故：earthdata 用户名被测试载荷 "tessa" 覆盖）。
#
# workflow_state 同理：users.sqlite3 / workflow_state.sqlite3 落点由该键决定。
# 全量跑时 app.core.config 在采集期被测试模块顶层 import，类默认值先于 app
# fixture 的 monkeypatch 固化——不在此处设隔离值，auth 类测试会把测试用户/
# Token 写进生产 users.sqlite3（2026-08-19 取证：token #64 user_id=2 悬空）。
_TEST_GEE_DB = _BACKEND_ROOT / ".pytest_tmp" / "test_gee_credentials.sqlite3"
_TEST_WS_DIR = _BACKEND_ROOT / ".pytest_tmp" / "test_workflow_state"
_TEST_ISOLATION = {
    "BACKEND_GEE_CREDENTIALS_DB_PATH": (
        str(_TEST_GEE_DB),
        "gee_credentials_db_path",
    ),
    "BACKEND_WORKFLOW_STATE_DIR": (
        str(_TEST_WS_DIR),
        "workflow_state_dir",
    ),
}
for _env_key, (_isolated, _field) in _TEST_ISOLATION.items():
    os.environ.setdefault(_env_key, _isolated)
# 导入前生效的隔离值（operator 显式覆盖时为其值），供导入后哨兵比对。
_TEST_ISOLATION_ARRANGED = {k: os.environ.get(k, "") for k in _TEST_ISOLATION}

# sys.path 必须先于下方 import app.core.config 就绪：测试套件迁至 Test/backend 后，
# pytest 的 rootdir 插入不含 Code/backend，此前 conftest 内的 import 一直抛
# ImportError 并被 except 静默吞掉（真实首次导入发生在测试模块顶层）——
# 隔离 env 变量仍生效，但依赖该 import 生效的哨兵从未执行（2026-08-19 取证）。
for path in (str(_BACKEND_ROOT), str(_CODE_ROOT), str(_GEE_SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

# B-N7：COG 导入链 algorithms.providers.Python.publish/__init__ → output_manager
# 依赖 provider 根上的顶层模块（path_utils 等），单文件运行也须可导入。
# 用 append 而非 insert(0)：保证 Code 根的 algorithms（含 __path__ 合并垫片）
# 始终优先于 provider 本地同名包，避免 B-N8 的包名遮蔽。
if str(_ALGO_ROOT) not in sys.path:
    sys.path.append(str(_ALGO_ROOT))

try:
    import app.core.config

    app.core.config.settings = app.core.config.Settings()
except Exception:
    pass
else:
    # 隔离哨兵（fail-fast）：apply_startup_overrides() 对 deployment.config.json
    # 中存在的键无条件覆写 os.environ（json 为部署真源，环境变量无法夺回）。
    # 若未来经配置中心把 workflow_state_dir 等运行时键写入 json，上述隔离值
    # 会在 config 导入时被静默踩掉、pytest 落回生产盘——此处直接拒绝采集，
    # 把 2026-08-19 事故的静默复发路径变成显式报错。
    for _env_key, (_isolated, _field) in _TEST_ISOLATION.items():
        _expected = _TEST_ISOLATION_ARRANGED[_env_key]
        _actual = str(getattr(app.core.config.settings, _field, ""))
        if _expected and _actual != _expected:
            raise RuntimeError(
                f"pytest 测试隔离被破坏：settings.{_field}={_actual!r} 与导入前"
                f"安排的隔离值 {_expected!r} 不一致——deployment.config.json 的"
                f" runtime 组键在导入 app.core.config 时强制覆盖了 {_env_key}"
                "（json 为部署真源，环境变量无法夺回）。请从"
                " deployment.config.json 移除该运行时键（或为测试机单独准备"
                "不含该键的部署配置），勿让 pytest 写生产库。"
            )

# ── 重定向 pytest tmp_path 到项目内可写目录 ──────────────────────────────
# 必须在 pytest 初始化 ``tmp_path_factory`` 之前设置 ``PYTEST_DEBUG_TEMPROOT``
# 环境变量。conftest.py 在 pytest 配置阶段加载，早于 session fixture 初始化，
# 因此模块级设置能生效。
_PROJECT_TMP = _BACKEND_ROOT / ".pytest_tmp"
_PROJECT_TMP.mkdir(parents=True, exist_ok=True)
# 仅当用户未显式覆盖时设置（避免与 --basetemp CLI 冲突）
if "PYTEST_DEBUG_TEMPROOT" not in os.environ:
    os.environ["PYTEST_DEBUG_TEMPROOT"] = str(_PROJECT_TMP)

# SpatiaLite 测试隔离：默认 spatial DB 落到项目 tmp，避免污染开发库
if not os.environ.get("BACKEND_SPATIALITE_DB_PATH", "").strip():
    os.environ["BACKEND_SPATIALITE_DB_PATH"] = str(_PROJECT_TMP / "spatial_test.sqlite")


# ── P1-9: 共享 fixture ─────────────────────────────────────────────────────
# 以下 fixture 供 Test/backend/ 下所有测试文件复用，消除重复的 app/client setup。
# 若测试文件本地定义了同名 fixture，pytest 优先使用本地定义（不冲突）。


@pytest.fixture()
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """创建隔离环境的 FastAPI app 实例。

    使用 tmp_path 隔离 DATA_ROOT / OUTPUT_ROOT / WORKFLOW_STATE_DIR，
    禁用 API Keys 以允许测试免鉴权访问公开端点。
    """
    monkeypatch.setenv("BACKEND_ENV", "test")
    monkeypatch.setenv("BACKEND_DATA_ROOT", str(tmp_path / "data_root"))
    monkeypatch.setenv("BACKEND_OUTPUT_ROOT", str(tmp_path / "output_root"))
    monkeypatch.setenv("BACKEND_WORKFLOW_STATE_DIR", str(tmp_path / "workflow_state"))
    monkeypatch.setenv("BACKEND_API_KEYS_ENABLED", "false")
    # 凭据类 DB 隔离：见模块级 _TEST_GEE_DB 注释（deployment.config.json 会强制
    # 覆写 BACKEND_DATA_ROOT，故须单独覆写本键才能落到 tmp）。
    monkeypatch.setenv(
        "BACKEND_GEE_CREDENTIALS_DB_PATH",
        str(tmp_path / "workflow_state" / "gee_credentials.sqlite3"),
    )

    # 重置 settings 以拾取新的环境变量
    try:
        import app.core.config

        app.core.config.settings = app.core.config.Settings()
    except Exception:
        pass

    from app.main import create_app

    return create_app()


@pytest.fixture()
def client(app):
    """返回带 lifespan 管理的 TestClient。"""
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    """返回临时 SQLite 数据库文件路径（不创建文件，首次连接时自动创建）。"""
    return tmp_path / "test.sqlite3"
