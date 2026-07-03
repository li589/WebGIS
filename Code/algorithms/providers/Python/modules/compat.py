from __future__ import annotations

from dataclasses import replace

from contracts.job import JobRequest
from modules.base import BaseModule
from modules.registry import register_module
from runner.call_guard import forbid_shim_pipeline_reentry, push_runtime_call
from runner.dispatch import _prepare_required_datasets
from runner.registry import get_pipeline
from workflow.schemas import ArtifactRef, NodeExecutionContext, PortSpec


class PipelineBackedModule(BaseModule):
    description = "Compatibility module that wraps an existing pipeline."
    input_ports = [
        PortSpec(name="datasource_selection", kind="config", data_class="dict", required=False),
        PortSpec(name="algorithm_params", kind="config", data_class="dict", required=False),
        PortSpec(name="output_spec_extra", kind="config", data_class="dict", required=False),
    ]
    output_ports = [
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]

    def __init__(self, name: str, pipeline_name: str, description: str | None = None) -> None:
        self.name = name
        self.pipeline_name = pipeline_name
        if description is not None:
            self.description = description

    def execute(self, inputs: dict[str, object], params: dict[str, object], ctx: NodeExecutionContext) -> dict[str, object]:
        resolved_params = self.resolve_params(params)
        forbid_shim_pipeline_reentry(self.pipeline_name)
        pipeline_cls = get_pipeline(self.pipeline_name)
        pipeline = pipeline_cls(
            datasource_adapter=ctx.datasource_adapter,
            logger_adapter=ctx.logger_adapter,
            product_sink=ctx.product_sink,
        )

        datasource_selection = dict(resolved_params.get("datasource_selection", {}))
        datasource_bindings = dict(resolved_params.get("datasource_bindings", {}))
        for target_key, input_name in datasource_bindings.items():
            datasource_selection[str(target_key)] = inputs[str(input_name)]
        if "datasource_selection" in inputs:
            datasource_selection.update(dict(inputs["datasource_selection"]))

        algorithm_params = dict(resolved_params.get("algorithm_params", {}))
        algorithm_param_bindings = dict(resolved_params.get("algorithm_param_bindings", {}))
        for target_key, input_name in algorithm_param_bindings.items():
            algorithm_params[str(target_key)] = inputs[str(input_name)]
        if "algorithm_params" in inputs:
            algorithm_params.update(dict(inputs["algorithm_params"]))

        output_spec_extra = dict(ctx.request.output_spec.extra)
        output_spec_extra.update(dict(resolved_params.get("output_spec_extra", {})))
        if "output_spec_extra" in inputs:
            output_spec_extra.update(dict(inputs["output_spec_extra"]))

        child_request = JobRequest(
            job_id=f"{ctx.request.job_id}:{ctx.node_id}",
            pipeline_name=self.pipeline_name,
            task_type=str(resolved_params.get("task_type", ctx.request.task_type)),
            time_range=ctx.request.time_range,
            region=ctx.request.region,
            datasource_selection=datasource_selection,
            algorithm_params=algorithm_params,
            output_spec=replace(ctx.request.output_spec, extra=output_spec_extra),
            resource_hint=ctx.request.resource_hint,
            cache_policy=ctx.request.cache_policy,
            resume_policy=ctx.request.resume_policy,
            priority=ctx.request.priority,
            tags=dict(ctx.request.tags),
            workflow_name=ctx.request.workflow_name,
            workflow_definition=ctx.request.workflow_definition,
        )

        with push_runtime_call(ctx.runtime_context, f"pipeline:{self.pipeline_name}"):
            plan = pipeline.plan(child_request, ctx.runtime_context)
            prepared_bundle_payloads, prepared_input_payloads = _prepare_required_datasets(
                child_request,
                ctx.datasource_adapter,
                ctx.logger_adapter,
                plan.required_datasets,
                plan.required_variables,
                acquire_mode=plan.cache_requirement,
                cache_root=ctx.runtime_context.cache_dir,
            )
            if prepared_bundle_payloads:
                child_request.datasource_selection = dict(child_request.datasource_selection)
                child_request.datasource_selection["_prepared_bundles"] = prepared_bundle_payloads
            if prepared_input_payloads:
                child_request.datasource_selection = dict(child_request.datasource_selection)
                child_request.datasource_selection["_prepared_inputs"] = prepared_input_payloads
            manifest = pipeline.execute(child_request, ctx.runtime_context)
        artifact = ArtifactRef(
            artifact_id=f"{ctx.runtime_context.run_id}:{ctx.node_id}:manifest",
            artifact_type="product_manifest",
            format="python_object",
            uri=None,
            producer_node_id=ctx.node_id,
            schema_name="ProductManifest",
            metadata={
                "module_name": self.name,
                "pipeline_name": self.pipeline_name,
                "product_count": len(manifest.products),
            },
        )
        ctx.artifact_store.put(artifact, payload=manifest)
        return {"manifest": artifact}


def register_default_compat_modules() -> None:
    register_module(PipelineBackedModule("smap_daily", "smap_daily_pipeline"), aliases=["smap_daily_pipeline"])
    register_module(PipelineBackedModule("ndvi_daily", "ndvi_daily_pipeline"), aliases=["ndvi_daily_pipeline"])
    register_module(PipelineBackedModule("fy_daily", "fy_daily_pipeline"), aliases=["fy_daily_pipeline"])
    register_module(PipelineBackedModule("station_daily", "station_daily_pipeline"), aliases=["station_daily_pipeline"])
    register_module(PipelineBackedModule("inversion_daily", "inversion_daily_pipeline"), aliases=["inversion_daily_pipeline"])
    register_module(PipelineBackedModule("daily_bundle", "daily_bundle_pipeline"), aliases=["daily_bundle_pipeline"])
    register_module(PipelineBackedModule("timeseries_bundle", "timeseries_bundle_pipeline"), aliases=["timeseries_bundle_pipeline"])
    register_module(PipelineBackedModule("block_inversion", "block_inversion_pipeline"), aliases=["block_inversion_pipeline"])
    register_module(PipelineBackedModule("omega_block", "omega_block_pipeline"), aliases=["omega_block_pipeline"])


register_default_compat_modules()
