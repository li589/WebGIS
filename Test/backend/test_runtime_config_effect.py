"""运行时配置「写入→生效」修复回归测试（P-A / P-B / P-C）。

对应 .ai/progress/2026-08-18-config-effect-verification.md 的修复项，防止回归：

- P-B：runtime PATCH 白名单与前端 GeneralSettings 键对齐。
  workflow_node_parallelism / algorithm_max_parallel_workers /
  task_memory_budget_mb / task_cpu_budget_cores 此前 PATCH 必 400
  （消费方已就绪但白名单拒绝）。
- P-A：log_level 快照应用到根 logger。此前全仓零消费（惰性键），
  FE 描述「立即生效」为虚假承诺。
- P-C：Celery worker 启动钩子应用 DB 持久化配置。此前仅 FastAPI
  进程 hydrate，worker 侧 PATCH 后不生效直至重启。
"""

from __future__ import annotations

import logging
import weakref
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator

import pytest

from app.services.workflow_repository import SQLiteWorkflowRepository
from app.services.workflow.runtime_status_service import RuntimeStatusService
from shared.contracts.api_contracts import (
    RuntimeConfigPatch,
    RuntimeConfigScope,
    RuntimeConfigUpdateRequest,
)

P_B_CONCURRENCY_KEYS: dict[str, int] = {
    "workflow_node_parallelism": 4,
    "algorithm_max_parallel_workers": 3,
    "task_memory_budget_mb": 2048,
    "task_cpu_budget_cores": 2,
}


@contextmanager
def _temp_repository() -> Iterator[SQLiteWorkflowRepository]:
    """临时 repository；Windows 上须先关连接池再清目录。"""
    with TemporaryDirectory() as tmpdir:
        repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
        try:
            yield repository
        finally:
            repository.close()


def _patch_items(pairs: dict[str, object]) -> RuntimeConfigUpdateRequest:
    return RuntimeConfigUpdateRequest(
        items=[
            RuntimeConfigPatch(scope=RuntimeConfigScope.backend, key=key, value=value)
            for key, value in pairs.items()
        ]
    )


def _as_dev_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings 为 frozen dataclass：整体替换为 environment=development 的副本。"""
    from app.core.config import settings

    monkeypatch.setattr(
        "app.core.config.settings", replace(settings, environment="development")
    )


def _isolate_effective_config(monkeypatch: pytest.MonkeyPatch, overrides: dict):
    """hydrate 读 tmp overrides 并跳过 DB api-key 表（沿用 test_concurrency_config 规避）。"""
    from app.services import effective_config

    monkeypatch.setattr(effective_config, "_hydrated", False)
    monkeypatch.setattr(
        effective_config, "_load_runtime_overrides", lambda: dict(overrides)
    )
    monkeypatch.setattr(
        "app.services.config_service.get_effective_api_key", lambda name: None
    )
    monkeypatch.setattr(
        "app.services.config_service.has_api_key_db_row", lambda name: False
    )
    return effective_config


# ── P-B：白名单对齐（PATCH 200 + 快照生效 + 边界仍拒绝）──────────────────


class TestPatchWhitelistAlignment:
    def test_concurrency_keys_accepted_and_persisted(self) -> None:
        """此前 4 键 PATCH 必 400；修复后 accepted 且 DB 快照读回新值。"""
        with _temp_repository() as repository:
            service = RuntimeStatusService(repository)
            resp = service.update_runtime_config(_patch_items(P_B_CONCURRENCY_KEYS))
            assert resp.accepted is True
            assert resp.applied_count == 4
            backend = resp.config_snapshot["backend"]
            for key, value in P_B_CONCURRENCY_KEYS.items():
                assert backend[key] == value, key

    def test_patch_projects_into_effective_snapshot(self, monkeypatch) -> None:
        """PATCH 写入 DB 后经 hydrate 投影到 getter（写入→生效闭环）。"""
        effective_config = _isolate_effective_config(
            monkeypatch, dict(P_B_CONCURRENCY_KEYS)
        )
        snap = effective_config.hydrate_effective_config()
        assert snap.workflow_node_parallelism == 4
        assert snap.algorithm_max_parallel_workers == 3
        assert snap.task_memory_budget_mb == 2048
        assert snap.task_cpu_budget_cores == 2
        assert effective_config.get_workflow_node_parallelism() == 4
        assert effective_config.get_algorithm_max_parallel_workers() == 3
        assert effective_config.get_task_memory_budget_mb() == 2048
        assert effective_config.get_task_cpu_budget_cores() == 2

    def test_out_of_range_values_rejected(self) -> None:
        """白名单放行不等于放弃边界：越界值仍 400（ValueError）。"""
        cases = {
            "workflow_node_parallelism": (0, 17),
            "algorithm_max_parallel_workers": (-1, 65),
            "task_memory_budget_mb": (-1, 65537),
            "task_cpu_budget_cores": (-1, 65),
        }
        with _temp_repository() as repository:
            service = RuntimeStatusService(repository)
            for key, (low, high) in cases.items():
                for bad in (low, high):
                    with pytest.raises(ValueError, match=key):
                        service.update_runtime_config(_patch_items({key: bad}))

    def test_ghost_key_still_rejected(self) -> None:
        """回归防护：幽灵 key（无消费方）不得因白名单扩容而混入。"""
        with _temp_repository() as repository:
            service = RuntimeStatusService(repository)
            with pytest.raises(ValueError, match="Unsupported runtime config key"):
                service.update_runtime_config(
                    _patch_items({"default_queue": "workflow.standard"})
                )

    def test_bool_rejected_for_int_key(self) -> None:
        """bool 是 int 子类，验证器须显式排除（True≠1 合法值）。"""
        with _temp_repository() as repository:
            service = RuntimeStatusService(repository)
            with pytest.raises(ValueError, match="expected int"):
                service.update_runtime_config(
                    _patch_items({"task_memory_budget_mb": True})
                )


# ── P-A：log_level 快照应用到根 logger ────────────────────────────────────


class TestLogLevelApplication:
    @pytest.fixture(autouse=True)
    def _restore_root_level(self):
        root = logging.getLogger()
        before = root.level
        yield
        root.setLevel(before)

    def test_test_env_is_noop(self) -> None:
        """test/testing 环境跳过应用，避免干扰 pytest 日志捕获。"""
        from app.services.effective_config import _apply_runtime_log_level

        root = logging.getLogger()
        before = root.level
        _apply_runtime_log_level("ERROR")
        assert root.level == before

    def test_dev_env_applies_to_root_logger(self, monkeypatch) -> None:
        """非 test 环境应用到根 logger（此前全仓零消费，惰性键）。"""
        from app.services.effective_config import _apply_runtime_log_level

        _as_dev_environment(monkeypatch)
        _apply_runtime_log_level("WARNING")
        assert logging.getLogger().level == logging.WARNING

    def test_invalid_level_ignored(self, monkeypatch, caplog) -> None:
        """非法级别告警而非抛错，级别保持不变。"""
        from app.services.effective_config import _apply_runtime_log_level

        _as_dev_environment(monkeypatch)
        root = logging.getLogger()
        before = root.level
        _apply_runtime_log_level("NOT_A_LEVEL")
        assert root.level == before

    def test_hydrate_applies_snapshot_log_level(self, monkeypatch) -> None:
        """hydrate 链路将快照 log_level 应用到根 logger（写入→生效闭环）。"""
        effective_config = _isolate_effective_config(
            monkeypatch, {"log_level": "ERROR"}
        )
        _as_dev_environment(monkeypatch)
        snap = effective_config.hydrate_effective_config()
        assert snap.log_level == "ERROR"
        assert logging.getLogger().level == logging.ERROR


# ── P-C：Celery worker 启动钩子 ───────────────────────────────────────────


def _iter_receivers(signal):
    """yield 信号 receiver 函数（receivers 为 (key, weakref) 元组列表）。"""
    for entry in signal.receivers:
        ref = entry[1] if isinstance(entry, tuple) else entry
        target = ref() if isinstance(ref, weakref.ref) else ref
        if target is not None:
            yield target


def _receiver_names(signal) -> set[str]:
    names: set[str] = set()
    for target in _iter_receivers(signal):
        name = getattr(target, "__name__", None)
        if name:
            names.add(name)
    return names


def _find_receiver(signal, name: str):
    for target in _iter_receivers(signal):
        if getattr(target, "__name__", None) == name:
            return target
    return None


@pytest.fixture
def worker_signals():
    pytest.importorskip("celery")
    import app.core.celery_app  # noqa: F401 — 触发模块级信号注册

    from celery.signals import worker_process_init, worker_ready

    return worker_ready, worker_process_init


class TestWorkerBootstrapHook:
    def test_signals_registered(self, worker_signals) -> None:
        """worker_ready / worker_process_init 均注册 bootstrap 钩子。"""
        worker_ready, worker_process_init = worker_signals
        assert "_on_worker_ready" in _receiver_names(worker_ready)
        assert "_on_worker_process_init" in _receiver_names(worker_process_init)

    def test_bootstrap_applies_celery_limits(self, worker_signals, monkeypatch) -> None:
        """prefork 钩子真实应用 runtime celery 时限到 conf（非仅注册）。"""
        from app.core.celery_app import celery_app

        _isolate_effective_config(
            monkeypatch,
            {
                "celery_task_soft_time_limit": 111,
                "celery_task_time_limit": 222,
            },
        )
        _, worker_process_init = worker_signals
        receiver = _find_receiver(worker_process_init, "_on_worker_process_init")
        assert receiver is not None
        before = (
            celery_app.conf.task_soft_time_limit,
            celery_app.conf.task_time_limit,
        )
        try:
            receiver()
            assert celery_app.conf.task_soft_time_limit == 111
            assert celery_app.conf.task_time_limit == 222
        finally:
            celery_app.conf.update(
                task_soft_time_limit=before[0],
                task_time_limit=before[1],
            )

    def test_bootstrap_tolerates_backend_failures(
        self, worker_signals, monkeypatch
    ) -> None:
        """DB/依赖不可用时仅告警不抛错（保持 env/code 默认，不阻断 worker 启动）。"""
        _, worker_process_init = worker_signals
        receiver = _find_receiver(worker_process_init, "_on_worker_process_init")
        assert receiver is not None

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated backend outage")

        monkeypatch.setattr(
            "app.services.config_weather_providers.apply_persisted_provider_overrides",
            _boom,
        )
        monkeypatch.setattr(
            "app.services.effective_config.hydrate_effective_config",
            _boom,
        )
        receiver()  # 不得抛出
