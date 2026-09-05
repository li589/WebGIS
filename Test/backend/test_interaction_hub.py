from __future__ import annotations

import pytest
from contextlib import nullcontext
from pathlib import Path
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator
from unittest.mock import MagicMock, patch

from app.core.config import settings
from app.services.bridge_protocol import BridgeExecutionError
from app.services.workflow.submission_service import (
    WorkflowSubmissionService,
    WorkflowValidationError,
)
from app.services.workflow.lifecycle_service import WorkflowLifecycleService
from app.services.workflow.persistence_service import WorkflowPersistenceService
from app.services.workflow.transition_builder import WorkflowTransitionBuilder
from app.services.workflow.follow_up_dispatch_service import FollowUpDispatchService
from app.services.workflow.runtime_status_service import RuntimeStatusService
from app.services.workflow_execution import WorkflowExecutionResult
from app.services.workflow_repository import SQLiteWorkflowRepository
from shared.contracts.api_contracts import (
    ExecutionStatus,
    FailureCategory,
    WorkflowAcceptedResponse,
    WorkflowCommandType,
    WorkflowPriority,
    WorkflowSubmitRequest,
    RuntimeMapContext,
    ClientIdentity,
    ServiceHealth,
)


def _build_services(repository: SQLiteWorkflowRepository):
    """Build all workflow services wired together with a custom repository.

    Dependency direction is one-way: submission → lifecycle (for finalize).
    User-initiated retry is handled by RetryDispatcher (not wired here since
    no test in this file exercises retry_workflow_run directly; the router-
    level retry test patches retry_dispatcher in test_frontend_call_simulation.py).
    """
    transitions = WorkflowTransitionBuilder()
    persistence = WorkflowPersistenceService(repository)
    follow_up = FollowUpDispatchService(repository, persistence, transitions)
    runtime_status = RuntimeStatusService(repository)
    submission = WorkflowSubmissionService(
        repository, persistence, transitions, follow_up
    )
    lifecycle = WorkflowLifecycleService(
        repository, persistence, transitions, follow_up
    )
    submission.set_lifecycle_service(lifecycle)
    return submission, lifecycle, runtime_status


@contextmanager
def _temp_repository() -> Iterator[SQLiteWorkflowRepository]:
    """创建临时 SQLiteWorkflowRepository，退出时关闭连接池。

    Windows 上 SQLite 连接池持有的文件句柄会阻止 TemporaryDirectory 清理，
    必须在 __exit__ 前调用 repository.close() 释放句柄。
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
        try:
            yield repository
        finally:
            repository.close()


def _build_payload(
    command_type: WorkflowCommandType, *, layer_id: str = "wind-field"
) -> WorkflowSubmitRequest:
    return WorkflowSubmitRequest(
        command_type=command_type,
        layer_id=layer_id,
        priority=WorkflowPriority.normal,
        requested_outputs=[],
        client=ClientIdentity(client_id="test-client"),
        map_context=RuntimeMapContext(active_layer_id=layer_id),
    )


def _as_dict(value):
    return value if isinstance(value, dict) else value.model_dump(mode="json")


def test_submit_workflow_creates_accepted_run() -> None:
    with _temp_repository() as repository:
        submission, lifecycle, runtime_status = _build_services(repository)
        with patch(
            "app.services.workflow.submission_service.execute_workflow_task",
            return_value=WorkflowExecutionResult(message="ok"),
        ):
            response = submission.submit_workflow(
                _build_payload(WorkflowCommandType.analysis)
            )

        assert isinstance(response, WorkflowAcceptedResponse), 'isinstance(response, WorkflowAcceptedResponse)'
        run = submission.get_workflow_run(response.run_id)
        assert run is not None, 'run is not None'
        assert run.status == ExecutionStatus.succeeded, 'run.status == ExecutionStatus.succeeded'
        assert run.status_url == f"/workflow-runs/{response.run_id}", 'run.status_url == f"/workflow-runs/{response.run_id}"'
        assert run.events_url == f"/workflow-runs/{response.run_id}/events", 'run.events_url == f"/workflow-runs/{response.run_id}/events"'


def test_cancel_workflow_marks_terminal_cancelled() -> None:
    with _temp_repository() as repository:
        submission, lifecycle, runtime_status = _build_services(repository)
        with patch(
            "app.services.workflow.submission_service.execute_workflow_task",
            return_value=WorkflowExecutionResult(message="ok"),
        ):
            response = submission.submit_workflow(
                _build_payload(WorkflowCommandType.analysis)
            )
        with pytest.raises(ValueError, match="terminal state"):
            lifecycle.cancel_workflow_run(response.run_id)


def test_runtime_status_reports_services() -> None:
    with _temp_repository() as repository:
        submission, lifecycle, runtime_status = _build_services(repository)
        status = runtime_status.get_runtime_status()

        assert status.service_name == settings.service_name, 'status.service_name == settings.service_name'
        assert len(status.services) >= 3, 'len(status.services) >= 3'


def test_runtime_status_overall_health_rollup_degraded() -> None:
    with _temp_repository() as repository:
        _submission, _lifecycle, runtime_status = _build_services(repository)
        with patch.object(
            runtime_status,
            "_get_redis_health",
            return_value=ServiceHealth.degraded,
        ):
            status = runtime_status.get_runtime_status()
        assert status.overall_health == ServiceHealth.degraded, 'status.overall_health == ServiceHealth.degraded'


def test_schedule_retry_passes_countdown_and_attempt() -> None:
    with _temp_repository() as repository:
        submission, lifecycle, runtime_status = _build_services(repository)
        payload = _build_payload(WorkflowCommandType.analysis)

        with patch(
            "app.services.workflow.lifecycle_service.dispatch_workflow_task"
        ) as dispatch_mock:
            lifecycle._schedule_retry(
                run_id="run-retry-1",
                payload=payload,
                next_attempt=2,
                backoff_seconds=4.5,
            )

        dispatch_mock.assert_called_once()
        call_kwargs = dispatch_mock.call_args.kwargs
        assert call_kwargs["run_id"] == "run-retry-1", 'call_kwargs["run_id"] == "run-retry-1"'
        assert call_kwargs["countdown"] == 4.5, 'call_kwargs["countdown"] == 4.5'
        assert call_kwargs["payload"].retry_attempt == 2, 'call_kwargs["payload"].retry_attempt == 2'


def test_cancelled_workflow_does_not_schedule_retry() -> None:
    with _temp_repository() as repository:
        submission, lifecycle, runtime_status = _build_services(repository)
        payload = _build_payload(WorkflowCommandType.analysis)
        run_id = "run-cancelled-retry"
        created_at = datetime.now(timezone.utc)
        repository.save_run(
            lifecycle._transitions.build_execution_transition(
                run_id=run_id,
                payload=payload,
                status=ExecutionStatus.cancelled,
                progress=100,
                message="工作流已被用户取消。",
                created_at=created_at,
                updated_at=created_at,
            )
        )

        with patch(
            "app.services.workflow.lifecycle_service.dispatch_workflow_task"
        ) as dispatch_mock:
            lifecycle.finalize_workflow_retry(
                run_id=run_id,
                payload=payload,
                created_at=created_at,
                exc=ConnectionError("transient"),
                category=FailureCategory.transient_network,
                current_attempt=1,
                next_attempt=2,
                backoff_seconds=1.0,
            )

        dispatch_mock.assert_not_called()
        assert repository.get_run(run_id).status == ExecutionStatus.cancelled, 'repository.get_run(run_id).status == ExecutionStatus.cancelled'


def test_submit_workflow_auto_populates_algorithm_request_from_layer_catalog(
) -> None:
    with _temp_repository() as repository:
        submission, lifecycle, runtime_status = _build_services(repository)

        with (
            patch(
                "app.services.workflow_request_resolver._resolve_data_access_source_uri",
                side_effect=lambda source: f"D:/prepared/{str(source).replace('/', '_')}",
            ),
            patch(
                "app.services.workflow.submission_service.execute_workflow_task",
                return_value=WorkflowExecutionResult(message="ok"),
            ) as execute_mock,
        ):
            response = submission.submit_workflow(
                _build_payload(WorkflowCommandType.analysis, layer_id="ndvi")
            )

        execute_mock.assert_called_once()
        normalized_payload = execute_mock.call_args.kwargs["payload"]
        algorithm_request = _as_dict(normalized_payload.algorithm_request)
        # X2 变体路由：ndvi 默认走 online 变体 workflow_name，不再注入 module_name。
        assert algorithm_request["workflow_name"] == "ndvi_online_read", (
            'algorithm_request["workflow_name"] == "ndvi_online_read"'
        )
        assert algorithm_request["datasource_selection"]["_data_access_requests"][
                "NDVI_16DAY_RASTER"
            ]["selector"]["uris"] == ["D:/prepared/NDVI_16DAY_RASTER"], (
            'algorithm_request["datasource_selection"]["_data_access_requests"]'
            '["NDVI_16DAY_RASTER"]["selector"]["uris"] == ["D:/prepared/NDVI_16DAY_RASTER"]'
        )

        request_json = repository.get_run_request_json(response.run_id)
        assert request_json is not None, 'request_json is not None'
        persisted_payload = WorkflowSubmitRequest.model_validate_json(request_json)
        persisted_algorithm_request = _as_dict(
            persisted_payload.algorithm_request
        )
        assert persisted_algorithm_request["workflow_name"] == "ndvi_online_read", (
            'persisted_algorithm_request["workflow_name"] == "ndvi_online_read"'
        )


def test_submit_workflow_auto_populates_python_provider_defaults_for_smap_and_fy_layers(
) -> None:
    # P2.2 修复后 ref-fy-tb-202512-mwri 的首个候选数据源从 “fy” 扩展为 “FY_MWRI_HDF”
    # （见 layer_catalog.py 中 ref-fy-tb-202512-mwri.default_data_access_sources）。
    # catalog 演进：smap-soil 已移除，改用 ref-smap-sm-202512-l3（module=smap_daily, dataset=SMAP_L3_DEC2025）。
    # 业务判定（2026-08-07）：本地候选为可解析数据源名 "SMAP_L3"
    # （dataset_config → Soil_Moisture/SMAP），故派生 URI 为 D:/prepared/SMAP_L3。
    expected_layers = {
        "ref-smap-sm-202512-l3": {
            "entry": "module_name",
            "value": "smap_daily",
            "dataset": "SMAP_L3_DEC2025",
            "uri": "D:/prepared/SMAP_L3",
        },
        "ref-fy-tb-202512-mwri": {
            "entry": "workflow_name",
            "value": "fy_tb_online_read",
            "dataset": "FY_MWRI_HDF",
            "uri": "D:/prepared/Satellite_FY3_FY3D_MWRI_L1",
        },
    }

    with _temp_repository() as repository:
        submission, lifecycle, runtime_status = _build_services(repository)
        with (
            patch(
                "app.services.workflow_request_resolver._resolve_data_access_source_uri",
                side_effect=lambda source: f"D:/prepared/{str(source).replace('/', '_')}",
            ),
            patch(
                "app.services.workflow.submission_service.execute_workflow_task",
                return_value=WorkflowExecutionResult(message="ok"),
            ) as execute_mock,
            # SMAP DEC2025 迁移后算法模板 dataset key (SMAP_L3_DEC2025) 与 catalog 一致，
            # 提交期模板校验通过，无需跳过。
        ):
            for layer_id in expected_layers:
                submission.submit_workflow(
                    _build_payload(
                        WorkflowCommandType.analysis, layer_id=layer_id
                    )
                )

        assert execute_mock.call_count == len(expected_layers), 'execute_mock.call_count == len(expected_layers)'
        for call in execute_mock.call_args_list:
            normalized_payload = call.kwargs["payload"]
            layer_id = normalized_payload.layer_id
            spec = expected_layers[layer_id]
            algorithm_request = _as_dict(normalized_payload.algorithm_request)

            with nullcontext():
                assert algorithm_request[spec["entry"]] == spec["value"], (
                    f'algorithm_request[{spec["entry"]!r}] == {spec["value"]!r}'
                )
                assert algorithm_request["datasource_selection"][
                        "_data_access_requests"
                    ][spec["dataset"]]["selector"]["uris"] == [spec["uri"]], (
                    'algorithm_request["datasource_selection"]["_data_access_requests"]'
                    f'[{spec["dataset"]!r}]["selector"]["uris"] == [{spec["uri"]!r}]'
                )


def test_submit_workflow_keeps_python_provider_datasource_missing_when_default_sources_are_unavailable(
) -> None:
    with _temp_repository() as repository:
        submission, lifecycle, runtime_status = _build_services(repository)

        with (
            patch(
                "app.services.workflow_request_resolver._resolve_data_access_source_uri",
                return_value=None,
            ),
            patch(
                "app.services.workflow.submission_service.execute_workflow_task",
                return_value=WorkflowExecutionResult(message="ok"),
            ) as execute_mock,
            # 跳过提交期参数预校验：本测试关注 normalization 行为
            # （_data_access_requests 在数据源不可用时应留空），
            # 而非校验逻辑（校验逻辑由独立测试覆盖）。
            patch(
                "app.services.workflow.submission_service.WorkflowSubmissionService._validate_request_params",
                lambda self, payload: None,
            ),
        ):
            submission.submit_workflow(
                _build_payload(WorkflowCommandType.analysis, layer_id="ndvi")
            )

        execute_mock.assert_called_once()
        normalized_payload = execute_mock.call_args.kwargs["payload"]
        algorithm_request = _as_dict(normalized_payload.algorithm_request)
        assert algorithm_request["workflow_name"] == "ndvi_online_read", (
            'algorithm_request["workflow_name"] == "ndvi_online_read"'
        )
        datasource_selection = algorithm_request.get("datasource_selection", {})
        assert not datasource_selection.get("_data_access_requests"), 'datasource_selection.get("_data_access_requests") is falsy'


def test_submit_workflow_surfaces_validation_failure_message() -> None:
    with _temp_repository() as repository:
        submission, lifecycle, runtime_status = _build_services(repository)

        with (
            patch(
                "app.services.workflow.submission_service.execute_workflow_task",
                side_effect=BridgeExecutionError(
                    category=FailureCategory.validation_error,
                    message="Provider template validation failed: module 'ndvi_daily' requires datasource_selection keys: input_dir",
                ),
            ),
            # 跳过提交期预校验，以便测试执行期校验失败的消息上抛路径
            # （提交期预校验由独立测试覆盖）。
            patch(
                "app.services.workflow.submission_service.WorkflowSubmissionService._validate_request_params",
                lambda self, payload: None,
            ),
        ):
            response = submission.submit_workflow(
                _build_payload(WorkflowCommandType.analysis, layer_id="ndvi")
            )

        run = submission.get_workflow_run(response.run_id)
        assert run is not None, 'run is not None'
        assert run.status == ExecutionStatus.failed, 'run.status == ExecutionStatus.failed'
        assert "工作流校验失败：" in run.message, '"工作流校验失败：" in run.message'
        assert "Provider template validation failed" in run.message, '"Provider template validation failed" in run.message'


def test_submit_workflow_persists_resolution_diagnostics_for_validation_failure(
) -> None:
    with _temp_repository() as repository:
        submission, lifecycle, runtime_status = _build_services(repository)

        with (
            patch(
                "app.services.workflow.submission_service.execute_workflow_task",
                side_effect=BridgeExecutionError(
                    category=FailureCategory.validation_error,
                    message="Provider template validation failed: module 'ndvi_daily' requires datasource_selection keys: input_dir",
                    details={
                        "resolution_diagnostics": {
                            "layer_id": "ndvi",
                            "module_name": "ndvi_daily",
                            "task_type": "ndvi_daily",
                            "layer_status": "placeholder",
                            "unresolved_default_datasets": [
                                {
                                    "dataset_name": "NDVI_16DAY_RASTER",
                                    "candidate_sources": [
                                        "NDVI_VIIRS",
                                        "NDVI_MODIS",
                                        "ndvi",
                                    ],
                                }
                            ],
                        }
                    },
                ),
            ),
            # 跳过提交期预校验，以便测试执行期校验失败的 diagnostics 持久化路径
            # （提交期预校验由独立测试覆盖）。
            patch(
                "app.services.workflow.submission_service.WorkflowSubmissionService._validate_request_params",
                lambda self, payload: None,
            ),
        ):
            response = submission.submit_workflow(
                _build_payload(WorkflowCommandType.analysis, layer_id="ndvi")
            )

        run = submission.get_workflow_run(response.run_id)
        assert run is not None, 'run is not None'
        assert "validation_layer_id=ndvi" in run.diagnostics, '"validation_layer_id=ndvi" in run.diagnostics'
        assert "validation_module_name=ndvi_daily" in run.diagnostics, '"validation_module_name=ndvi_daily" in run.diagnostics'
        assert "validation_layer_status=placeholder" in run.diagnostics, '"validation_layer_status=placeholder" in run.diagnostics'
        assert "validation_dataset_missing=NDVI_16DAY_RASTER" in run.diagnostics, '"validation_dataset_missing=NDVI_16DAY_RASTER" in run.diagnostics'
        assert "validation_dataset_candidates.NDVI_16DAY_RASTER=NDVI_VIIRS|NDVI_MODIS|ndvi" in run.diagnostics, '"validation_dataset_candidates.NDVI_16DAY_RASTER=NDVI_VIIRS|NDVI_MODIS|ndvi" in run.diagnostics'


def test_submit_workflow_raises_validation_error_when_required_datasource_missing(
) -> None:
    """提交期预校验：缺必需 datasource key 时抛出 WorkflowValidationError。

    通过 mock 模板校验器返回校验错误，验证 submission_service 能正确
    将错误转为结构化 WorkflowValidationError（携带字段级 issues）。
    使用 mock 而非真实导入因 algorithms 包 contracts 模块依赖
    Python 3.11+（StrEnum / datetime.UTC），本地 Python 3.10 无法导入；
    CI（Python 3.12）覆盖真实集成路径。
    """
    import importlib as _importlib

    # Mock deriver: 模板存在但校验失败（缺 input_dir）
    mock_deriver = MagicMock()
    # list_module_templates 返回空 dict，使 normalization 不受 mock 影响
    mock_deriver.list_module_templates.return_value = {}
    # get_module_request_template 返回非 None，使校验逻辑继续执行
    mock_deriver.get_module_request_template.return_value = "mock_template"
    # validate_request_against_template 返回校验失败 + 字符串错误列表
    mock_deriver.validate_request_against_template.return_value = (
        False,
        ["Missing required datasource key: 'input_dir'"],
    )

    # 条件 mock：仅 "contracts.template_deriver" 返回 mock_deriver，
    # 其他模块名委托给真实 importlib.import_module
    _real_import_module = _importlib.import_module

    def _side_effect(name, *args, **kwargs):
        if name == "contracts.template_deriver":
            return mock_deriver
        return _real_import_module(name, *args, **kwargs)

    with _temp_repository() as repository:
        submission, lifecycle, runtime_status = _build_services(repository)
        with (
            patch(
                "app.services.workflow_request_resolver._resolve_data_access_source_uri",
                return_value=None,
            ),
            patch(
                "app.services.workflow.submission_service.execute_workflow_task"
            ) as execute_mock,
            patch(
                "app.services.workflow.submission_service.importlib.import_module",
                side_effect=_side_effect,
            ),
        ):
            with pytest.raises(WorkflowValidationError) as ctx:
                submission.submit_workflow(
                    _build_payload(
                        WorkflowCommandType.analysis,
                        layer_id="ref-smap-sm-202512-l3",
                    )
                )

        # 不应进入执行阶段
        execute_mock.assert_not_called()
        issues = ctx.value.issues
        assert len(issues) >= 1, 'len(issues) >= 1 is truthy'
        # 至少有一个 issue 指向 input_dir 字段
        assert any("input_dir" in issue["field"] for issue in issues), f"expected an issue targeting input_dir, got {issues}"
        # 每个 issue 都有 field 和 message
        for issue in issues:
            assert "field" in issue, '"field" in issue'
            assert "message" in issue, '"message" in issue'


def test_submit_workflow_skips_validation_when_no_module_name() -> None:
    """无 module_name 的请求（如 workflow_definition 模式）跳过提交期预校验。"""
    with _temp_repository() as repository:
        submission, lifecycle, runtime_status = _build_services(repository)
        # wind-field 图层未注册 module_name，normalize 后 algorithm_request 无 module_name
        with patch(
            "app.services.workflow.submission_service.execute_workflow_task",
            return_value=WorkflowExecutionResult(message="ok"),
        ):
            response = submission.submit_workflow(
                _build_payload(
                    WorkflowCommandType.analysis, layer_id="wind-field"
                )
            )
        assert isinstance(response, WorkflowAcceptedResponse), 'isinstance(response, WorkflowAcceptedResponse)'
