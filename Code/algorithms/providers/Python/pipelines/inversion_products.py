from __future__ import annotations

from pathlib import Path

from contracts.job import JobRequest
from contracts.product import ProductManifest, ProductRef
from contracts.runtime import RuntimeContext
from data_access import resolve_prepared_local_path
from ingest.mat_bundle import (
    extract_ddca_inputs,
    extract_inversion_inputs,
    load_mat_file,
)
from pipelines.base import BasePipeline, PipelinePlan


def _resolve_inversion_input_mat(datasource_selection: dict[str, object]) -> Path:
    prepared_path = resolve_prepared_local_path(
        datasource_selection, ("daily_bundle_mat", "input_mat")
    )
    if prepared_path is not None:
        return prepared_path
    input_mat = datasource_selection.get("input_mat")
    if input_mat is None:
        raise KeyError("input_mat")
    return Path(str(input_mat))


class InversionDailyPipeline(BasePipeline):
    name = "inversion_daily_pipeline"

    def plan(self, request: JobRequest, ctx: RuntimeContext) -> PipelinePlan:
        mode = str(request.algorithm_params.get("mode", "ddca")).lower()
        estimated_outputs = ["sm_vod_mat"] if mode == "ddca" else ["dh_mat"]
        return PipelinePlan(
            required_datasets=["daily_bundle_mat"],
            required_variables=[
                "TBv",
                "TBh",
                "Ts",
                "Tau_ini",
                "CF",
                "Albedo",
                "porosity",
                "Theta",
            ],
            estimated_outputs=estimated_outputs,
            parallelizable=True,
            chunk_strategy="array_block",
            cache_requirement="partial",
        )

    def execute(self, request: JobRequest, ctx: RuntimeContext) -> ProductManifest:
        from scipy.io import savemat

        from algorithms.inversion import ddca_retrieve_grid, retrieve_dynamic_h_grid

        input_mat = _resolve_inversion_input_mat(request.datasource_selection)
        payload = load_mat_file(input_mat)
        mode = str(request.algorithm_params.get("mode", "ddca")).lower()
        freq_ghz = float(request.algorithm_params.get("freq_ghz", 1.4))
        output_dir = Path(
            request.output_spec.extra.get(
                "output_dir", ctx.workspace / "products" / "inversion_daily"
            )
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        if self.logger_adapter is not None:
            self.logger_adapter.emit_stage_start(
                "inversion_daily", f"Run {mode} inversion for {input_mat.name}"
            )

        if mode == "dh":
            inputs = extract_inversion_inputs(payload)
            dh = retrieve_dynamic_h_grid(
                inputs["tbv"],
                inputs["tbh"],
                inputs["ts"],
                inputs["tau_ini"],
                inputs["clay_fraction"],
                inputs["albedo"],
                inputs["porosity"],
                freq_ghz,
                inputs["theta_deg"],
            )
            output_path = output_dir / f"{input_mat.stem}_dh.mat"
            savemat(output_path, {"DH": dh}, do_compression=True)
            products = [
                ProductRef(
                    name=f"{input_mat.stem}_dh",
                    type="dh_mat",
                    uri=str(output_path),
                    variable="DH",
                )
            ]
            main_layers = ["DH"]
        else:
            inputs = extract_ddca_inputs(payload)
            sm, vod = ddca_retrieve_grid(
                inputs["tbv"],
                inputs["tbh"],
                inputs["ts"],
                inputs["tau_ini"],
                inputs["h_value"],
                inputs["clay_fraction"],
                inputs["albedo"],
                inputs["porosity"],
                freq_ghz,
                inputs["theta_deg"],
            )
            output_path = output_dir / f"{input_mat.stem}_sm_vod.mat"
            savemat(output_path, {"SM": sm, "VOD": vod}, do_compression=True)
            products = [
                ProductRef(
                    name=f"{input_mat.stem}_sm",
                    type="sm_mat",
                    uri=str(output_path),
                    variable="SM",
                ),
                ProductRef(
                    name=f"{input_mat.stem}_vod",
                    type="vod_mat",
                    uri=str(output_path),
                    variable="VOD",
                ),
            ]
            main_layers = ["SM", "VOD"]

        if self.logger_adapter is not None:
            self.logger_adapter.emit_artifact(
                "inversion_daily", str(output_path), "inversion_mat"
            )
            self.logger_adapter.emit_stage_end(
                "inversion_daily", f"Generated {output_path.name}"
            )

        return ProductManifest(
            job_id=request.job_id,
            run_id=ctx.run_id,
            products=products,
            main_layers=main_layers,
            metadata_uri=None,
            extra={
                "pipeline_name": self.name,
                "mode": mode,
                "input_mat": str(input_mat),
                "output_path": str(output_path),
                "freq_ghz": freq_ghz,
            },
        )
