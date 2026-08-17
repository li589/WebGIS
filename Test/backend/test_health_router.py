"""W8：/health 存活探测解耦——async 端点 + 中间件早退（不触 Redis 指标/限流）。

高负载时同步端点占满线程池、Redis 指标抖动曾拖慢 /health，导致前端误报断联。
回归约束：
- /health 返回 200 且为 async 处理器（不再走线程池）；
- /health 请求不触发 record_request_metric（Redis 写）；
- 其它路径的指标记录行为保持不变。
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_CODE_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_PROVIDER = _CODE_ROOT / "algorithms" / "providers" / "Python"
for _p in (_PYTHON_PROVIDER, _CODE_ROOT):
    _s = str(_p)
    if _s in sys.path:
        sys.path.remove(_s)
    sys.path.insert(0, _s)


@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_ENV", "test")
    monkeypatch.setenv("BACKEND_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("BACKEND_OUTPUT_ROOT", str(tmp_path / "out"))
    monkeypatch.setenv("BACKEND_WORKFLOW_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("BACKEND_API_KEYS_ENABLED", "false")

    import app.core.config as cfg_mod
    from app.core.config import Settings

    cfg_mod.settings = Settings()

    from app.main import create_app

    return TestClient(create_app())


def test_health_returns_ok(api_client: TestClient):
    resp = api_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"]


def test_health_handler_is_async():
    from app.api.routers.health_router import health_check

    assert inspect.iscoroutinefunction(health_check), (
        "/health 必须为 async 处理器：同步 def 走 Starlette 线程池，"
        "高负载时与瓦片渲染/导入等同步端点争抢线程导致健康检查排队超时"
    )


def test_health_skips_request_metric(api_client: TestClient, monkeypatch):
    import app.main as main_mod

    calls: list[str] = []

    def _spy(*args, **kwargs):
        calls.append("metric")

    monkeypatch.setattr(main_mod, "record_request_metric", _spy)

    resp = api_client.get("/health")
    assert resp.status_code == 200
    assert calls == [], "/health 不应触发 Redis 指标记录"


def test_other_paths_still_record_metric(api_client: TestClient, monkeypatch):
    import app.main as main_mod

    calls: list[str] = []

    def _spy(*args, **kwargs):
        calls.append("metric")

    monkeypatch.setattr(main_mod, "record_request_metric", _spy)

    resp = api_client.get("/this-route-does-not-exist")
    assert resp.status_code == 404
    assert calls == ["metric"], "非 /health 路径的指标记录行为应保持不变"
