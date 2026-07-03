from __future__ import annotations

from pathlib import Path

from contracts.job import JobRequest
from contracts.product import ProductManifest, ProductRef
from contracts.runtime import RuntimeContext
from data_access import resolve_prepared_local_path
from ingest.mat_bundle import load_mat_file
from pipelines.base import BasePipeline, PipelinePlan


def _resolve_block_datasource_selection(datasource_selection: dict[str, object]) -> dict[str, object]:
    resolved = dict(datasource_selection)
    input_mat = resolve_prepared_local_path(resolved, ("timeseries_bundle_mat", "input_mat"))
    if input_mat is not None:
        resolved["input_mat"] = str(input_mat)
    dh_mat = resolve_prepared_local_path(resolved, ("dh_mat",))
    if dh_mat is not None:
        resolved["dh_mat"] = str(dh_mat)
    return resolved


class BlockInversionPipeline(BasePipeline):
    name = "block_inversion_pipeline"

    def plan(self, request: JobRequest, ctx: RuntimeContext) -> PipelinePlan:
        mode = str(request.algorithm_params.get("mode", "dh")).lower()
        outputs = ["dh_block_mat", "tau_block_mat"] if mode == "dh" else ["sm_vod_block_mat", "tau_block_mat"]
        return PipelinePlan(
            required_datasets=["timeseries_bundle_mat"],
            required_variables=["TBv_mat", "TBh_mat", "IA_mat", "Ts_mat", "NDVI_mat", "SF_mat", "Albedo", "B", "CF", "porosity"],
            estimated_outputs=outputs,
            parallelizable=True,
            chunk_strategy="pixel_block",
            cache_requirement="partial",
        )

    def execute(self, request: JobRequest, ctx: RuntimeContext) -> ProductManifest:
        from scipy.io import savemat

        from algorithms.block_inversion import build_block_field_config, execute_block_inversion

        datasource_selection = _resolve_block_datasource_selection(request.datasource_selection)
        input_mat = Path(datasource_selection["input_mat"])
        payload = load_mat_file(input_mat)
        mode = str(request.algorithm_params.get("mode", "dh")).lower()
        freq_ghz = float(request.algorithm_params.get("freq_ghz", 1.4))
        pixel_chunk_size = int(request.algorithm_params.get("pixel_chunk_size", 2000))
        write_daily_files = bool(request.algorithm_params.get("write_daily_files", True))
        dh_mat_path = datasource_selection.get("dh_mat")
        field_config = build_block_field_config(request.algorithm_params)

        output_dir = Path(request.output_spec.extra.get("output_dir", ctx.workspace / "products" / "block_inversion"))
        output_dir.mkdir(parents=True, exist_ok=True)

        if self.logger_adapter is not None:
            self.logger_adapter.emit_stage_start("block_inversion", f"Run {mode} block inversion for {input_mat.name}")

        result = execute_block_inversion(
            payload,
            mode=mode,
            freq_ghz=freq_ghz,
            pixel_chunk_size=pixel_chunk_size,
            dh_mat_path=dh_mat_path,
            field_config=field_config,
        )

        products: list[ProductRef] = []
        start_key = result["date_keys"][0] if result["date_keys"] else input_mat.stem
        end_key = result["date_keys"][-1] if result["date_keys"] else input_mat.stem

        tau_path = output_dir / f"tau_block_{start_key}_{end_key}.mat"
        savemat(tau_path, {"Tau_ini_mat": result["Tau_ini_mat"], "date_keys": result["date_keys"]}, do_compression=True)
        products.append(ProductRef(name=f"tau_block_{start_key}_{end_key}", type="tau_block_mat", uri=str(tau_path), variable="Tau_ini_mat"))

        if mode == "dh":
            block_path = output_dir / f"dh_block_{start_key}_{end_key}.mat"
            savemat(block_path, {"DH_mat": result["DH_mat"], "Tau_ini_mat": result["Tau_ini_mat"], "date_keys": result["date_keys"]}, do_compression=True)
            products.append(ProductRef(name=f"dh_block_{start_key}_{end_key}", type="dh_block_mat", uri=str(block_path), variable="DH_mat"))
            main_layers = ["DH_mat", "Tau_ini_mat"]
            if write_daily_files:
                daily_dir = output_dir / "daily_dh"
                daily_dir.mkdir(parents=True, exist_ok=True)
                for day_index, date_key in enumerate(result["date_keys"]):
                    day_path = daily_dir / f"{date_key}.mat"
                    savemat(day_path, {"DH": result["DH_mat"][day_index, :], "Tau_ini": result["Tau_ini_mat"][day_index, :]}, do_compression=True)
                    products.append(ProductRef(name=f"{date_key}_dh", type="dh_daily_mat", uri=str(day_path), variable="DH"))
        else:
            block_path = output_dir / f"sm_vod_block_{start_key}_{end_key}.mat"
            savemat(
                block_path,
                {
                    "SM_mat": result["SM_mat"],
                    "VOD_mat": result["VOD_mat"],
                    "H_used_mat": result["H_used_mat"],
                    "Tau_ini_mat": result["Tau_ini_mat"],
                    "date_keys": result["date_keys"],
                },
                do_compression=True,
            )
            products.append(ProductRef(name=f"sm_vod_block_{start_key}_{end_key}", type="sm_vod_block_mat", uri=str(block_path), variable="SM_mat"))
            main_layers = ["SM_mat", "VOD_mat", "Tau_ini_mat"]
            if write_daily_files:
                daily_dir = output_dir / "daily_sm_vod"
                daily_dir.mkdir(parents=True, exist_ok=True)
                for day_index, date_key in enumerate(result["date_keys"]):
                    day_path = daily_dir / f"{date_key}.mat"
                    savemat(
                        day_path,
                        {
                            "SM": result["SM_mat"][day_index, :],
                            "VOD": result["VOD_mat"][day_index, :],
                            "Tau_ini": result["Tau_ini_mat"][day_index, :],
                        },
                        do_compression=True,
                    )
                    products.append(ProductRef(name=f"{date_key}_sm", type="sm_daily_mat", uri=str(day_path), variable="SM"))
                    products.append(ProductRef(name=f"{date_key}_vod", type="vod_daily_mat", uri=str(day_path), variable="VOD"))

        if self.logger_adapter is not None:
            for product in products:
                self.logger_adapter.emit_artifact("block_inversion", product.uri, product.type)
            self.logger_adapter.emit_stage_end("block_inversion", f"Generated {len(products)} block inversion products")

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
                "output_dir": str(output_dir),
                "freq_ghz": freq_ghz,
                "pixel_chunk_size": pixel_chunk_size,
                "missing_dates": result.get("missing_dates", []),
            },
        )
