"""C-1（2026-08-23）：天气 provider 配置跨进程版本戳回归测试。

背景：``update_weather_provider`` 只写 DB + 改本进程 registry，多 worker
（BACKEND_FASTAPI_WORKERS>1 / Celery）下其余进程持旧 enabled/priority 直到
重启。修复 = Redis 版本戳 + 短 TTL 检查点（fetch 入口调用），≤5s 传播。

本测试用假 Redis 客户端隔离验证机制本身（不依赖真实 Redis/DB）。
"""

from __future__ import annotations

import pytest

from app.services import config_weather_providers as cwp
from app.weatherengine.provider_ids import OPEN_METEO_ONLINE_ID
from app.weatherengine.provider_registry import get_registry, register_default_providers


class _FakeRedis:
    """记录 GET/INCR 调用与版本的假 Redis。"""

    def __init__(self, version: int = 0) -> None:
        self.version = version
        self.get_calls = 0
        self.incr_calls = 0

    def get(self, key: str):
        self.get_calls += 1
        return str(self.version) if self.version else None

    def incr(self, key: str) -> int:
        self.incr_calls += 1
        self.version += 1
        return self.version


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """每个测试前：注册默认 provider + 清空 registry / 版本缓存 / 单例。"""
    from app.core.redis_client import reset_redis_client_state

    registry = get_registry()
    registry.clear()
    register_default_providers()
    cwp.reset_provider_override_refresh_state()
    cache_clear = getattr(cwp._get_weather_providers_repository, "cache_clear", None)
    if cache_clear is not None:
        cache_clear()
    reset_redis_client_state()
    yield
    cwp.reset_provider_override_refresh_state()
    cache_clear = getattr(cwp._get_weather_providers_repository, "cache_clear", None)
    if cache_clear is not None:
        cache_clear()


def _patch_redis(monkeypatch, fake: _FakeRedis) -> None:
    monkeypatch.setattr(cwp, "get_redis_client", lambda: fake)


def _patch_repo(monkeypatch, record: dict | None = None) -> None:
    if record is not None:
        record = {**record, "provider_id": OPEN_METEO_ONLINE_ID}

    class _FakeRepo:
        def get_provider(self, provider_id):
            return record

        def upsert_provider(self, **kwargs):
            return None

        def delete_provider(self, provider_id):
            return True

        def list_providers(self, *, include_disabled=True):
            return [record] if record else []

    monkeypatch.setattr(cwp, "_get_weather_providers_repository", lambda: _FakeRepo())


def test_update_bumps_version_stamp(monkeypatch) -> None:
    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)
    _patch_repo(monkeypatch, {"enabled": True, "priority": 1, "config": None})

    cwp.update_weather_provider(OPEN_METEO_ONLINE_ID, enabled=True)

    assert fake.incr_calls == 1, "DB 写入后必须 bump Redis 版本戳"


def test_delete_bumps_version_stamp(monkeypatch) -> None:
    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)
    _patch_repo(monkeypatch)

    cwp.delete_weather_provider(OPEN_METEO_ONLINE_ID)

    assert fake.incr_calls == 1


def test_refresh_replays_only_on_version_change(monkeypatch) -> None:
    fake = _FakeRedis(version=3)
    _patch_redis(monkeypatch, fake)
    applied: list[str] = []

    def _fake_apply() -> None:
        applied.append("apply")

    monkeypatch.setattr(cwp, "apply_persisted_provider_overrides", _fake_apply)

    cwp.maybe_refresh_provider_overrides(force=True)
    assert len(applied) == 1, "版本变化（3 != None）应重放一次"

    cwp.maybe_refresh_provider_overrides(force=True)
    assert len(applied) == 1, "版本未变不应重复重放"

    fake.version = 5
    cwp.maybe_refresh_provider_overrides(force=True)
    assert len(applied) == 2, "版本再次变化应重放"


def test_ttl_window_throttles_redis_reads(monkeypatch) -> None:
    fake = _FakeRedis(version=1)
    _patch_redis(monkeypatch, fake)
    monkeypatch.setattr(cwp, "apply_persisted_provider_overrides", lambda: None)

    # TTL 窗口内的两次调用只应读一次 Redis
    cwp.maybe_refresh_provider_overrides()
    cwp.maybe_refresh_provider_overrides()
    assert fake.get_calls == 1, "TTL 窗口内不得重复 GET 版本戳"

    # force=True 绕过 TTL（测试/启动场景）
    cwp.maybe_refresh_provider_overrides(force=True)
    assert fake.get_calls == 2


def test_redis_unavailable_degrades_silently(monkeypatch) -> None:
    monkeypatch.setattr(cwp, "get_redis_client", lambda: None)
    applied: list[str] = []
    monkeypatch.setattr(
        cwp, "apply_persisted_provider_overrides", lambda: applied.append("apply")
    )

    # 不得抛异常，也不得重放（降级为"重启生效"语义）
    cwp.maybe_refresh_provider_overrides(force=True)
    assert applied == []


def test_fetch_gateway_checkpoint_present_and_harmless() -> None:
    """fetch 入口带检查点且不破坏既有解析（冒烟）。"""
    from app.weatherengine import fetch_gateway
    from app.weatherengine.constants import WEATHER_LAYER_SPECS

    layer_id = next(iter(WEATHER_LAYER_SPECS))
    provider = fetch_gateway.resolve_provider_for_layer(layer_id)
    assert provider is not None

    rows = fetch_gateway.list_providers_for_layer(layer_id, include_disabled=True)
    assert isinstance(rows, list)
