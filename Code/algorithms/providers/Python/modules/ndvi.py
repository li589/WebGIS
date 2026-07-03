from __future__ import annotations

from pathlib import Path

from algorithms.ndvi import build_ndvi_quality_metrics, merge_ndvi_quality_metrics, process_ndvi_stack_to_daily
from contracts.product import ProductManifest
from data_access import resolve_prepared_local_directory
from ingest.ndvi import load_ndvi_stack
from modules.base import BaseModule
from modules.registry import register_module
from output import OutputCoordinator
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


def _extract_region_bounds(region, stack_shape: tuple) -> tuple[float, float, float, float] | None:
    """
    从 RegionSpec 中提取地理边界（west, south, east, north）。

    无 region 时返回中国区域默认值（73E-135E, 18N-53N）。
    """
    if region is None:
        return (73.0, 18.0, 135.0, 53.0)

    kind = getattr(region, "kind", None)
    value = getattr(region, "value", None)

    if kind == "bbox":
        bbox = value.get("bbox") if value else None
        if bbox is None and value:
            bbox = (value.get("west"), value.get("south"), value.get("east"), value.get("north"))
        if bbox and len(bbox) == 4:
            return tuple(float(c) for c in bbox)

    if kind == "aoi":
        # AOI: 从 geometry bounds 提取
        geom = value.get("geometry") or value.get("coordinates")
        if geom:
            coords = geom.get("coordinates", geom) if isinstance(geom, dict) else geom
            return _bounds_from_geojson_coords(coords)

    return (73.0, 18.0, 135.0, 53.0)


def _bounds_from_geojson_coords(coords) -> tuple[float, float, float, float]:
    """从 GeoJSON 坐标计算边界"""
    def _flatten(lst):
        for item in lst:
            if isinstance(item, (list, tuple)) and isinstance(item[0], (int, float)):
                yield item
            else:
                yield from _flatten(item)
    pts = list(_flatten(coords))
    if not pts:
        return (73.0, 18.0, 135.0, 53.0)
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    return (min(lons), min(lats), max(lons), max(lats))


def _build_transform_from_bounds(
    bounds: tuple[float, float, float, float] | None,
    stack_shape: tuple,
) -> tuple:
    """
    根据边界和数组 shape 构建 rasterio.Affine 变换对象和 CRS。

    返回：(transform, crs)
    """
    try:
        from rasterio.transform import from_bounds
    except ImportError:
        return (None, None)

    height, width = stack_shape[:2]
    if bounds is None:
        bounds = (73.0, 18.0, 135.0, 53.0)
    west, south, east, north = bounds

    transform = from_bounds(west, south, east, north, width, height)

    try:
        import rasterio
        crs = rasterio.crs.CRS.from_epsg(4326)
    except ImportError:
        crs = None

    return (transform, crs)


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


class NdviDailyModule(BaseModule):
    name = "ndvi_daily"
    description = "Native module that converts 16-day NDVI rasters to daily MAT products."
    input_ports = [
        PortSpec(name="datasource_selection", kind="config", data_class="dict", required=False),
        PortSpec(name="algorithm_params", kind="config", data_class="dict", required=False),
        PortSpec(name="output_spec_extra", kind="config", data_class="dict", required=False),
    ]
    output_ports = [PortSpec(name="manifest", kind="artifact", data_class="product_manifest")]

    def execute(self, inputs: dict[str, object], params: dict[str, object], ctx: NodeExecutionContext) -> dict[str, object]:
        from scipy.io import savemat

        datasource_selection = dict(inputs.get("datasource_selection", {}))
        algorithm_params = dict(inputs.get("algorithm_params", {}))
        output_spec_extra = dict(inputs.get("output_spec_extra", {}))

        input_dir = _resolve_ndvi_input_dir(datasource_selection)
        output_dir = Path(output_spec_extra.get("output_dir", ctx.workspace / "products" / "ndvi_daily"))
        output_dir.mkdir(parents=True, exist_ok=True)
        emit_quality_products = bool(algorithm_params.get("emit_quality_products", True))
        ndvi_clim_dir_value = _resolve_ndvi_climatology_dir(datasource_selection)
        quality_dir = Path(output_spec_extra.get("quality_output_dir", output_dir.parent / "ndvi_quality"))
        quality_dir.mkdir(parents=True, exist_ok=True)

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start("ndvi_daily", f"Build daily NDVI from {input_dir}")

        ndvi_stack, observation_dates = load_ndvi_stack(
            input_dir=input_dir,
            start_time=ctx.request.time_range.start,
            end_time=ctx.request.time_range.end,
        )
        daily_stack, daily_dates = process_ndvi_stack_to_daily(
            ndvi_stack=ndvi_stack,
            observation_dates=observation_dates,
            start_time=ctx.request.time_range.start,
            end_time=ctx.request.time_range.end,
            sg_step_days=int(algorithm_params.get("sg_step_days", 8)),
            daily_step_days=int(algorithm_params.get("daily_step_days", 1)),
            gap_threshold_days=int(algorithm_params.get("gap_threshold_days", 30)),
            sg_polyorder=int(algorithm_params.get("sg_polyorder", 6)),
            sg_window_length=int(algorithm_params.get("sg_window_length", 9)),
        )

        # 从 region 提取地理范围，无 region 时使用中国区域默认值
        region_bounds = _extract_region_bounds(ctx.request.region, daily_stack.shape)
        transform, crs = _build_transform_from_bounds(region_bounds, daily_stack.shape)

        # 初始化输出协调器
        coordinator = OutputCoordinator(
            job_id=ctx.request.job_id,
            output_dir=output_dir,
            module_name=self.name,
            workflow_name=ctx.request.workflow_name or "",
            time_range={
                "start": ctx.request.time_range.start.isoformat(),
                "end": ctx.request.time_range.end.isoformat(),
            },
            region={"bounds": region_bounds} if region_bounds else None,
            crs="EPSG:4326",
            pixel_resolution=abs(transform.a) if transform else 0.01,
            preview_cmap="viridis",
            preview_size=(512, 512),
            compress="deflate",
            overwrite=True,
        )

        # 写出每日 NDVI 产物：MAT（保留） + COG + preview PNG + manifest 条目
        for index, current_date in enumerate(daily_dates):
            mat_path = output_dir / f"{current_date:%Y%m%d}.mat"
            savemat(mat_path, {"NDVI": daily_stack[:, :, index]}, do_compression=True)

            daily_data = daily_stack[:, :, index]
            name = f"ndvi_{current_date:%Y%m%d}"
            coordinator.write_raster(
                name=name,
                data=daily_data,
                transform=transform,
                nodata=-9999.0,
                unit="NDVI",
                description=f"VIIRS NDVI 日值 {current_date:%Y-%m-%d}",
                var_name="NDVI",
                generate_preview=True,
            )
            coordinator.add_mat(
                name=mat_path.stem,
                path=mat_path,
                variable="NDVI",
                description="VIIRS NDVI 日值 MATLAB 格式",
            )
            if ctx.logger_adapter is not None:
                ctx.logger_adapter.emit_artifact("ndvi_daily", str(mat_path), "daily_ndvi_mat")

        # 写出质量评价产物
        quality_product_count = 0
        if emit_quality_products:
            climatology_stack = None
            if ndvi_clim_dir_value is not None:
                climatology_stack = _load_daily_climatology_stack(ndvi_clim_dir_value, daily_dates)
            yearly_metrics_by_year = _build_yearly_quality_metrics(daily_stack, daily_dates, climatology_stack)
            yearly_metrics_only = [metrics for _, metrics in yearly_metrics_by_year]

            for year_label, yearly_metrics in yearly_metrics_by_year:
                yearly_path = quality_dir / f"VI_viirs_{year_label}.mat"
                savemat(yearly_path, yearly_metrics, do_compression=True)
                coordinator.add_mat(
                    name=yearly_path.stem,
                    path=yearly_path,
                    variable="NDVI_v_mean,NDVI_v_max,NDVI_v_min,NDVI_v_diff_mean,NDVI_v_diff_std,NDVI_v_range,NDVI_v_od,NDVI_v_vali",
                    description=f"NDVI 年质量统计 {year_label} 年",
                )
                quality_product_count += 1

            merged_metrics = merge_ndvi_quality_metrics(yearly_metrics_only)
            merged_path = quality_dir / "VI_v_qa.mat"
            savemat(merged_path, merged_metrics, do_compression=True)
            coordinator.add_mat(
                name=merged_path.stem,
                path=merged_path,
                variable="NDVI_v_mean,NDVI_v_max,NDVI_v_min,NDVI_v_diff_mean,NDVI_v_diff_std,NDVI_v_range,NDVI_v_od,NDVI_v_vali",
                description="NDVI 多年质量统计汇总",
            )
            quality_product_count += 1

            if ctx.logger_adapter is not None:
                ctx.logger_adapter.emit_artifact("ndvi_daily", str(merged_path), "ndvi_multi_year_qa_mat")

        # 添加诊断信息
        coordinator.add_diagnostic("daily_count", len(daily_dates))
        coordinator.add_diagnostic("stack_shape", list(daily_stack.shape))
        coordinator.add_diagnostic("input_dir", str(input_dir))
        coordinator.add_diagnostic("algorithm_params", algorithm_params)

        # 构建并写出 manifest.json
        manifest_dict = coordinator.build_manifest(extra={
            "module_name": self.name,
            "output_dir": str(output_dir),
            "quality_output_dir": str(quality_dir) if emit_quality_products else None,
            "region_bounds": region_bounds,
        })

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_end(
                "ndvi_daily",
                f"Generated {len(daily_dates)} daily NDVI + {quality_product_count} quality products"
                f" → {manifest_dict.get('manifest_path', output_dir / 'manifest.json')}",
            )

        manifest = ProductManifest(
            job_id=ctx.request.job_id,
            run_id=ctx.runtime_context.run_id,
            products=[],
            main_layers=["NDVI"],
            metadata_uri=manifest_dict.get("manifest_uri"),
            extra={
                "module_name": self.name,
                "output_dir": str(output_dir),
                "count": len(daily_dates),
                "emit_quality_products": emit_quality_products,
                "quality_output_dir": str(quality_dir) if emit_quality_products else None,
                "manifest_path": manifest_dict.get("manifest_path", ""),
                "product_count": len(daily_dates) + quality_product_count,
            },
        )
        return _store_manifest(
            ctx,
            module_name=self.name,
            manifest=manifest,
            metadata={
                "product_count": len(daily_dates),
                "quality_product_count": quality_product_count,
                "manifest_path": manifest_dict.get("manifest_path", ""),
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


def _build_yearly_quality_metrics(
    daily_stack: object,
    daily_dates: list,
    climatology_stack: object | None,
) -> list[tuple[str, dict[str, object]]]:
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


def register_default_ndvi_modules() -> None:
    register_module(NdviDailyModule(), aliases=["ndvi_daily_pipeline"])


register_default_ndvi_modules()
