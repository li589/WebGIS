from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from contracts.data import DataBundle
from contracts.job import JobRequest
from contracts.product import OutputSpec, ProductManifest, ProductRef
from contracts.runtime import RegionSpec, RuntimeContext, TimeRange
from modules.base import BaseModule
from modules.registry import MODULE_REGISTRY, MODULE_ALIASES, register_module
from pipelines.base import BasePipeline, PipelinePlan
from runner.registry import PIPELINE_REGISTRY, register_pipeline
from workflow.executor import WorkflowRunner
from workflow.graph import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNodeSpec,
    WorkflowOutputSpec,
)
from workflow.registry import NODE_EXECUTOR_REGISTRY, register_node_executor
from workflow.schemas import NodeExecutionContext, PortSpec


class _LiteralNodeExecutor:
    node_type = "test.literal"

    def get_input_ports(self) -> list[PortSpec]:
        return []

    def get_output_ports(self) -> list[PortSpec]:
        return [PortSpec(name="value", kind="scalar", data_class="python_object")]

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        _ = (inputs, ctx)
        return {"value": params["value"]}


class _WorkflowFakeModule(BaseModule):
    name = "workflow_fake_module"
    input_ports = [
        PortSpec(name="input_value", kind="scalar", data_class="python_object")
    ]
    output_ports = [
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest")
    ]

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        input_value = str(inputs["input_value"])
        scale = int(inputs["scale_value"])
        output_dir = str(params["output_dir"])
        manifest = ProductManifest(
            job_id=ctx.request.job_id,
            run_id=ctx.runtime_context.run_id,
            products=[
                ProductRef(
                    name="workflow_fake",
                    type="workflow_fake_product",
                    uri=str(Path(output_dir) / "workflow_fake.mat"),
                    variable="value",
                )
            ],
            main_layers=["value"],
            extra={
                "input_value": input_value,
                "scale": scale,
                "output_dir": output_dir,
            },
        )
        from workflow.schemas import ArtifactRef

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


class _WorkflowDefaultParamModule(BaseModule):
    name = "workflow_default_param_module"
    default_params = {"output_dir": "default-workflow-out"}

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        _ = inputs
        manifest = ProductManifest(
            job_id=ctx.request.job_id,
            run_id=ctx.runtime_context.run_id,
            products=[
                ProductRef(
                    name="workflow_default",
                    type="workflow_default_product",
                    uri=str(Path(params["output_dir"]) / "workflow_default.mat"),
                    variable="value",
                )
            ],
            main_layers=["value"],
            extra={"output_dir": params["output_dir"]},
        )
        from workflow.schemas import ArtifactRef

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


class _BridgeAcceptancePipeline(BasePipeline):
    name = "bridge_acceptance_pipeline"

    def plan(self, request: JobRequest, ctx: RuntimeContext) -> PipelinePlan:
        _ = (request, ctx)
        return PipelinePlan(
            required_datasets=["mock_dataset"],
            required_variables=["TBv"],
            estimated_outputs=["mock_product"],
            cache_requirement="partial",
        )

    def execute(self, request: JobRequest, ctx: RuntimeContext) -> ProductManifest:
        prepared = request.datasource_selection.get("_prepared_bundles")
        prepared_inputs = request.datasource_selection.get("_prepared_inputs")
        assert prepared is not None
        assert prepared_inputs is not None
        assert prepared["mock_dataset"]["bundle"]["is_materialized"] is True
        assert (
            prepared_inputs["mock_dataset"]["request"]["dataset_name"] == "mock_dataset"
        )
        return ProductManifest(
            job_id=request.job_id,
            run_id=ctx.run_id,
            products=[
                ProductRef(
                    name="bridge-mock",
                    type="bridge_mock_product",
                    uri=str(ctx.workspace / "bridge_mock.mat"),
                    variable="TBv",
                )
            ],
            main_layers=["TBv"],
            extra={
                "prepared_dataset_count": len(prepared),
                "prepared_input_count": len(prepared_inputs),
            },
        )


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
        self.stage_starts: list[tuple[str, str]] = []
        self.stage_ends: list[tuple[str, str]] = []
        self.progress_events: list[tuple[str, float, str]] = []
        self.errors: list[tuple[str, str, dict | None]] = []

    def emit_stage_start(self, stage: str, message: str) -> None:
        self.stage_starts.append((stage, message))

    def emit_stage_end(self, stage: str, message: str) -> None:
        self.stage_ends.append((stage, message))

    def emit_progress(self, stage: str, progress: float, message: str) -> None:
        self.progress_events.append((stage, progress, message))

    def emit_error(self, stage: str, message: str, extra=None) -> None:
        self.errors.append((stage, message, extra))

    def emit_warning(self, stage: str, message: str, extra=None) -> None:
        _ = (stage, message, extra)

    def emit_artifact(self, stage: str, artifact_uri: str, artifact_type: str) -> None:
        _ = (stage, artifact_uri, artifact_type)


class WorkflowRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_literal = NODE_EXECUTOR_REGISTRY.get(
            _LiteralNodeExecutor.node_type
        )
        self._original_module = MODULE_REGISTRY.get(_WorkflowFakeModule.name)
        self._original_default_module = MODULE_REGISTRY.get(
            _WorkflowDefaultParamModule.name
        )
        self._original_bridge_pipeline = PIPELINE_REGISTRY.get(
            _BridgeAcceptancePipeline.name
        )
        self._original_module_aliases = dict(MODULE_ALIASES)
        register_node_executor(_LiteralNodeExecutor.node_type, _LiteralNodeExecutor)
        register_module(_WorkflowFakeModule())
        register_module(_WorkflowDefaultParamModule())
        register_pipeline(_BridgeAcceptancePipeline.name, _BridgeAcceptancePipeline)

    def tearDown(self) -> None:
        if self._original_literal is None:
            NODE_EXECUTOR_REGISTRY.pop(_LiteralNodeExecutor.node_type, None)
        else:
            NODE_EXECUTOR_REGISTRY[_LiteralNodeExecutor.node_type] = (
                self._original_literal
            )
        if self._original_module is None:
            MODULE_REGISTRY.pop(_WorkflowFakeModule.name, None)
        else:
            MODULE_REGISTRY[_WorkflowFakeModule.name] = self._original_module
        if self._original_default_module is None:
            MODULE_REGISTRY.pop(_WorkflowDefaultParamModule.name, None)
        else:
            MODULE_REGISTRY[_WorkflowDefaultParamModule.name] = (
                self._original_default_module
            )
        if self._original_bridge_pipeline is None:
            PIPELINE_REGISTRY.pop(_BridgeAcceptancePipeline.name, None)
        else:
            PIPELINE_REGISTRY[_BridgeAcceptancePipeline.name] = (
                self._original_bridge_pipeline
            )
        MODULE_ALIASES.clear()
        MODULE_ALIASES.update(self._original_module_aliases)

    def test_workflow_runner_executes_module_after_upstream_node(self) -> None:
        definition = WorkflowDefinition(
            workflow_id="wf-1",
            nodes=[
                WorkflowNodeSpec(
                    node_id="literal", node_type="test.literal", params={"value": 7}
                ),
                WorkflowNodeSpec(
                    node_id="module_node",
                    node_type="module",
                    input_bindings={"input_value": "input:source_value"},
                    params={
                        "module_name": "workflow_fake_module",
                        "output_dir": "workflow-out",
                    },
                ),
            ],
            edges=[
                WorkflowEdge(
                    from_node="literal",
                    from_port="value",
                    to_node="module_node",
                    to_port="scale_value",
                )
            ],
            outputs=[
                WorkflowOutputSpec(
                    name="final_manifest", source="node:module_node.manifest"
                )
            ],
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            request = JobRequest(
                job_id="job-workflow",
                pipeline_name="workflow",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"source_value": "demo-input"},
                algorithm_params={},
                output_spec=OutputSpec(),
            )
            runtime_context = RuntimeContext(
                job_id=request.job_id,
                run_id="run-workflow",
                workspace=workspace,
                tmp_dir=workspace / "tmp",
                cache_dir=workspace / "cache",
            )
            runtime_context.tmp_dir.mkdir(parents=True, exist_ok=True)
            runtime_context.cache_dir.mkdir(parents=True, exist_ok=True)

            runner = WorkflowRunner()
            result = runner.run(definition, request, runtime_context)

            self.assertEqual(result.execution_order, ["literal", "module_node"])
            artifact = result.outputs["final_manifest"]
            manifest = runner.artifact_store.load(artifact.artifact_id)
            self.assertEqual(manifest.extra["input_value"], "demo-input")
            self.assertEqual(manifest.extra["scale"], 7)
            self.assertEqual(manifest.extra["output_dir"], "workflow-out")
            self.assertEqual(manifest.products[0].type, "workflow_fake_product")

    def test_workflow_runner_emits_node_level_logs_and_progress(self) -> None:
        definition = WorkflowDefinition(
            workflow_id="wf-logging",
            nodes=[
                WorkflowNodeSpec(
                    node_id="literal", node_type="test.literal", params={"value": 7}
                ),
                WorkflowNodeSpec(
                    node_id="module_node",
                    node_type="module",
                    input_bindings={"input_value": "input:source_value"},
                    params={
                        "module_name": "workflow_fake_module",
                        "output_dir": "workflow-out",
                    },
                ),
            ],
            edges=[
                WorkflowEdge(
                    from_node="literal",
                    from_port="value",
                    to_node="module_node",
                    to_port="scale_value",
                )
            ],
            outputs=[
                WorkflowOutputSpec(
                    name="final_manifest", source="node:module_node.manifest"
                )
            ],
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            request = JobRequest(
                job_id="job-logging",
                pipeline_name="workflow",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"source_value": "demo-input"},
                algorithm_params={},
                output_spec=OutputSpec(),
            )
            runtime_context = RuntimeContext(
                job_id=request.job_id,
                run_id="run-logging",
                workspace=workspace,
                tmp_dir=workspace / "tmp",
                cache_dir=workspace / "cache",
            )
            runtime_context.tmp_dir.mkdir(parents=True, exist_ok=True)
            runtime_context.cache_dir.mkdir(parents=True, exist_ok=True)

            logger = _RecordingLogger()
            runner = WorkflowRunner(logger_adapter=logger)
            runner.run(definition, request, runtime_context)

            self.assertEqual(
                [stage for stage, _ in logger.stage_starts],
                ["workflow.node.literal", "workflow.node.module_node"],
            )
            self.assertEqual(
                [stage for stage, _ in logger.stage_ends],
                ["workflow.node.literal", "workflow.node.module_node"],
            )
            self.assertEqual(
                [stage for stage, _, _ in logger.progress_events],
                ["workflow.dispatch", "workflow.dispatch"],
            )
            self.assertAlmostEqual(logger.progress_events[-1][1], 1.0)

    def test_workflow_runner_applies_module_default_params(self) -> None:
        definition = WorkflowDefinition(
            workflow_id="wf-default-params",
            nodes=[
                WorkflowNodeSpec(
                    node_id="module_node",
                    node_type="module",
                    params={"module_name": "workflow_default_param_module"},
                )
            ],
            outputs=[
                WorkflowOutputSpec(
                    name="final_manifest", source="node:module_node.manifest"
                )
            ],
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            request = JobRequest(
                job_id="job-default-params",
                pipeline_name="workflow",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={},
                algorithm_params={},
                output_spec=OutputSpec(),
            )
            runtime_context = RuntimeContext(
                job_id=request.job_id,
                run_id="run-default-params",
                workspace=workspace,
                tmp_dir=workspace / "tmp",
                cache_dir=workspace / "cache",
            )
            runtime_context.tmp_dir.mkdir(parents=True, exist_ok=True)
            runtime_context.cache_dir.mkdir(parents=True, exist_ok=True)

            runner = WorkflowRunner()
            result = runner.run(definition, request, runtime_context)

            artifact = result.outputs["final_manifest"]
            manifest = runner.artifact_store.load(artifact.artifact_id)
            self.assertEqual(manifest.extra["output_dir"], "default-workflow-out")

    def test_workflow_runner_rejects_duplicate_bindings_for_same_input_port(
        self,
    ) -> None:
        definition = WorkflowDefinition(
            workflow_id="wf-conflict",
            nodes=[
                WorkflowNodeSpec(
                    node_id="literal", node_type="test.literal", params={"value": 7}
                ),
                WorkflowNodeSpec(
                    node_id="module_node",
                    node_type="module",
                    input_bindings={"input_value": "input:source_value"},
                    params={
                        "module_name": "workflow_fake_module",
                        "output_dir": "workflow-out",
                    },
                ),
            ],
            edges=[
                WorkflowEdge(
                    from_node="literal",
                    from_port="value",
                    to_node="module_node",
                    to_port="input_value",
                )
            ],
            outputs=[
                WorkflowOutputSpec(
                    name="final_manifest", source="node:module_node.manifest"
                )
            ],
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            request = JobRequest(
                job_id="job-conflict",
                pipeline_name="workflow",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"source_value": "demo-input"},
                algorithm_params={},
                output_spec=OutputSpec(),
            )
            runtime_context = RuntimeContext(
                job_id=request.job_id,
                run_id="run-conflict",
                workspace=workspace,
                tmp_dir=workspace / "tmp",
                cache_dir=workspace / "cache",
            )
            runtime_context.tmp_dir.mkdir(parents=True, exist_ok=True)
            runtime_context.cache_dir.mkdir(parents=True, exist_ok=True)

            runner = WorkflowRunner()
            with self.assertRaisesRegex(ValueError, "multiple bindings"):
                runner.run(definition, request, runtime_context)

    def test_workflow_runner_bridge_pipeline_prepares_required_datasets(self) -> None:
        definition = WorkflowDefinition(
            workflow_id="wf-bridge",
            nodes=[
                WorkflowNodeSpec(
                    node_id="bridge_node",
                    node_type="bridge.pipeline",
                    params={"pipeline_name": "bridge_acceptance_pipeline"},
                )
            ],
            outputs=[
                WorkflowOutputSpec(
                    name="final_manifest", source="node:bridge_node.manifest"
                )
            ],
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            request = JobRequest(
                job_id="job-bridge",
                pipeline_name="workflow",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={},
                algorithm_params={},
                output_spec=OutputSpec(),
            )
            runtime_context = RuntimeContext(
                job_id=request.job_id,
                run_id="run-bridge",
                workspace=workspace,
                tmp_dir=workspace / "tmp",
                cache_dir=workspace / "cache",
            )
            runtime_context.tmp_dir.mkdir(parents=True, exist_ok=True)
            runtime_context.cache_dir.mkdir(parents=True, exist_ok=True)

            datasource = _RecordingDataSource()
            runner = WorkflowRunner(
                datasource_adapter=datasource, logger_adapter=_RecordingLogger()
            )
            result = runner.run(definition, request, runtime_context)

            artifact = result.outputs["final_manifest"]
            manifest = runner.artifact_store.load(artifact.artifact_id)
            self.assertEqual(manifest.extra["prepared_dataset_count"], 1)
            self.assertEqual(manifest.extra["prepared_input_count"], 1)
            self.assertEqual(
                datasource.events,
                [
                    "discover:mock_dataset:partial",
                    "resolve:mock_dataset",
                    "acquire:mock_dataset",
                    "materialize:mock_dataset",
                ],
            )

    def test_workflow_runner_bridge_pipeline_rejects_shim_pipeline_reentry(
        self,
    ) -> None:
        definition = WorkflowDefinition(
            workflow_id="wf-shim-bridge",
            nodes=[
                WorkflowNodeSpec(
                    node_id="bridge_node",
                    node_type="bridge.pipeline",
                    params={"pipeline_name": "retrieval_workflow_pipeline"},
                )
            ],
            outputs=[
                WorkflowOutputSpec(
                    name="final_manifest", source="node:bridge_node.manifest"
                )
            ],
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            request = JobRequest(
                job_id="job-shim-bridge",
                pipeline_name="workflow",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={},
                algorithm_params={},
                output_spec=OutputSpec(),
            )
            runtime_context = RuntimeContext(
                job_id=request.job_id,
                run_id="run-shim-bridge",
                workspace=workspace,
                tmp_dir=workspace / "tmp",
                cache_dir=workspace / "cache",
            )
            runtime_context.tmp_dir.mkdir(parents=True, exist_ok=True)
            runtime_context.cache_dir.mkdir(parents=True, exist_ok=True)

            runner = WorkflowRunner(logger_adapter=_RecordingLogger())
            with self.assertRaisesRegex(RuntimeError, "Compatibility shim pipeline"):
                runner.run(definition, request, runtime_context)


if __name__ == "__main__":
    unittest.main()
