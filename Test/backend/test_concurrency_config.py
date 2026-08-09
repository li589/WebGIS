"""并发与资源配置投影测试。

验证 effective_config.RuntimeSnapshot 正确投影新增的并发/资源字段，
以及 runtime config PATCH 覆盖生效：
- workflow_node_parallelism（工作流节点并行度，热更新）
- algorithm_max_parallel_workers（算法并行进程上限，热更新）
- task_memory_budget_mb / task_cpu_budget_cores（声明值，调度准入参考）
"""

from __future__ import annotations

import pytest

from app.services import effective_config


def _hydrate_with_overrides(
    monkeypatch, overrides: dict
) -> effective_config.RuntimeSnapshot:
    """用指定 runtime_config overrides 重建 effective_config 投影。

    规避 DB 依赖：monkeypatch _load_runtime_overrides + get_effective_api_key。
    """
    monkeypatch.setattr(effective_config, "_hydrated", False)
    monkeypatch.setattr(
        effective_config,
        "_load_runtime_overrides",
        lambda: dict(overrides),
    )
    # 规避 SQLite api_keys 表依赖
    monkeypatch.setattr(
        "app.services.config_service.get_effective_api_key", lambda name: None
    )
    monkeypatch.setattr(
        "app.services.config_service.has_api_key_db_row", lambda name: False
    )
    return effective_config.hydrate_effective_config()


class TestConcurrencyConfigHydration:
    def test_new_fields_present_in_snapshot(self) -> None:
        """RuntimeSnapshot 包含新增并发/资源字段且有合理默认。"""
        snap = effective_config.RuntimeSnapshot()
        assert snap.workflow_node_parallelism == 1
        assert snap.algorithm_max_parallel_workers == 0
        assert snap.task_memory_budget_mb == 0
        assert snap.task_cpu_budget_cores == 0

    def test_overrides_projected_to_snapshot(self, monkeypatch) -> None:
        """runtime_config overrides 正确投影到新字段。"""
        snap = _hydrate_with_overrides(
            monkeypatch,
            {
                "workflow_node_parallelism": 4,
                "algorithm_max_parallel_workers": 3,
                "task_memory_budget_mb": 2048,
                "task_cpu_budget_cores": 2,
            },
        )
        assert snap.workflow_node_parallelism == 4
        assert snap.algorithm_max_parallel_workers == 3
        assert snap.task_memory_budget_mb == 2048
        assert snap.task_cpu_budget_cores == 2
        assert snap.hydrated is True

    def test_getters_return_snapshot_values(self, monkeypatch) -> None:
        """getter 函数返回当前 snapshot 值。"""
        _hydrate_with_overrides(
            monkeypatch,
            {
                "workflow_node_parallelism": 8,
                "algorithm_max_parallel_workers": 5,
                "task_memory_budget_mb": 4096,
                "task_cpu_budget_cores": 4,
            },
        )
        assert effective_config.get_workflow_node_parallelism() == 8
        assert effective_config.get_algorithm_max_parallel_workers() == 5
        assert effective_config.get_task_memory_budget_mb() == 4096
        assert effective_config.get_task_cpu_budget_cores() == 4

    def test_node_parallelism_clamped_to_minimum_one(self, monkeypatch) -> None:
        """workflow_node_parallelism < 1 被钳制为 1（避免 0/负值导致串行逻辑失效）。"""
        snap = _hydrate_with_overrides(monkeypatch, {"workflow_node_parallelism": 0})
        assert snap.workflow_node_parallelism == 1
        snap_neg = _hydrate_with_overrides(
            monkeypatch, {"workflow_node_parallelism": -3}
        )
        assert snap_neg.workflow_node_parallelism == 1

    def test_algorithm_max_parallel_workers_clamped_to_zero(self, monkeypatch) -> None:
        """algorithm_max_parallel_workers 负值钳制为 0（0=自动）。"""
        snap = _hydrate_with_overrides(
            monkeypatch, {"algorithm_max_parallel_workers": -1}
        )
        assert snap.algorithm_max_parallel_workers == 0

    def test_memory_and_cpu_budget_clamped_to_zero(self, monkeypatch) -> None:
        """内存/CPU 预算负值钳制为 0（0=不限制）。"""
        snap = _hydrate_with_overrides(
            monkeypatch,
            {"task_memory_budget_mb": -100, "task_cpu_budget_cores": -2},
        )
        assert snap.task_memory_budget_mb == 0
        assert snap.task_cpu_budget_cores == 0

    def test_defaults_when_no_overrides(self, monkeypatch) -> None:
        """无 overrides 时回退到 settings 默认值。"""
        snap = _hydrate_with_overrides(monkeypatch, {})
        # 默认值来自 config.settings（env 或 dataclass 默认）
        assert snap.workflow_node_parallelism >= 1
        assert snap.algorithm_max_parallel_workers >= 0
        assert snap.task_memory_budget_mb >= 0
        assert snap.task_cpu_budget_cores >= 0

    def test_invalidate_forces_rehydrate(self, monkeypatch) -> None:
        """invalidate 后下次读取触发重新 hydrate（热更新机制）。"""
        _hydrate_with_overrides(monkeypatch, {"workflow_node_parallelism": 2})
        assert effective_config.get_workflow_node_parallelism() == 2
        # 模拟前端 PATCH 后 invalidate + 新 overrides
        monkeypatch.setattr(
            effective_config,
            "_load_runtime_overrides",
            lambda: {"workflow_node_parallelism": 6},
        )
        effective_config.invalidate_effective_config()
        assert effective_config.get_workflow_node_parallelism() == 6


class TestSettingsFieldsExist:
    """验证 Settings dataclass 包含新增字段（编译期契约）。"""

    def test_settings_has_concurrency_fields(self) -> None:
        from app.core.config import settings

        for field_name in (
            "celery_worker_max_tasks_per_child",
            "task_memory_budget_mb",
            "task_cpu_budget_cores",
            "workflow_node_parallelism",
            "algorithm_max_parallel_workers",
        ):
            assert hasattr(settings, field_name), f"Settings missing {field_name}"

    def test_celery_app_uses_max_tasks_per_child(self) -> None:
        """celery_app.conf 注入了 worker_max_tasks_per_child（防泄漏兜底）。"""
        from app.core.celery_app import celery_app

        if celery_app is None:
            pytest.skip("Celery unavailable")
        assert "worker_max_tasks_per_child" in celery_app.conf
