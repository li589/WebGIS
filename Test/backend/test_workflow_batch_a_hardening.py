"""批次 A 加固回归（2026-08-23 机制核查实施）。

对应核查报告建议的低风险实施项：
- A2-1 celery task_default_queue 兜底（新任务漏配 queue 不再落无消费者的 "celery" 队列）
- A2-2 import_jobs 移除 "celery" 死 fallback（队列直接取 settings.workflow_queue_batch）
- A3   weather_engine fallback 纳入 enabled flag（BACKEND_WEATHER_ENGINE_FALLBACK_ENABLED）
- A4   materialize R2：白名单外 product type 静默丢弃 → warning 日志可观测
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from shared.contracts.api_contracts import (
    WorkflowCommandType,
    WorkflowSubmitRequest,
)


def test_celery_task_default_queue_backstop() -> None:
    """A2-1：默认队列必须兜底到有 worker 监听的 standard，而非无消费者的 celery。"""
    from app.core.celery_app import celery_app, celery_available
    from app.core.config import settings

    if not celery_available or celery_app is None:
        pytest.skip("celery unavailable")
    assert celery_app.conf.task_default_queue == settings.workflow_queue_standard
    assert celery_app.conf.task_default_queue != "celery"


def test_import_job_task_queue_is_batch_not_celery() -> None:
    """A2-2：run_import_job 队列直接取 settings.workflow_queue_batch。"""
    from app.core.celery_app import celery_app, celery_available
    from app.core.config import settings

    if not celery_available or celery_app is None:
        pytest.skip("celery unavailable")
    from app.data_io.tasks import import_jobs  # noqa: F401  # 确保任务注册

    task = celery_app.tasks["app.tasks.import_tasks.run_import_job"]
    assert task.queue == settings.workflow_queue_batch


def _weather_payload() -> WorkflowSubmitRequest:
    return WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        layer_id="wind-field",  # WEATHER_LAYER_SPECS 成员（DEFAULT_LAYER_ID）
    )


def test_weather_engine_fallback_enabled_by_default() -> None:
    """A3：默认开启（保持现状），weather 图层 layer-based fallback 正常接管。"""
    from app.weatherengine.service import WeatherEngineService

    service = WeatherEngineService()
    assert service.supports(_weather_payload()) is True


def test_weather_engine_fallback_disabled_blocks_supports() -> None:
    """A3：flag=False 时 WeatherEngineService.supports 永远返回 False。

    与 weather_bridge / provider_workflow 的 enabled flag 语义对齐。
    settings 为 frozen 实例不可 monkeypatch 属性，按既有惯例 patch 模块级 settings 名。
    """
    from app.weatherengine import service as weather_service_module

    service = weather_service_module.WeatherEngineService()
    with patch.object(weather_service_module, "settings") as mock_settings:
        mock_settings.weather_engine_fallback_enabled = False
        assert service.supports(_weather_payload()) is False


def test_unmappable_product_type_logs_warning(caplog) -> None:
    """A4/R2：白名单外的 product type 被丢弃时必须留下 warning 可观测信号。"""
    from app.services.python_provider_result_builder import PythonProviderResultBuilder

    builder = PythonProviderResultBuilder()
    with caplog.at_level(
        logging.WARNING, logger="app.services.python_provider_result_builder"
    ):
        refs = builder.build_product_map_layer_refs(
            run_id="run-test-unmappable-001",
            requested_at=datetime.now(timezone.utc),
            payload=_weather_payload(),
            result_dto={"products": [{"name": "x", "type": "totally_unknown_type"}]},
        )
    assert refs == []
    assert any(
        "Unmappable workflow product dropped" in record.getMessage()
        for record in caplog.records
    ), f"缺少静默丢弃 warning: {[r.getMessage() for r in caplog.records]}"
