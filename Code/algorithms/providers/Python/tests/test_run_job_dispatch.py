from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from contracts.data import DataBundle
from contracts.job import JobRequest, JobResult
from contracts.product import OutputSpec, ProductManifest, ProductRef
from contracts.runtime import RegionSpec, RuntimeContext, TimeRange
from modules.base import BaseModule
from modules.registry import MODULE_ALIASES, MODULE_REGISTRY, register_module
from pipelines.base import BasePipeline, PipelinePlan
from pipelines.retrieval_workflow_products import RetrievalWorkflowPipeline
from runner.dispatch import run_job
from runner.registry import PIPELINE_REGISTRY, register_pipeline
from utils.local_adapters import LocalProductSink
from workflow.graph import WorkflowDefinition, WorkflowNodeSpec, WorkflowOutputSpec
from workflow.schemas import ArtifactRef, NodeExecutionContext


def _write_minimal_xlsx(path: Path) -> None:
    workbook_xml = """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheets>
    <sheet xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" name="Stations" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>
"""
    worksheet_xml = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="inlineStr"><is><t>site_id</t></is></c>
      <c r="B1" t="inlineStr"><is><t>network_id</t></is></c>
    </row>
    <row r="2">
      <c r="A2" t="inlineStr"><is><t>A</t></is></c>
      <c r="B2" t="inlineStr"><is><t>NET1</t></is></c>
    </row>
  </sheetData>
</worksheet>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet_xml)


class _RecordingScheduler:
    def __init__(self) -> None:
        self.statuses: list[tuple[str, dict | None]] = []
        self.completed: list[JobResult] = []

    def get_run_context(self, request: JobRequest) -> dict[str, str]:
        return {"job_id": request.job_id}

    def update_status(self, job_id: str, run_id: str, status: str, detail=None) -> None:
        _ = (job_id, run_id)
        self.statuses.append((status, detail))

    def complete(self, result: JobResult) -> None:
        self.completed.append(result)


class _RecordingDataSource:
    def __init__(self) -> None:
        self.events: list[str] = []

    def discover(self, request) -> list[object]:
        self.events.append(f"discover:{request.dataset_name}:{request.acquire_mode}")
        return []

    def resolve(self, request) -> DataBundle:
        self.events.append(f"resolve:{request.dataset_name}")
        return DataBundle(
            bundle_id=f"bundle-{request.dataset_name}",
            dataset_name=request.dataset_name,
            variables=list(request.variables),
            time_range=request.time_range,
            storage_mode=request.acquire_mode,
            local_paths=[f"/tmp/{request.dataset_name}.mat"],
            metadata={"dataset_name": request.dataset_name},
        )

    def acquire(self, bundle: DataBundle) -> DataBundle:
        self.events.append(f"acquire:{bundle.dataset_name}")
        return bundle

    def materialize(self, bundle: DataBundle) -> DataBundle:
        self.events.append(f"materialize:{bundle.dataset_name}")
        bundle.is_materialized = True
        return bundle


class _RecordingLogger:
    def __init__(self) -> None:
        self.errors: list[tuple[str, str]] = []
        self.warnings: list[tuple[str, str]] = []
        self.warning_extras: list[dict | None] = []

    def bind_context(self, job_id: str, run_id: str) -> None:
        _ = (job_id, run_id)

    def emit_stage_start(self, stage: str, message: str) -> None:
        _ = (stage, message)

    def emit_progress(self, stage: str, progress: float, message: str) -> None:
        _ = (stage, progress, message)

    def emit_warning(self, stage: str, message: str, extra=None) -> None:
        self.warnings.append((stage, message))
        self.warning_extras.append(extra)

    def emit_error(self, stage: str, message: str, extra=None) -> None:
        _ = extra
        self.errors.append((stage, message))

    def emit_artifact(self, stage: str, artifact_uri: str, artifact_type: str) -> None:
        _ = (stage, artifact_uri, artifact_type)

    def emit_stage_end(self, stage: str, message: str) -> None:
        _ = (stage, message)


class _AcceptancePipeline(BasePipeline):
    name = "acceptance_pipeline"

    def plan(self, request: JobRequest, ctx: RuntimeContext) -> PipelinePlan:
        _ = (request, ctx)
        return PipelinePlan(
            required_datasets=["mock_dataset"],
            required_variables=["TBv", "TBh"],
            estimated_outputs=["mock_product"],
            parallelizable=True,
            chunk_strategy="none",
            cache_requirement="partial",
        )

    def execute(self, request: JobRequest, ctx: RuntimeContext) -> ProductManifest:
        prepared = request.datasource_selection.get("_prepared_bundles")
        prepared_inputs = request.datasource_selection.get("_prepared_inputs")
        assert prepared is not None
        assert prepared_inputs is not None
        assert "mock_dataset" in prepared
        assert "mock_dataset" in prepared_inputs
        assert prepared["mock_dataset"]["request"]["acquire_mode"] == "partial"
        assert prepared["mock_dataset"]["bundle"]["is_materialized"] is True
        assert (
            prepared_inputs["mock_dataset"]["request"]["dataset_name"] == "mock_dataset"
        )
        assert len(prepared_inputs["mock_dataset"]["materialized_resources"]) >= 1
        return ProductManifest(
            job_id=request.job_id,
            run_id=ctx.run_id,
            products=[
                ProductRef(
                    name="mock",
                    type="mock_product",
                    uri=str(ctx.workspace / "mock.mat"),
                    variable="TBv",
                )
            ],
            main_layers=["TBv"],
            extra={
                "prepared_dataset_count": len(prepared),
                "prepared_input_count": len(prepared_inputs),
            },
        )


class _FailingPipeline(BasePipeline):
    name = "failing_acceptance_pipeline"

    def plan(self, request: JobRequest, ctx: RuntimeContext) -> PipelinePlan:
        _ = (request, ctx)
        return PipelinePlan(
            required_datasets=[], required_variables=[], estimated_outputs=["none"]
        )

    def execute(self, request: JobRequest, ctx: RuntimeContext) -> ProductManifest:
        _ = (request, ctx)
        raise RuntimeError("acceptance failure")


class _AcceptanceModule(BaseModule):
    name = "acceptance_module"

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        _ = params
        datasource_selection = dict(inputs.get("datasource_selection", {}))
        algorithm_params = dict(inputs.get("algorithm_params", {}))
        manifest = ProductManifest(
            job_id=ctx.request.job_id,
            run_id=ctx.runtime_context.run_id,
            products=[
                ProductRef(
                    name="workflow-mock",
                    type="workflow_mock_product",
                    uri=str(ctx.workspace / "workflow_mock.mat"),
                    variable="value",
                )
            ],
            main_layers=["value"],
            extra={
                "input_value": inputs.get("input_value"),
                "datasource_selection": datasource_selection,
                "algorithm_params": algorithm_params,
            },
        )
        artifact = ArtifactRef(
            artifact_id=f"{ctx.runtime_context.run_id}:{ctx.node_id}:manifest",
            artifact_type="product_manifest",
            format="python_object",
            uri=None,
            producer_node_id=ctx.node_id,
            schema_name="ProductManifest",
        )
        ctx.artifact_store.put(artifact, payload=manifest)
        return {"manifest": artifact}


class RunJobDispatchTests(unittest.TestCase):
    def _assert_highlight_present(
        self,
        highlights: list[dict[str, object]],
        *,
        key: str,
        value: object,
    ) -> None:
        self.assertTrue(
            any(
                item.get("key") == key and item.get("value") == value
                for item in highlights
            ),
            msg=f"Expected highlight {key}={value!r} in {highlights!r}",
        )

    def setUp(self) -> None:
        self._original_acceptance = PIPELINE_REGISTRY.get(_AcceptancePipeline.name)
        self._original_failure = PIPELINE_REGISTRY.get(_FailingPipeline.name)
        self._original_module = MODULE_REGISTRY.get(_AcceptanceModule.name)
        self._original_module_aliases = dict(MODULE_ALIASES)
        register_pipeline(_AcceptancePipeline.name, _AcceptancePipeline)
        register_pipeline(_FailingPipeline.name, _FailingPipeline)
        register_module(_AcceptanceModule())

    def tearDown(self) -> None:
        if self._original_acceptance is None:
            PIPELINE_REGISTRY.pop(_AcceptancePipeline.name, None)
        else:
            PIPELINE_REGISTRY[_AcceptancePipeline.name] = self._original_acceptance
        if self._original_failure is None:
            PIPELINE_REGISTRY.pop(_FailingPipeline.name, None)
        else:
            PIPELINE_REGISTRY[_FailingPipeline.name] = self._original_failure
        if self._original_module is None:
            MODULE_REGISTRY.pop(_AcceptanceModule.name, None)
        else:
            MODULE_REGISTRY[_AcceptanceModule.name] = self._original_module
        MODULE_ALIASES.clear()
        MODULE_ALIASES.update(self._original_module_aliases)

    def _build_request(self, pipeline_name: str, job_id: str) -> JobRequest:
        return JobRequest(
            job_id=job_id,
            pipeline_name=pipeline_name,
            task_type="acceptance",
            time_range=TimeRange(start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)),
            region=RegionSpec(kind="global", value={}),
            datasource_selection={},
            algorithm_params={},
            output_spec=OutputSpec(),
        )

    def test_run_job_executes_plan_prepare_execute_and_manifest_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _RecordingDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")

            result = run_job(
                self._build_request(_AcceptancePipeline.name, "job-success"),
                scheduler,
                datasource,
                logger,
                product_sink=sink,
                workspace=workspace,
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            self.assertTrue(Path(result.manifest_uri).exists())
            self.assertEqual(
                [status for status, _ in scheduler.statuses], ["running", "planning"]
            )
            self.assertEqual(
                datasource.events,
                [
                    "discover:mock_dataset:partial",
                    "resolve:mock_dataset",
                    "acquire:mock_dataset",
                    "materialize:mock_dataset",
                ],
            )

            payload = json.loads(Path(result.manifest_uri).read_text(encoding="utf-8"))
            self.assertEqual(payload["products"][0]["type"], "mock_product")
            self.assertEqual(payload["main_layers"], ["TBv"])
            self.assertEqual(payload["extra"]["prepared_dataset_count"], 1)
            self.assertEqual(payload["extra"]["prepared_input_count"], 1)

    def test_run_job_uses_data_access_requests_when_explicit_sources_are_provided(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            remote_file = workspace / "stations.xlsx"
            _write_minimal_xlsx(remote_file)
            scheduler = _RecordingScheduler()
            datasource = _RecordingDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            request = self._build_request(
                _AcceptancePipeline.name, "job-success-data-access"
            )
            request.datasource_selection["_data_access_requests"] = {
                "mock_dataset": {
                    "selector": {
                        "uris": [
                            {
                                "uri": "https://example.com/data/mock_dataset.xlsx",
                                "metadata": {"mock_local_path": str(remote_file)},
                            }
                        ]
                    },
                    "accepted_formats": ["excel"],
                }
            }

            result = run_job(
                request,
                scheduler,
                datasource,
                logger,
                product_sink=sink,
                workspace=workspace,
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(datasource.events, [])
            payload = json.loads(Path(result.manifest_uri).read_text(encoding="utf-8"))
            self.assertEqual(payload["extra"]["prepared_dataset_count"], 1)
            self.assertEqual(payload["extra"]["prepared_input_count"], 1)
            manifest_trace = payload["extra"]["conversion_trace"]
            self.assertEqual(manifest_trace["dataset_count"], 1)
            self.assertEqual(manifest_trace["entry_count"], 1)
            self.assertEqual(len(manifest_trace["datasets"]), 1)
            dataset_trace = manifest_trace["datasets"][0]
            self.assertEqual(dataset_trace["dataset_name"], "mock_dataset")
            self.assertEqual(dataset_trace["entry_count"], 1)
            self.assertEqual(dataset_trace["resource_count"], 1)
            self.assertEqual(dataset_trace["adapters"], ["excel"])
            self.assertEqual(dataset_trace["formats"], ["excel"])
            self.assertEqual(dataset_trace["logical_types"], ["table"])
            self.assertEqual(len(dataset_trace["resources"]), 1)
            resource_trace = dataset_trace["resources"][0]
            self.assertEqual(resource_trace["adapter"], "excel")
            self.assertEqual(resource_trace["format"], "excel")
            self.assertEqual(resource_trace["logical_type"], "table")
            self.assertEqual(
                resource_trace["origin_uri"],
                "https://example.com/data/mock_dataset.xlsx",
            )
            self.assertTrue(
                str(resource_trace["uri"]).startswith("cache://materialized/")
            )
            self.assertTrue(str(resource_trace["local_path"]).endswith(".excel"))
            self.assertEqual(
                resource_trace["loaded_summary"]["counts"]["worksheet_count"], 1
            )
            self.assertEqual(resource_trace["loaded_summary"]["counts"]["row_count"], 1)
            self.assertEqual(
                resource_trace["loaded_summary"]["schema"]["headers"],
                ["site_id", "network_id"],
            )
            self.assertEqual(
                resource_trace["loaded_summary"]["title"], "Excel workbook"
            )
            self._assert_highlight_present(
                resource_trace["loaded_summary"]["highlights"],
                key="sheet_name",
                value="Stations",
            )
            self.assertEqual(resource_trace["loaded_summary"]["warnings"], [])
            self.assertIn("conversion_trace", result.metrics)
            self.assertEqual(result.metrics["conversion_trace"]["dataset_count"], 1)
            self.assertEqual(result.metrics["conversion_trace"]["entry_count"], 1)
            self.assertEqual(
                result.metrics["conversion_trace"]["datasets"][0]["resource_count"], 1
            )
            self.assertEqual(
                result.metrics["conversion_trace"]["datasets"][0]["resources"][0][
                    "origin_uri"
                ],
                "https://example.com/data/mock_dataset.xlsx",
            )
            self.assertTrue(
                any(
                    extra is not None
                    and extra.get("conversion_trace", {}).get("dataset_name")
                    == "mock_dataset"
                    and extra.get("conversion_trace", {}).get("adapters") == ["excel"]
                    for extra in logger.warning_extras
                )
            )

    def test_run_job_returns_failed_result_when_pipeline_execute_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _RecordingDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")

            result = run_job(
                self._build_request(_FailingPipeline.name, "job-fail"),
                scheduler,
                datasource,
                logger,
                product_sink=sink,
                workspace=workspace,
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.error_summary, "acceptance failure")
            self.assertEqual(scheduler.completed[-1].status, "failed")
            self.assertEqual(logger.errors[-1][0], "dispatch.pipeline")

    def test_run_job_executes_workflow_definition_via_module_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _RecordingDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            workflow_definition = WorkflowDefinition(
                workflow_id="wf-acceptance",
                nodes=[
                    WorkflowNodeSpec(
                        node_id="module_node",
                        node_type="module",
                        input_bindings={"input_value": "input:source_value"},
                        params={"module_name": "acceptance_module"},
                    )
                ],
                outputs=[
                    WorkflowOutputSpec(
                        name="final_manifest", source="node:module_node.manifest"
                    )
                ],
            )
            request = JobRequest(
                job_id="job-workflow",
                pipeline_name="workflow",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"source_value": "demo-workflow"},
                algorithm_params={},
                output_spec=OutputSpec(),
                workflow_name="acceptance-workflow",
                workflow_definition=workflow_definition,
            )

            result = run_job(
                request,
                scheduler,
                datasource,
                logger,
                product_sink=sink,
                workspace=workspace,
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            payload = json.loads(Path(result.manifest_uri).read_text(encoding="utf-8"))
            self.assertEqual(payload["products"][0]["type"], "workflow_mock_product")
            self.assertEqual(payload["extra"]["input_value"], "demo-workflow")
            self.assertEqual(
                [status for status, _ in scheduler.statuses], ["running", "planning"]
            )

    def test_run_job_workflow_metrics_include_conversion_trace_for_explicit_data_access(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            xml_file = workspace / "payload.xml"
            xml_file.write_text(
                "<root><station id='A'>demo</station></root>", encoding="utf-8"
            )
            scheduler = _RecordingScheduler()
            datasource = _RecordingDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            workflow_definition = WorkflowDefinition(
                workflow_id="wf-explicit-data-access",
                nodes=[
                    WorkflowNodeSpec(
                        node_id="module_node",
                        node_type="module",
                        input_bindings={"input_value": "input:source_value"},
                        params={"module_name": "acceptance_module"},
                    )
                ],
                outputs=[
                    WorkflowOutputSpec(
                        name="final_manifest", source="node:module_node.manifest"
                    )
                ],
            )
            request = JobRequest(
                job_id="job-workflow-trace",
                pipeline_name="workflow",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "source_value": "demo-workflow-trace",
                    "_data_access_requests": {
                        "mock_dataset": {
                            "selector": {
                                "uris": [
                                    {
                                        "uri": "https://example.com/data/mock_dataset.xml",
                                        "metadata": {"mock_local_path": str(xml_file)},
                                    }
                                ]
                            },
                            "accepted_formats": ["xml"],
                        }
                    },
                },
                algorithm_params={},
                output_spec=OutputSpec(),
                workflow_name="acceptance-workflow-trace",
                workflow_definition=workflow_definition,
            )

            result = run_job(
                request,
                scheduler,
                datasource,
                logger,
                product_sink=sink,
                workspace=workspace,
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.metrics["workflow_id"], "wf-explicit-data-access")
            self.assertEqual(result.metrics["node_count"], 1)
            payload = json.loads(Path(result.manifest_uri).read_text(encoding="utf-8"))
            manifest_trace = payload["extra"]["conversion_trace"]
            self.assertEqual(manifest_trace["dataset_count"], 1)
            self.assertEqual(manifest_trace["entry_count"], 1)
            self.assertEqual(len(manifest_trace["datasets"]), 1)
            dataset_trace = manifest_trace["datasets"][0]
            self.assertEqual(dataset_trace["dataset_name"], "mock_dataset")
            self.assertEqual(dataset_trace["resource_count"], 1)
            self.assertEqual(dataset_trace["adapters"], ["xml"])
            self.assertEqual(dataset_trace["formats"], ["xml"])
            self.assertEqual(dataset_trace["logical_types"], ["document"])
            resource_trace = dataset_trace["resources"][0]
            self.assertEqual(resource_trace["adapter"], "xml")
            self.assertEqual(resource_trace["format"], "xml")
            self.assertEqual(resource_trace["logical_type"], "document")
            self.assertEqual(
                resource_trace["origin_uri"],
                "https://example.com/data/mock_dataset.xml",
            )
            self.assertTrue(
                str(resource_trace["uri"]).startswith("cache://materialized/")
            )
            self.assertTrue(str(resource_trace["local_path"]).endswith(".xml"))
            self.assertEqual(
                resource_trace["loaded_summary"]["document"]["root_tag"], "root"
            )
            self.assertEqual(
                resource_trace["loaded_summary"]["title"], "XML document root"
            )
            self._assert_highlight_present(
                resource_trace["loaded_summary"]["highlights"],
                key="root_tag",
                value="root",
            )
            self.assertEqual(
                result.metrics["conversion_trace"]["datasets"][0]["resources"][0][
                    "origin_uri"
                ],
                "https://example.com/data/mock_dataset.xml",
            )
            self.assertTrue(
                any(
                    extra is not None
                    and extra.get("conversion_trace", {}).get("dataset_name")
                    == "mock_dataset"
                    and extra.get("conversion_trace", {}).get("formats") == ["xml"]
                    for extra in logger.warning_extras
                )
            )

    def test_run_job_accepts_workflow_definition_mapping_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _RecordingDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            workflow_definition = {
                "workflow_id": "wf-acceptance-json",
                "nodes": [
                    {
                        "node_id": "module_node",
                        "node_type": "module",
                        "input_bindings": {"input_value": "input:source_value"},
                        "params": {"module_name": "acceptance_module"},
                    }
                ],
                "outputs": [
                    {"name": "final_manifest", "source": "node:module_node.manifest"},
                ],
            }
            request = JobRequest(
                job_id="job-workflow-json",
                pipeline_name="workflow",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"source_value": "demo-workflow-json"},
                algorithm_params={},
                output_spec=OutputSpec(),
                workflow_definition=workflow_definition,
            )

            result = run_job(
                request,
                scheduler,
                datasource,
                logger,
                product_sink=sink,
                workspace=workspace,
            )

            self.assertEqual(result.status, "success")
            payload = json.loads(Path(result.manifest_uri).read_text(encoding="utf-8"))
            self.assertEqual(payload["extra"]["input_value"], "demo-workflow-json")

    def test_run_job_selects_final_manifest_when_not_first_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _RecordingDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            workflow_definition = WorkflowDefinition(
                workflow_id="wf-manifest-selection",
                nodes=[
                    WorkflowNodeSpec(
                        node_id="module_node",
                        node_type="module",
                        input_bindings={"input_value": "input:source_value"},
                        params={"module_name": "acceptance_module"},
                    )
                ],
                outputs=[
                    WorkflowOutputSpec(name="debug_value", source="input:source_value"),
                    WorkflowOutputSpec(
                        name="final_manifest", source="node:module_node.manifest"
                    ),
                ],
            )
            request = JobRequest(
                job_id="job-workflow-output-selection",
                pipeline_name="workflow",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"source_value": "demo-nonfirst-manifest"},
                algorithm_params={},
                output_spec=OutputSpec(),
                workflow_definition=workflow_definition,
            )

            result = run_job(
                request,
                scheduler,
                datasource,
                logger,
                product_sink=sink,
                workspace=workspace,
            )

            self.assertEqual(result.status, "success")
            payload = json.loads(Path(result.manifest_uri).read_text(encoding="utf-8"))
            self.assertEqual(payload["extra"]["input_value"], "demo-nonfirst-manifest")

    def test_run_job_ignores_non_manifest_output_named_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _RecordingDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            workflow_definition = WorkflowDefinition(
                workflow_id="wf-manifest-name-collision",
                nodes=[
                    WorkflowNodeSpec(
                        node_id="module_node",
                        node_type="module",
                        input_bindings={"input_value": "input:source_value"},
                        params={"module_name": "acceptance_module"},
                    )
                ],
                outputs=[
                    WorkflowOutputSpec(name="manifest", source="input:source_value"),
                    WorkflowOutputSpec(
                        name="report_manifest", source="node:module_node.manifest"
                    ),
                ],
            )
            request = JobRequest(
                job_id="job-workflow-manifest-name-collision",
                pipeline_name="workflow",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"source_value": "demo-name-collision"},
                algorithm_params={},
                output_spec=OutputSpec(),
                workflow_definition=workflow_definition,
            )

            result = run_job(
                request,
                scheduler,
                datasource,
                logger,
                product_sink=sink,
                workspace=workspace,
            )

            self.assertEqual(result.status, "success")
            payload = json.loads(Path(result.manifest_uri).read_text(encoding="utf-8"))
            self.assertEqual(payload["extra"]["input_value"], "demo-name-collision")

    def test_run_job_fails_fast_on_invalid_workflow_request_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _RecordingDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            workflow_definition = {
                "workflow_id": "wf-invalid-request-binding",
                "nodes": [
                    {
                        "node_id": "module_node",
                        "node_type": "module",
                        "input_bindings": {"input_value": "request:not_supported"},
                        "params": {"module_name": "acceptance_module"},
                    }
                ],
                "outputs": [
                    {"name": "final_manifest", "source": "node:module_node.manifest"},
                ],
            }
            request = JobRequest(
                job_id="job-invalid-workflow-binding",
                pipeline_name="workflow",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"source_value": "unused"},
                algorithm_params={},
                output_spec=OutputSpec(),
                workflow_definition=workflow_definition,
            )

            result = run_job(
                request,
                scheduler,
                datasource,
                logger,
                product_sink=sink,
                workspace=workspace,
            )

            self.assertEqual(result.status, "failed")
            self.assertIn("unsupported request binding", result.error_summary)

    def test_run_job_wraps_module_name_as_single_node_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _RecordingDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            request = JobRequest(
                job_id="job-module",
                pipeline_name="workflow",
                module_name="acceptance_module",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "source_value": "unused",
                    "dataset_name": "demo-dataset",
                },
                algorithm_params={"threshold": 3},
                output_spec=OutputSpec(extra={"publish": False}),
            )

            result = run_job(
                request,
                scheduler,
                datasource,
                logger,
                product_sink=sink,
                workspace=workspace,
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            payload = json.loads(Path(result.manifest_uri).read_text(encoding="utf-8"))
            self.assertEqual(payload["products"][0]["type"], "workflow_mock_product")
            self.assertEqual(
                payload["extra"]["datasource_selection"]["dataset_name"], "demo-dataset"
            )
            self.assertEqual(payload["extra"]["algorithm_params"]["threshold"], 3)
            self.assertIsNone(request.workflow_name)
            self.assertIsNone(request.workflow_definition)

    def test_run_job_executes_named_retrieval_workflow_preset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _RecordingDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            output_dir = workspace / "retrieval-workflow"
            request = JobRequest(
                job_id="job-retrieval-preset",
                pipeline_name="workflow",
                workflow_name="retrieval_workflow",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"dh_mat": str(workspace / "dh.mat")},
                algorithm_params={"mode": "ddca", "write_daily_files": True},
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )

            bundle = SimpleNamespace(
                data={"TBv_mat": np.array([[1.0], [2.0]], dtype=np.float64)},
                date_keys=["20200101", "20200102"],
                missing_dates=["20200103"],
                pixel_count=1,
            )
            block_result = {
                "date_keys": ["20200101", "20200102"],
                "missing_dates": ["20200103"],
                "Tau_ini_mat": np.array([[0.5], [0.7]], dtype=np.float64),
                "SM_mat": np.array([[0.2], [0.3]], dtype=np.float64),
                "VOD_mat": np.array([[1.1], [1.3]], dtype=np.float64),
                "H_used_mat": np.array([[0.15], [0.17]], dtype=np.float64),
            }

            with (
                patch("modules.bundles.load_lin_pix_selection", return_value=None),
                patch(
                    "modules.bundles.build_timeseries_bundle_from_range",
                    return_value=bundle,
                ),
                patch(
                    "modules.block_inversion.load_mat_file",
                    return_value={
                        "date_keys": block_result["date_keys"],
                        "TBv_mat": bundle.data["TBv_mat"],
                    },
                ),
                patch(
                    "algorithms.block_inversion.build_block_field_config",
                    return_value=object(),
                ),
                patch(
                    "algorithms.block_inversion.execute_block_inversion",
                    return_value=block_result,
                ),
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            payload = json.loads(Path(result.manifest_uri).read_text(encoding="utf-8"))
            product_types = [product["type"] for product in payload["products"]]
            self.assertIn("sm_vod_block_mat", product_types)
            self.assertIn("tau_block_mat", product_types)
            self.assertIn("sm_daily_mat", product_types)
            self.assertEqual(payload["extra"]["module_name"], "block_inversion")
            self.assertEqual(payload["extra"]["mode"], "ddca")
            self.assertIsNone(request.workflow_definition)
            self.assertEqual(
                [status for status, _ in scheduler.statuses], ["running", "planning"]
            )

    def test_run_job_promotes_legacy_retrieval_pipeline_name_to_workflow_preset(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _RecordingDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            output_dir = workspace / "retrieval-workflow-legacy"
            request = JobRequest(
                job_id="job-retrieval-legacy",
                pipeline_name="retrieval_workflow_pipeline",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={},
                algorithm_params={"mode": "dh", "write_daily_files": False},
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )

            bundle = SimpleNamespace(
                data={"TBv_mat": np.array([[1.0], [2.0]], dtype=np.float64)},
                date_keys=["20200101", "20200102"],
                missing_dates=[],
                pixel_count=1,
            )
            block_result = {
                "date_keys": ["20200101", "20200102"],
                "missing_dates": [],
                "Tau_ini_mat": np.array([[0.5], [0.7]], dtype=np.float64),
                "DH_mat": np.array([[0.2], [0.3]], dtype=np.float64),
            }

            with (
                patch("modules.bundles.load_lin_pix_selection", return_value=None),
                patch(
                    "modules.bundles.build_timeseries_bundle_from_range",
                    return_value=bundle,
                ),
                patch(
                    "modules.block_inversion.load_mat_file",
                    return_value={
                        "date_keys": block_result["date_keys"],
                        "TBv_mat": bundle.data["TBv_mat"],
                    },
                ),
                patch(
                    "algorithms.block_inversion.build_block_field_config",
                    return_value=object(),
                ),
                patch(
                    "algorithms.block_inversion.execute_block_inversion",
                    return_value=block_result,
                ),
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNone(request.workflow_name)
            self.assertIsNone(request.workflow_definition)
            payload = json.loads(Path(result.manifest_uri).read_text(encoding="utf-8"))
            product_types = [product["type"] for product in payload["products"]]
            self.assertIn("dh_block_mat", product_types)
            self.assertIn("tau_block_mat", product_types)

    def test_retrieval_workflow_pipeline_execute_is_compatibility_shim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            logger = _RecordingLogger()
            request = JobRequest(
                job_id="job-retrieval-shim",
                pipeline_name="retrieval_workflow_pipeline",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={},
                algorithm_params={"mode": "ddca"},
                output_spec=OutputSpec(
                    extra={"output_dir": str(workspace / "shim-out")}
                ),
            )
            runtime_context = RuntimeContext(
                job_id=request.job_id,
                run_id="run-retrieval-shim",
                workspace=workspace,
                tmp_dir=workspace / "tmp",
                cache_dir=workspace / "cache",
            )
            runtime_context.tmp_dir.mkdir(parents=True, exist_ok=True)
            runtime_context.cache_dir.mkdir(parents=True, exist_ok=True)
            pipeline = RetrievalWorkflowPipeline(logger_adapter=logger)

            fake_manifest = ProductManifest(
                job_id=request.job_id,
                run_id=runtime_context.run_id,
                products=[
                    ProductRef(
                        name="shim-product",
                        type="sm_vod_block_mat",
                        uri=str(workspace / "shim-product.mat"),
                        variable="SM_mat",
                    )
                ],
                main_layers=["SM_mat"],
                extra={"module_name": "block_inversion"},
            )
            fake_artifact = ArtifactRef(
                artifact_id="artifact:manifest",
                artifact_type="product_manifest",
                format="python_object",
                uri=None,
                producer_node_id="block_inversion",
                schema_name="ProductManifest",
            )

            class _FakeArtifactStore:
                def load(self, artifact_id: str) -> ProductManifest:
                    self.loaded_artifact_id = artifact_id
                    return fake_manifest

            fake_store = _FakeArtifactStore()
            fake_result = type(
                "_FakeWorkflowResult",
                (),
                {
                    "outputs": {"final_manifest": fake_artifact},
                    "execution_order": ["timeseries_bundle", "block_inversion"],
                },
            )()

            with (
                patch(
                    "workflow.presets.build_retrieval_workflow_definition"
                ) as builder,
                patch("workflow.executor.WorkflowRunner") as runner_cls,
            ):
                runner = runner_cls.return_value
                runner.run.return_value = fake_result
                runner.artifact_store = fake_store

                manifest = pipeline.execute(request, runtime_context)

            self.assertIs(manifest, fake_manifest)
            self.assertEqual(
                manifest.extra["compat_pipeline_name"], "retrieval_workflow_pipeline"
            )
            self.assertEqual(fake_store.loaded_artifact_id, "artifact:manifest")
            self.assertEqual(builder.call_args.args[0], request)
            self.assertTrue(
                any(
                    stage == "retrieval_workflow" and "compatibility shim" in message
                    for stage, message in logger.warnings
                )
            )


if __name__ == "__main__":
    unittest.main()
