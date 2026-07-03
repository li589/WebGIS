from __future__ import annotations

from pathlib import Path

from algorithms.ndvi import build_ndvi_quality_metrics, merge_ndvi_quality_metrics, process_ndvi_stack_to_daily
from contracts.job import JobRequest
from contracts.product import ProductManifest, ProductRef
from contracts.runtime import RuntimeContext
from data_access import resolve_prepared_local_directory
from ingest.ndvi import load_ndvi_stack
from pipelines.base import BasePipeline, PipelinePlan


def _resolve_ndvi_input_dir(datasource_selection: dict[str, object]) -> Path:
    prepared_dir = resolve_prepared_local_directory(datasource_selection, ("NDVI_16DAY_RASTER",))
    if prepared_dir is not None:
        return prepared_dir
    input_dir = datasource_selection.get("input_dir")
    if input_dir is None:
        raise KeyError("input_dir")
    return Path(str(input_dir))


def _resolve_ndvi_climatology_dir(datasource_selection: dict[str, object]) -> str | None:
    prepared_dir = resolve_prepared_local_directory(
        datasource_selection,
        ("ndvi_clim_dir", "ndvi_clim_folder", "NDVI_DAILY_CLIM", "NDVI_CLIM_DAILY"),
    )
    if prepared_dir is not None:
        return str(prepared_dir)
    ndvi_clim_dir_value = datasource_selection.get("ndvi_clim_dir") or datasource_selection.get("ndvi_clim_folder")
    if ndvi_clim_dir_value is None:
        return None
    return str(ndvi_clim_dir_value)


class NdviDailyPipeline(BasePipeline):
    name = "ndvi_daily_pipeline"

    def plan(self, request: JobRequest, ctx: RuntimeContext) -> PipelinePlan:
        estimated_outputs = ["daily_ndvi_mat"]
        if bool(request.algorithm_params.get("emit_quality_products", True)):
            estimated_outputs.extend(["ndvi_yearly_qa_mat", "ndvi_multi_year_qa_mat"])
        return PipelinePlan(
            required_datasets=["NDVI_16DAY_RASTER"],
            required_variables=["NDVI"],
            estimated_outputs=estimated_outputs,
            parallelizable=True,
            chunk_strategy="pixel_timeseries",
            cache_requirement="partial",
        )

    def execute(self, request: JobRequest, ctx: RuntimeContext) -> ProductManifest:
        from scipy.io import savemat

        input_dir = _resolve_ndvi_input_dir(request.datasource_selection)
        output_dir = Path(request.output_spec.extra.get("output_dir", ctx.workspace / "products" / "ndvi_daily"))
        output_dir.mkdir(parents=True, exist_ok=True)
        emit_quality_products = bool(request.algorithm_params.get("emit_quality_products", True))
        ndvi_clim_dir_value = _resolve_ndvi_climatology_dir(request.datasource_selection)
        quality_dir = Path(request.output_spec.extra.get("quality_output_dir", output_dir.parent / "ndvi_quality"))
        quality_dir.mkdir(parents=True, exist_ok=True)

        if self.logger_adapter is not None:
            self.logger_adapter.emit_stage_start("ndvi_daily", f"Build daily NDVI from {input_dir}")

        ndvi_stack, observation_dates = load_ndvi_stack(
            input_dir=input_dir,
            start_time=request.time_range.start,
            end_time=request.time_range.end,
        )
        daily_stack, daily_dates = process_ndvi_stack_to_daily(
            ndvi_stack=ndvi_stack,
            observation_dates=observation_dates,
            start_time=request.time_range.start,
            end_time=request.time_range.end,
            sg_step_days=int(request.algorithm_params.get("sg_step_days", 8)),
            daily_step_days=int(request.algorithm_params.get("daily_step_days", 1)),
            gap_threshold_days=int(request.algorithm_params.get("gap_threshold_days", 30)),
            sg_polyorder=int(request.algorithm_params.get("sg_polyorder", 6)),
            sg_window_length=int(request.algorithm_params.get("sg_window_length", 9)),
        )

        product_refs: list[ProductRef] = []
        for index, current_date in enumerate(daily_dates):
            output_path = output_dir / f"{current_date:%Y%m%d}.mat"
            savemat(output_path, {"NDVI": daily_stack[:, :, index]}, do_compression=True)
            product_refs.append(
                ProductRef(
                    name=output_path.stem,
                    type="daily_ndvi_mat",
                    uri=str(output_path),
                    variable="NDVI",
                    tags={"date_key": output_path.stem},
                )
            )
            if self.logger_adapter is not None:
                self.logger_adapter.emit_artifact("ndvi_daily", str(output_path), "daily_ndvi_mat")

        quality_product_refs: list[ProductRef] = []
        if emit_quality_products:
            climatology_stack = None
            if ndvi_clim_dir_value is not None:
                climatology_stack = _load_daily_climatology_stack(ndvi_clim_dir_value, daily_dates)
            yearly_metrics_by_year = _build_yearly_quality_metrics(daily_stack, daily_dates, climatology_stack)
            yearly_metrics_only = [metrics for _, metrics in yearly_metrics_by_year]
            for year_label, yearly_metrics in yearly_metrics_by_year:
                yearly_path = quality_dir / f"VI_viirs_{year_label}.mat"
                savemat(yearly_path, yearly_metrics, do_compression=True)
                quality_product_refs.append(
                    ProductRef(
                        name=yearly_path.stem,
                        type="ndvi_yearly_qa_mat",
                        uri=str(yearly_path),
                        variable="NDVI_v_mean,NDVI_v_max,NDVI_v_min,NDVI_v_diff_mean,NDVI_v_diff_std,NDVI_v_range,NDVI_v_od,NDVI_v_vali",
                        tags={"year": year_label},
                    )
                )
            merged_metrics = merge_ndvi_quality_metrics(yearly_metrics_only)
            merged_path = quality_dir / "VI_v_qa.mat"
            savemat(merged_path, merged_metrics, do_compression=True)
            quality_product_refs.append(
                ProductRef(
                    name=merged_path.stem,
                    type="ndvi_multi_year_qa_mat",
                    uri=str(merged_path),
                    variable="NDVI_v_mean,NDVI_v_max,NDVI_v_min,NDVI_v_diff_mean,NDVI_v_diff_std,NDVI_v_range,NDVI_v_od,NDVI_v_vali",
                    tags={"aggregation": "multi_year"},
                )
            )
            if self.logger_adapter is not None:
                for product in quality_product_refs:
                    self.logger_adapter.emit_artifact("ndvi_daily", product.uri, product.type)

        if self.logger_adapter is not None:
            self.logger_adapter.emit_stage_end(
                "ndvi_daily",
                f"Generated {len(product_refs)} daily NDVI files"
                + (f" and {len(quality_product_refs)} quality products" if quality_product_refs else ""),
            )

        return ProductManifest(
            job_id=request.job_id,
            run_id=ctx.run_id,
            products=[*product_refs, *quality_product_refs],
            main_layers=["NDVI"],
            metadata_uri=None,
            extra={
                "pipeline_name": self.name,
                "output_dir": str(output_dir),
                "count": len(product_refs),
                "emit_quality_products": emit_quality_products,
                "quality_output_dir": str(quality_dir) if emit_quality_products else None,
            },
        )


def _load_daily_climatology_stack(input_dir: str | Path, daily_dates: list) -> object:
    import numpy as np
    from scipy.io import loadmat

    input_dir = Path(input_dir)
    stacks: list[np.ndarray] = []
    for current_date in daily_dates:
        doy = current_date.timetuple().tm_yday
        payload = loadmat(input_dir / f"{doy}.mat")
        if "NDVI_clim" not in payload:
            raise KeyError(f"NDVI climatology file missing NDVI_clim: {input_dir / f'{doy}.mat'}")
        stacks.append(np.asarray(payload["NDVI_clim"], dtype=np.float64))
    return np.stack(stacks, axis=2)


def _build_yearly_quality_metrics(daily_stack: object, daily_dates: list, climatology_stack: object | None) -> list[tuple[str, dict[str, object]]]:
    import numpy as np

    years: list[int] = []
    for current_date in daily_dates:
        if current_date.year not in years:
            years.append(current_date.year)

    metrics_by_year: list[tuple[str, dict[str, object]]] = []
    for year in years:
        indices = [index for index, current_date in enumerate(daily_dates) if current_date.year == year]
        year_stack = np.asarray(daily_stack[:, :, indices], dtype=np.float64)
        year_climatology = None
        if climatology_stack is not None:
            year_climatology = np.asarray(climatology_stack[:, :, indices], dtype=np.float64)
        metrics_by_year.append((str(year), build_ndvi_quality_metrics(year_stack, year_climatology)))
    return metrics_by_year
