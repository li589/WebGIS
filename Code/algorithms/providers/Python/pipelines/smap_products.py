from __future__ import annotations

from pathlib import Path

from contracts.job import JobRequest
from contracts.product import ProductManifest, ProductRef
from contracts.runtime import RuntimeContext
from data_access import resolve_prepared_local_directory
from ingest.smap import convert_smap_l3_directory_to_mat
from pipelines.base import BasePipeline, PipelinePlan


def _resolve_smap_input_dir(datasource_selection: dict[str, object]) -> Path:
    prepared_dir = resolve_prepared_local_directory(datasource_selection, ("SMAP_SPL3SMP_E",))
    if prepared_dir is not None:
        return prepared_dir
    input_dir = datasource_selection.get("input_dir")
    if input_dir is None:
        raise KeyError("input_dir")
    return Path(str(input_dir))


class SmapDailyPipeline(BasePipeline):
    name = "smap_daily_pipeline"

    def plan(self, request: JobRequest, ctx: RuntimeContext) -> PipelinePlan:
        return PipelinePlan(
            required_datasets=["SMAP_SPL3SMP_E"],
            required_variables=["TBh", "TBv", "Ts", "vwc", "IA", "sm_dca", "sm_scav", "vod_dca", "vod_sca"],
            estimated_outputs=["smap_daily_mat"],
            parallelizable=True,
            chunk_strategy="file_level",
            cache_requirement="partial",
        )

    def execute(self, request: JobRequest, ctx: RuntimeContext) -> ProductManifest:
        input_dir = _resolve_smap_input_dir(request.datasource_selection)
        output_dir = Path(request.output_spec.extra.get("output_dir", ctx.workspace / "products" / "smap_daily"))
        if self.logger_adapter is not None:
            self.logger_adapter.emit_stage_start("smap_extract", f"Extract SMAP L3 from {input_dir}")
        outputs = convert_smap_l3_directory_to_mat(
            input_dir=input_dir,
            output_dir=output_dir,
            start_time=request.time_range.start,
            end_time=request.time_range.end,
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
        if self.logger_adapter is not None:
            for output_path in outputs:
                self.logger_adapter.emit_artifact("smap_extract", str(output_path), "smap_daily_mat")
            self.logger_adapter.emit_stage_end("smap_extract", f"Generated {len(outputs)} SMAP daily files")

        return ProductManifest(
            job_id=request.job_id,
            run_id=ctx.run_id,
            products=product_refs,
            main_layers=["TBh", "TBv", "Ts", "vwc", "IA", "sm_dca", "sm_scav", "vod_dca", "vod_sca"],
            metadata_uri=None,
            extra={
                "pipeline_name": self.name,
                "output_dir": str(output_dir),
                "count": len(outputs),
            },
        )
