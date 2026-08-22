"""批次4（2026-08-23）：A-2 配置快照跨进程版本戳 + C-2 瓦片槽位配置化 + C-4 LRU 并发安全。

A-2 背景：API key 写路径只 rehydrate 本进程快照，多 worker（FastAPI workers>1 /
Celery）下其余进程持旧密钥直到重启（get_backend_auth_key 在鉴权热路径上）。
修复 = Redis 版本戳 + 5s TTL 检查点（get_runtime_snapshot 入口），与 C-1 同构。

C-2：weather_tile_max_concurrent 从常量 6 改为 settings 可配置（重启生效），
显式传参优先（测试用）。

C-4：tile LRU（OrderedDict）被事件循环线程与 anyio/Celery 线程池并发读写，
无锁会 RuntimeError: mutated during iteration——修复 = threading.Lock 统一保护。

本测试用假 Redis 客户端与轻量 service 实例隔离验证机制（不依赖真实 Redis/DB）。
"""

from __future__ import annotations

import threading

import pytest
from redis import RedisError

from app.services import effective_config as ec
from app.services.effective_config import RuntimeSnapshot


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


class _BrokenRedis:
    """所有操作抛 RedisError 的假 Redis（验证降级）。"""

    def get(self, key: str):
        raise RedisError("connection lost")

    def incr(self, key: str) -> int:
        raise RedisError("connection lost")


@pytest.fixture(autouse=True)
def _clean_effective_config_state(monkeypatch):
    """每个测试前：重置快照状态与版本戳缓存；teardown 恢复未 hydrate 状态。"""
    ec._hydrated = False
    ec._snapshot = RuntimeSnapshot()
    ec.reset_effective_config_refresh_state()
    yield
    ec._hydrated = False
    ec._snapshot = RuntimeSnapshot()
    ec.reset_effective_config_refresh_state()


def _patch_redis(monkeypatch, fake) -> None:
    monkeypatch.setattr("app.core.redis_client.get_redis_client", lambda: fake)


# ── A-2：版本戳机制 ───────────────────────────────────────────────────────────


def test_bump_increments_version_stamp(monkeypatch) -> None:
    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)

    ec.bump_effective_config_version()

    assert fake.incr_calls == 1


def test_bump_silent_when_redis_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("app.core.redis_client.get_redis_client", lambda: None)
    ec.bump_effective_config_version()  # 不应抛异常

    broken = _BrokenRedis()
    _patch_redis(monkeypatch, broken)
    ec.bump_effective_config_version()  # RedisError 静默


def test_version_change_triggers_rehydrate(monkeypatch) -> None:
    fake = _FakeRedis(version=0)
    _patch_redis(monkeypatch, fake)
    hydrate_calls: list[int] = []
    monkeypatch.setattr(ec, "hydrate_effective_config", lambda: hydrate_calls.append(1))
    # 已 hydrate 状态；首查把 None→0 记为基线（多一次幂等 rehydrate，无害）
    ec._hydrated = True
    ec._snapshot = RuntimeSnapshot(hydrated=True)
    ec.get_runtime_snapshot()
    baseline = len(hydrate_calls)
    assert baseline == 1
    assert ec._snapshot_refresh_state["version"] == 0

    # 版本未变 + TTL 过期 → 不再 rehydrate
    ec._snapshot_refresh_state["checked_at"] = 0.0
    ec.get_runtime_snapshot()
    assert len(hydrate_calls) == baseline

    # 其他进程 bump → 版本变化 → rehydrate 且记录新版本
    fake.version = 1
    ec._snapshot_refresh_state["checked_at"] = 0.0  # 强制 TTL 过期
    ec.get_runtime_snapshot()
    assert len(hydrate_calls) == baseline + 1
    assert ec._snapshot_refresh_state["version"] == 1


def test_ttl_window_throttles_redis_reads(monkeypatch) -> None:
    fake = _FakeRedis(version=0)
    _patch_redis(monkeypatch, fake)
    ec._hydrated = True
    ec._snapshot = RuntimeSnapshot(hydrated=True)

    ec.get_runtime_snapshot()
    first = fake.get_calls
    ec.get_runtime_snapshot()
    ec.get_runtime_snapshot()

    assert fake.get_calls == first  # TTL 窗口内零额外 Redis 读


def test_redis_unavailable_degrades_gracefully(monkeypatch) -> None:
    monkeypatch.setattr("app.core.redis_client.get_redis_client", lambda: None)
    ec._hydrated = True
    snap = RuntimeSnapshot(hydrated=True)
    ec._snapshot = snap

    result = ec.get_runtime_snapshot()

    assert result is snap  # 原快照原样返回，不抛异常

    broken = _BrokenRedis()
    _patch_redis(monkeypatch, broken)
    ec._snapshot_refresh_state["checked_at"] = 0.0
    assert ec.get_runtime_snapshot() is snap  # RedisError 降级同样安全


def test_first_check_after_hydrate_reads_version(monkeypatch) -> None:
    """启动 hydrate 后首次检查应记录版本（后续 bump 才能被感知）。"""
    fake = _FakeRedis(version=7)
    _patch_redis(monkeypatch, fake)
    ec._hydrated = True
    ec._snapshot = RuntimeSnapshot(hydrated=True)

    ec.get_runtime_snapshot()

    assert ec._snapshot_refresh_state["version"] == 7


# ── C-2：瓦片槽位配置化 ───────────────────────────────────────────────────────


def test_tile_max_concurrent_default_from_settings() -> None:
    """默认值经 settings 解析（env BACKEND_WEATHER_TILE_MAX_CONCURRENT，缺省 6）。"""
    from app.core.config import settings

    assert settings.weather_tile_max_concurrent >= 1


def test_tile_service_reads_settings_when_param_none() -> None:
    """不传参时从 settings 读取（真实 settings；frozen 不可 patch）。"""
    from app.core.config import settings
    from app.weatherengine.tile_service import WeatherTileService

    svc = WeatherTileService(engine_service=object())
    assert svc._max_concurrent == settings.weather_tile_max_concurrent


def test_tile_service_explicit_param_overrides_settings() -> None:
    from app.weatherengine.tile_service import WeatherTileService

    svc = WeatherTileService(engine_service=object(), max_concurrent=2)
    assert svc._max_concurrent == 2


# ── C-4：LRU 并发安全 ─────────────────────────────────────────────────────────


def _light_tile_service(cache_max: int = 8):
    """绕过 __init__ 的轻量实例（不构造 WeatherEngineService）。"""
    from collections import OrderedDict

    from app.weatherengine.tile_service import WeatherTileService

    svc = WeatherTileService.__new__(WeatherTileService)
    svc._in_memory_cache = OrderedDict()
    svc._in_memory_cache_max = cache_max
    svc._cache_lock = threading.Lock()
    return svc


def test_lru_concurrent_read_write_no_error() -> None:
    """多线程混合读写（含 move_to_end/popitem 驱逐）不再 mutated during iteration。"""
    svc = _light_tile_service(cache_max=8)
    errors: list[Exception] = []

    def worker(seed: int) -> None:
        try:
            for i in range(2000):
                key = f"k{(seed * 31 + i) % 16}"
                if i % 3 == 0:
                    svc._write_memory_cache(key, {"v": i})
                else:
                    svc._read_memory_cache(key)
        except Exception as exc:  # noqa: BLE001 — 收集并发错误
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(s,)) for s in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"并发读写出现异常: {errors[:3]}"
    assert len(svc._in_memory_cache) <= 8  # 上限不被突破


def test_lru_write_evicts_oldest() -> None:
    svc = _light_tile_service(cache_max=2)
    svc._write_memory_cache("a", {"v": 1})
    svc._write_memory_cache("b", {"v": 2})
    svc._write_memory_cache("c", {"v": 3})

    assert "a" not in svc._in_memory_cache
    assert len(svc._in_memory_cache) == 2
    assert svc._read_memory_cache("c") == {"v": 3}
