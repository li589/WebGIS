from __future__ import annotations

from contracts.job import JobRequest
from contracts.product import ProductManifest
from contracts.runtime import RuntimeContext
from pipelines.base import BasePipeline, PipelinePlan


class RetrievalWorkflowPipeline(BasePipeline):
    name = "retrieval_workflow_pipeline"

    def plan(self, request: JobRequest, ctx: RuntimeContext) -> PipelinePlan:
        _ = ctx
        mode = str(request.algorithm_params.get("mode", "dh")).lower()
        if mode == "dh":
            outputs = ["timeseries_bundle_mat", "dh_block_mat", "tau_block_mat"]
        elif mode == "omega":
            outputs = ["timeseries_bundle_mat", "omega_block_mat", "omega_daily_mat"]
        else:
            outputs = ["timeseries_bundle_mat", "sm_vod_block_mat", "tau_block_mat"]
        return PipelinePlan(
            required_datasets=["daily_mat_sources", "ancillary_mat"],
            required_variables=["TBv", "TBh", "IA", "Ts", "NDVI", "SF", "Albedo", "B", "CF", "BD", "H"],
            estimated_outputs=outputs,
            parallelizable=True,
            chunk_strategy="timerange_then_pixel_block",
            cache_requirement="partial",
        )

    def execute(self, request: JobRequest, ctx: RuntimeContext) -> ProductManifest:
        from workflow.executor import WorkflowRunner
        from workflow.presets import build_retrieval_workflow_definition
        from workflow.schemas import ArtifactRef

        if self.logger_adapter is not None:
            self.logger_adapter.emit_warning(
                "retrieval_workflow",
                "retrieval_workflow_pipeline is a compatibility shim; prefer workflow_name='retrieval_workflow'",
            )

        definition = build_retrieval_workflow_definition(request)
        runner = WorkflowRunner(
            datasource_adapter=self.datasource_adapter,
            logger_adapter=self.logger_adapter,
            product_sink=self.product_sink,
        )
        result = runner.run(definition, request, ctx)
        manifest_value = result.outputs["final_manifest"]
        if isinstance(manifest_value, ProductManifest):
            manifest = manifest_value
        elif isinstance(manifest_value, ArtifactRef):
            manifest = runner.artifact_store.load(manifest_value.artifact_id)
        else:
            raise TypeError(f"Unsupported retrieval workflow manifest output: {type(manifest_value)!r}")
        manifest.extra = dict(manifest.extra)
        manifest.extra.setdefault("compat_pipeline_name", self.name)
        return manifest
