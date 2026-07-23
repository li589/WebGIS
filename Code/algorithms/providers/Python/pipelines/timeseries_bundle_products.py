from __future__ import annotations

from pathlib import Path

from contracts.job import JobRequest
from contracts.product import ProductManifest, ProductRef
from contracts.runtime import RuntimeContext
from data_access import resolve_prepared_local_path
from ingest.daily_bundle import build_daily_bundle_config, load_lin_pix_selection
from ingest.timeseries_bundle import build_timeseries_bundle_from_range
from pipelines.base import BasePipeline, PipelinePlan


_TIMESERIES_PREPARED_KEY_MAP: dict[str, tuple[str, ...]] = {
    "anc_root": ("anc_root", "ancillary_mat"),
    "smap_folder": ("smap_folder", "smap_daily_mat", "daily_mat_sources"),
    "ndvi_folder": ("ndvi_folder", "ndvi_daily_mat", "daily_mat_sources"),
    "ndvi_clim_folder": ("ndvi_clim_folder", "daily_mat_sources"),
    "fy3b_folder": ("fy3b_folder", "daily_mat_sources"),
    "fy3d_folder": ("fy3d_folder", "daily_mat_sources"),
    "lin_pix_mat": ("lin_pix_mat",),
    "ndvi_extrema_mat": ("ndvi_extrema_mat",),
    "ddca_sm_folder": ("ddca_sm_folder", "daily_mat_sources"),
}


def _resolve_timeseries_datasource_selection(
    datasource_selection: dict[str, object],
) -> dict[str, object]:
    resolved = dict(datasource_selection)
    for target_key, dataset_names in _TIMESERIES_PREPARED_KEY_MAP.items():
        if target_key in resolved:
            continue
        local_path = resolve_prepared_local_path(
            resolved,
            dataset_names,
            preferred_resource_keys=(target_key,),
        )
        if local_path is not None:
            resolved[target_key] = str(local_path)
    return resolved


class TimeSeriesBundlePipeline(BasePipeline):
    name = "timeseries_bundle_pipeline"

    def plan(self, request: JobRequest, ctx: RuntimeContext) -> PipelinePlan:
        return PipelinePlan(
            required_datasets=["daily_mat_sources", "ancillary_mat"],
            required_variables=[
                "TBv",
                "TBh",
                "IA",
                "Ts",
                "sm_dca",
                "NDVI",
                "SF",
                "Albedo",
                "B",
                "CF",
                "BD",
                "H",
            ],
            estimated_outputs=["timeseries_bundle_mat"],
            parallelizable=True,
            chunk_strategy="pixel_subset_or_timerange",
            cache_requirement="partial",
        )

    def execute(self, request: JobRequest, ctx: RuntimeContext) -> ProductManifest:
        from scipy.io import savemat

        datasource_selection = _resolve_timeseries_datasource_selection(
            request.datasource_selection
        )
        config = build_daily_bundle_config(request.algorithm_params)
        output_dir = Path(
            request.output_spec.extra.get(
                "output_dir", ctx.workspace / "products" / "timeseries_bundle"
            )
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        lin_pix = load_lin_pix_selection(
            lin_pix=request.algorithm_params.get("lin_pix"),
            lin_pix_mat=datasource_selection.get("lin_pix_mat"),
            variable_name=str(
                request.algorithm_params.get("lin_pix_varname", "lin_pix")
            ),
        )

        if self.logger_adapter is not None:
            self.logger_adapter.emit_stage_start(
                "timeseries_bundle",
                f"Build time-series bundle from {request.time_range.start:%Y%m%d} to {request.time_range.end:%Y%m%d}",
            )

        bundle = build_timeseries_bundle_from_range(
            request.time_range.start,
            request.time_range.end,
            config,
            datasource_selection,
            lin_pix=lin_pix,
        )
        start_key = request.time_range.start.strftime("%Y%m%d")
        end_key = request.time_range.end.strftime("%Y%m%d")
        output_path = output_dir / f"timeseries_bundle_{start_key}_{end_key}.mat"
        payload = dict(bundle.data)
        payload["date_keys"] = bundle.date_keys
        payload["missing_dates"] = bundle.missing_dates
        payload["pixel_count"] = bundle.pixel_count
        savemat(output_path, payload, do_compression=True)

        if self.logger_adapter is not None:
            self.logger_adapter.emit_artifact(
                "timeseries_bundle", str(output_path), "timeseries_bundle_mat"
            )
            self.logger_adapter.emit_stage_end(
                "timeseries_bundle",
                f"Generated bundle with {len(bundle.date_keys)} days and {bundle.pixel_count} pixels",
            )

        main_layers = [
            "TBv_mat",
            "TBh_mat",
            "IA_mat",
            "Ts_mat",
            "SMref_mat",
            "NDVI_mat",
            "SF_mat",
            "vwc_mat",
        ]
        if str(config.temp_scheme).upper() == "DUAL":
            main_layers.extend(
                ["TC_mat", "Tsoil1_mat", "Tsoil2_mat", "Ct_mat", "TG_mat"]
            )
            if config.save_match_info:
                main_layers.extend(
                    [
                        "match_slot_index_mat",
                        "match_day_offset_mat",
                        "match_picked_file_mat",
                        "match_picked_utc_mat",
                    ]
                )

        return ProductManifest(
            job_id=request.job_id,
            run_id=ctx.run_id,
            products=[
                ProductRef(
                    name=f"timeseries_bundle_{start_key}_{end_key}",
                    type="timeseries_bundle_mat",
                    uri=str(output_path),
                    variable="bundle",
                    tags={"start": start_key, "end": end_key},
                )
            ],
            main_layers=main_layers,
            metadata_uri=None,
            extra={
                "pipeline_name": self.name,
                "output_path": str(output_path),
                "missing_dates": bundle.missing_dates,
                "pixel_count": bundle.pixel_count,
                "tb_source": config.tb_source,
                "sm_source": config.sm_source,
                "ndvi_mode": config.ndvi_mode,
                "sf_mode": config.sf_mode,
                "temp_scheme": config.temp_scheme,
                "save_match_info": config.save_match_info,
            },
        )
