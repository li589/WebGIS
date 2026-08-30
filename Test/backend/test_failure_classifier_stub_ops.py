"""FailureClassifier + python provider bridge exception mapping tests."""

from __future__ import annotations

import pytest
import errno
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from app.services.bridge_protocol import BridgeExecutionError
from app.services.failure_classifier import FailureClassifier
from app.services.python_provider_bridge_service import python_provider_bridge_service
from shared.contracts.api_contracts import (
    ClientIdentity,
    FailureCategory,
    RuntimeMapContext,
    WorkflowCommandType,
    WorkflowPriority,
    WorkflowSubmitRequest,
)


class _RasterOpsValidationError(ValueError):
    """Stand-in matching algorithms package class name."""


class _RasterOpsDataError(FileNotFoundError):
    """Stand-in matching algorithms package class name."""


_RasterOpsValidationError.__name__ = "RasterOpsValidationError"
_RasterOpsDataError.__name__ = "RasterOpsDataError"


def test_raster_ops_validation() -> None:
    cat = FailureClassifier.classify(_RasterOpsValidationError("bad bbox"))
    assert cat == FailureCategory.validation_error, 'cat == FailureCategory.validation_error'
    assert not cat.retryable, 'cat.retryable is falsy'


def test_raster_ops_data_and_file_not_found() -> None:
    assert FailureClassifier.classify(_RasterOpsDataError("missing")) == FailureCategory.not_found, 'FailureClassifier.classify(_RasterOpsDataError("missing")) == FailureCategory.not_found'
    assert FailureClassifier.classify(FileNotFoundError("nope")) == FailureCategory.not_found, 'FailureClassifier.classify(FileNotFoundError("nope")) == FailureCategory.not_found'


def test_nas_date_unavailable_is_coverage_gap() -> None:
    exc = RuntimeError(
        "NAS FileBrowser download failed: /fy/FY3D.tif. "
        "The requested date/file may not be available on NAS; verify the FY3D archive date."
    )
    assert FailureClassifier.classify(exc) == FailureCategory.coverage_gap
    assert not FailureClassifier.is_retryable(exc)


def test_coverage_gap_token_and_zero_intersection() -> None:
    assert (
        FailureClassifier.classify(ValueError("error_code=coverage_gap 时间窗与本地 SMAP 零交集"))
        == FailureCategory.coverage_gap
    )
    assert not FailureCategory.coverage_gap.retryable


def test_memory_and_disk_are_terminal() -> None:
    assert FailureClassifier.classify(MemoryError("oom")) == FailureCategory.terminal_failure, 'FailureClassifier.classify(MemoryError("oom")) == FailureCategory.terminal_failure'
    disk = OSError(errno.ENOSPC, "No space left on device")
    assert FailureClassifier.classify(disk) == FailureCategory.terminal_failure, 'FailureClassifier.classify(disk) == FailureCategory.terminal_failure'


def test_soft_time_limit_by_name() -> None:
    class SoftTimeLimitExceeded(Exception):
        pass

    SoftTimeLimitExceeded.__name__ = "SoftTimeLimitExceeded"
    assert FailureClassifier.classify(SoftTimeLimitExceeded("limit")) == FailureCategory.timeout, 'FailureClassifier.classify(SoftTimeLimitExceeded("limit")) == FailureCategory.timeout'


class _ServiceResponse:
    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self.body = body


def _payload() -> WorkflowSubmitRequest:
    return WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        layer_id="demo",
        priority=WorkflowPriority.normal,
        requested_outputs=[],
        client=ClientIdentity(client_id="test-client"),
        map_context=RuntimeMapContext(active_layer_id="demo"),
        algorithm_request={
            "module_name": "stats_spatial_mean",
            "task_type": "workflow",
        },
    )


def test_submit_job_validation_error_mapped() -> None:
    mock_svc = MagicMock()
    mock_svc.validate_job_response.return_value = _ServiceResponse(
        200, {"is_valid": True, "errors": []}
    )
    mock_svc.submit_job.side_effect = _RasterOpsValidationError("empty clip window")

    with patch.object(
        python_provider_bridge_service, "_get_job_service", return_value=mock_svc
    ):
        with pytest.raises(BridgeExecutionError) as ctx:
            python_provider_bridge_service.execute(
                run_id="run-test",
                payload=_payload(),
                requested_at=datetime.now(UTC),
                event_factory=None,
            )
    assert ctx.value.category == FailureCategory.validation_error, 'ctx.exception.category == FailureCategory.validation_error'


def test_submit_job_not_found_mapped() -> None:
    mock_svc = MagicMock()
    mock_svc.validate_job_response.return_value = _ServiceResponse(
        200, {"is_valid": True, "errors": []}
    )
    mock_svc.submit_job.side_effect = FileNotFoundError("raster gone")

    with patch.object(
        python_provider_bridge_service, "_get_job_service", return_value=mock_svc
    ):
        with pytest.raises(BridgeExecutionError) as ctx:
            python_provider_bridge_service.execute(
                run_id="run-test",
                payload=_payload(),
                requested_at=datetime.now(UTC),
                event_factory=None,
            )
    assert ctx.value.category == FailureCategory.not_found, 'ctx.exception.category == FailureCategory.not_found'


def test_fy_hdf_missing_file_not_found_is_coverage_gap() -> None:
    exc = FileNotFoundError(
        r"No FY HDF files found in I:\Geograph_DataSet\Soil_Moisture\FY3D"
    )
    assert FailureClassifier.classify(exc) == FailureCategory.coverage_gap
    assert not FailureClassifier.is_retryable(exc)


def test_submit_job_http_500_fy_hdf_message_is_coverage_gap_not_transient() -> None:
    """job HTTP 500 但文案是本地缺数时，不得空转 transient_upstream 重试。"""
    mock_svc = MagicMock()
    mock_svc.validate_job_response.return_value = _ServiceResponse(
        200, {"is_valid": True, "errors": []}
    )
    mock_svc.submit_job.return_value = _ServiceResponse(
        500,
        {
            "developer_message": (
                "No FY HDF files found in I:\\Geograph_DataSet\\Soil_Moisture\\FY3D"
            ),
            "user_message": "工作流执行失败",
        },
    )

    with patch.object(
        python_provider_bridge_service, "_get_job_service", return_value=mock_svc
    ):
        with pytest.raises(BridgeExecutionError) as ctx:
            python_provider_bridge_service.execute(
                run_id="run-test",
                payload=_payload(),
                requested_at=datetime.now(UTC),
                event_factory=None,
            )
    assert ctx.value.category == FailureCategory.coverage_gap
    assert not ctx.value.category.retryable


def test_requires_start_date_is_validation_error_not_transient() -> None:
    """缺 start_date 属参数校验，不得 HTTP 500 → transient_upstream 空转重试。"""
    exc = RuntimeError(
        "fy_download requires start_date "
        "(set algorithm_params.start_date or job_request.time_range)"
    )
    assert FailureClassifier.classify(exc) == FailureCategory.validation_error
    assert not FailureClassifier.is_retryable(exc)


def test_submit_job_http_500_requires_start_date_is_validation_error() -> None:
    mock_svc = MagicMock()
    mock_svc.validate_job_response.return_value = _ServiceResponse(
        200, {"is_valid": True, "errors": []}
    )
    mock_svc.submit_job.return_value = _ServiceResponse(
        500,
        {
            "developer_message": (
                "fy_download requires start_date "
                "(set algorithm_params.start_date or job_request.time_range)"
            ),
            "user_message": "工作流执行失败",
        },
    )

    with patch.object(
        python_provider_bridge_service, "_get_job_service", return_value=mock_svc
    ):
        with pytest.raises(BridgeExecutionError) as ctx:
            python_provider_bridge_service.execute(
                run_id="run-test",
                payload=_payload(),
                requested_at=datetime.now(UTC),
                event_factory=None,
            )
    assert ctx.value.category == FailureCategory.validation_error
    assert not ctx.value.category.retryable


def test_submit_job_http_500_generic_still_transient_upstream() -> None:
    mock_svc = MagicMock()
    mock_svc.validate_job_response.return_value = _ServiceResponse(
        200, {"is_valid": True, "errors": []}
    )
    mock_svc.submit_job.return_value = _ServiceResponse(
        500,
        {"developer_message": "Internal server error", "user_message": "失败"},
    )

    with patch.object(
        python_provider_bridge_service, "_get_job_service", return_value=mock_svc
    ):
        with pytest.raises(BridgeExecutionError) as ctx:
            python_provider_bridge_service.execute(
                run_id="run-test",
                payload=_payload(),
                requested_at=datetime.now(UTC),
                event_factory=None,
            )
    assert ctx.value.category == FailureCategory.transient_upstream
    assert ctx.value.category.retryable
