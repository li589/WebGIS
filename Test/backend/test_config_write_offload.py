"""F11 事件循环专测：config 写路由经 anyio.to_thread.run_sync offload 事件循环。

背景（Phase 2 审查发现 F11）：config 写操作已改为
``await anyio.to_thread.run_sync(...)`` 从事件循环 offload 到工作线程，
但此前无专门测试证明写操作确实不阻塞事件循环。

策略：
1) run_sync 调用路径断言（主）：monkeypatch 包裹 ``anyio.to_thread.run_sync``，
   记录被调用的函数，然后打 api-key 写路由，断言写操作确实经 run_sync 执行，
   且写入/翻转/删除在 HTTP 层读回一致。
2) 事件循环级非阻塞检查（尽力而为）：用 asyncio + httpx ASGITransport 并发发起
   一个写请求与一个轻量 GET，断言 GET 在写请求在途时仍被及时响应。该检查为
   附加项；若在特定 CI/测试环境不稳定，第 1 类断言已足以证明 offload 路径。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from typing import Callable

import anyio
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import create_app
from app.services import config_service


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        "app.services.effective_config.get_backend_auth_key",
        lambda: "test-key",
    )
    # RBAC v2: 配置管理路由需 admin 角色。
    monkeypatch.setattr(
        "app.core.config.settings",
        replace(settings, api_key_role="admin"),
    )
    return TestClient(create_app(), headers={"X-API-Key": "test-key"})


def _install_run_sync_spy(monkeypatch: pytest.MonkeyPatch, calls: list) -> None:
    """记录 anyio.to_thread.run_sync 的 func 实参，同时保持原行为。"""
    original = anyio.to_thread.run_sync

    def spy(func: Callable, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(func)
        return original(func, *args, **kwargs)

    monkeypatch.setattr(anyio.to_thread, "run_sync", spy)


# ── 1) run_sync 调用路径断言 ───────────────────────────────────────────────


def test_update_api_key_offloads_via_run_sync(client: TestClient, monkeypatch):
    calls: list = []
    _install_run_sync_spy(monkeypatch, calls)

    name = "tessa_offload_ak_update"
    resp = client.put(
        f"/config/api-keys/{name}",
        json={"key_value": "tessa-offload-secret-1", "enabled": True},
    )
    assert resp.status_code == 200
    # 写操作确实经过 run_sync（更新路由用 lambda 包裹 upsert_api_key）
    assert calls, "update_api_key 未经过 anyio.to_thread.run_sync"
    assert all(callable(c) for c in calls)
    # offload 后写入生效（HTTP 读回一致）
    listed = client.get("/config/api-keys").json()
    assert any(k["key_name"] == name for k in listed)


def test_toggle_api_key_offloads_via_run_sync(client: TestClient, monkeypatch):
    name = "tessa_offload_ak_toggle"
    client.put(
        f"/config/api-keys/{name}",
        json={"key_value": "tessa-offload-secret-2", "enabled": False},
    )

    calls: list = []
    _install_run_sync_spy(monkeypatch, calls)

    resp = client.put(f"/config/api-keys/{name}/toggle", json={"enabled": True})
    assert resp.status_code == 200
    # toggle 路由直接把 config_service.toggle_api_key 交给 run_sync
    assert any(c is config_service.toggle_api_key for c in calls), (
        "toggle_api_key 未把 config_service.toggle_api_key 交给 run_sync"
    )
    listed = client.get("/config/api-keys").json()
    item = next(k for k in listed if k["key_name"] == name)
    assert item["enabled"] is True


def test_delete_api_key_offloads_via_run_sync(client: TestClient, monkeypatch):
    name = "tessa_offload_ak_delete"
    client.put(
        f"/config/api-keys/{name}",
        json={"key_value": "tessa-offload-secret-3", "enabled": True},
    )

    calls: list = []
    _install_run_sync_spy(monkeypatch, calls)

    resp = client.delete(f"/config/api-keys/{name}")
    assert resp.status_code == 200
    # delete 路由直接把 config_service.delete_api_key 交给 run_sync
    assert any(c is config_service.delete_api_key for c in calls), (
        "delete_api_key 未把 config_service.delete_api_key 交给 run_sync"
    )
    listed = client.get("/config/api-keys").json()
    assert not any(k["key_name"] == name for k in listed)


# ── 2) 事件循环级非阻塞检查（尽力而为） ─────────────────────────────────────


def test_write_request_does_not_block_event_loop(monkeypatch):
    """写请求在途时，轻量 GET 仍应被及时响应（事件循环未被阻塞）。

    若该并发检查在特定环境不稳定，可删除本用例——run_sync 路径断言（上文
    3 个用例）已足以证明写路由经 run_sync offload。
    """
    monkeypatch.setattr(
        "app.services.effective_config.get_backend_auth_key",
        lambda: "test-key",
    )
    # RBAC v2: 配置管理路由需 admin 角色。
    monkeypatch.setattr(
        "app.core.config.settings",
        replace(settings, api_key_role="admin"),
    )
    import httpx

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=create_app())
        headers = {"X-API-Key": "test-key"}
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", headers=headers
        ) as ac:
            write_task = asyncio.create_task(
                ac.put(
                    "/config/data-source/open-data-presets",
                    json={"open_data_presets": {"noaa_nomads": "https://nomads.ncep.noaa.gov/"}},
                )
            )
            # 让写请求先进入事件循环（至少开始执行）
            await asyncio.sleep(0)
            t0 = time.monotonic()
            resp = await ac.get("/config/about")
            elapsed = time.monotonic() - t0
            assert resp.status_code == 200
            assert elapsed < 1.0, f"轻量 GET 被在途写请求阻塞了 {elapsed:.3f}s"
            write_resp = await write_task
            assert write_resp.status_code == 200

    asyncio.run(scenario())
