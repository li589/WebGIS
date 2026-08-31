"""C-3（2026-08-23）：工作流执行互斥锁回归测试。

背景：``apply_async`` 8s 限时超时只放弃等待不撤销投递 + Beat 2min 重派 →
同 run 双消息；worker 端 running 重投原逻辑"警告后从头执行" → 与原 worker
并发。修复 = Redis 执行锁（双消息跳过 / 持有者死亡接管 / Redis 故障降级）。
"""

from __future__ import annotations

import os
import socket

import pytest

from app.services.workflow.execution_lock import (
    LockAcquireResult,
    WorkflowExecutionLock,
    is_local_process_alive,
)


class _FakeLockRedis:
    """实现锁所需最小接口的假 Redis（含 delete_if_equal 语义）。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, bool]] = []

    def set(self, key: str, value: str, nx: bool = False, ex: int = 0):
        self.set_calls.append((key, value, nx))
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def get(self, key: str):
        return self.store.get(key)

    def eval(self, script: str, numkeys: int, key: str, value: str):
        # 模拟 delete_if_equal lua
        if self.store.get(key) == value:
            del self.store[key]
            return 1
        return 0


def _lock(fake: _FakeLockRedis, alive_checker=None) -> WorkflowExecutionLock:
    return WorkflowExecutionLock(
        lambda: fake, alive_checker=alive_checker or (lambda h, p: True)
    )


# ── 锁模块行为 ─────────────────────────────────────────────────────────────


def test_first_acquire_succeeds() -> None:
    fake = _FakeLockRedis()
    result = _lock(fake).acquire("run-a")
    assert result.state == "acquired"
    assert result.token is not None
    assert fake.store["cgda:workflow:execution_lock:run-a"] == result.token


def test_second_acquire_blocked_when_holder_alive() -> None:
    fake = _FakeLockRedis()
    lock = _lock(fake, alive_checker=lambda h, p: True)
    first = lock.acquire("run-a")
    assert first.state == "acquired"

    second = lock.acquire("run-a")
    assert second.state == "blocked"
    assert second.token is None
    assert fake.store["cgda:workflow:execution_lock:run-a"] == first.token


def test_takeover_when_holder_dead() -> None:
    fake = _FakeLockRedis()
    # 预置死亡持有者（本机 hostname + 不存在的 pid）
    dead_holder = f"{socket.gethostname()}:99999999:deadbeef"
    fake.store["cgda:workflow:execution_lock:run-a"] = dead_holder

    result = _lock(fake, alive_checker=lambda h, p: False).acquire("run-a")
    assert result.state == "takeover"
    assert result.token is not None
    assert fake.store["cgda:workflow:execution_lock:run-a"] == result.token


def test_takeover_race_loser_blocked() -> None:
    fake = _FakeLockRedis()
    dead_holder = f"{socket.gethostname()}:99999999:deadbeef"
    fake.store["cgda:workflow:execution_lock:run-a"] = dead_holder

    class _RacingRedis(_FakeLockRedis):
        """接管 eval 删除后、SET NX 前被其他重投 worker 抢先写入。"""

        def eval(self, script, numkeys, key, value):
            result = super().eval(script, numkeys, key, value)
            if result:
                # 模拟抢先接管者：删除成功瞬间第三方写入
                self.store[key] = f"{socket.gethostname()}:42:raced"
            return result

    fake_racing = _RacingRedis()
    fake_racing.store.update(fake.store)
    result = _lock(fake_racing, alive_checker=lambda h, p: False).acquire("run-a")
    assert result.state == "blocked"


def test_cross_host_holder_treated_alive() -> None:
    fake = _FakeLockRedis()
    fake.store["cgda:workflow:execution_lock:run-a"] = "other-host:123:abc"
    # 跨机部署 alive_checker 返回 None → 保守 blocked
    result = _lock(fake, alive_checker=lambda h, p: None).acquire("run-a")
    assert result.state == "blocked"


def test_release_value_matched() -> None:
    fake = _FakeLockRedis()
    lock = _lock(fake)
    result = lock.acquire("run-a")
    assert result.state == "acquired"

    lock.release("run-a", result.token)
    assert "cgda:workflow:execution_lock:run-a" not in fake.store

    # 释放后可重新获取
    again = lock.acquire("run-a")
    assert again.state == "acquired"


def test_release_does_not_delete_others_lock() -> None:
    fake = _FakeLockRedis()
    lock = _lock(fake)
    lock.acquire("run-a")
    # 用错误 token 释放（模拟接管者已换锁）
    lock.release("run-a", "wrong-token")
    assert "cgda:workflow:execution_lock:run-a" in fake.store


def test_redis_unavailable_degrades_open() -> None:
    def _broken_provider():
        raise ConnectionError("redis down")

    lock = WorkflowExecutionLock(_broken_provider)
    result = lock.acquire("run-a")
    assert result.state == "degraded"
    assert result.token is None
    # 释放不抛
    lock.release("run-a", None)


def test_release_redis_error_silent() -> None:
    fake = _FakeLockRedis()
    lock = _lock(fake)
    result = lock.acquire("run-a")

    def _broken_provider():
        raise ConnectionError("redis down")

    lock2 = WorkflowExecutionLock(_broken_provider)
    lock2.release("run-a", result.token)  # 不应抛异常


# ── 进程探活 ────────────────────────────────────────────────────────────────


def test_alive_checker_current_pid_alive() -> None:
    # 当前进程 pid 一定活着
    assert is_local_process_alive(socket.gethostname(), os.getpid()) is True


def test_alive_checker_dead_pid() -> None:
    # Windows pid 空间 32 位；99999999 一定不存在
    assert is_local_process_alive(socket.gethostname(), 99999999) is False


def test_alive_checker_cross_host_unknown() -> None:
    assert is_local_process_alive("definitely-not-this-host", 123) is None


# ── submission_service 集成 ─────────────────────────────────────────────────


@pytest.fixture()
def integration_env(monkeypatch, tmp_path):
    """构造带 fake redis 锁的 submission_service + 执行探针。"""
    fake_redis = _FakeLockRedis()
    executed: list[str] = []

    # 探测执行体是否被进入：monkeypatch execute_workflow_task
    import app.services.workflow.submission_service as svc_mod

    class _ProbeError(Exception):
        pass

    def _probe_execute(**kwargs):
        executed.append(kwargs["run_id"])
        raise _ProbeError("stop-here")  # 深入执行无必要：到这一步即证明"会执行"

    monkeypatch.setattr(svc_mod, "execute_workflow_task", _probe_execute)

    from app.services.workflow.execution_lock import WorkflowExecutionLock
    from app.services.workflow.persistence_service import (
        WorkflowPersistenceService,
    )
    from app.services.workflow.transition_builder import (
        WorkflowTransitionBuilder,
    )

    class _StubRepo:
        def __init__(self) -> None:
            self.runs: dict[str, object] = {}

        def get_run(self, run_id):
            return self.runs.get(run_id)

    class _StubPersistence:
        def __init__(self) -> None:
            self.events: list[dict] = []

        def record_event(self, **kwargs):
            self.events.append(kwargs)

        def save_run_status(self, **kwargs):
            pass

    from shared.contracts.api_contracts import WorkflowSubmitRequest

    payload = WorkflowSubmitRequest.model_validate(
        {"command_type": "analysis", "parameters": {}}
    )

    repo = _StubRepo()
    persistence = _StubPersistence()
    service = svc_mod.WorkflowSubmissionService(
        repository=repo,
        persistence=persistence,
        transitions=WorkflowTransitionBuilder(),
        execution_lock=WorkflowExecutionLock(lambda: fake_redis),
    )

    # 绑定 stub lifecycle：ProbeError 走 failure/timeout 分支不炸
    class _StubLifecycle:
        def handle_workflow_failure(self, **kwargs):
            pass

        def handle_workflow_timeout(self, **kwargs):
            pass

        def finalize_workflow_success(self, **kwargs):
            pass

    service.set_lifecycle_service(_StubLifecycle())
    return {
        "service": service,
        "repo": repo,
        "persistence": persistence,
        "fake_redis": fake_redis,
        "executed": executed,
        "payload": payload,
    }


def test_duplicate_delivery_skips_execution(integration_env, monkeypatch) -> None:
    """C-3 核心场景：另一 worker 持锁执行中，第二条消息到达 → 不执行。"""
    env = integration_env
    # 模拟第一条消息的 worker 正在执行（持锁、进程活着——用当前 pid）
    holder = f"{socket.gethostname()}:{os.getpid()}:firstworker"
    env["fake_redis"].store["cgda:workflow:execution_lock:run-dup"] = holder

    env["service"].process_workflow_run("run-dup", env["payload"])
    assert env["executed"] == []  # 未进入执行体
    # 有"重复投递被拦截"事件
    messages = [e.get("message", "") for e in env["persistence"].events]
    assert any("拦截" in m for m in messages)
    # 锁未被误删（blocked 路径不释放他人锁）
    assert env["fake_redis"].store["cgda:workflow:execution_lock:run-dup"] == holder


def test_first_execution_lock_released_on_failure(integration_env) -> None:
    """执行失败（异常）后 finally 释放锁 → 重投可重新执行。"""
    env = integration_env
    env["service"].process_workflow_run("run-rel", env["payload"])
    assert env["executed"] == ["run-rel"]
    # probe 抛错 → finally 释放锁 → 锁位空闲
    assert "cgda:workflow:execution_lock:run-rel" not in env["fake_redis"].store

    env["executed"].clear()
    env["service"].process_workflow_run("run-rel", env["payload"])
    assert env["executed"] == ["run-rel"]  # 可重新执行


def test_degraded_lock_still_executes(integration_env) -> None:
    """Redis 不可用 → fail-open 保持原行为（执行）。"""
    env = integration_env

    # 让 redis provider 抛错
    def _broken_provider():
        raise ConnectionError("down")

    env["service"]._execution_lock._client_provider = _broken_provider
    env["service"].process_workflow_run("run-deg", env["payload"])
    assert env["executed"] == ["run-deg"]
