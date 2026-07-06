from __future__ import annotations

from pathlib import Path

from contracts.product import ProductManifest, ProductRef
from data_access import resolve_prepared_local_path
from ingest.daily_bundle import build_daily_bundle_config, build_daily_bundle_for_date, date_keys_from_range, load_lin_pix_selection
from ingest.timeseries_bundle import build_timeseries_bundle_from_range
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


_DAILY_BUNDLE_PREPARED_KEY_MAP: dict[str, tuple[str, ...]] = {
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


def _resolve_bundle_datasource_selection(datasource_selection: dict[str, object]) -> dict[str, object]:
    resolved = dict(datasource_selection)
    for target_key, dataset_names in _DAILY_BUNDLE_PREPARED_KEY_MAP.items():
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


@register_module_decorator(name="daily_bundle", aliases=["daily_bundle_pipeline"])
class DailyBundleModule(BaseModule):
    name = "daily_bundle"
    description = "Native module that builds one MAT bundle per day."
    input_ports = [
        PortSpec(name="datasource_selection", kind="config", data_class="dict", required=False),
        PortSpec(name="algorithm_params", kind="config", data_class="dict", required=False),
        PortSpec(name="output_spec_extra", kind="config", data_class="dict", required=False),
    ]
    output_ports = [PortSpec(name="manifest", kind="artifact", data_class="product_manifest")]

    def execute(self, inputs: dict[str, object], params: dict[str, object], ctx: NodeExecutionContext) -> dict[str, object]:
        from scipy.io import savemat

        datasource_selection = _resolve_bundle_datasource_selection(dict(inputs.get("datasource_selection", {})))
        algorithm_params = dict(inputs.get("algorithm_params", {}))
        output_spec_extra = dict(inputs.get("output_spec_extra", {}))

        config = build_daily_bundle_config(algorithm_params)
        output_dir = Path(output_spec_extra.get("output_dir", ctx.workspace / "products" / "daily_bundle"))
        output_dir.mkdir(parents=True, exist_ok=True)

        lin_pix = load_lin_pix_selection(
            lin_pix=algorithm_params.get("lin_pix"),
            lin_pix_mat=datasource_selection.get("lin_pix_mat"),
            variable_name=str(algorithm_params.get("lin_pix_varname", "lin_pix")),
        )
        date_keys = date_keys_from_range(ctx.request.time_range.start, ctx.request.time_range.end)

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start("daily_bundle", f"Build {len(date_keys)} daily bundles")

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
            if ctx.logger_adapter is not None:
                ctx.logger_adapter.emit_artifact("daily_bundle", str(output_path), "daily_bundle_mat")

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_end("daily_bundle", f"Generated {len(products)} daily bundles")

        main_layers = ["TBv", "TBh", "IA", "Ts", "SM_ref", "NDVI", "SF", "vwc"]
        if str(config.temp_scheme).upper() == "DUAL":
            main_layers.extend(["TC", "Tsoil1", "Tsoil2", "Ct", "TG"])
            if config.save_match_info:
                main_layers.extend(["match_slot_index", "match_day_offset", "match_picked_file", "match_picked_utc"])

        manifest = ProductManifest(
            job_id=ctx.request.job_id,
            run_id=ctx.runtime_context.run_id,
            products=products,
            main_layers=main_layers,
            metadata_uri=None,
            extra={
                "module_name": self.name,
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
        return _store_manifest(ctx, module_name=self.name, manifest=manifest, metadata={"product_count": len(products)})


@register_module_decorator(name="timeseries_bundle", aliases=["timeseries_bundle_pipeline"])
class TimeSeriesBundleModule(BaseModule):
    name = "timeseries_bundle"
    description = "Native module that builds one MAT time-series bundle for a date range."
    input_ports = [
        PortSpec(name="datasource_selection", kind="config", data_class="dict", required=False),
        PortSpec(name="algorithm_params", kind="config", data_class="dict", required=False),
        PortSpec(name="output_spec_extra", kind="config", data_class="dict", required=False),
    ]
    output_ports = [
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
        PortSpec(name="output_path", kind="scalar", data_class="path"),
        PortSpec(name="missing_dates", kind="scalar", data_class="list"),
        PortSpec(name="pixel_count", kind="scalar", data_class="int"),
    ]

    def execute(self, inputs: dict[str, object], params: dict[str, object], ctx: NodeExecutionContext) -> dict[str, object]:
        from scipy.io import savemat

        datasource_selection = _resolve_bundle_datasource_selection(dict(inputs.get("datasource_selection", {})))
        algorithm_params = dict(inputs.get("algorithm_params", {}))
        output_spec_extra = dict(inputs.get("output_spec_extra", {}))

        config = build_daily_bundle_config(algorithm_params)
        output_dir = Path(output_spec_extra.get("output_dir", ctx.workspace / "products" / "timeseries_bundle"))
        output_dir.mkdir(parents=True, exist_ok=True)

        lin_pix = load_lin_pix_selection(
            lin_pix=algorithm_params.get("lin_pix"),
            lin_pix_mat=datasource_selection.get("lin_pix_mat"),
            variable_name=str(algorithm_params.get("lin_pix_varname", "lin_pix")),
        )

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start(
                "timeseries_bundle",
                f"Build time-series bundle from {ctx.request.time_range.start:%Y%m%d} to {ctx.request.time_range.end:%Y%m%d}",
            )

        bundle = build_timeseries_bundle_from_range(
            ctx.request.time_range.start,
            ctx.request.time_range.end,
            config,
            datasource_selection,
            lin_pix=lin_pix,
        )
        start_key = ctx.request.time_range.start.strftime("%Y%m%d")
        end_key = ctx.request.time_range.end.strftime("%Y%m%d")
        output_path = output_dir / f"timeseries_bundle_{start_key}_{end_key}.mat"
        payload = dict(bundle.data)
        payload["date_keys"] = bundle.date_keys
        payload["missing_dates"] = bundle.missing_dates
        payload["pixel_count"] = bundle.pixel_count
        savemat(output_path, payload, do_compression=True)

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_artifact("timeseries_bundle", str(output_path), "timeseries_bundle_mat")
            ctx.logger_adapter.emit_stage_end(
                "timeseries_bundle",
                f"Generated bundle with {len(bundle.date_keys)} days and {bundle.pixel_count} pixels",
            )

        main_layers = ["TBv_mat", "TBh_mat", "IA_mat", "Ts_mat", "SMref_mat", "NDVI_mat", "SF_mat", "vwc_mat"]
        if str(config.temp_scheme).upper() == "DUAL":
            main_layers.extend(["TC_mat", "Tsoil1_mat", "Tsoil2_mat", "Ct_mat", "TG_mat"])
            if config.save_match_info:
                main_layers.extend(
                    [
                        "match_slot_index_mat",
                        "match_day_offset_mat",
                        "match_picked_file_mat",
                        "match_picked_utc_mat",
                    ]
                )

        manifest = ProductManifest(
            job_id=ctx.request.job_id,
            run_id=ctx.runtime_context.run_id,
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
                "module_name": self.name,
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
        outputs = _store_manifest(ctx, module_name=self.name, manifest=manifest, metadata={"pixel_count": bundle.pixel_count})
        outputs["output_path"] = str(output_path)
        outputs["missing_dates"] = list(bundle.missing_dates)
        outputs["pixel_count"] = bundle.pixel_count
        return outputs
