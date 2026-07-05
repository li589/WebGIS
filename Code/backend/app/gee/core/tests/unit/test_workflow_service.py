import threading
import time
from pathlib import Path

import pytest

from webgis_gee.accounts.pool import InMemoryAccountPool
from webgis_gee.api.facade import create_default_facade
from webgis_gee.application.services import WorkflowService
from webgis_gee.config.settings import Settings
from webgis_gee.domain.enums import AccountState, PortKind, RunStatus
from webgis_gee.domain.models import (
    EdgeSpec,
    ExecutionContext,
    NodeExecutionResult,
    NodeSpec,
    PortSpec,
    RunResult,
    RuntimePolicy,
    StoragePolicy,
    WorkflowDefinition,
)
from webgis_gee.gee.context import GeeContext
from webgis_gee.nodes.base import BaseNode
from webgis_gee.nodes.registry import NodeRegistry
from webgis_gee.nodes.sample_nodes import LiteralNode
from webgis_gee.runtime.exceptions import ResourceExhaustedError, WorkflowValidationError
from webgis_gee.runtime.observability import InMemoryMetricsSink, InMemoryStructuredEventSink
from webgis_gee.runtime.resources import InMemoryResourceQuotaCoordinator
from webgis_gee.storage.local import LocalStorageBackend


class FailingNode(BaseNode):
    node_type = "failing"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="failing",
            node_type=FailingNode.node_type,
            output_ports=[PortSpec(name="value", kind=PortKind.VALUE)],
        )

    def execute(self, inputs: dict[str, object]) -> NodeExecutionResult:
        return NodeExecutionResult(
            node_id=self.spec.node_id,
            status=RunStatus.FAILED,
            warnings=["boom"],
        )


class QuotaFailingNode(BaseNode):
    node_type = "quota_failing"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="quota_failing",
            node_type=QuotaFailingNode.node_type,
        )

    def execute(self, inputs: dict[str, object]) -> NodeExecutionResult:
        return NodeExecutionResult(
            node_id=self.spec.node_id,
            status=RunStatus.FAILED,
            warnings=["quota exceeded"],
        )


class ExceptionNode(BaseNode):
    node_type = "exception_node"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="exception_node",
            node_type=ExceptionNode.node_type,
        )

    def execute(self, inputs: dict[str, object]) -> NodeExecutionResult:
        raise RuntimeError("temporary backend error")


class TempDirProbeNode(BaseNode):
    node_type = "temp_dir_probe"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="temp_dir_probe",
            node_type=TempDirProbeNode.node_type,
            output_ports=[
                PortSpec(name="temp_dir", kind=PortKind.VALUE),
                PortSpec(name="temp_dir_exists", kind=PortKind.VALUE),
                PortSpec(name="marker_exists", kind=PortKind.VALUE),
            ],
        )

    def execute(self, inputs: dict[str, object]) -> NodeExecutionResult:
        workflow_temp_dir = Path(str(self.context.metadata["workflow_temp_dir"]))
        marker_path = workflow_temp_dir / "probe.txt"
        marker_path.write_text("ok", encoding="utf-8")
        return NodeExecutionResult(
            node_id=self.spec.node_id,
            outputs={
                "temp_dir": str(workflow_temp_dir),
                "temp_dir_exists": workflow_temp_dir.exists(),
                "marker_exists": marker_path.exists(),
            },
        )


class AuthExceptionNode(BaseNode):
    node_type = "auth_exception_node"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="auth_exception_node",
            node_type=AuthExceptionNode.node_type,
        )

    def execute(self, inputs: dict[str, object]) -> NodeExecutionResult:
        raise RuntimeError("authentication failed for service account")


class FakeExportTask:
    def __init__(self, task_id: str = "task-1") -> None:
        self.id = task_id
        self.started = False

    def start(self) -> None:
        self.started = True


class FakeExportImageApi:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def toDrive(self, **kwargs):
        self.calls.append(kwargs)
        return FakeExportTask()


class FakeExportApi:
    def __init__(self) -> None:
        self.image = FakeExportImageApi()


class FakeBatchApi:
    def __init__(self) -> None:
        self.Export = FakeExportApi()


class FakeGeeModule:
    def __init__(self) -> None:
        self.batch = FakeBatchApi()


class FakeImage:
    def __init__(
        self,
        name: str,
        selected_bands: list[str] | None = None,
        band_values: dict[str, object] | None = None,
        properties: dict[str, object] | None = None,
    ) -> None:
        self.name = name
        self.selected_bands = selected_bands or []
        self.band_values = band_values or {"B3": 0.2, "B4": 0.3, "B8": 0.8, "B11": 0.5}
        self.properties = properties or {}
        self.renamed_to: str | None = None
        self.normalized_diff_bands: list[str] | None = None
        self.expression_text: str | None = None
        self.expression_variables: dict[str, object] | None = None

    def select(self, bands, rename=None):
        selected_values = {band: self.band_values[band] for band in bands}
        image = FakeImage(
            f"{self.name}:select",
            selected_bands=list(bands),
            band_values=selected_values,
            properties=dict(self.properties),
        )
        if rename is not None:
            image.selected_bands = list(rename)
            image.band_values = {
                rename[index]: self.band_values[bands[index]]
                for index in range(len(bands))
            }
        return image

    def normalizedDifference(self, bands):
        image = FakeImage(f"{self.name}:normalized_difference", properties=dict(self.properties))
        image.normalized_diff_bands = list(bands)
        return image

    def expression(self, expression: str, variables):
        resolved_variables: dict[str, object] = {}
        for key, value in variables.items():
            if isinstance(value, FakeImage) and value.band_values:
                resolved_variables[key] = next(iter(value.band_values.values()))
            else:
                resolved_variables[key] = value
        result_value = eval(expression, {"__builtins__": {}}, resolved_variables)
        image = FakeImage(
            f"{self.name}:expression",
            band_values={"expression": result_value},
            properties=dict(self.properties),
        )
        image.expression_text = expression
        image.expression_variables = resolved_variables
        return image

    def multiply(self, value: float):
        return FakeImage(
            f"{self.name}:multiply",
            selected_bands=list(self.selected_bands),
            band_values={band: band_value * value for band, band_value in self.band_values.items()},
            properties=dict(self.properties),
        )

    def add(self, value: float):
        return FakeImage(
            f"{self.name}:add",
            selected_bands=list(self.selected_bands),
            band_values={band: band_value + value for band, band_value in self.band_values.items()},
            properties=dict(self.properties),
        )

    def gte(self, threshold: float):
        return FakeImage(
            f"{self.name}:gte",
            selected_bands=list(self.selected_bands),
            band_values={
                band: 1 if band_value >= threshold else 0
                for band, band_value in self.band_values.items()
            },
            properties=dict(self.properties),
        )

    def lte(self, threshold: float):
        return FakeImage(
            f"{self.name}:lte",
            selected_bands=list(self.selected_bands),
            band_values={
                band: 1 if band_value <= threshold else 0
                for band, band_value in self.band_values.items()
            },
            properties=dict(self.properties),
        )

    def eq(self, target: float):
        return FakeImage(
            f"{self.name}:eq",
            selected_bands=list(self.selected_bands),
            band_values={
                band: 1 if band_value == target else 0
                for band, band_value in self.band_values.items()
            },
            properties=dict(self.properties),
        )

    def And(self, other):
        other_values = other.band_values if isinstance(other, FakeImage) else {}
        return FakeImage(
            f"{self.name}:and",
            selected_bands=list(self.selected_bands),
            band_values={
                band: 1 if band_value and other_values.get(band) else 0
                for band, band_value in self.band_values.items()
            },
            properties=dict(self.properties),
        )

    def where(self, condition, value: float):
        condition_values = condition.band_values if isinstance(condition, FakeImage) else {}
        return FakeImage(
            f"{self.name}:where",
            selected_bands=list(self.selected_bands),
            band_values={
                band: value if condition_values.get(band) else band_value
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
        return FakeImage(
            self.name,
            selected_bands=list(self.selected_bands),
            band_values=dict(self.band_values),
            properties={**self.properties, key: value},
        )


class FakeImageCollection:
    def __init__(self, name: str, images: list[FakeImage] | None = None) -> None:
        self.name = name
        self.images = images or []

    def median(self):
        return FakeImage(f"{self.name}:median")

    def mean(self):
        return FakeImage(f"{self.name}:mean")

    def mosaic(self):
        return FakeImage(f"{self.name}:mosaic")

    def map(self, fn):
        return FakeImageCollection(self.name, [fn(image) for image in self.images])

    def aggregate_array(self, property_name: str):
        return [image.get(property_name) for image in self.images]


def test_validate_workflow_accepts_simple_dag() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": 42}),
            NodeSpec(node_id="n2", node_type="identity"),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="value",
            )
        ],
    )

    validated = facade.validate_workflow(workflow)

    assert validated.workflow_id == "demo"


def test_execute_workflow_runs_sample_nodes() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": "gee"}),
            NodeSpec(node_id="n2", node_type="identity"),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="value",
            )
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == "completed"
    assert result.outputs["n1.value"] == "gee"
    assert result.outputs["n2.value"] == "gee"


def test_execute_workflow_runs_batch_map_node() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="batch-demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": [1, 2]}),
            NodeSpec(
                node_id="n2",
                node_type="batch_map",
                params={"item_key": "tile_id", "extra_params": {"source": "demo"}},
            ),
            NodeSpec(node_id="n3", node_type="identity"),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="items",
            ),
            EdgeSpec(
                source_node_id="n2",
                source_port="batch_items",
                target_node_id="n3",
                target_port="value",
            ),
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.COMPLETED
    assert result.outputs["n2.batch_items"] == [
        {"index": 0, "item": 1, "payload": {"tile_id": 1, "source": "demo"}},
        {"index": 1, "item": 2, "payload": {"tile_id": 2, "source": "demo"}},
    ]
    assert result.outputs["n3.value"] == result.outputs["n2.batch_items"]


def test_execute_workflow_fails_when_batch_map_params_are_invalid() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="batch-invalid-demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": [1]}),
            NodeSpec(
                node_id="n2",
                node_type="batch_map",
                params={"extra_params": ["bad"]},
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="items",
            )
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.FAILED
    assert result.errors == ["node n2 failed: batch_map extra_params must be an object"]


def test_execute_workflow_runs_batch_split_by_time_node() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="batch-time-demo",
        nodes=[
            NodeSpec(
                node_id="n1",
                node_type="batch_split_by_time",
                params={
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-05",
                    "step_unit": "day",
                    "step_size": 2,
                    "extra_params": {"dataset": "s2"},
                },
            ),
            NodeSpec(node_id="n2", node_type="identity"),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="batch_items",
                target_node_id="n2",
                target_port="value",
            )
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.COMPLETED
    assert result.outputs["n1.batch_items"] == [
        {
            "index": 0,
            "item": {"start_date": "2026-01-01", "end_date": "2026-01-02"},
            "payload": {
                "time_window": {"start_date": "2026-01-01", "end_date": "2026-01-02"},
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
                "dataset": "s2",
            },
        },
        {
            "index": 1,
            "item": {"start_date": "2026-01-03", "end_date": "2026-01-04"},
            "payload": {
                "time_window": {"start_date": "2026-01-03", "end_date": "2026-01-04"},
                "start_date": "2026-01-03",
                "end_date": "2026-01-04",
                "dataset": "s2",
            },
        },
        {
            "index": 2,
            "item": {"start_date": "2026-01-05", "end_date": "2026-01-05"},
            "payload": {
                "time_window": {"start_date": "2026-01-05", "end_date": "2026-01-05"},
                "start_date": "2026-01-05",
                "end_date": "2026-01-05",
                "dataset": "s2",
            },
        },
    ]
    assert result.outputs["n2.value"] == result.outputs["n1.batch_items"]


def test_execute_workflow_fails_when_batch_split_by_time_params_are_invalid() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="batch-time-invalid-demo",
        nodes=[
            NodeSpec(
                node_id="n1",
                node_type="batch_split_by_time",
                params={
                    "start_date": "2026-01-05",
                    "end_date": "2026-01-01",
                },
            ),
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.FAILED
    assert result.errors == [
        "node n1 failed: batch_split_by_time end_date must be on or after start_date"
    ]


def test_execute_workflow_runs_batch_split_by_regions_node() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="batch-region-demo",
        nodes=[
            NodeSpec(
                node_id="n1",
                node_type="literal",
                params={
                    "value": [
                        {"region_id": "r1", "name": "A"},
                        {"region_id": "r2", "name": "B"},
                    ]
                },
            ),
            NodeSpec(
                node_id="n2",
                node_type="batch_split_by_regions",
                params={"extra_params": {"dataset": "s2"}},
            ),
            NodeSpec(node_id="n3", node_type="identity"),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="regions",
            ),
            EdgeSpec(
                source_node_id="n2",
                source_port="batch_items",
                target_node_id="n3",
                target_port="value",
            ),
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.COMPLETED
    assert result.outputs["n2.batch_items"] == [
        {
            "index": 0,
            "item": {"region_id": "r1", "name": "A"},
            "payload": {
                "region": {"region_id": "r1", "name": "A"},
                "region_id": "r1",
                "name": "A",
                "dataset": "s2",
            },
        },
        {
            "index": 1,
            "item": {"region_id": "r2", "name": "B"},
            "payload": {
                "region": {"region_id": "r2", "name": "B"},
                "region_id": "r2",
                "name": "B",
                "dataset": "s2",
            },
        },
    ]
    assert result.outputs["n3.value"] == result.outputs["n2.batch_items"]


def test_execute_workflow_runs_gee_select_bands_node() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="gee-select-bands-demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": FakeImage("img")}),
            NodeSpec(
                node_id="n2",
                node_type="gee_select_bands",
                params={"bands": ["B4", "B8"], "rename": ["red", "nir"]},
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="image",
            )
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.COMPLETED
    assert result.outputs["n2.image"].selected_bands == ["red", "nir"]


def test_execute_workflow_fails_when_gee_select_bands_params_are_invalid() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="gee-select-bands-invalid-demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": FakeImage("img")}),
            NodeSpec(
                node_id="n2",
                node_type="gee_select_bands",
                params={"bands": ["B4", "B8"], "rename": ["red"]},
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="image",
            )
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.FAILED
    assert result.errors == ["node n2 failed: gee_select_bands rename must match bands length"]


def test_execute_workflow_runs_gee_spectral_index_node() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="gee-spectral-index-demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": FakeImage("img")}),
            NodeSpec(
                node_id="n2",
                node_type="gee_spectral_index",
                params={"index": "ndvi", "nir_band": "B8", "red_band": "B4", "output_band": "ndvi_band"},
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="image",
            )
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.COMPLETED
    assert result.outputs["n2.index_image"].normalized_diff_bands == ["B8", "B4"]
    assert result.outputs["n2.index_image"].renamed_to == "ndvi_band"


def test_execute_workflow_runs_gee_raster_algebra_node() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="gee-raster-algebra-demo",
        nodes=[
            NodeSpec(
                node_id="n1",
                node_type="literal",
                params={"value": FakeImage("img", band_values={"B4": 0.3, "B8": 0.8})},
            ),
            NodeSpec(
                node_id="n2",
                node_type="gee_raster_algebra",
                params={
                    "expression": "(nir - red) / (nir + red)",
                    "band_map": {"nir": "B8", "red": "B4"},
                    "output_band": "ndvi_like",
                },
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="image",
            )
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.COMPLETED
    assert result.outputs["n2.image"].expression_text == "(nir - red) / (nir + red)"
    assert result.outputs["n2.image"].expression_variables == {"nir": 0.8, "red": 0.3}
    assert result.outputs["n2.image"].band_values == pytest.approx({"ndvi_like": 0.45454545454545453})
    assert result.outputs["n2.image"].renamed_to == "ndvi_like"


def test_execute_workflow_fails_when_gee_raster_algebra_band_map_is_invalid() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="gee-raster-algebra-invalid-demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": FakeImage("img")}),
            NodeSpec(
                node_id="n2",
                node_type="gee_raster_algebra",
                params={
                    "expression": "(nir - red) / (nir + red)",
                    "band_map": {"nir": "B8", "red": ""},
                    "output_band": "ndvi_like",
                },
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="image",
            )
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.FAILED
    assert result.errors == [
        "node n2 failed: gee_raster_algebra band_map keys and values must be non-empty strings"
    ]


def test_execute_workflow_runs_gee_threshold_classify_node() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="gee-threshold-classify-demo",
        nodes=[
            NodeSpec(
                node_id="n1",
                node_type="literal",
                params={"value": FakeImage("img", band_values={"ndvi": 0.45})},
            ),
            NodeSpec(
                node_id="n2",
                node_type="gee_threshold_classify",
                params={
                    "band": "ndvi",
                    "thresholds": [0.2, 0.4],
                    "class_values": [1, 2, 3],
                    "output_band": "ndvi_class",
                },
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="image",
            )
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.COMPLETED
    assert result.outputs["n2.image"].band_values == {"ndvi_class": 3}
    assert result.outputs["n2.image"].renamed_to == "ndvi_class"


def test_execute_workflow_fails_when_gee_threshold_classify_thresholds_are_invalid() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="gee-threshold-classify-invalid-demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": FakeImage("img", band_values={"ndvi": 0.45})}),
            NodeSpec(
                node_id="n2",
                node_type="gee_threshold_classify",
                params={
                    "band": "ndvi",
                    "thresholds": [0.4, 0.2],
                    "class_values": [1, 2, 3],
                    "output_band": "ndvi_class",
                },
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="image",
            )
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.FAILED
    assert result.errors == [
        "node n2 failed: gee_threshold_classify thresholds must be strictly ascending"
    ]


def test_execute_workflow_runs_gee_reclassify_node() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="gee-reclassify-demo",
        nodes=[
            NodeSpec(
                node_id="n1",
                node_type="literal",
                params={"value": FakeImage("img", band_values={"landcover": 0.45})},
            ),
            NodeSpec(
                node_id="n2",
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
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="image",
            )
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.COMPLETED
    assert result.outputs["n2.image"].band_values == {"landcover_class": 20.0}
    assert result.outputs["n2.image"].renamed_to == "landcover_class"


def test_execute_workflow_fails_when_gee_reclassify_rule_is_invalid() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="gee-reclassify-invalid-demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": FakeImage("img")}),
            NodeSpec(
                node_id="n2",
                node_type="gee_reclassify",
                params={
                    "band": "B4",
                    "rules": [{"min": 0.6, "max": 0.2, "value": 1}],
                    "default_value": 0,
                    "output_band": "reclassed",
                },
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="image",
            )
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.FAILED
    assert result.errors == [
        "node n2 failed: gee_reclassify range rule min must be <= max"
    ]


def test_execute_workflow_fails_when_gee_spectral_index_index_is_invalid() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="gee-spectral-index-invalid-demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": FakeImage("img")}),
            NodeSpec(
                node_id="n2",
                node_type="gee_spectral_index",
                params={"index": "bad_index"},
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="image",
            )
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.FAILED
    assert result.errors == [
        "node n2 failed: gee_spectral_index index must be one of 'ndvi', 'ndwi', 'ndmi'"
    ]


def test_execute_workflow_runs_gee_image_collection_composite_node() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="gee-composite-demo",
        nodes=[
            NodeSpec(
                node_id="n1",
                node_type="literal",
                params={"value": FakeImageCollection("collection")},
            ),
            NodeSpec(
                node_id="n2",
                node_type="gee_image_collection_composite",
                params={"reducer": "mean"},
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="collection",
            )
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.COMPLETED
    assert result.outputs["n2.image"].name == "collection:mean"


def test_execute_workflow_fails_when_gee_image_collection_composite_reducer_is_invalid() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="gee-composite-invalid-demo",
        nodes=[
            NodeSpec(
                node_id="n1",
                node_type="literal",
                params={"value": FakeImageCollection("collection")},
            ),
            NodeSpec(
                node_id="n2",
                node_type="gee_image_collection_composite",
                params={"reducer": "max"},
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="collection",
            )
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.FAILED
    assert result.errors == [
        "node n2 failed: gee_image_collection_composite reducer must be 'median', 'mean' or 'mosaic'"
    ]


def test_execute_workflow_runs_gee_region_stats_node() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="gee-region-stats-demo",
        nodes=[
            NodeSpec(
                node_id="n1",
                node_type="literal",
                params={"value": FakeImage("img", band_values={"B4": 0.3, "B8": 0.8})},
            ),
            NodeSpec(node_id="n2", node_type="literal", params={"value": {"type": "Polygon"}}),
            NodeSpec(
                node_id="n3",
                node_type="gee_region_stats",
                params={"reducer": "mean", "scale": 10},
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n3",
                target_port="image",
            ),
            EdgeSpec(
                source_node_id="n2",
                source_port="value",
                target_node_id="n3",
                target_port="geometry",
            ),
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.COMPLETED
    assert result.outputs["n3.stats"] == {"B4": 0.3, "B8": 0.8}


def test_execute_workflow_fails_when_gee_region_stats_reducer_is_invalid() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="gee-region-stats-invalid-demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": FakeImage("img")}),
            NodeSpec(node_id="n2", node_type="literal", params={"value": {"type": "Polygon"}}),
            NodeSpec(
                node_id="n3",
                node_type="gee_region_stats",
                params={"reducer": "bad"},
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n3",
                target_port="image",
            ),
            EdgeSpec(
                source_node_id="n2",
                source_port="value",
                target_node_id="n3",
                target_port="geometry",
            ),
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.FAILED
    assert result.errors == [
        "node n3 failed: gee_region_stats reducer must be one of 'mean', 'sum', 'min', 'max', 'median', 'count'"
    ]


def test_execute_workflow_runs_gee_time_series_stats_node() -> None:
    facade = create_default_facade()
    collection = FakeImageCollection(
        "collection",
        images=[
            FakeImage("img-1", band_values={"B8": 0.8}, properties={"system:time_start": "2026-01-01"}),
            FakeImage("img-2", band_values={"B8": 0.6}, properties={"system:time_start": "2026-01-02"}),
        ],
    )
    workflow = WorkflowDefinition(
        workflow_id="gee-time-series-demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": collection}),
            NodeSpec(node_id="n2", node_type="literal", params={"value": {"type": "Polygon"}}),
            NodeSpec(
                node_id="n3",
                node_type="gee_time_series_stats",
                params={"reducer": "mean", "band": "B8"},
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n3",
                target_port="collection",
            ),
            EdgeSpec(
                source_node_id="n2",
                source_port="value",
                target_node_id="n3",
                target_port="geometry",
            ),
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.COMPLETED
    assert result.outputs["n3.series"]["dates"] == ["2026-01-01", "2026-01-02"]
    assert result.outputs["n3.series"]["values"] == [0.8, 0.6]


def test_execute_workflow_fails_when_gee_time_series_band_is_missing() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="gee-time-series-invalid-demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": FakeImageCollection("collection", images=[])}),
            NodeSpec(node_id="n2", node_type="literal", params={"value": {"type": "Polygon"}}),
            NodeSpec(
                node_id="n3",
                node_type="gee_time_series_stats",
                params={"reducer": "mean", "band": None},
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n3",
                target_port="collection",
            ),
            EdgeSpec(
                source_node_id="n2",
                source_port="value",
                target_node_id="n3",
                target_port="geometry",
            ),
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.FAILED
    assert result.errors == ["node n3 failed: gee_time_series_stats band must be a non-empty string"]


def test_execute_workflow_fails_when_batch_split_by_regions_params_are_invalid() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="batch-region-invalid-demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": [1, 2]}),
            NodeSpec(
                node_id="n2",
                node_type="batch_split_by_regions",
                params={"extra_params": ["bad"]},
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="regions",
            )
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.FAILED
    assert result.errors == [
        "node n2 failed: batch_split_by_regions extra_params must be an object"
    ]


def test_execute_workflow_runs_batch_collect_node() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="batch-collect-demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": [1, 2]}),
            NodeSpec(
                node_id="n2",
                node_type="batch_map",
                params={"item_key": "tile_id", "extra_params": {"dataset": "s2"}},
            ),
            NodeSpec(
                node_id="n3",
                node_type="batch_collect",
                params={"collect_field": "payload"},
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="items",
            ),
            EdgeSpec(
                source_node_id="n2",
                source_port="batch_items",
                target_node_id="n3",
                target_port="batch_items",
            ),
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.COMPLETED
    assert result.outputs["n3.collected_items"] == [
        {"tile_id": 1, "dataset": "s2"},
        {"tile_id": 2, "dataset": "s2"},
    ]
    assert result.outputs["n3.item_count"] == 2


def test_execute_workflow_fails_when_batch_collect_input_is_invalid() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="batch-collect-invalid-demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": "bad"}),
            NodeSpec(node_id="n2", node_type="batch_collect"),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="batch_items",
            )
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.FAILED
    assert result.errors == ["node n2 failed: batch_collect batch_items input must be a list"]


def test_execute_workflow_runs_batch_flatten_node() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="batch-flatten-demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": [[1, 2], 3, [4]]}),
            NodeSpec(node_id="n2", node_type="batch_flatten"),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="items",
            )
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.COMPLETED
    assert result.outputs["n2.flattened_items"] == [1, 2, 3, 4]
    assert result.outputs["n2.item_count"] == 4


def test_execute_workflow_fails_when_batch_flatten_input_is_invalid() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="batch-flatten-invalid-demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": "bad"}),
            NodeSpec(node_id="n2", node_type="batch_flatten"),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="items",
            )
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.FAILED
    assert result.errors == ["node n2 failed: batch_flatten items input must be a list"]


def test_execute_workflow_runs_batch_filter_node_by_field() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="batch-filter-field-demo",
        nodes=[
            NodeSpec(
                node_id="n1",
                node_type="literal",
                params={
                    "value": [
                        {"tile_id": "t1", "status": "ready"},
                        {"tile_id": "t2", "status": "skip"},
                        {"tile_id": "t3", "status": "ready"},
                    ]
                },
            ),
            NodeSpec(
                node_id="n2",
                node_type="batch_filter",
                params={"field": "status", "operator": "eq", "value": "ready"},
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="items",
            )
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.COMPLETED
    assert result.outputs["n2.filtered_items"] == [
        {"tile_id": "t1", "status": "ready"},
        {"tile_id": "t3", "status": "ready"},
    ]
    assert result.outputs["n2.item_count"] == 2


def test_execute_workflow_runs_batch_filter_node_by_indices() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="batch-filter-indices-demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": ["a", "b", "c"]}),
            NodeSpec(
                node_id="n2",
                node_type="batch_filter",
                params={"indices": [0, 2]},
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="items",
            )
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.COMPLETED
    assert result.outputs["n2.filtered_items"] == ["a", "c"]
    assert result.outputs["n2.item_count"] == 2


def test_execute_workflow_fails_when_batch_filter_params_are_missing() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="batch-filter-invalid-demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": [1, 2, 3]}),
            NodeSpec(node_id="n2", node_type="batch_filter"),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="items",
            )
        ],
    )

    result = facade.execute_workflow(workflow)

    assert result.status == RunStatus.FAILED
    assert result.errors == [
        "node n2 failed: batch_filter requires indices or a field/value filter condition"
    ]


def test_validate_workflow_rejects_unknown_ports() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="bad-port",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": 42}),
            NodeSpec(node_id="n2", node_type="identity"),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="missing",
            )
        ],
    )

    with pytest.raises(WorkflowValidationError, match="unknown target port"):
        facade.validate_workflow(workflow)


def test_validate_workflow_rejects_missing_required_inputs() -> None:
    facade = create_default_facade()
    workflow = WorkflowDefinition(
        workflow_id="missing-input",
        nodes=[NodeSpec(node_id="n1", node_type="identity")],
    )

    with pytest.raises(WorkflowValidationError, match="missing required input port"):
        facade.validate_workflow(workflow)


def test_execute_workflow_stops_on_failed_result_by_default() -> None:
    registry = NodeRegistry()
    registry.register(FailingNode)
    service = WorkflowService(registry=registry)
    workflow = WorkflowDefinition(
        workflow_id="stop-on-fail",
        nodes=[
            NodeSpec(node_id="n1", node_type="failing"),
            NodeSpec(node_id="n2", node_type="literal", params={"value": "later"}),
        ],
    )

    result = service.execute_workflow(workflow)

    assert result.status == RunStatus.FAILED
    assert len(result.node_results) == 1
    assert result.errors == ["node n1 failed: boom"]
    assert "n2.value" not in result.outputs


def test_execute_workflow_continues_on_failed_result_when_enabled() -> None:
    registry = NodeRegistry()
    registry.register(FailingNode)
    service = WorkflowService(registry=registry)
    workflow = WorkflowDefinition(
        workflow_id="continue-on-fail",
        runtime_policy=RuntimePolicy(continue_on_error=True),
        nodes=[
            NodeSpec(node_id="n1", node_type="failing"),
            NodeSpec(node_id="n2", node_type="literal", params={"value": "still-runs"}),
        ],
    )

    result = service.execute_workflow(workflow)

    assert result.status == RunStatus.FAILED
    assert len(result.node_results) == 2
    assert result.outputs["n2.value"] == "still-runs"


def test_workflow_service_skips_duplicate_default_registration() -> None:
    registry = NodeRegistry()
    registry.register(LiteralNode)

    service = WorkflowService(registry=registry)

    assert "literal" in service.diagnose().checks["node_registry"]["supported_node_types"]


def test_execute_workflow_releases_account_pool_lease() -> None:
    pool = InMemoryAccountPool(["acc-1"])
    service = WorkflowService(account_pool=pool)
    context = ExecutionContext(workflow_id="lease-demo")
    workflow = WorkflowDefinition(
        workflow_id="lease-demo",
        nodes=[NodeSpec(node_id="n1", node_type="literal", params={"value": 1})],
    )

    result = service.execute_workflow(workflow, context=context)

    assert result.status == RunStatus.COMPLETED
    assert context.account_id == "acc-1"
    assert pool.snapshot()[0].state == AccountState.AVAILABLE


def test_execute_workflow_cools_down_account_for_quota_failures() -> None:
    registry = NodeRegistry()
    registry.register(QuotaFailingNode)
    pool = InMemoryAccountPool(["acc-1"])
    service = WorkflowService(registry=registry, account_pool=pool)
    workflow = WorkflowDefinition(
        workflow_id="quota-demo",
        nodes=[NodeSpec(node_id="n1", node_type="quota_failing")],
    )

    result = service.execute_workflow(workflow)

    assert result.status == RunStatus.FAILED
    assert pool.snapshot()[0].state == AccountState.COOLDOWN


def test_execute_workflow_releases_account_for_non_account_failures() -> None:
    registry = NodeRegistry()
    registry.register(FailingNode)
    pool = InMemoryAccountPool(["acc-1"])
    service = WorkflowService(registry=registry, account_pool=pool)
    workflow = WorkflowDefinition(
        workflow_id="generic-fail-demo",
        nodes=[NodeSpec(node_id="n1", node_type="failing")],
    )

    result = service.execute_workflow(workflow)

    assert result.status == RunStatus.FAILED
    assert pool.snapshot()[0].state == AccountState.AVAILABLE


def test_execute_workflow_releases_account_for_transient_exceptions() -> None:
    registry = NodeRegistry()
    registry.register(ExceptionNode)
    pool = InMemoryAccountPool(["acc-1"])
    service = WorkflowService(registry=registry, account_pool=pool)
    workflow = WorkflowDefinition(
        workflow_id="transient-exception-demo",
        nodes=[NodeSpec(node_id="n1", node_type="exception_node")],
    )

    result = service.execute_workflow(workflow)

    assert result.status == RunStatus.FAILED
    assert pool.snapshot()[0].state == AccountState.AVAILABLE


def test_execute_workflow_cools_down_account_for_auth_exceptions() -> None:
    registry = NodeRegistry()
    registry.register(AuthExceptionNode)
    pool = InMemoryAccountPool(["acc-1"])
    service = WorkflowService(registry=registry, account_pool=pool)
    workflow = WorkflowDefinition(
        workflow_id="auth-exception-demo",
        nodes=[NodeSpec(node_id="n1", node_type="auth_exception_node")],
    )

    result = service.execute_workflow(workflow)

    assert result.status == RunStatus.FAILED
    assert pool.snapshot()[0].state == AccountState.COOLDOWN


def test_execute_workflow_exception_path_uses_error_classification(monkeypatch) -> None:
    pool = InMemoryAccountPool(["acc-1"])
    service = WorkflowService(account_pool=pool)
    workflow = WorkflowDefinition(
        workflow_id="raised-auth-demo",
        nodes=[NodeSpec(node_id="n1", node_type="literal", params={"value": 1})],
    )

    def raise_auth_error(workflow: WorkflowDefinition, context: ExecutionContext):
        raise RuntimeError("authentication failed during gee initialization")

    monkeypatch.setattr(service._executor, "execute", raise_auth_error)

    with pytest.raises(RuntimeError, match="authentication failed"):
        service.execute_workflow(workflow)

    assert pool.snapshot()[0].state == AccountState.COOLDOWN


@pytest.mark.parametrize(
    ("messages", "expected_state"),
    [
        (["authentication failed while polling export task"], AccountState.COOLDOWN),
        (["quota exceeded during export task polling"], AccountState.COOLDOWN),
        (["export task was cancelled by user"], AccountState.AVAILABLE),
        (["export task failed with invalid region input"], AccountState.AVAILABLE),
    ],
)
def test_execute_workflow_export_terminal_messages_drive_account_pool_state(
    monkeypatch,
    messages: list[str],
    expected_state: AccountState,
) -> None:
    pool = InMemoryAccountPool(["acc-1"])
    service = WorkflowService(account_pool=pool)
    workflow = WorkflowDefinition(
        workflow_id="export-terminal-demo",
        nodes=[NodeSpec(node_id="n1", node_type="literal", params={"value": 1})],
    )

    def return_failed_result(workflow: WorkflowDefinition, context: ExecutionContext) -> RunResult:
        return RunResult(
            run_id=context.run_id,
            workflow_id=workflow.workflow_id,
            status=RunStatus.FAILED,
            errors=list(messages),
        )

    monkeypatch.setattr(service._executor, "execute", return_failed_result)

    result = service.execute_workflow(workflow)

    assert result.status == RunStatus.FAILED
    assert pool.snapshot()[0].state == expected_state


def test_execute_workflow_respects_workflow_storage_policy_base_path(tmp_path) -> None:
    default_root = tmp_path / "default"
    override_root = tmp_path / "override"
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(default_root)),
    )
    workflow = WorkflowDefinition(
        workflow_id="storage-policy-demo",
        storage_policy=StoragePolicy(backend="local", base_path=str(override_root)),
        nodes=[
            NodeSpec(node_id="source", node_type="literal", params={"value": "fake-image"}),
            NodeSpec(
                node_id="export",
                node_type="gee_export_image",
                params={"destination": "drive", "file_name_prefix": "storage_policy_manifest"},
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

    result = service.execute_workflow(workflow)

    manifest_uri = result.outputs["export.manifest_uri"]
    assert manifest_uri.startswith(f"file://{override_root}")
    assert not (default_root / "exports").exists()


def test_execute_workflow_respects_context_storage_backend(monkeypatch, tmp_path) -> None:
    captured: dict[str, str | None] = {}

    def fake_create_storage_backend(settings, *, backend_type=None, local_storage_root=None):
        captured["backend_type"] = backend_type
        captured["local_storage_root"] = local_storage_root
        return LocalStorageBackend(base_path=str(tmp_path / "context-storage"))

    monkeypatch.setattr(
        "webgis_gee.application.services.create_storage_backend",
        fake_create_storage_backend,
    )

    service = WorkflowService(settings=Settings(storage_backend="local"))
    workflow = WorkflowDefinition(
        workflow_id="context-storage-demo",
        nodes=[
            NodeSpec(node_id="source", node_type="literal", params={"value": "fake-image"}),
            NodeSpec(
                node_id="export",
                node_type="gee_export_image",
                params={"destination": "drive", "file_name_prefix": "context_storage_manifest"},
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
    context = ExecutionContext(workflow_id=workflow.workflow_id, storage_backend="minio")

    service.execute_workflow(workflow, context)

    assert captured["backend_type"] == "minio"


def test_gee_context_serializes_runtime_access_across_accounts() -> None:
    class FakeEeModule:
        def __init__(self) -> None:
            self.initialize_calls = 0

        def Initialize(self, credentials=None) -> None:
            self.initialize_calls += 1

    ctx1 = GeeContext(account_id="acc-1", ee_module=FakeEeModule())
    ctx2 = GeeContext(account_id="acc-2", ee_module=FakeEeModule())
    first_ready = threading.Event()
    release_first = threading.Event()
    second_ready = threading.Event()

    def use_first_context() -> None:
        _ = ctx1.ee
        first_ready.set()
        release_first.wait(timeout=2)
        ctx1.close()

    def use_second_context() -> None:
        _ = ctx2.ee
        second_ready.set()
        ctx2.close()

    thread_one = threading.Thread(target=use_first_context)
    thread_two = threading.Thread(target=use_second_context)

    thread_one.start()
    assert first_ready.wait(timeout=1)

    thread_two.start()
    time.sleep(0.1)
    assert not second_ready.is_set()

    release_first.set()
    thread_one.join(timeout=1)
    thread_two.join(timeout=1)

    assert second_ready.is_set()


def test_execute_workflow_fails_when_export_slots_are_exhausted(tmp_path) -> None:
    storage_backend = LocalStorageBackend(base_path=str(tmp_path))
    service = WorkflowService(
        settings=Settings(
            storage_backend="local",
            local_storage_root=str(tmp_path),
            max_parallel_exports=1,
        ),
    )
    workflow = WorkflowDefinition(
        workflow_id="export-slot-demo",
        nodes=[
            NodeSpec(node_id="source", node_type="literal", params={"value": "fake-image"}),
            NodeSpec(
                node_id="export",
                node_type="gee_export_image",
                params={
                    "destination": "drive",
                    "description": "slot-limited-export",
                    "file_name_prefix": "slot_limited_export",
                    "start_task": True,
                },
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
    context = ExecutionContext(
        workflow_id=workflow.workflow_id,
        metadata={
            "storage_backend": storage_backend,
            "gee_module": FakeGeeModule(),
        },
    )

    with service._resource_controller.export_slot():
        result = service.execute_workflow(workflow, context)

    manifest_uri = result.outputs["export.manifest_uri"]
    manifest_payload = storage_backend.get(manifest_uri.removeprefix("file://")).decode("utf-8")

    assert result.status == RunStatus.FAILED
    assert result.outputs["export.task_ref"]["status"] == "submit_failed"
    assert "max_parallel_exports=1" in result.errors[0]
    assert '"status": "submit_failed"' in manifest_payload


def test_execute_workflow_fails_when_upload_slots_are_exhausted(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(
            storage_backend="local",
            local_storage_root=str(tmp_path),
            max_parallel_uploads=1,
        ),
    )
    workflow = WorkflowDefinition(
        workflow_id="upload-slot-demo",
        nodes=[
            NodeSpec(node_id="source", node_type="literal", params={"value": "fake-image"}),
            NodeSpec(
                node_id="export",
                node_type="gee_export_image",
                params={"destination": "manifest", "file_name_prefix": "upload_slot_manifest"},
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

    with service._resource_controller.upload_slot(run_id="held-upload"):
        result = service.execute_workflow(workflow)

    assert result.status == RunStatus.FAILED
    assert "upload concurrency limit reached" in result.errors[0]


def test_poll_export_task_fails_when_download_slots_are_exhausted(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(
            storage_backend="local",
            local_storage_root=str(tmp_path),
            max_parallel_downloads=1,
        ),
    )
    manifest_path = tmp_path / "exports" / "download_limited.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        '{"workflow_id":"demo","task_ref":{"started":false,"status":"manifest_created"}}',
        encoding="utf-8",
    )

    with pytest.raises(ResourceExhaustedError, match="download concurrency limit reached"):
        with service._resource_controller.download_slot(run_id="held-download"):
            service.poll_export_task(manifest_uri=f"file://{manifest_path}")


def test_execute_workflow_respects_shared_export_quota_across_services(tmp_path) -> None:
    shared_quota = InMemoryResourceQuotaCoordinator()
    service_a = WorkflowService(
        settings=Settings(
            storage_backend="local",
            local_storage_root=str(tmp_path / "a"),
            max_parallel_exports=1,
        ),
        quota_coordinator=shared_quota,
    )
    service_b = WorkflowService(
        settings=Settings(
            storage_backend="local",
            local_storage_root=str(tmp_path / "b"),
            max_parallel_exports=1,
        ),
        quota_coordinator=shared_quota,
    )
    workflow = WorkflowDefinition(
        workflow_id="shared-export-quota-demo",
        nodes=[
            NodeSpec(node_id="source", node_type="literal", params={"value": "fake-image"}),
            NodeSpec(
                node_id="export",
                node_type="gee_export_image",
                params={
                    "destination": "drive",
                    "description": "shared-quota-export",
                    "file_name_prefix": "shared_quota_export",
                    "start_task": True,
                },
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
    context = ExecutionContext(
        workflow_id=workflow.workflow_id,
        metadata={"gee_module": FakeGeeModule()},
    )

    with service_a._resource_controller.export_slot(run_id="worker-a-held"):
        result = service_b.execute_workflow(workflow, context)

    diagnostics = service_b.diagnose()
    assert result.status == RunStatus.FAILED
    assert result.outputs["export.task_ref"]["status"] == "submit_failed"
    assert "shared quota reached" in result.errors[0]
    assert diagnostics.checks["resource_control"]["quota_coordinator"]["type"] == "InMemoryResourceQuotaCoordinator"


def test_execute_workflow_cleans_up_workflow_temp_dir(tmp_path) -> None:
    registry = NodeRegistry()
    registry.register(TempDirProbeNode)
    service = WorkflowService(
        registry=registry,
        settings=Settings(
            storage_backend="local",
            local_storage_root=str(tmp_path / "artifacts"),
            temp_dir=str(tmp_path / "runtime-tmp"),
        ),
    )
    workflow = WorkflowDefinition(
        workflow_id="temp-dir-demo",
        nodes=[NodeSpec(node_id="n1", node_type="temp_dir_probe")],
    )

    result = service.execute_workflow(workflow)

    workflow_temp_dir = Path(result.outputs["n1.temp_dir"])
    diagnostics = service.diagnose()
    assert result.status == RunStatus.COMPLETED
    assert result.outputs["n1.temp_dir_exists"] is True
    assert result.outputs["n1.marker_exists"] is True
    assert not workflow_temp_dir.exists()
    assert diagnostics.checks["resource_control"]["active_temp_dirs"] == 0
    assert diagnostics.checks["resource_control"]["active_local_write_bytes"] == 0


def test_execute_workflow_fails_when_local_write_budget_is_exhausted(tmp_path) -> None:
    artifacts_root = tmp_path / "artifacts"
    service = WorkflowService(
        settings=Settings(
            storage_backend="local",
            local_storage_root=str(artifacts_root),
            max_local_write_bytes=32,
        ),
    )
    workflow = WorkflowDefinition(
        workflow_id="local-write-budget-demo",
        nodes=[
            NodeSpec(node_id="source", node_type="literal", params={"value": "fake-image"}),
            NodeSpec(
                node_id="export",
                node_type="gee_export_image",
                params={"destination": "manifest", "file_name_prefix": "budget_limited_manifest"},
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

    result = service.execute_workflow(workflow)

    assert result.status == RunStatus.FAILED
    assert "local storage write budget exceeded" in result.errors[0]
    assert list(artifacts_root.rglob("*.json")) == []


def test_execute_workflow_emits_structured_logs(caplog) -> None:
    service = WorkflowService()
    workflow = WorkflowDefinition(
        workflow_id="structured-log-demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": "gee"}),
            NodeSpec(node_id="n2", node_type="identity"),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="value",
            )
        ],
    )

    with caplog.at_level("INFO"):
        result = service.execute_workflow(workflow)

    assert result.status == RunStatus.COMPLETED
    messages = [record.getMessage() for record in caplog.records]
    assert any('"event": "workflow.execute.started"' in message for message in messages)
    assert any('"event": "node.execute.started"' in message for message in messages)
    assert any(f'"run_id": "{result.run_id}"' in message for message in messages)
    assert any('"node_id": "n1"' in message for message in messages)


def test_execute_workflow_emits_events_and_metrics_to_external_sinks() -> None:
    event_sink = InMemoryStructuredEventSink()
    metrics_sink = InMemoryMetricsSink()
    service = WorkflowService(
        event_sink=event_sink,
        metrics_sink=metrics_sink,
    )
    workflow = WorkflowDefinition(
        workflow_id="external-observability-demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": "gee"}),
            NodeSpec(node_id="n2", node_type="identity"),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="value",
            )
        ],
    )

    result = service.execute_workflow(workflow)

    event_snapshot = event_sink.snapshot()
    metrics_snapshot = metrics_sink.snapshot()
    diagnostics = service.diagnose()
    assert result.status == RunStatus.COMPLETED
    assert any(event["payload"]["event"] == "workflow.execute.started" for event in event_snapshot)
    assert any(event["payload"]["event"] == "node.execute.started" for event in event_snapshot)
    assert metrics_snapshot["counters"]["workflow.execute.started"] == 1
    assert metrics_snapshot["counters"]["workflow.execute.completed"] == 1
    assert "workflow.execute.duration_ms" in metrics_snapshot["durations"]
    assert diagnostics.checks["observability"]["structured_event_sink"]["type"] == "InMemoryStructuredEventSink"
    assert diagnostics.checks["observability"]["metrics_sink"]["type"] == "InMemoryMetricsSink"
