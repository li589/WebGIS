"""导入任务属主隔离 —— 回归锁（审查发现 C-1）。

根因
────
``require_data_transfer_access`` 是**同步** ``def``，FastAPI 会在线程池中执行同步依赖
（anyio ``copy_context()``），因此依赖内部的 ``ContextVar.set()`` 不会回传到事件循环；
而所有导入端点都是 ``async def``，读到的永远是默认值。属主一旦只靠 ContextVar 兜底，
``create_job`` 写入的 ``owner_user_id`` 恒为 ``None``，随后：

* ``list_jobs`` 按 fail-closed 过滤掉无主任务  → 提交者在列表里看不到自己的任务
* ``_deny_job_if_not_owner`` 对 ``owner is None`` 直接 403 → 轮询/取消/下载全被拒

契约
────
属主必须由**端点显式传参**下传（``enqueue_job(..., owner_user_id=...)``），
不得依赖任何隐式上下文。本文件即该契约的回归锁。

覆盖场景
────────
1. 提交者本人：任务落库带正确属主，且可查详情、可在列表中看到
2. 另一 standard 用户：不可读（属主隔离）
3. admin：可读任意任务（管理旁路）

注意：本文件**故意不**断言「未登录/service key 调用者」的行为——那属于既有 fail-closed
设计（无 user_id 者列表为空、无主任务仅管理员可见），见 ``jobs.list_jobs`` 与
``_deny_job_if_not_owner`` 注释。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_CODE_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_PROVIDER = _CODE_ROOT / "algorithms" / "providers" / "Python"
for _p in (_PYTHON_PROVIDER, _CODE_ROOT):
    _s = str(_p)
    if _s in sys.path:
        sys.path.remove(_s)
    sys.path.insert(0, _s)


@dataclass
class _Env:
    client: TestClient
    std_id: int
    other_id: int


@pytest.fixture(scope="module")
def env(tmp_path_factory) -> _Env:
    """真实 app + 真实用户体系：一名 standard 提交者、一名 standard 旁观者、一名 admin。

    模块级：三次用例共享一次 app 启动（单次启动约 10s，函数级会让本文件在 CI 上过慢）。
    用例之间互不干扰——各自显式登录、各自提交独立任务。
    """
    tmp_path = tmp_path_factory.mktemp("import_job_ownership")
    # monkeypatch 是函数级夹具，模块级作用域下改用手动实例并在收尾 undo。
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("BACKEND_ENV", "test")
    monkeypatch.setenv("BACKEND_USER_AUTH_ENABLED", "true")
    monkeypatch.setenv("BACKEND_ADMIN_USERNAME", "testadmin")
    monkeypatch.setenv("BACKEND_ADMIN_PASSWORD", "test-pass-123")
    monkeypatch.setenv("BACKEND_API_KEY", "test-api-key")
    monkeypatch.setenv("BACKEND_API_KEYS_ENABLED", "true")
    monkeypatch.setenv("BACKEND_API_KEY_ROLE", "standard")
    monkeypatch.setenv("BACKEND_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("BACKEND_OUTPUT_ROOT", str(tmp_path / "out"))
    monkeypatch.setenv("BACKEND_WORKFLOW_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("BACKEND_DEV_AUTH_PREFILL", "false")
    monkeypatch.setenv(
        "BACKEND_GEE_CREDENTIALS_DB_PATH",
        str(tmp_path / "state" / "gee_credentials.sqlite3"),
    )

    from dataclasses import replace

    import app.core.config as cfg_mod
    from app.core.config import Settings

    cfg_mod.settings = replace(
        Settings(),
        admin_username="testadmin",
        admin_password="test-pass-123",
        environment="test",
        api_key="test-api-key",
        api_keys_enabled=True,
        api_key_role="standard",
        user_auth_enabled=True,
        data_root=str(tmp_path / "data"),
    )
    monkeypatch.setattr("app.core.config.settings", cfg_mod.settings)

    from app.services import user_repository as ur_mod
    from app.services.user_repository import UserRepository

    # 两处桩必须挂在模块级：它们在**后台线程**里被消费，若用 with 块做上下文补丁，
    # 线程真正执行时 patch 早已退出（竞态）。
    #   * import_vector_from_paths：真正的矢量解析，与属主无关；不桩会抛 ValueError。
    #   * celery_available：关掉 Celery 派发走本地线程兜底。否则 send_task 会连
    #     Redis 结果后端，失败时重试 20 次（约 60s/用例），拖垮 CI 且结果依赖 Redis。
    monkeypatch.setattr(
        "app.data_io.api.router.import_vector_from_paths",
        lambda *a, **k: {"layer_id": "test-layer", "feature_count": 0},
    )
    monkeypatch.setattr("app.core.celery_app.celery_available", False)

    repo = UserRepository(tmp_path / "state" / "users.sqlite3")

    from app.main import create_app
    from app.services.auth_bootstrap import bootstrap_auth
    from app.services.config_service import (
        _get_api_keys_repository,
        _get_effective_api_key_cached,
    )
    from app.services.effective_config import hydrate_effective_config

    with patch.object(ur_mod, "_repo", repo):
        hydrate_effective_config()
        bootstrap_auth()
        std = repo.create_user(username="stduser", password="std-pass-123", role="standard")
        other = repo.create_user(username="otheruser", password="other-pass-123", role="standard")
        _get_api_keys_repository().upsert_key(
            key_name="backend_auth",
            key_value="test-api-key",
            display_name="Test backend auth",
            description="pytest fixture",
            history_source="test",
            archive_previous=False,
        )
        _get_effective_api_key_cached.cache_clear()
        hydrate_effective_config()

        with TestClient(create_app()) as client:
            yield _Env(
                client=client,
                std_id=int(std["id"]),
                other_id=int(other["id"]),
            )
        monkeypatch.undo()


def _login(client: TestClient, username: str, password: str) -> None:
    res = client.post("/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text


def _submit_async_vector_import(client: TestClient, tmp_file: Path) -> str:
    """以当前登录身份提交一个异步矢量导入，返回 job_id。

    真实链路：依赖 ``require_data_transfer_access`` → 端点 ``import_vector``
    → ``enqueue_job`` → ``create_job`` → ``jobs.py`` 落盘。

    另两处桩（``import_vector_from_paths`` / ``celery_available``）挂在模块级夹具上——
    它们在后台线程中被消费，上下文补丁会与之竞态，详见 ``env`` 夹具注释。
    """
    with patch("app.data_io.api.router.resolve_upload_path", return_value=tmp_file):
        res = client.post(
            "/import/vector",
            json={"upload_ids": ["fake-uid"], "async_mode": True},
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("async") is True
    return str(body["job_id"])


def test_submitter_owns_and_can_read_own_job(env: _Env, tmp_path):
    """核心回归锁：属主必须落库，且提交者本人可查详情、可在列表看到。"""
    from app.data_io.services.jobs import get_job

    fake = tmp_path / "sample.shp"
    fake.write_bytes(b"not-a-real-shapefile")

    _login(env.client, "stduser", "std-pass-123")
    job_id = _submit_async_vector_import(env.client, fake)

    # 1) 属主落库 = 提交者 user_id（而非 None）
    owner = get_job(job_id).get("owner_user_id")
    assert owner is not None, "owner_user_id 未落库 —— ContextVar 兜底失效（C-1 回归）"
    assert int(owner) == env.std_id

    # 2) 提交者本人可轮询
    status_res = env.client.get(f"/import/jobs/{job_id}")
    assert status_res.status_code == 200, status_res.text

    # 3) 提交者本人可在列表中看到
    listed = [i["job_id"] for i in env.client.get("/import/jobs").json()["items"]]
    assert job_id in listed


def test_other_standard_user_cannot_read_job(env: _Env, tmp_path):
    """属主隔离：另一 standard 用户既读不到详情，也看不到列表。"""
    fake = tmp_path / "sample.shp"
    fake.write_bytes(b"not-a-real-shapefile")

    _login(env.client, "stduser", "std-pass-123")
    job_id = _submit_async_vector_import(env.client, fake)

    env.client.post("/auth/logout")
    _login(env.client, "otheruser", "other-pass-123")

    assert env.client.get(f"/import/jobs/{job_id}").status_code == 403
    listed = [i["job_id"] for i in env.client.get("/import/jobs").json()["items"]]
    assert job_id not in listed


def test_admin_can_read_any_job(env: _Env, tmp_path):
    """管理旁路不受影响：admin 可读任意任务。"""
    fake = tmp_path / "sample.shp"
    fake.write_bytes(b"not-a-real-shapefile")

    _login(env.client, "stduser", "std-pass-123")
    job_id = _submit_async_vector_import(env.client, fake)

    env.client.post("/auth/logout")
    _login(env.client, "testadmin", "test-pass-123")

    assert env.client.get(f"/import/jobs/{job_id}").status_code == 200
    listed = [i["job_id"] for i in env.client.get("/import/jobs").json()["items"]]
    assert job_id in listed
