"""B-N2：retry 复用目录 claim（写互斥 + 持有者终态自愈抢占）。

问题（问题清单-2026-08-15 B-N2）：并发双 retry 解析出同一 ``reuse_output_dir``
后，两个新 run 会同时向该目录写 chunk checkpoint / 块缓存 → 并发写损坏。

设计（小设计，W3.5b）：
- 提交前先 acquire claim（Redis ``SET NX``，value=``pending:{token}``，TTL=300s）
- 提交成功且新 run 落库后 upgrade 为 ``{run_id}:{token}``（TTL=6h）
- 后续 retry acquire 冲突时检查持有者 run：
  * ``pending``（提交中）或 run 仍在跑 → 拒绝
  * run 已终态 / 已被清理 → Lua compare-and-delete 抢占后重取
- submit 抛错 / 新 run 未落库 → 立即 release
- Redis 不可用 → 进程内 dict 兜底（仅单进程内互斥，与 B-N3 sync 锁同定位）
"""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.workflow import reuse_cache
from app.services.workflow.reuse_cache import (
    RETRY_REUSE_PENDING_TTL_SECONDS,
    RETRY_REUSE_RUNNING_TTL_SECONDS,
    acquire_retry_reuse_claim,
    release_retry_reuse_claim,
    upgrade_retry_reuse_claim,
)
from app.services.workflow.retry_dispatcher import RetryDispatcher
from app.services.workflow.transition_builder import WorkflowTransitionBuilder
from shared.contracts.api_contracts import (
    ExecutionStatus,
    WorkflowAcceptedResponse,
    WorkflowCommandType,
    WorkflowPriority,
    WorkflowSubmitRequest,
)


class _ClaimRedis:
    """SET NX / GET / Lua compare-delete 与 compare-upgrade 的最小假客户端。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def set(
        self,
        key: str,
        value: str,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool | None:
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def eval(self, script: str, numkeys: int, *args: Any) -> int:
        # cas-delete: eval(script, 1, key, expected) -> 1/0
        # cas-upgrade: eval(script, 1, key, expected, new_value, ex) -> 1/0
        key, expected = args[0], args[1]
        if self.store.get(key) != expected:
            return 0
        if "cas-delete" in script:
            del self.store[key]
            self.ttls.pop(key, None)
            return 1
        if "cas-upgrade" in script:
            self.store[key] = args[2]
            self.ttls[key] = int(args[3])
            return 1
        raise AssertionError(f"unknown script marker: {script[:40]}")


class _FakeRepo:
    def __init__(self, statuses: dict[str, str] | None = None) -> None:
        self.statuses = statuses or {}
        self.calls: list[str] = []

    def get_run(self, run_id: str) -> Any:
        self.calls.append(run_id)
        status = self.statuses.get(run_id)
        if status is None:
            return None
        row = MagicMock()
        row.status = status
        return row


@pytest.fixture()
def claim_redis(monkeypatch: pytest.MonkeyPatch) -> _ClaimRedis:
    fake = _ClaimRedis()
    monkeypatch.setattr(reuse_cache, "get_redis_client", lambda: fake)
    return fake


@pytest.fixture()
def local_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reuse_cache, "get_redis_client", lambda: None)
    with reuse_cache._retry_reuse_local_lock:
        reuse_cache._retry_reuse_local_holders.clear()


REUSE_DIR = "I:/products/omega_sf"


# ── claim 原语：互斥 / 抢占 / 释放 ────────────────────────────────────────────


def test_claim_mutual_exclusion_while_pending(claim_redis: _ClaimRedis) -> None:
    repo = _FakeRepo()
    first = acquire_retry_reuse_claim(repo, REUSE_DIR)
    assert first is not None and first.startswith("pending:")
    # 提交窗口内的第二个 retry 必须被拒，且不触发持有者查询
    assert acquire_retry_reuse_claim(repo, REUSE_DIR) is None
    assert repo.calls == []


def test_claim_not_stealable_while_holder_running(claim_redis: _ClaimRedis) -> None:
    repo = _FakeRepo({"run-a": "running"})
    first = acquire_retry_reuse_claim(repo, REUSE_DIR)
    assert first is not None
    assert upgrade_retry_reuse_claim(REUSE_DIR, first, "run-a") is True
    assert acquire_retry_reuse_claim(repo, REUSE_DIR) is None
    assert repo.calls == ["run-a"]


@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled"])
def test_claim_stealable_when_holder_terminal(
    claim_redis: _ClaimRedis, status: str
) -> None:
    repo = _FakeRepo({"run-a": status})
    first = acquire_retry_reuse_claim(repo, REUSE_DIR)
    assert first is not None
    assert upgrade_retry_reuse_claim(REUSE_DIR, first, "run-a") is True
    second = acquire_retry_reuse_claim(repo, REUSE_DIR)
    assert second is not None and second != first


def test_claim_stealable_when_holder_run_cleaned(claim_redis: _ClaimRedis) -> None:
    """持有者 run 已被清理（get_run -> None）视为早已终态，可抢占。"""
    repo = _FakeRepo()
    first = acquire_retry_reuse_claim(repo, REUSE_DIR)
    assert first is not None
    assert upgrade_retry_reuse_claim(REUSE_DIR, first, "run-gone") is True
    assert acquire_retry_reuse_claim(repo, REUSE_DIR) is not None


def test_claim_release_allows_reacquire(claim_redis: _ClaimRedis) -> None:
    repo = _FakeRepo()
    first = acquire_retry_reuse_claim(repo, REUSE_DIR)
    assert first is not None
    release_retry_reuse_claim(REUSE_DIR, first)
    assert acquire_retry_reuse_claim(repo, REUSE_DIR) is not None


def test_claim_release_wrong_token_is_noop(claim_redis: _ClaimRedis) -> None:
    repo = _FakeRepo()
    first = acquire_retry_reuse_claim(repo, REUSE_DIR)
    assert first is not None
    release_retry_reuse_claim(REUSE_DIR, "pending:wrong-token")
    assert acquire_retry_reuse_claim(repo, REUSE_DIR) is None


def test_claim_upgrade_rejects_stale_token(claim_redis: _ClaimRedis) -> None:
    repo = _FakeRepo()
    first = acquire_retry_reuse_claim(repo, REUSE_DIR)
    assert first is not None
    assert upgrade_retry_reuse_claim(REUSE_DIR, "pending:stale", "run-x") is False
    assert claim_redis.store[
        f"workflow:retry-reuse:{_key_of(REUSE_DIR)}"
    ] == first


def test_claim_ttl_pending_then_running(claim_redis: _ClaimRedis) -> None:
    repo = _FakeRepo({"run-a": "running"})
    key = f"workflow:retry-reuse:{_key_of(REUSE_DIR)}"
    first = acquire_retry_reuse_claim(repo, REUSE_DIR)
    assert first is not None
    assert claim_redis.ttls[key] == RETRY_REUSE_PENDING_TTL_SECONDS
    assert upgrade_retry_reuse_claim(REUSE_DIR, first, "run-a") is True
    assert claim_redis.ttls[key] == RETRY_REUSE_RUNNING_TTL_SECONDS


def test_claim_same_dir_different_spellings_share_key(
    claim_redis: _ClaimRedis,
) -> None:
    repo = _FakeRepo()
    assert acquire_retry_reuse_claim(repo, REUSE_DIR) is not None
    assert acquire_retry_reuse_claim(repo, REUSE_DIR + "/") is None
    assert acquire_retry_reuse_claim(repo, " " + REUSE_DIR) is None


def _key_of(reuse_dir: str) -> str:
    import os

    import hashlib

    normalized = os.path.abspath(reuse_dir.strip())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


# ── Redis 不可用：进程内兜底 ────────────────────────────────────────────────


def test_claim_local_fallback_mutual_exclusion_and_steal(local_only: None) -> None:
    repo = _FakeRepo({"run-a": "running"})
    first = acquire_retry_reuse_claim(repo, REUSE_DIR)
    assert first is not None
    assert upgrade_retry_reuse_claim(REUSE_DIR, first, "run-a") is True
    assert acquire_retry_reuse_claim(repo, REUSE_DIR) is None

    repo.statuses["run-a"] = "failed"
    second = acquire_retry_reuse_claim(repo, REUSE_DIR)
    assert second is not None
    release_retry_reuse_claim(REUSE_DIR, second)
    assert acquire_retry_reuse_claim(repo, REUSE_DIR) is not None


# ── RetryDispatcher 接线 ─────────────────────────────────────────────────────


def _payload() -> WorkflowSubmitRequest:
    return WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        command_label="retry claim test",
        priority=WorkflowPriority.high,
        requested_outputs=[],
        algorithm_request={"algorithm_params": {}},
    )


def _accepted(run_id: str) -> WorkflowAcceptedResponse:
    return WorkflowAcceptedResponse(
        run_id=run_id,
        status=ExecutionStatus.accepted,
        status_url=f"/workflow-runs/{run_id}",
        events_url=f"/workflow-runs/{run_id}/events",
        created_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        message="re-submitted",
    )


def _run_status(run_id: str, status: ExecutionStatus) -> object:
    return WorkflowTransitionBuilder().build_execution_transition(
        run_id=run_id,
        payload=_payload(),
        status=status,
        progress=3,
        message=str(status.value),
        created_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        updated_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )


def _dispatcher(repo: Any, submit_fn: Any) -> RetryDispatcher:
    transitions = WorkflowTransitionBuilder()
    return RetryDispatcher(repo, MagicMock(), transitions, submit_fn)


def test_dispatcher_second_retry_rejected_while_first_running(
    claim_redis: _ClaimRedis,
) -> None:
    repo = MagicMock()
    repo.get_run_request_json.return_value = _payload().model_dump_json()
    repo.get_run_payload.return_value = None
    # 第一次 retry：resolve(new run) + claim 抢占检查（新 run accepted 非终态）
    repo.get_run.side_effect = [
        _run_status("run-new", ExecutionStatus.accepted),
        _run_status("run-new", ExecutionStatus.accepted),
    ]
    submit_fn = MagicMock(return_value=_accepted("run-new"))
    dispatcher = _dispatcher(repo, submit_fn)

    with patch(
        "app.services.workflow.retry_dispatcher.resolve_reuse_output_dir",
        lambda repository, run_id: (REUSE_DIR, "omega_sf"),
    ):
        assert dispatcher.retry_workflow_run("run-old").run_id == "run-new"
        with pytest.raises(ValueError, match="already in progress"):
            dispatcher.retry_workflow_run("run-old")

    assert submit_fn.call_count == 1


def test_dispatcher_releases_claim_when_submit_fails(
    claim_redis: _ClaimRedis,
) -> None:
    repo = MagicMock()
    repo.get_run_request_json.return_value = _payload().model_dump_json()

    def boom(_: WorkflowSubmitRequest) -> WorkflowAcceptedResponse:
        raise RuntimeError("queue down")

    dispatcher = _dispatcher(repo, boom)
    with patch(
        "app.services.workflow.retry_dispatcher.resolve_reuse_output_dir",
        lambda repository, run_id: (REUSE_DIR, "omega_sf"),
    ):
        with pytest.raises(RuntimeError, match="queue down"):
            dispatcher.retry_workflow_run("run-old")

    # claim 已释放：可立即再次 acquire
    assert acquire_retry_reuse_claim(_FakeRepo(), REUSE_DIR) is not None


def test_dispatcher_releases_claim_when_new_run_missing(
    claim_redis: _ClaimRedis,
) -> None:
    repo = MagicMock()
    repo.get_run_request_json.return_value = _payload().model_dump_json()
    repo.get_run.return_value = None
    submit_fn = MagicMock(return_value=_accepted("run-orphan"))
    dispatcher = _dispatcher(repo, submit_fn)

    with patch(
        "app.services.workflow.retry_dispatcher.resolve_reuse_output_dir",
        lambda repository, run_id: (REUSE_DIR, "omega_sf"),
    ):
        assert dispatcher.retry_workflow_run("run-old").run_id == "run-orphan"

    assert acquire_retry_reuse_claim(_FakeRepo(), REUSE_DIR) is not None


def test_dispatcher_claim_upgraded_to_holder_run_id(
    claim_redis: _ClaimRedis,
) -> None:
    repo = MagicMock()
    repo.get_run_request_json.return_value = _payload().model_dump_json()
    repo.get_run_payload.return_value = None
    repo.get_run.side_effect = [
        _run_status("run-new", ExecutionStatus.accepted),
        _run_status("run-new", ExecutionStatus.accepted),
    ]
    submit_fn = MagicMock(return_value=_accepted("run-new"))
    dispatcher = _dispatcher(repo, submit_fn)

    with patch(
        "app.services.workflow.retry_dispatcher.resolve_reuse_output_dir",
        lambda repository, run_id: (REUSE_DIR, "omega_sf"),
    ):
        dispatcher.retry_workflow_run("run-old")

    key = f"workflow:retry-reuse:{_key_of(REUSE_DIR)}"
    assert claim_redis.store[key].startswith("run-new:")


def test_dispatcher_without_reuse_dir_skips_claim(
    claim_redis: _ClaimRedis,
) -> None:
    """无可复用目录时不加锁（各 run 独立目录，本就无冲突）。"""
    repo = MagicMock()
    repo.get_run_request_json.return_value = _payload().model_dump_json()
    repo.get_run_payload.return_value = None
    repo.get_run.side_effect = [
        _run_status("run-new", ExecutionStatus.accepted),
    ]
    submit_fn = MagicMock(return_value=_accepted("run-new"))
    dispatcher = _dispatcher(repo, submit_fn)

    with patch(
        "app.services.workflow.retry_dispatcher.resolve_reuse_output_dir",
        lambda repository, run_id: (None, None),
    ):
        assert dispatcher.retry_workflow_run("run-old").run_id == "run-new"

    assert claim_redis.store == {}
