import json
import time
from pathlib import Path

import pytest

from webgis_gee.api.contracts import SavebackTerminalPlanPayload, WorkflowContractAdapter
from webgis_gee.api.facade import create_default_facade
from webgis_gee.accounts.pool import InMemoryAccountPool
from webgis_gee.application.services import WorkflowService
from webgis_gee.config.settings import Settings
from webgis_gee.domain.models import EdgeSpec, ExecutionContext, NodeSpec, WorkflowDefinition
from webgis_gee.runtime.observability import InMemoryStructuredEventSink
from webgis_gee.runtime.exceptions import ResourceExhaustedError
from webgis_gee.runtime.resources import RedisResourceQuotaCoordinator, RuntimeResourceController
from webgis_gee.storage.local import LocalStorageBackend
from webgis_gee.workflow.schema import CURRENT_SCHEMA_VERSION


class FakeEeTask:
    def __init__(self, task_id: str) -> None:
        self.id = task_id
        self.started = False

    def start(self) -> None:
        self.started = True


class FakeEeData:
    def __init__(self, state: str, error_message: str | None = None) -> None:
        self._state = state
        self._error_message = error_message

    def getTaskStatus(self, task_id: str):
        payload = {"id": task_id, "state": self._state}
        if self._error_message is not None:
            payload["error_message"] = self._error_message
        return [payload]


class FakeImageExportApi:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.counter = 0

    def toDrive(self, **kwargs):
        self.counter += 1
        self.calls.append(kwargs)
        return FakeEeTask(task_id=f"task-{self.counter}")


class FakeExportApi:
    def __init__(self) -> None:
        self.image = FakeImageExportApi()


class FakeBatchApi:
    def __init__(self) -> None:
        self.Export = FakeExportApi()


class FakeEeModule:
    def __init__(self, state: str, error_message: str | None = None) -> None:
        self.data = FakeEeData(state, error_message=error_message)
        self.batch = FakeBatchApi()


class FakeRedisClient:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiry: dict[str, int] = {}

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        if ex is not None:
            self.expiry[key] = ex
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def incr(self, key: str) -> int:
        value = int(self.values.get(key, "0")) + 1
        self.values[key] = str(value)
        return value

    def decr(self, key: str) -> int:
        value = int(self.values.get(key, "0")) - 1
        self.values[key] = str(value)
        return value

    def delete(self, key: str) -> int:
        existed = key in self.values
        self.values.pop(key, None)
        self.expiry.pop(key, None)
        return 1 if existed else 0

    def expire(self, key: str, seconds: int) -> bool:
        if key not in self.values:
            return False
        self.expiry[key] = seconds
        return True


class FailOnceRenewingRedisQuotaCoordinator(RedisResourceQuotaCoordinator):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.renewed_event = False
        self._should_fail_next_renew = True

    def renew(self, lease) -> bool:
        self.renewed_event = True
        if self._should_fail_next_renew:
            self._should_fail_next_renew = False
            return False
        return super().renew(lease)


class SequencedFakeEeData:
    def __init__(self, default_states: list[str] | None = None) -> None:
        self._default_states = default_states or ["READY", "RUNNING", "RUNNING", "COMPLETED"]
        self._states_by_task_id: dict[str, list[str]] = {}
        self._poll_count_by_task_id: dict[str, int] = {}

    def register_task(self, task_id: str, *, states: list[str] | None = None) -> None:
        self._states_by_task_id[task_id] = list(states or self._default_states)
        self._poll_count_by_task_id[task_id] = 0

    def getTaskStatus(self, task_id: str):
        states = self._states_by_task_id.get(task_id, self._default_states)
        poll_count = self._poll_count_by_task_id.get(task_id, 0)
        state = states[min(poll_count, len(states) - 1)]
        self._poll_count_by_task_id[task_id] = poll_count + 1
        return [{"id": task_id, "state": state}]


class SequencedFakeImageExportApi:
    def __init__(self, data: SequencedFakeEeData) -> None:
        self._data = data
        self.calls: list[dict[str, object]] = []
        self.counter = 0

    def toDrive(self, **kwargs):
        self.counter += 1
        task_id = f"sequenced-task-{self.counter}"
        self.calls.append(kwargs)
        self._data.register_task(task_id)
        return FakeEeTask(task_id=task_id)


class SequencedFakeExportApi:
    def __init__(self, data: SequencedFakeEeData) -> None:
        self.image = SequencedFakeImageExportApi(data)


class SequencedFakeBatchApi:
    def __init__(self, data: SequencedFakeEeData) -> None:
        self.Export = SequencedFakeExportApi(data)


class SequencedFakeEeModule:
    def __init__(self, default_states: list[str] | None = None) -> None:
        self.data = SequencedFakeEeData(default_states=default_states)
        self.batch = SequencedFakeBatchApi(self.data)


class OversizedStatusEeData:
    def __init__(self, payload_size: int) -> None:
        self._payload_size = payload_size

    def getTaskStatus(self, task_id: str):
        return [
            {
                "id": task_id,
                "state": "RUNNING",
                "error_message": "x" * self._payload_size,
            }
        ]


class OversizedStatusEeModule:
    def __init__(self, payload_size: int) -> None:
        self.data = OversizedStatusEeData(payload_size)


class FakeAnalysisImage:
    def __init__(
        self,
        name: str,
        *,
        band_values: dict[str, float] | None = None,
        properties: dict[str, object] | None = None,
    ) -> None:
        self.name = name
        self.band_values = band_values or {"B3": 0.2, "B4": 0.3, "B8": 0.8, "B11": 0.5}
        self.properties = properties or {}
        self.selected_bands: list[str] = []
        self.renamed_to: str | None = None
        self.normalized_diff_bands: list[str] | None = None
        self.expression_text: str | None = None

    def select(self, bands, rename=None):
        selected_values = {band: self.band_values[band] for band in bands}
        image = FakeAnalysisImage(
            f"{self.name}:select",
            band_values=selected_values,
            properties=dict(self.properties),
        )
        image.selected_bands = list(rename) if rename is not None else list(bands)
        if rename is not None:
            image.band_values = {
                rename[index]: self.band_values[bands[index]]
                for index in range(len(bands))
            }
        return image

    def normalizedDifference(self, bands):
        left = self.band_values[bands[0]]
        right = self.band_values[bands[1]]
        value = 0.0 if left + right == 0 else (left - right) / (left + right)
        image = FakeAnalysisImage(
            f"{self.name}:normalized_difference",
            band_values={"index": value},
            properties=dict(self.properties),
        )
        image.normalized_diff_bands = list(bands)
        return image

    def expression(self, expression: str, variables):
        resolved_variables: dict[str, float] = {}
        for key, value in variables.items():
            if isinstance(value, FakeAnalysisImage) and value.band_values:
                resolved_variables[key] = float(next(iter(value.band_values.values())))
            else:
                resolved_variables[key] = float(value)
        result_value = float(eval(expression, {"__builtins__": {}}, resolved_variables))
        image = FakeAnalysisImage(
            f"{self.name}:expression",
            band_values={"expression": result_value},
            properties=dict(self.properties),
        )
        image.expression_text = expression
        return image

    def multiply(self, value: float):
        return FakeAnalysisImage(
            f"{self.name}:multiply",
            band_values={band: band_value * value for band, band_value in self.band_values.items()},
            properties=dict(self.properties),
        )

    def add(self, value: float):
        return FakeAnalysisImage(
            f"{self.name}:add",
            band_values={band: band_value + value for band, band_value in self.band_values.items()},
            properties=dict(self.properties),
        )

    def gte(self, threshold: float):
        return FakeAnalysisImage(
            f"{self.name}:gte",
            band_values={
                band: 1.0 if band_value >= threshold else 0.0
                for band, band_value in self.band_values.items()
            },
            properties=dict(self.properties),
        )

    def lte(self, threshold: float):
        return FakeAnalysisImage(
            f"{self.name}:lte",
            band_values={
                band: 1.0 if band_value <= threshold else 0.0
                for band, band_value in self.band_values.items()
            },
            properties=dict(self.properties),
        )

    def eq(self, target: float):
        return FakeAnalysisImage(
            f"{self.name}:eq",
            band_values={
                band: 1.0 if band_value == target else 0.0
                for band, band_value in self.band_values.items()
            },
            properties=dict(self.properties),
        )

    def And(self, other):
        other_values = other.band_values if isinstance(other, FakeAnalysisImage) else {}
        return FakeAnalysisImage(
            f"{self.name}:and",
            band_values={
                band: 1.0 if band_value and other_values.get(band) else 0.0
                for band, band_value in self.band_values.items()
            },
            properties=dict(self.properties),
        )

    def where(self, condition, value: float):
        condition_values = condition.band_values if isinstance(condition, FakeAnalysisImage) else {}
        return FakeAnalysisImage(
            f"{self.name}:where",
            band_values={
                band: float(value) if condition_values.get(band) else band_value
                for band, band_value in self.band_values.items()
            },
            properties=dict(self.properties),
        )

    def rename(self, name: str):
        if len(self.band_values) == 1:
            only_value = next(iter(self.band_values.values()))
            self.band_values = {name: only_value}
        self.renamed_to = name
        return self

    def reduceRegion(self, reducer, geometry, scale):
        return dict(self.band_values)

    def get(self, key: str):
        return self.properties.get(key)

    def set(self, key: str, value):
        return FakeAnalysisImage(
            self.name,
            band_values=dict(self.band_values),
            properties={**self.properties, key: value},
        )


class FakeAnalysisCollection:
    def __init__(self, name: str, images: list[FakeAnalysisImage]) -> None:
        self.name = name
        self.images = images

    def median(self):
        return FakeAnalysisImage(f"{self.name}:median")

    def mean(self):
        return FakeAnalysisImage(f"{self.name}:mean")

    def mosaic(self):
        return FakeAnalysisImage(f"{self.name}:mosaic")

    def map(self, fn):
        return FakeAnalysisCollection(self.name, [fn(image) for image in self.images])

    def aggregate_array(self, property_name: str):
        return [image.get(property_name) for image in self.images]


def assert_export_diagnostics_snapshot(
    diagnostics,
    *,
    min_counter_values: dict[str, int] | None = None,
    quota_coordinator_type: str | None = None,
    expected_degraded_shared_quotas: dict[str, float] | None = None,
) -> None:
    resource_control = diagnostics.checks["resource_control"]
    workflow_schema = diagnostics.checks["workflow_schema"]
    metrics_counters = diagnostics.checks["metrics"]["counters"]

    assert resource_control["active_export_slots"] == 0
    assert resource_control["active_upload_slots"] == 0
    assert resource_control["active_download_slots"] == 0
    assert resource_control["active_temp_dirs"] == 0
    assert resource_control["active_local_write_bytes"] == 0
    if quota_coordinator_type is not None:
        assert resource_control["quota_coordinator"]["type"] == quota_coordinator_type
    if expected_degraded_shared_quotas is not None:
        assert resource_control["degraded_shared_quotas"] == expected_degraded_shared_quotas

    assert workflow_schema["current_schema_version"] == CURRENT_SCHEMA_VERSION
    assert workflow_schema["saveback_terminal_plan_summary"] == {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "field": "saveback_terminal_plan",
        "description": "terminal audit writeback summary for API consumers",
        "subfields": ["action", "reasons", "summary"],
    }
    assert workflow_schema["saveback_terminal_plan_response_schema"]["schema_version"] == CURRENT_SCHEMA_VERSION
    assert workflow_schema["saveback_terminal_plan_response_schema"]["field"] == "saveback_terminal_plan"
    assert workflow_schema["saveback_terminal_plan_response_schema"]["response_fields"] == [
        "action",
        "reasons",
        "summary",
    ]

    for metric_name, min_value in (min_counter_values or {}).items():
        assert metrics_counters.get(metric_name, 0) >= min_value


def test_export_workflow_writes_manifest_artifact(tmp_path) -> None:
    facade = create_default_facade()
    storage_backend = LocalStorageBackend(base_path=str(tmp_path))
    context = ExecutionContext(
        workflow_id="export-demo",
        metadata={"storage_backend": storage_backend},
    )
    workflow = WorkflowDefinition(
        workflow_id="export-demo",
        nodes=[
            NodeSpec(node_id="source", node_type="literal", params={"value": "fake-image"}),
            NodeSpec(
                node_id="export",
                node_type="gee_export_image",
                params={"destination": "manifest", "file_name_prefix": "image_export"},
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="source",
                source_port="value",
                target_node_id="export",
                target_port="image",
            )
        ],
    )

    result = facade.execute_workflow(workflow, context=context)

    manifest_uri = result.outputs["export.manifest_uri"]
    manifest_path = manifest_uri.replace("file://", "")
    manifest_payload = json.loads(open(manifest_path, "r", encoding="utf-8").read())

    assert result.status == "completed"
    assert manifest_payload["workflow_id"] == "export-demo"
    assert manifest_payload["task_ref"]["destination"] == "manifest"
    assert manifest_payload["task_ref"]["status"] == "manifest_created"
    assert len(result.artifacts) == 1


def test_batch_preparation_and_export_polling_work_together(tmp_path) -> None:
    storage_backend = LocalStorageBackend(base_path=str(tmp_path))
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path)),
    )
    adapter = WorkflowContractAdapter(service)

    batch_context = ExecutionContext(
        workflow_id="batch-prepare-demo",
        metadata={"storage_backend": storage_backend},
    )
    batch_workflow = WorkflowDefinition(
        workflow_id="batch-prepare-demo",
        nodes=[
            NodeSpec(
                node_id="regions",
                node_type="literal",
                params={
                    "value": [
                        {"region_id": "r1", "name": "A"},
                        {"region_id": "r2", "name": "B"},
                        {"region_id": "r3", "name": "C"},
                    ]
                },
            ),
            NodeSpec(
                node_id="split",
                node_type="batch_split_by_regions",
                params={"extra_params": {"dataset": "s2"}},
            ),
            NodeSpec(
                node_id="collect",
                node_type="batch_collect",
                params={"collect_field": "payload"},
            ),
            NodeSpec(
                node_id="filter",
                node_type="batch_filter",
                params={"field": "region_id", "operator": "in", "value": ["r1", "r3"]},
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="regions",
                source_port="value",
                target_node_id="split",
                target_port="regions",
            ),
            EdgeSpec(
                source_node_id="split",
                source_port="batch_items",
                target_node_id="collect",
                target_port="batch_items",
            ),
            EdgeSpec(
                source_node_id="collect",
                source_port="collected_items",
                target_node_id="filter",
                target_port="items",
            ),
        ],
    )

    batch_result = adapter.submit_workflow(batch_workflow, batch_context)

    assert batch_result.status == "completed"
    filtered_payloads = batch_result.outputs["filter.filtered_items"]
    assert filtered_payloads == [
        {
            "region": {"region_id": "r1", "name": "A"},
            "region_id": "r1",
            "name": "A",
            "dataset": "s2",
        },
        {
            "region": {"region_id": "r3", "name": "C"},
            "region_id": "r3",
            "name": "C",
            "dataset": "s2",
        },
    ]

    manifest_uris: list[str] = []
    for payload in filtered_payloads:
        export_context = ExecutionContext(
            workflow_id=f"export-{payload['region_id']}",
            metadata={"storage_backend": storage_backend},
        )
        export_workflow = WorkflowDefinition(
            workflow_id=f"export-{payload['region_id']}",
            nodes=[
                NodeSpec(
                    node_id="image",
                    node_type="literal",
                    params={"value": f"fake-image-{payload['region_id']}"},
                ),
                NodeSpec(
                    node_id="export",
                    node_type="gee_export_image",
                    params={
                        "destination": "manifest",
                        "file_name_prefix": f"image_export_{payload['region_id']}",
                        "description": f"export-{payload['region_id']}",
                    },
                ),
            ],
            edges=[
                EdgeSpec(
                    source_node_id="image",
                    source_port="value",
                    target_node_id="export",
                    target_port="image",
                )
            ],
        )

        export_result = adapter.run_workflow_job(
            {
                "workflow": export_workflow.model_dump(),
                "context": export_context.model_dump(),
            }
        )
        manifest_uris.append(export_result.outputs["export.manifest_uri"])
        assert export_result.status == "completed"

    poll_results = [
        adapter.get_export_task_status(manifest_uri, update_manifest=True)
        for manifest_uri in manifest_uris
    ]

    assert len(manifest_uris) == 2
    assert all(uri.startswith("file://") for uri in manifest_uris)
    assert [result["status"] for result in poll_results] == ["manifest_created", "manifest_created"]
    assert [result["state"] for result in poll_results] == ["LOCAL_ONLY", "LOCAL_ONLY"]

    manifest_payloads = [
        json.loads(storage_backend.get(uri.removeprefix("file://")).decode("utf-8"))
        for uri in manifest_uris
    ]
    assert [payload["task_ref"]["description"] for payload in manifest_payloads] == [
        "export-r1",
        "export-r3",
    ]
    assert all(payload["task_status"]["state"] == "LOCAL_ONLY" for payload in manifest_payloads)


def test_export_task_status_flow_updates_manifest_from_submitted_to_completed(tmp_path) -> None:
    storage_backend = LocalStorageBackend(base_path=str(tmp_path))
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path)),
    )
    adapter = WorkflowContractAdapter(service)
    submit_gee = FakeEeModule("RUNNING")
    export_context = ExecutionContext(
        workflow_id="export-status-flow-demo",
        metadata={
            "storage_backend": storage_backend,
            "gee_module": submit_gee,
        },
    )
    export_workflow = WorkflowDefinition(
        workflow_id="export-status-flow-demo",
        nodes=[
            NodeSpec(node_id="image", node_type="literal", params={"value": "fake-image"}),
            NodeSpec(
                node_id="export",
                node_type="gee_export_image",
                params={
                    "destination": "drive",
                    "description": "export-status-flow",
                    "file_name_prefix": "image_export_status_flow",
                    "start_task": True,
                },
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="image",
                source_port="value",
                target_node_id="export",
                target_port="image",
            )
        ],
    )

    run_result = adapter.run_workflow_job(
        {
            "workflow": export_workflow.model_dump(),
            "context": export_context.model_dump(),
        }
    )

    manifest_uri = run_result.outputs["export.manifest_uri"]
    running_result = adapter.get_export_task_status(
        manifest_uri,
        gee_module=FakeEeModule("RUNNING"),
        update_manifest=True,
    )
    completed_result = adapter.get_export_task_status(
        manifest_uri,
        gee_module=FakeEeModule("COMPLETED"),
        update_manifest=True,
    )

    manifest_payload = json.loads(storage_backend.get(manifest_uri.removeprefix("file://")).decode("utf-8"))
    assert run_result.status == "completed"
    assert submit_gee.batch.Export.image.calls[0]["description"] == "export-status-flow"
    assert submit_gee.batch.Export.image.calls[0]["fileNamePrefix"] == "image_export_status_flow"
    assert run_result.outputs["export.task_ref"]["started"] is True
    assert run_result.outputs["export.task_ref"]["task_id"] == "task-1"
    assert running_result["status"] == "running"
    assert running_result["state"] == "RUNNING"
    assert completed_result["status"] == "completed"
    assert completed_result["state"] == "COMPLETED"
    assert manifest_payload["task_ref"]["status"] == "completed"
    assert manifest_payload["task_status"]["raw"]["state"] == "COMPLETED"


@pytest.mark.parametrize(
    ("gee_state", "expected_state"),
    [("FAILED", "FAILED"), ("CANCELLED", "CANCELLED")],
)
def test_export_task_status_flow_updates_manifest_for_failed_terminal_states(
    tmp_path,
    gee_state: str,
    expected_state: str,
) -> None:
    storage_backend = LocalStorageBackend(base_path=str(tmp_path))
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path)),
    )
    adapter = WorkflowContractAdapter(service)
    export_context = ExecutionContext(
        workflow_id=f"export-{gee_state.lower()}-demo",
        metadata={
            "storage_backend": storage_backend,
            "gee_module": FakeEeModule("RUNNING"),
        },
    )
    export_workflow = WorkflowDefinition(
        workflow_id=f"export-{gee_state.lower()}-demo",
        nodes=[
            NodeSpec(node_id="image", node_type="literal", params={"value": "fake-image"}),
            NodeSpec(
                node_id="export",
                node_type="gee_export_image",
                params={
                    "destination": "drive",
                    "description": f"export-{gee_state.lower()}",
                    "file_name_prefix": f"image_export_{gee_state.lower()}",
                    "start_task": True,
                },
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="image",
                source_port="value",
                target_node_id="export",
                target_port="image",
            )
        ],
    )

    run_result = adapter.run_workflow_job(
        {
            "workflow": export_workflow.model_dump(),
            "context": export_context.model_dump(),
        }
    )

    manifest_uri = run_result.outputs["export.manifest_uri"]
    failed_result = adapter.get_export_task_status(
        manifest_uri,
        gee_module=FakeEeModule(gee_state, error_message="gee export terminal failure"),
        update_manifest=True,
    )

    manifest_payload = json.loads(storage_backend.get(manifest_uri.removeprefix("file://")).decode("utf-8"))
    assert run_result.status == "completed"
    assert failed_result["status"] == "failed"
    assert failed_result["state"] == expected_state
    assert failed_result["error_message"] == "gee export terminal failure"
    assert manifest_payload["task_ref"]["status"] == "failed"
    assert manifest_payload["task_status"]["state"] == expected_state
    assert manifest_payload["task_status"]["error_message"] == "gee export terminal failure"
    assert manifest_payload["task_status"]["raw"]["error_message"] == "gee export terminal failure"


def test_export_task_status_manifest_write_respects_local_write_budget_and_preserves_original_file(tmp_path) -> None:
    manifest_path = tmp_path / "exports" / "budget-guard.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_payload = {
        "workflow_id": "budget-guard-demo",
        "task_ref": {
            "started": True,
            "status": "submitted",
            "task_id": "task-budget-1",
        },
    }
    manifest_path.write_text(
        json.dumps(manifest_payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    original_content = manifest_path.read_text(encoding="utf-8")

    service = WorkflowService(
        settings=Settings(
            storage_backend="local",
            local_storage_root=str(tmp_path),
            max_local_write_bytes=64,
        ),
        resource_controller=RuntimeResourceController(
            max_parallel_exports=1,
            max_parallel_uploads=1,
            max_parallel_downloads=1,
            max_local_write_bytes=64,
        ),
    )
    adapter = WorkflowContractAdapter(service)

    with pytest.raises(ResourceExhaustedError, match="local storage write budget exceeded"):
        adapter.get_export_task_status(
            f"file://{manifest_path}",
            gee_module=OversizedStatusEeModule(payload_size=512),
            update_manifest=True,
        )

    assert manifest_path.read_text(encoding="utf-8") == original_content
    assert not any(path.suffix == ".tmp" for path in Path(manifest_path.parent).iterdir())


def test_analysis_nodes_can_chain_into_export_workflow(tmp_path) -> None:
    storage_backend = LocalStorageBackend(base_path=str(tmp_path))
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path)),
    )
    adapter = WorkflowContractAdapter(service)
    collection = FakeAnalysisCollection(
        "analysis-collection",
        images=[
            FakeAnalysisImage("img-1", properties={"system:time_start": "2026-01-01"}),
            FakeAnalysisImage("img-2", properties={"system:time_start": "2026-01-02"}),
        ],
    )
    context = ExecutionContext(
        workflow_id="analysis-export-demo",
        metadata={
            "storage_backend": storage_backend,
            "gee_module": FakeEeModule("RUNNING"),
        },
    )
    workflow = WorkflowDefinition(
        workflow_id="analysis-export-demo",
        nodes=[
            NodeSpec(node_id="collection", node_type="literal", params={"value": collection}),
            NodeSpec(node_id="geometry", node_type="literal", params={"value": {"type": "Polygon"}}),
            NodeSpec(
                node_id="composite",
                node_type="gee_image_collection_composite",
                params={"reducer": "median"},
            ),
            NodeSpec(
                node_id="index",
                node_type="gee_spectral_index",
                params={"index": "ndvi", "output_band": "ndvi"},
            ),
            NodeSpec(
                node_id="region_stats",
                node_type="gee_region_stats",
                params={"reducer": "mean", "scale": 10},
            ),
            NodeSpec(
                node_id="export",
                node_type="gee_export_image",
                params={
                    "destination": "manifest",
                    "file_name_prefix": "analysis_export_result",
                    "description": "analysis-export",
                },
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="collection",
                source_port="value",
                target_node_id="composite",
                target_port="collection",
            ),
            EdgeSpec(
                source_node_id="composite",
                source_port="image",
                target_node_id="index",
                target_port="image",
            ),
            EdgeSpec(
                source_node_id="index",
                source_port="index_image",
                target_node_id="region_stats",
                target_port="image",
            ),
            EdgeSpec(
                source_node_id="geometry",
                source_port="value",
                target_node_id="region_stats",
                target_port="geometry",
            ),
            EdgeSpec(
                source_node_id="index",
                source_port="index_image",
                target_node_id="export",
                target_port="image",
            ),
        ],
    )

    result = adapter.run_workflow_job(
        {"workflow": workflow.model_dump(), "context": context.model_dump()}
    )

    manifest_uri = result.outputs["export.manifest_uri"]
    manifest_payload = json.loads(storage_backend.get(manifest_uri.removeprefix("file://")).decode("utf-8"))
    assert result.status == "completed"
    assert result.outputs["region_stats.stats"] == pytest.approx({"ndvi": 0.45454545454545453})
    assert manifest_payload["task_ref"]["status"] == "manifest_created"
    assert manifest_payload["task_ref"]["description"] == "analysis-export"


def test_raster_algebra_node_can_chain_into_export_workflow(tmp_path) -> None:
    storage_backend = LocalStorageBackend(base_path=str(tmp_path))
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path)),
    )
    adapter = WorkflowContractAdapter(service)
    context = ExecutionContext(
        workflow_id="raster-algebra-export-demo",
        metadata={
            "storage_backend": storage_backend,
            "gee_module": FakeEeModule("RUNNING"),
        },
    )
    workflow = WorkflowDefinition(
        workflow_id="raster-algebra-export-demo",
        nodes=[
            NodeSpec(
                node_id="image",
                node_type="literal",
                params={"value": FakeAnalysisImage("img-1", band_values={"B4": 0.3, "B8": 0.8})},
            ),
            NodeSpec(
                node_id="algebra",
                node_type="gee_raster_algebra",
                params={
                    "expression": "(nir - red) / (nir + red)",
                    "band_map": {"nir": "B8", "red": "B4"},
                    "output_band": "ndvi_like",
                },
            ),
            NodeSpec(
                node_id="export",
                node_type="gee_export_image",
                params={
                    "destination": "manifest",
                    "file_name_prefix": "raster_algebra_export_result",
                    "description": "raster-algebra-export",
                },
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="image",
                source_port="value",
                target_node_id="algebra",
                target_port="image",
            ),
            EdgeSpec(
                source_node_id="algebra",
                source_port="image",
                target_node_id="export",
                target_port="image",
            ),
        ],
    )

    result = adapter.run_workflow_job(
        {"workflow": workflow.model_dump(), "context": context.model_dump()}
    )

    manifest_uri = result.outputs["export.manifest_uri"]
    manifest_payload = json.loads(storage_backend.get(manifest_uri.removeprefix("file://")).decode("utf-8"))
    assert result.status == "completed"
    assert result.outputs["algebra.image"].band_values == pytest.approx({"ndvi_like": 0.45454545454545453})
    assert manifest_payload["task_ref"]["status"] == "manifest_created"
    assert manifest_payload["task_ref"]["description"] == "raster-algebra-export"


def test_threshold_classify_node_can_chain_into_export_workflow(tmp_path) -> None:
    storage_backend = LocalStorageBackend(base_path=str(tmp_path))
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path)),
    )
    adapter = WorkflowContractAdapter(service)
    context = ExecutionContext(
        workflow_id="threshold-classify-export-demo",
        metadata={
            "storage_backend": storage_backend,
            "gee_module": FakeEeModule("RUNNING"),
        },
    )
    workflow = WorkflowDefinition(
        workflow_id="threshold-classify-export-demo",
        nodes=[
            NodeSpec(
                node_id="image",
                node_type="literal",
                params={"value": FakeAnalysisImage("img-1", band_values={"ndvi": 0.45})},
            ),
            NodeSpec(
                node_id="classify",
                node_type="gee_threshold_classify",
                params={
                    "band": "ndvi",
                    "thresholds": [0.2, 0.4],
                    "class_values": [1, 2, 3],
                    "output_band": "ndvi_class",
                },
            ),
            NodeSpec(
                node_id="export",
                node_type="gee_export_image",
                params={
                    "destination": "manifest",
                    "file_name_prefix": "threshold_classify_export_result",
                    "description": "threshold-classify-export",
                },
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="image",
                source_port="value",
                target_node_id="classify",
                target_port="image",
            ),
            EdgeSpec(
                source_node_id="classify",
                source_port="image",
                target_node_id="export",
                target_port="image",
            ),
        ],
    )

    result = adapter.run_workflow_job(
        {"workflow": workflow.model_dump(), "context": context.model_dump()}
    )

    manifest_uri = result.outputs["export.manifest_uri"]
    manifest_payload = json.loads(storage_backend.get(manifest_uri.removeprefix("file://")).decode("utf-8"))
    assert result.status == "completed"
    assert result.outputs["classify.image"].band_values == {"ndvi_class": 3.0}
    assert manifest_payload["task_ref"]["status"] == "manifest_created"
    assert manifest_payload["task_ref"]["description"] == "threshold-classify-export"


def test_reclassify_node_can_chain_into_export_workflow(tmp_path) -> None:
    storage_backend = LocalStorageBackend(base_path=str(tmp_path))
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path)),
    )
    adapter = WorkflowContractAdapter(service)
    context = ExecutionContext(
        workflow_id="reclassify-export-demo",
        metadata={
            "storage_backend": storage_backend,
            "gee_module": FakeEeModule("RUNNING"),
        },
    )
    workflow = WorkflowDefinition(
        workflow_id="reclassify-export-demo",
        nodes=[
            NodeSpec(
                node_id="image",
                node_type="literal",
                params={"value": FakeAnalysisImage("img-1", band_values={"landcover": 0.45})},
            ),
            NodeSpec(
                node_id="reclassify",
                node_type="gee_reclassify",
                params={
                    "band": "landcover",
                    "rules": [
                        {"match": 1, "value": 10},
                        {"min": 0.4, "max": 0.6, "value": 20},
                    ],
                    "default_value": 0,
                    "output_band": "landcover_class",
                },
            ),
            NodeSpec(
                node_id="export",
                node_type="gee_export_image",
                params={
                    "destination": "manifest",
                    "file_name_prefix": "reclassify_export_result",
                    "description": "reclassify-export",
                },
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="image",
                source_port="value",
                target_node_id="reclassify",
                target_port="image",
            ),
            EdgeSpec(
                source_node_id="reclassify",
                source_port="image",
                target_node_id="export",
                target_port="image",
            ),
        ],
    )

    result = adapter.run_workflow_job(
        {"workflow": workflow.model_dump(), "context": context.model_dump()}
    )

    manifest_uri = result.outputs["export.manifest_uri"]
    manifest_payload = json.loads(storage_backend.get(manifest_uri.removeprefix("file://")).decode("utf-8"))
    assert result.status == "completed"
    assert result.outputs["reclassify.image"].band_values == {"landcover_class": 20.0}
    assert manifest_payload["task_ref"]["status"] == "manifest_created"
    assert manifest_payload["task_ref"]["description"] == "reclassify-export"


def test_repeated_analysis_export_runs_do_not_leak_resource_slots(tmp_path) -> None:
    storage_backend = LocalStorageBackend(base_path=str(tmp_path))
    service = WorkflowService(
        settings=Settings(
            storage_backend="local",
            local_storage_root=str(tmp_path),
            max_parallel_exports=1,
        ),
    )
    adapter = WorkflowContractAdapter(service)

    for index in range(5):
        workflow = WorkflowDefinition(
            workflow_id=f"analysis-pressure-{index}",
            nodes=[
                NodeSpec(
                    node_id="image",
                    node_type="literal",
                    params={"value": FakeAnalysisImage(f"img-{index}")},
                ),
                NodeSpec(
                    node_id="index",
                    node_type="gee_spectral_index",
                    params={"index": "ndvi", "output_band": "ndvi"},
                ),
                NodeSpec(
                    node_id="export",
                    node_type="gee_export_image",
                    params={
                        "destination": "drive",
                        "file_name_prefix": f"analysis_pressure_{index}",
                        "description": f"analysis-pressure-{index}",
                        "start_task": True,
                    },
                ),
            ],
            edges=[
                EdgeSpec(
                    source_node_id="image",
                    source_port="value",
                    target_node_id="index",
                    target_port="image",
                ),
                EdgeSpec(
                    source_node_id="index",
                    source_port="index_image",
                    target_node_id="export",
                    target_port="image",
                ),
            ],
        )
        context = ExecutionContext(
            workflow_id=workflow.workflow_id,
            metadata={
                "storage_backend": storage_backend,
                "gee_module": FakeEeModule("RUNNING"),
            },
        )

        result = adapter.run_workflow_job(
            {"workflow": workflow.model_dump(), "context": context.model_dump()}
        )
        assert result.status == "completed"
        assert result.outputs["export.task_ref"]["status"] == "submitted"

    diagnostics = service.diagnose()
    assert_export_diagnostics_snapshot(
        diagnostics,
        min_counter_values={"export.submit.completed": 5},
    )


def test_multi_account_batch_polling_pressure_stays_consistent_with_shared_redis_quota(tmp_path) -> None:
    storage_backend = LocalStorageBackend(base_path=str(tmp_path))
    redis_client = FakeRedisClient()
    shared_quota = RedisResourceQuotaCoordinator(
        client=redis_client,
        key_prefix="pressure_quota",
        lease_ttl_seconds=120,
        renew_interval_seconds=30,
    )
    event_sink = InMemoryStructuredEventSink()
    gee_module = SequencedFakeEeModule()
    service_a = WorkflowService(
        settings=Settings(
            storage_backend="local",
            local_storage_root=str(tmp_path),
            max_parallel_exports=1,
            max_parallel_uploads=1,
            max_parallel_downloads=1,
        ),
        account_pool=InMemoryAccountPool(["acc-1"]),
        quota_coordinator=shared_quota,
        event_sink=event_sink,
    )
    service_b = WorkflowService(
        settings=Settings(
            storage_backend="local",
            local_storage_root=str(tmp_path),
            max_parallel_exports=1,
            max_parallel_uploads=1,
            max_parallel_downloads=1,
        ),
        account_pool=InMemoryAccountPool(["acc-2"]),
        quota_coordinator=shared_quota,
        event_sink=event_sink,
    )
    adapter_a = WorkflowContractAdapter(service_a)
    adapter_b = WorkflowContractAdapter(service_b)

    batch_context = ExecutionContext(
        workflow_id="pressure-batch-demo",
        metadata={"storage_backend": storage_backend},
    )
    batch_workflow = WorkflowDefinition(
        workflow_id="pressure-batch-demo",
        nodes=[
            NodeSpec(
                node_id="regions",
                node_type="literal",
                params={
                    "value": [
                        {"region_id": "r1", "name": "A"},
                        {"region_id": "r2", "name": "B"},
                        {"region_id": "r3", "name": "C"},
                        {"region_id": "r4", "name": "D"},
                    ]
                },
            ),
            NodeSpec(
                node_id="split",
                node_type="batch_split_by_regions",
                params={"extra_params": {"dataset": "s2", "batch_tag": "pressure"}},
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="regions",
                source_port="value",
                target_node_id="split",
                target_port="regions",
            )
        ],
    )

    batch_result = adapter_a.submit_workflow(batch_workflow, batch_context)
    batch_items = batch_result.outputs["split.batch_items"]
    manifest_uris: list[str] = []

    for index, batch_item in enumerate(batch_items):
        adapter = adapter_a if index % 2 == 0 else adapter_b
        region_id = batch_item["payload"]["region_id"]
        export_context = ExecutionContext(
            workflow_id=f"pressure-export-{region_id}",
            metadata={
                "storage_backend": storage_backend,
                "gee_module": gee_module,
            },
        )
        export_workflow = WorkflowDefinition(
            workflow_id=f"pressure-export-{region_id}",
            nodes=[
                NodeSpec(
                    node_id="image",
                    node_type="literal",
                    params={"value": FakeAnalysisImage(f"img-{region_id}")},
                ),
                NodeSpec(
                    node_id="index",
                    node_type="gee_spectral_index",
                    params={"index": "ndvi", "output_band": "ndvi"},
                ),
                NodeSpec(
                    node_id="export",
                    node_type="gee_export_image",
                    params={
                        "destination": "drive",
                        "file_name_prefix": f"pressure_export_{region_id}",
                        "description": f"pressure-export-{region_id}",
                        "start_task": True,
                    },
                ),
            ],
            edges=[
                EdgeSpec(
                    source_node_id="image",
                    source_port="value",
                    target_node_id="index",
                    target_port="image",
                ),
                EdgeSpec(
                    source_node_id="index",
                    source_port="index_image",
                    target_node_id="export",
                    target_port="image",
                ),
            ],
        )

        run_result = adapter.run_workflow_job(
            {
                "workflow": export_workflow.model_dump(),
                "context": export_context.model_dump(),
            }
        )
        assert run_result.status == "completed"
        assert run_result.outputs["export.task_ref"]["status"] == "submitted"
        manifest_uris.append(run_result.outputs["export.manifest_uri"])

    poll_histories: dict[str, list[str]] = {manifest_uri: [] for manifest_uri in manifest_uris}
    for round_index in range(4):
        for manifest_index, manifest_uri in enumerate(manifest_uris):
            adapter = adapter_a if (round_index + manifest_index) % 2 == 0 else adapter_b
            status_payload = adapter.get_export_task_status(
                manifest_uri,
                gee_module=gee_module,
                update_manifest=True,
            )
            poll_histories[manifest_uri].append(status_payload["state"])

    manifest_payloads = [
        json.loads(storage_backend.get(manifest_uri.removeprefix("file://")).decode("utf-8"))
        for manifest_uri in manifest_uris
    ]
    events = event_sink.snapshot()
    export_events = [
        event["payload"]
        for event in events
        if event["payload"].get("event") == "export.submit.completed"
    ]
    account_ids = {event["account_id"] for event in export_events}
    diagnostics_a = service_a.diagnose()
    diagnostics_b = service_b.diagnose()

    assert len(batch_items) == 4
    assert len(manifest_uris) == 4
    assert all(history == ["READY", "RUNNING", "RUNNING", "COMPLETED"] for history in poll_histories.values())
    assert all(payload["task_ref"]["status"] == "completed" for payload in manifest_payloads)
    assert all(payload["task_status"]["state"] == "COMPLETED" for payload in manifest_payloads)
    assert account_ids == {"acc-1", "acc-2"}
    assert_export_diagnostics_snapshot(
        diagnostics_a,
        min_counter_values={
            "export.submit.completed": 1,
        },
        quota_coordinator_type="RedisResourceQuotaCoordinator",
        expected_degraded_shared_quotas={},
    )
    assert_export_diagnostics_snapshot(
        diagnostics_b,
        min_counter_values={
            "export.submit.completed": 1,
        },
        quota_coordinator_type="RedisResourceQuotaCoordinator",
        expected_degraded_shared_quotas={},
    )
    assert (
        diagnostics_a.checks["metrics"]["counters"].get("export.submit.completed", 0)
        + diagnostics_b.checks["metrics"]["counters"].get("export.submit.completed", 0)
    ) >= len(manifest_uris)
    assert redis_client.values == {}
    assert redis_client.expiry == {}


@pytest.mark.parametrize(
    (
        "scenario_name",
        "poll_states",
        "expected_blocked_error",
        "recovery_mode",
        "expected_diag_retry_prefix",
        "expected_terminal_action",
    ),
    [
        (
            "steady_recovery",
            ["RUNNING", "COMPLETED"],
            "shared quota recovery in progress",
            "single",
            None,
            "writeback_required",
        ),
        (
            "recovery_failure_then_degrade",
            ["FAILED"],
            "shared quota recovery in progress",
            "double",
            "shared quota recovery in progress",
            "writeback_required",
        ),
        (
            "multi_account_rotation",
            ["RUNNING", "RUNNING", "COMPLETED"],
            "shared quota recovery in progress",
            "single",
            None,
            "writeback_required",
        ),
        (
            "diagnostic_snapshot_consistency",
            ["RUNNING", "COMPLETED"],
            "shared quota recovery in progress",
            "single",
            None,
            "writeback_required",
        ),
    ],
)
def test_cross_worker_recovery_window_blocks_other_service_until_shared_redis_quota_recovers(
    tmp_path,
    scenario_name: str,
    poll_states: list[str],
    expected_blocked_error: str,
    recovery_mode: str,
    expected_diag_retry_prefix: str | None,
    expected_terminal_action: str,
) -> None:
    storage_backend = LocalStorageBackend(base_path=str(tmp_path))
    redis_client = FakeRedisClient()
    coordinator_a = FailOnceRenewingRedisQuotaCoordinator(
        client=redis_client,
        key_prefix="shared_recovery_quota",
        lease_ttl_seconds=120,
        renew_interval_seconds=0.01,
    )
    coordinator_b = RedisResourceQuotaCoordinator(
        client=redis_client,
        key_prefix="shared_recovery_quota",
        lease_ttl_seconds=120,
        renew_interval_seconds=0.01,
    )
    service_a = WorkflowService(
        settings=Settings(
            storage_backend="local",
            local_storage_root=str(tmp_path / "a"),
            max_parallel_exports=2,
        ),
        storage_backend=storage_backend,
        account_pool=InMemoryAccountPool(["acc-a"]),
        resource_controller=RuntimeResourceController(
            max_parallel_exports=2,
            max_parallel_uploads=1,
            max_parallel_downloads=1,
            max_local_write_bytes=4096,
            quota_coordinator=coordinator_a,
            shared_quota_recovery_cooldown_seconds=0.08,
        ),
    )
    service_b = WorkflowService(
        settings=Settings(
            storage_backend="local",
            local_storage_root=str(tmp_path / "b"),
            max_parallel_exports=2,
            account_cooldown_seconds=0,
        ),
        storage_backend=storage_backend,
        account_pool=InMemoryAccountPool(["acc-b"]),
        resource_controller=RuntimeResourceController(
            max_parallel_exports=2,
            max_parallel_uploads=1,
            max_parallel_downloads=1,
            max_local_write_bytes=4096,
            quota_coordinator=coordinator_b,
            shared_quota_recovery_cooldown_seconds=0.08,
        ),
    )
    adapter_b = WorkflowContractAdapter(service_b)
    export_workflow = WorkflowDefinition(
        workflow_id="shared-recovery-window-demo",
        nodes=[
            NodeSpec(node_id="image", node_type="literal", params={"value": FakeAnalysisImage("img-shared")}),
            NodeSpec(
                node_id="export",
                node_type="gee_export_image",
                params={
                    "destination": "drive",
                    "description": "shared-recovery-window-demo",
                    "file_name_prefix": "shared_recovery_window_demo",
                    "start_task": True,
                },
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="image",
                source_port="value",
                target_node_id="export",
                target_port="image",
            )
        ],
    )

    with service_a._resource_controller.export_slot(run_id="worker-a"):
        time.sleep(0.03)
        assert coordinator_a.renewed_event is True

    blocked_context = ExecutionContext(
        workflow_id=f"shared-recovery-window-demo-blocked-{scenario_name}",
        metadata={
            "storage_backend": storage_backend,
            "gee_module": SequencedFakeEeModule(default_states=["RUNNING", "FAILED"] if recovery_mode == "double" else ["RUNNING", "COMPLETED"]),
        },
    )
    blocked_result = adapter_b.run_workflow_job_response(
        {
            "workflow": export_workflow.model_dump(),
            "context": blocked_context.model_dump(),
        }
    )

    time.sleep(0.1)

    recovered_context = ExecutionContext(
        workflow_id=f"shared-recovery-window-demo-recovered-{scenario_name}",
        metadata={
            "storage_backend": storage_backend,
            "gee_module": SequencedFakeEeModule(default_states=poll_states),
        },
    )
    recovered_result = adapter_b.run_workflow_job_response(
        {
            "workflow": export_workflow.model_dump(),
            "context": recovered_context.model_dump(),
        }
    )

    recovered_poll_states: list[str] = []
    manifest_uri = recovered_result.outputs["export.manifest_uri"]
    for _ in range(len(poll_states)):
        status_payload = adapter_b.get_export_task_status(
            manifest_uri,
            gee_module=recovered_context.metadata["gee_module"],
            update_manifest=True,
        )
        recovered_poll_states.append(status_payload["state"])

    diagnostics_a = service_a.diagnose()
    diagnostics_b = service_b.diagnose()
    assert blocked_result.status == "failed"
    assert blocked_result.outputs["export.task_ref"]["status"] == "submit_failed"
    assert expected_blocked_error in blocked_result.errors[0]
    assert recovered_result.status == "completed"
    assert recovered_result.outputs["export.task_ref"]["status"] == "submitted"
    assert recovered_poll_states == poll_states
    assert_export_diagnostics_snapshot(
        diagnostics_a,
        quota_coordinator_type="FailOnceRenewingRedisQuotaCoordinator",
    )
    assert_export_diagnostics_snapshot(
        diagnostics_b,
        min_counter_values={
            "export.submit.completed": 1,
        },
        quota_coordinator_type="RedisResourceQuotaCoordinator",
        expected_degraded_shared_quotas={},
    )
    assert recovered_result.outputs["export.task_ref"]["task_id"].startswith("sequenced-task-")
    assert recovered_result.saveback_terminal_plans["export"].action == expected_terminal_action
    assert SavebackTerminalPlanPayload.model_validate(
        recovered_result.saveback_terminal_plans["export"].model_dump(mode="python")
    ).summary.terminal_state in {
        "closed_confirmed",
        "closed_reviewed",
    }
