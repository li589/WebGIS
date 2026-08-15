"""并发加固回归（B-R1 / B-R2 / B-R3）。

覆盖 brooks-lint 并发审查确认的三个 P1 修复：
- B-R1 acquire_api_slot 须用 Lua 原子 INCR+EXPIRE，消除「INCR 后崩溃 → 计数器无 TTL 永久泄漏」
- B-R2 天气缓存临时文件名须唯一（pid + thread id），消除跨线程/跨进程同 key 竞态写
- B-R3 Open-Meteo 同步锁键须对 domains 归一化（排序+去重），消除「顺序不同的同一域集合漏互斥」
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from app.core import redis_client
from app.tasks import open_meteo_sync_tasks
from app.weatherengine.client import replace_with_retry, unique_cache_tmp_path


# ── B-R1：Redis API 槽位原子获取 ─────────────────────────────────────────────


class _EvalOnlyRedis:
    """只实现 eval 的假客户端：若实现仍走 incr/expire 分离调用会 AttributeError。"""

    def __init__(self, store: dict[str, int], ttls: dict[str, int]) -> None:
        self.store = store
        self.ttls = ttls
        self.eval_calls: list[tuple] = []

    def eval(self, script: str, numkeys: int, key: str, ttl: str | int) -> int:
        self.eval_calls.append((key, ttl))
        value = self.store.get(key, 0) + 1
        self.store[key] = value
        if value == 1 or key not in self.ttls:
            self.ttls[key] = int(ttl)
        return value

    def decr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) - 1
        return self.store[key]

    def set(self, key: str, value: int, ex: int | None = None) -> None:
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex


def test_acquire_api_slot_uses_atomic_lua(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _EvalOnlyRedis({}, {})
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: fake)
    assert redis_client.acquire_api_slot(pool="atomic-test") is True
    # 每次获取只允许一次 eval 往返；TTL 随同一次往返设置
    assert len(fake.eval_calls) == 1
    assert fake.ttls.get("weather:api_concurrent:atomic-test") == redis_client._API_SLOT_TTL


def test_acquire_api_slot_enforces_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _EvalOnlyRedis({}, {})
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: fake)
    limit = redis_client._MAX_CONCURRENT_API_CALLS_OPEN_METEO
    for _ in range(limit):
        assert redis_client.acquire_api_slot(pool="open-meteo.com", timeout=0.01) is True
    # 超限立即失败且计数回退
    assert redis_client.acquire_api_slot(pool="open-meteo.com", timeout=0.01) is False
    assert fake.store["weather:api_concurrent:open-meteo.com"] == limit


def test_acquire_api_slot_reapplies_ttl_on_orphaned_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模拟崩溃遗留的无 TTL 计数器：下一次获取须补挂 TTL，避免永久泄漏。"""
    fake = _EvalOnlyRedis({"weather:api_concurrent:orphan": 1}, {})
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: fake)
    assert redis_client.acquire_api_slot(pool="orphan") is True
    assert fake.ttls.get("weather:api_concurrent:orphan") == redis_client._API_SLOT_TTL


# ── B-R2：天气缓存临时文件唯一化 ─────────────────────────────────────────────


def test_unique_cache_tmp_path_differs_per_call() -> None:
    target = Path("cache") / "wind-field-best_match-6-23_1291_113_2644.json"
    first = unique_cache_tmp_path(target)
    second = unique_cache_tmp_path(target)
    assert first != second
    assert first.parent == target.parent
    assert first.name.startswith(target.stem)
    assert first.name.endswith(".tmp")


def test_unique_cache_tmp_path_concurrent_replace_is_safe() -> None:
    """N 线程各写唯一 tmp 后 replace 同一目标：无异常，最终文件为合法 JSON。"""
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        target = Path(tmpdir) / "grid-key.json"
        errors: list[Exception] = []

        def writer(index: int) -> None:
            try:
                tmp = unique_cache_tmp_path(target)
                tmp.write_text(
                    json.dumps({"payload": {"i": index}}), encoding="utf-8"
                )
                replace_with_retry(tmp, target)
            except Exception as exc:  # noqa: BLE001 - 收集所有线程错误
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["payload"]["i"] in range(8)
        # 目标目录不应残留被遗弃的 tmp 文件
        assert list(target.parent.glob("*.tmp")) == []


# ── B-R3：同步锁键归一化 ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("ecmwf_ifs025,gfs_global", "gfs_global,ecmwf_ifs025"),
        ("ecmwf_ifs025, gfs_global", "ecmwf_ifs025,gfs_global"),
        ("ecmwf_ifs025,gfs_global,", "ecmwf_ifs025,gfs_global"),
        ("a,b,a", "b,a"),
    ],
)
def test_sync_lock_key_normalizes_domain_order(left: str, right: str) -> None:
    assert open_meteo_sync_tasks._sync_lock_key(left) == open_meteo_sync_tasks._sync_lock_key(
        right
    )


def test_sync_lock_key_empty_falls_back_to_default() -> None:
    assert open_meteo_sync_tasks._sync_lock_key("") == "sync:default"
    assert open_meteo_sync_tasks._sync_lock_key(None) == "sync:default"  # type: ignore[arg-type]
