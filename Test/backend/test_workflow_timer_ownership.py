"""定时器归属隔离（多用户数据泄漏防护）测试。

覆盖（2026-08-20）：
- 旧表迁移：无 owner_user_id 列的表自动 ALTER 补列
- 服务层 list_timers(owner_user_id=) 过滤 + owner 持久化
- 路由层：非 admin 用户仅见/可管本人定时器；越权 GET/PUT/DELETE/run
  统一 404 防枚举；admin 全可见；调度 fetch_due_timers 不受 owner 影响
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# 服务层（直接构造 store，显式 state_dir）
# ---------------------------------------------------------------------------


def _make_timer(timer_id: str, workflow_id: str = "wf-x", owner=None):
    from app.services.workflow_timer_service import WorkflowTimer

    return WorkflowTimer(
        timer_id=timer_id,
        workflow_id=workflow_id,
        name=f"timer {timer_id}",
        trigger_type="cron",
        trigger_config={"cron": "0 3 * * *"},
        owner_user_id=owner,
        created_at="2026-08-20T00:00:00+00:00",
        updated_at="2026-08-20T00:00:00+00:00",
    )


def test_legacy_table_migrated_with_owner_column(tmp_path: Path) -> None:
    """旧 schema（无 owner_user_id）打开后自动补列，旧数据 owner=NULL。"""
    from app.services.workflow_timer_service import WorkflowTimerStore

    db = tmp_path / "workflow_state.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE workflow_timers (
            timer_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            name TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            trigger_config TEXT NOT NULL,
            payload_overrides TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 1,
            last_fired_at TEXT,
            next_fire_at TEXT,
            last_run_id TEXT,
            last_error TEXT,
            fire_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO workflow_timers (timer_id, workflow_id, name, trigger_type,"
        " trigger_config, created_at, updated_at)"
        " VALUES ('t-legacy', 'wf-x', 'legacy', 'cron', '{}', '2026', '2026')"
    )
    conn.commit()
    conn.close()

    store = WorkflowTimerStore(tmp_path)
    cols = {
        row[1]
        for row in store._conn.execute("PRAGMA table_info(workflow_timers)").fetchall()
    }
    assert "owner_user_id" in cols
    legacy = store.get_timer("t-legacy")
    assert legacy is not None
    assert legacy.owner_user_id is None


def test_list_timers_filters_by_owner(tmp_path: Path) -> None:
    from app.services.workflow_timer_service import WorkflowTimerStore

    store = WorkflowTimerStore(tmp_path)
    store.create_timer(_make_timer("t-a", owner=1))
    store.create_timer(_make_timer("t-b", owner=2))
    store.create_timer(_make_timer("t-legacy"))  # owner=None 旧共享

    all_timers = store.list_timers()
    assert {t.timer_id for t in all_timers} == {"t-a", "t-b", "t-legacy"}

    user1 = store.list_timers(owner_user_id=1)
    assert [t.timer_id for t in user1] == ["t-a"]

    user2 = store.list_timers(owner_user_id=2)
    assert [t.timer_id for t in user2] == ["t-b"]


def test_fetch_due_timers_ignores_owner(tmp_path: Path) -> None:
    """调度路径不按 owner 过滤：任何归属的到期定时器都会被扫到。"""
    from datetime import UTC, datetime, timedelta

    from app.services.workflow_timer_service import WorkflowTimerStore

    store = WorkflowTimerStore(tmp_path)
    due_iso = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    timer = _make_timer("t-owned", owner=7)
    timer.enabled = True
    timer.next_fire_at = due_iso
    store.create_timer(timer)

    due = store.fetch_due_timers(datetime.now(UTC))
    assert [t.timer_id for t in due] == ["t-owned"]


# ---------------------------------------------------------------------------
# 路由层（完整 auth fixture，参照 test_error_codes.py 模式）
# ---------------------------------------------------------------------------


@pytest.fixture()
def auth_client(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_ENV", "test")
    monkeypatch.setenv("BACKEND_USER_AUTH_ENABLED", "true")
    monkeypatch.setenv("BACKEND_ADMIN_USERNAME", "testadmin")
    monkeypatch.setenv("BACKEND_ADMIN_PASSWORD", "test-pass-123")
    monkeypatch.setenv("BACKEND_API_KEY", "test-api-key")
    monkeypatch.setenv("BACKEND_API_KEYS_ENABLED", "true")
    monkeypatch.setenv("BACKEND_API_KEY_ROLE", "operator")
    monkeypatch.setenv("BACKEND_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("BACKEND_OUTPUT_ROOT", str(tmp_path / "out"))
    monkeypatch.setenv("BACKEND_WORKFLOW_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("BACKEND_DEV_AUTH_PREFILL", "false")

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
        # Settings 为 frozen dataclass，字段默认值在 import 时已求值，
        # monkeypatch.setenv 无效——须显式传 per-test 隔离路径
        workflow_state_dir=str(tmp_path / "state"),
    )
    from app.services import user_repository as ur_mod
    from app.services.user_repository import UserRepository

    ur_mod._repo = UserRepository(tmp_path / "state" / "users.sqlite3")

    # 定时器 store 单例与模块级 settings 绑定都指向 tmp state
    # （wts 模块 `from app.core.config import settings` 为模块级绑定，
    #  仅重置 _store_instance 会复用首个测试的 DB → 状态泄漏）
    from app.services import workflow_timer_service as wts

    monkeypatch.setattr(wts, "settings", cfg_mod.settings)
    wts._store_instance = None

    from app.main import create_app
    from app.services.auth_bootstrap import bootstrap_auth
    from app.services.config_service import (
        _get_api_keys_repository,
        _get_effective_api_key_cached,
    )
    from app.services.effective_config import hydrate_effective_config

    hydrate_effective_config()
    bootstrap_auth()
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
        yield client

    wts._store_instance = None


_TIMER_PAYLOAD = {
    "workflow_id": "wf-timer-test",
    "name": "nightly",
    "trigger_type": "cron",
    "trigger_config": {"cron": "0 3 * * *"},
    "enabled": True,
}


def _create_user_and_login(client: TestClient, username: str) -> None:
    client.post("/auth/logout")
    resp = client.post(
        "/auth/login", json={"username": "testadmin", "password": "test-pass-123"}
    )
    assert resp.status_code == 200, resp.text
    resp = client.post(
        "/auth/users",
        json={"username": username, "password": "user-pass-123", "role": "standard"},
    )
    assert resp.status_code in (201, 409), resp.text
    client.post("/auth/logout")
    resp = client.post(
        "/auth/login", json={"username": username, "password": "user-pass-123"}
    )
    assert resp.status_code == 200, resp.text


def _admin_login(client: TestClient) -> None:
    client.post("/auth/logout")
    resp = client.post(
        "/auth/login", json={"username": "testadmin", "password": "test-pass-123"}
    )
    assert resp.status_code == 200, resp.text


def _create_timer(client: TestClient) -> str:
    with patch(
        "app.services.workflow_definition_service.get_definition",
        return_value={"workflow_id": "wf-timer-test"},
    ):
        resp = client.post("/workflow-timers", json=_TIMER_PAYLOAD)
    assert resp.status_code == 201, resp.text
    return resp.json()["timer_id"]


def test_standard_user_cannot_manage_timers(auth_client: TestClient) -> None:
    """标准用户不可创建/列表/触发定时器（仅管理员）。"""
    _admin_login(auth_client)
    timer_id = _create_timer(auth_client)

    _create_user_and_login(auth_client, "alice")
    assert auth_client.get("/workflow-timers").status_code == 403
    assert auth_client.get(f"/workflow-timers/{timer_id}").status_code == 403
    assert (
        auth_client.put(
            f"/workflow-timers/{timer_id}", json={"enabled": False}
        ).status_code
        == 403
    )
    assert auth_client.delete(f"/workflow-timers/{timer_id}").status_code == 403
    assert auth_client.post(f"/workflow-timers/{timer_id}/run").status_code == 403
    with patch(
        "app.services.workflow_definition_service.get_definition",
        return_value={"workflow_id": "wf-timer-test"},
    ):
        assert auth_client.post("/workflow-timers", json=_TIMER_PAYLOAD).status_code == 403


def test_admin_can_create_list_and_run(auth_client: TestClient) -> None:
    _admin_login(auth_client)
    timer_id = _create_timer(auth_client)

    resp = auth_client.get("/workflow-timers")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [t["timer_id"] for t in items] == [timer_id]
    assert items[0]["owner_user_id"] is not None

    resp = auth_client.put(f"/workflow-timers/{timer_id}", json={"enabled": False})
    assert resp.status_code == 200, resp.text

    with patch(
        "app.services.workflow_timer_service.trigger_manually",
        return_value={"ok": True, "timer_id": timer_id},
    ):
        resp = auth_client.post(f"/workflow-timers/{timer_id}/run")
    assert resp.status_code == 200, resp.text

    resp = auth_client.delete(f"/workflow-timers/{timer_id}")
    assert resp.status_code == 200, resp.text


def test_admin_sees_legacy_ownerless_timer(auth_client: TestClient) -> None:
    from app.services import workflow_timer_service as wts

    wts.get_timer_store().create_timer(_make_timer("t-legacy-shared"))

    _create_user_and_login(auth_client, "alice")
    assert auth_client.get("/workflow-timers").status_code == 403

    _admin_login(auth_client)
    resp = auth_client.get("/workflow-timers")
    assert resp.status_code == 200
    assert [t["timer_id"] for t in resp.json()["items"]] == ["t-legacy-shared"]
