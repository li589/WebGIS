from __future__ import annotations

from pathlib import Path

from contracts.job import JobRequest
from contracts.product import ProductManifest, ProductRef
from contracts.runtime import RuntimeContext
from data_access import resolve_prepared_local_path
from ingest.daily_bundle import build_daily_bundle_config, build_daily_bundle_for_date, date_keys_from_range, load_lin_pix_selection
from pipelines.base import BasePipeline, PipelinePlan


_DAILY_BUNDLE_PREPARED_KEY_MAP: dict[str, tuple[str, ...]] = {
    "anc_root": ("anc_root", "ancillary_mat"),
    "smap_folder": ("smap_folder", "smap_daily_mat"),
    "ndvi_folder": ("ndvi_folder", "ndvi_daily_mat"),
    "ndvi_clim_folder": ("ndvi_clim_folder",),
    "fy3b_folder": ("fy3b_folder",),
    "fy3d_folder": ("fy3d_folder",),
    "lin_pix_mat": ("lin_pix_mat",),
    "ndvi_extrema_mat": ("ndvi_extrema_mat",),
    "ddca_sm_folder": ("ddca_sm_folder",),
}


def _resolve_bundle_datasource_selection(datasource_selection: dict[str, object]) -> dict[str, object]:
    resolved = dict(datasource_selection)
    for target_key, dataset_names in _DAILY_BUNDLE_PREPARED_KEY_MAP.items():
        if target_key in resolved:
            continue
        local_path = resolve_prepared_local_path(resolved, dataset_names)
        if local_path is not None:
            resolved[target_key] = str(local_path)
    return resolved


class DailyBundlePipeline(BasePipeline):
    name = "daily_bundle_pipeline"

    def plan(self, request: JobRequest, ctx: RuntimeContext) -> PipelinePlan:
        return PipelinePlan(
            required_datasets=["smap_daily_mat", "ndvi_daily_mat", "ancillary_mat"],
            required_variables=["TBv", "TBh", "IA", "Ts", "sm_dca", "NDVI", "Albedo", "B", "CF", "BD", "H"],
            estimated_outputs=["daily_bundle_mat"],
            parallelizable=True,
            chunk_strategy="daily_file",
            cache_requirement="partial",
        )

    def execute(self, request: JobRequest, ctx: RuntimeContext) -> ProductManifest:
        from scipy.io import savemat

        datasource_selection = _resolve_bundle_datasource_selection(request.datasource_selection)
        config = build_daily_bundle_config(request.algorithm_params)
        output_dir = Path(request.output_spec.extra.get("output_dir", ctx.workspace / "products" / "daily_bundle"))
        output_dir.mkdir(parents=True, exist_ok=True)

        lin_pix = load_lin_pix_selection(
            lin_pix=request.algorithm_params.get("lin_pix"),
            lin_pix_mat=datasource_selection.get("lin_pix_mat"),
            variable_name=str(request.algorithm_params.get("lin_pix_varname", "lin_pix")),
        )
        date_keys = date_keys_from_range(request.time_range.start, request.time_range.end)

        if self.logger_adapter is not None:
            self.logger_adapter.emit_stage_start("daily_bundle", f"Build {len(date_keys)} daily bundles")

        products: list[ProductRef] = []
        for date_key in date_keys:
            bundle = build_daily_bundle_for_date(
                date_key=date_key,
                config=config,
                datasource_selection=datasource_selection,
                lin_pix=lin_pix,
            )
            output_path = output_dir / f"{date_key}_bundle.mat"
            savemat(output_path, bundle, do_compression=True)
            products.append(
                ProductRef(
                    name=f"{date_key}_bundle",
                    type="daily_bundle_mat",
                    uri=str(output_path),
                    variable="bundle",
                    tags={"date_key": date_key},
                )
            )
            if self.logger_adapter is not None:
                self.logger_adapter.emit_artifact("daily_bundle", str(output_path), "daily_bundle_mat")

        if self.logger_adapter is not None:
            self.logger_adapter.emit_stage_end("daily_bundle", f"Generated {len(products)} daily bundles")

        main_layers = ["TBv", "TBh", "IA", "Ts", "SM_ref", "NDVI", "SF", "vwc"]
        if str(config.temp_scheme).upper() == "DUAL":
            main_layers.extend(["TC", "Tsoil1", "Tsoil2", "Ct", "TG"])
            if config.save_match_info:
                main_layers.extend(["match_slot_index", "match_day_offset", "match_picked_file", "match_picked_utc"])

        return ProductManifest(
            job_id=request.job_id,
            run_id=ctx.run_id,
            products=products,
            main_layers=main_layers,
            metadata_uri=None,
            extra={
                "pipeline_name": self.name,
                "output_dir": str(output_dir),
                "count": len(products),
                "tb_source": config.tb_source,
                "sm_source": config.sm_source,
                "ndvi_mode": config.ndvi_mode,
                "sf_mode": config.sf_mode,
                "temp_scheme": config.temp_scheme,
                "save_match_info": config.save_match_info,
            },
        )
