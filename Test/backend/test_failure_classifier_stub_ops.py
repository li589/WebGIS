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


def test_memory_and_disk_oserror() -> None:
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
