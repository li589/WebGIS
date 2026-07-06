from __future__ import annotations

from pathlib import Path

from contracts.product import ProductManifest, ProductRef
from data_access import resolve_prepared_local_directory
from ingest.smap import convert_smap_l3_directory_to_mat
from modules.base import BaseModule
from modules.registry import register_module_decorator
from workflow.schemas import ArtifactRef, NodeExecutionContext, PortSpec


def _store_manifest(
    ctx: NodeExecutionContext,
    *,
    module_name: str,
    manifest: ProductManifest,
    metadata: dict[str, object],
) -> dict[str, object]:
    artifact = ArtifactRef(
        artifact_id=f"{ctx.runtime_context.run_id}:{ctx.node_id}:manifest",
        artifact_type="product_manifest",
        format="python_object",
        uri=None,
        producer_node_id=ctx.node_id,
        schema_name="ProductManifest",
        metadata={"module_name": module_name, **metadata},
    )
    ctx.artifact_store.put(artifact, payload=manifest)
    return {"manifest": artifact}


def _resolve_smap_input_dir(datasource_selection: dict[str, object]) -> Path:
    prepared_dir = resolve_prepared_local_directory(datasource_selection, ("SMAP_SPL3SMP_E",))
    if prepared_dir is not None:
        return prepared_dir
    input_dir = datasource_selection.get("input_dir")
    if input_dir is None:
        raise KeyError("input_dir")
    return Path(str(input_dir))


@register_module_decorator(name="smap_daily", aliases=["smap_daily_pipeline"])
class SmapDailyModule(BaseModule):
    name = "smap_daily"
    description = "Native module that converts SMAP L3 HDF5 files to daily MAT products."
    input_ports = [
        PortSpec(name="datasource_selection", kind="config", data_class="dict", required=False),
        PortSpec(name="algorithm_params", kind="config", data_class="dict", required=False),
        PortSpec(name="output_spec_extra", kind="config", data_class="dict", required=False),
    ]
    output_ports = [PortSpec(name="manifest", kind="artifact", data_class="product_manifest")]

    def execute(self, inputs: dict[str, object], params: dict[str, object], ctx: NodeExecutionContext) -> dict[str, object]:
        _ = params
        datasource_selection = dict(inputs.get("datasource_selection", {}))
        output_spec_extra = dict(inputs.get("output_spec_extra", {}))

        input_dir = _resolve_smap_input_dir(datasource_selection)
        output_dir = Path(output_spec_extra.get("output_dir", ctx.workspace / "products" / "smap_daily"))
        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start("smap_extract", f"Extract SMAP L3 from {input_dir}")
        outputs = convert_smap_l3_directory_to_mat(
            input_dir=input_dir,
            output_dir=output_dir,
            start_time=ctx.request.time_range.start,
            end_time=ctx.request.time_range.end,
        )

        product_refs = [
            ProductRef(
                name=output_path.stem,
                type="smap_daily_mat",
                uri=str(output_path),
                variable="TBh,TBv,Ts,vwc,IA,sm_dca,sm_scav,vod_dca,vod_sca",
                tags={"date_key": output_path.stem},
            )
            for output_path in outputs
        ]
        if ctx.logger_adapter is not None:
            for output_path in outputs:
                ctx.logger_adapter.emit_artifact("smap_extract", str(output_path), "smap_daily_mat")
            ctx.logger_adapter.emit_stage_end("smap_extract", f"Generated {len(outputs)} SMAP daily files")

        manifest = ProductManifest(
            job_id=ctx.request.job_id,
            run_id=ctx.runtime_context.run_id,
            products=product_refs,
            main_layers=["TBh", "TBv", "Ts", "vwc", "IA", "sm_dca", "sm_scav", "vod_dca", "vod_sca"],
            metadata_uri=None,
            extra={
                "module_name": self.name,
                "output_dir": str(output_dir),
                "count": len(outputs),
            },
        )
        return _store_manifest(ctx, module_name=self.name, manifest=manifest, metadata={"product_count": len(outputs)})
