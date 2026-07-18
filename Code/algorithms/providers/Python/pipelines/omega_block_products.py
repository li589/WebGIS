from __future__ import annotations

from pathlib import Path

from contracts.job import JobRequest
from contracts.product import ProductManifest, ProductRef
from contracts.runtime import RuntimeContext
from data_access import resolve_prepared_local_path
from ingest.mat_bundle import load_mat_file
from pipelines.base import BasePipeline, PipelinePlan


def _resolve_omega_datasource_selection(datasource_selection: dict[str, object]) -> dict[str, object]:
    resolved = dict(datasource_selection)
    input_mat = resolve_prepared_local_path(resolved, ("timeseries_bundle_mat", "input_mat"))
    if input_mat is not None:
        resolved["input_mat"] = str(input_mat)
    for key in ("omega_fixed_mat", "exp0_calib_mat"):
        local_path = resolve_prepared_local_path(resolved, (key,))
        if local_path is not None:
            resolved[key] = str(local_path)
    return resolved


class OmegaBlockPipeline(BasePipeline):
    name = "omega_block_pipeline"

    def plan(self, request: JobRequest, ctx: RuntimeContext) -> PipelinePlan:
        return PipelinePlan(
            required_datasets=["timeseries_bundle_mat"],
            required_variables=["TBv_mat", "TBh_mat", "IA_mat", "Ts_mat", "SMref_mat", "NDVI_mat", "SF_mat", "Albedo", "B", "CF", "BD", "H", "LC"],
            estimated_outputs=["omega_block_mat", "omega_daily_mat"],
            parallelizable=True,
            chunk_strategy="pixel_timeseries",
            cache_requirement="partial",
        )

    def execute(self, request: JobRequest, ctx: RuntimeContext) -> ProductManifest:
        from scipy.io import savemat

        from algorithms.omega import build_omega_config, build_omega_field_config, execute_omega_retrieval

        datasource_selection = _resolve_omega_datasource_selection(request.datasource_selection)
        input_mat = Path(datasource_selection["input_mat"])
        payload = load_mat_file(input_mat)
        extra_mat_keys = ["omega_fixed_mat", "exp0_calib_mat"]
        for key in extra_mat_keys:
            extra_path = datasource_selection.get(key)
            if extra_path is not None:
                payload.update(load_mat_file(extra_path))
        config = build_omega_config(request.algorithm_params)
        field_config = build_omega_field_config(request.algorithm_params)
        write_daily_files = bool(request.algorithm_params.get("write_daily_files", True))

        output_dir = Path(request.output_spec.extra.get("output_dir", ctx.workspace / "products" / "omega_block"))
        output_dir.mkdir(parents=True, exist_ok=True)

        if self.logger_adapter is not None:
            self.logger_adapter.emit_stage_start("omega_block", f"Run omega block retrieval for {input_mat.name}")

        result = execute_omega_retrieval(payload, config=config, field_config=field_config)
        start_key = result["date_keys"][0] if result["date_keys"] else input_mat.stem
        end_key = result["date_keys"][-1] if result["date_keys"] else input_mat.stem

        block_path = output_dir / f"omega_block_{start_key}_{end_key}.mat"
        block_payload = {key: value for key, value in result.items() if value is not None}
        savemat(
            block_path,
            block_payload,
            do_compression=True,
        )

        products = [
            ProductRef(name=f"omega_block_{start_key}_{end_key}", type="omega_block_mat", uri=str(block_path), variable="OMEGA_mat"),
        ]

        if write_daily_files:
            daily_dir = output_dir / "daily_omega"
            daily_dir.mkdir(parents=True, exist_ok=True)
            for day_index, date_key in enumerate(result["date_keys"]):
                day_path = daily_dir / f"{date_key}.mat"
                savemat(
                    day_path,
                    {
                        "OMEGA": result["OMEGA_mat"][day_index, :],
                        "SM": result["SM_RET_mat"][day_index, :],
                        "VOD": result["VOD_RET_mat"][day_index, :],
                        "Tau_star": result["Tau_star_mat"][day_index, :],
                    },
                    do_compression=True,
                )
                products.append(ProductRef(name=f"{date_key}_omega", type="omega_daily_mat", uri=str(day_path), variable="OMEGA"))

        if self.logger_adapter is not None:
            for product in products:
                self.logger_adapter.emit_artifact("omega_block", product.uri, product.type)
            self.logger_adapter.emit_stage_end("omega_block", f"Generated {len(products)} omega products")

        return ProductManifest(
            job_id=request.job_id,
            run_id=ctx.run_id,
            products=products,
            main_layers=["OMEGA_mat", "SM_RET_mat", "VOD_RET_mat", "Tau_star_mat"],
            qc_layers=["qc_flag_mat", "qc_condk_mat", "qc_sratio_mat"],
            metadata_uri=None,
            extra={
                "pipeline_name": self.name,
                "output_dir": str(output_dir),
                "freq_ghz": config.freq_ghz,
                "temp_scheme": config.temp_scheme,
                "exp_mode": config.exp_mode,
                "block_days": config.block_days,
            },
        )
