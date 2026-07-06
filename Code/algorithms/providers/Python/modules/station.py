from __future__ import annotations

from datetime import datetime
from pathlib import Path

from algorithms.station import (
    aggregate_station_records_daily,
    build_station_validation_outputs,
    filter_station_records,
    station_records_to_rows,
)
from contracts.product import ProductManifest
from data_access import resolve_prepared_local_directory, resolve_prepared_local_path
from ingest.mat_bundle import load_mat_file
from ingest.station import (
    StationRecord,
    discover_casmos_txt_files,
    discover_ismn_stm_files,
    load_casmos_site_info,
    parse_casmos_txt_file,
    parse_ismn_stm_file,
)
from modules.base import BaseModule
from modules.registry import register_module_decorator
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


_STATION_PREPARED_DATASET_MAP: dict[str, tuple[str, ...]] = {
    "input_dir": ("ISMN_STM_OR_CASMOS_TXT", "input_dir"),
    "site_info_csv": ("site_info_csv",),
    "smap_grid_mat": ("smap_grid_mat",),
    "landcover_mat": ("landcover_mat",),
    "climate_mat": ("climate_mat",),
    "network_map_csv": ("network_map_csv",),
}


def _resolve_station_datasource_selection(datasource_selection: dict[str, object]) -> dict[str, object]:
    resolved = dict(datasource_selection)
    input_dir = resolve_prepared_local_directory(resolved, _STATION_PREPARED_DATASET_MAP["input_dir"])
    if input_dir is not None:
        resolved["input_dir"] = str(input_dir)
    for key in ("site_info_csv", "smap_grid_mat", "landcover_mat", "climate_mat", "network_map_csv"):
        local_path = resolve_prepared_local_path(resolved, _STATION_PREPARED_DATASET_MAP[key])
        if local_path is not None:
            resolved[key] = str(local_path)
    return resolved


@register_module_decorator(name="station_daily", aliases=["station_daily_pipeline"])
class StationDailyModule(BaseModule):
    name = "station_daily"
    description = "Native module that builds station daily/am6 products and validation artifacts."
    input_ports = [
        PortSpec(name="datasource_selection", kind="config", data_class="dict", required=False),
        PortSpec(name="algorithm_params", kind="config", data_class="dict", required=False),
        PortSpec(name="output_spec_extra", kind="config", data_class="dict", required=False),
    ]
    output_ports = [PortSpec(name="manifest", kind="artifact", data_class="product_manifest")]

    def execute(self, inputs: dict[str, object], params: dict[str, object], ctx: NodeExecutionContext) -> dict[str, object]:
        from scipy.io import savemat

        _ = params
        datasource_selection = _resolve_station_datasource_selection(dict(inputs.get("datasource_selection", {})))
        algorithm_params = dict(inputs.get("algorithm_params", {}))
        output_spec_extra = dict(inputs.get("output_spec_extra", {}))

        source_type = str(algorithm_params.get("source_type", "ISMN")).upper()
        input_dir = Path(datasource_selection["input_dir"])
        output_dir = Path(output_spec_extra.get("output_dir", ctx.workspace / "products" / "station_daily"))
        output_dir.mkdir(parents=True, exist_ok=True)
        emit_validation_products = bool(algorithm_params.get("emit_validation_products", True))
        validation_start = _coerce_datetime(algorithm_params.get("validation_start", ctx.request.time_range.start))
        validation_end = _coerce_datetime(algorithm_params.get("validation_end", ctx.request.time_range.end))
        min_valid_days = int(algorithm_params.get("validation_min_valid_days", 30))
        validation_hour = int(algorithm_params.get("validation_hour", 6))
        max_depth_cm = float(
            algorithm_params.get(
                "validation_max_depth_cm",
                5.1 if source_type == "ISMN" else 11.0,
            )
        )
        min_sm = float(algorithm_params.get("validation_min_sm", 0.001))
        max_sm = float(algorithm_params.get("validation_max_sm", 0.601))
        validation_records_by_site: dict[str, list] = {}

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start("station_daily", f"Process {source_type} station records from {input_dir}")

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
            crs="EPSG:4326",
            overwrite=True,
            storage_backend=ctx.runtime_context.storage_backend,
        )

        if source_type == "ISMN":
            input_files = discover_ismn_stm_files(input_dir)
            for file_path in input_files:
                records = parse_ismn_stm_file(file_path)
                daily_records = aggregate_station_records_daily(
                    filter_station_records(
                        records,
                        start_time=validation_start,
                        end_time=validation_end,
                        max_depth_cm=max_depth_cm,
                        min_sm=min_sm,
                        max_sm=max_sm,
                        require_good_quality=True,
                    )
                )
                am6_records = aggregate_station_records_daily(
                    filter_station_records(
                        records,
                        start_time=validation_start,
                        end_time=validation_end,
                        max_depth_cm=max_depth_cm,
                        min_sm=min_sm,
                        max_sm=max_sm,
                        require_good_quality=True,
                        hour_filter=validation_hour,
                    )
                )
                validation_records_by_site[file_path.stem] = am6_records or daily_records
                if not daily_records and not am6_records:
                    continue
                site_output = output_dir / file_path.stem
                site_output.mkdir(parents=True, exist_ok=True)

                if daily_records:
                    daily_path = site_output / "daily.mat"
                    savemat(daily_path, {"ismn": station_records_to_rows(daily_records)}, do_compression=True)
                    coordinator.add_mat(
                        name=f"{file_path.stem}_daily",
                        path=daily_path,
                        variable="soil_moisture",
                        description="ISMN 站点日均土壤水分 MATLAB 格式",
                    )
                    # 写出 Parquet 表格（前端可消费）
                    df = _station_records_to_dataframe(daily_records, source_type="ISMN")
                    coordinator.write_table(
                        name=f"{file_path.stem}_daily",
                        df=df,
                        description="ISMN 站点日均土壤水分表格",
                    )
                    if ctx.logger_adapter is not None:
                        ctx.logger_adapter.emit_artifact("station_daily", str(daily_path), "station_daily_mat")

                if am6_records:
                    am6_path = site_output / "am6.mat"
                    savemat(am6_path, {"ismn": station_records_to_rows(am6_records)}, do_compression=True)
                    coordinator.add_mat(
                        name=f"{file_path.stem}_am6",
                        path=am6_path,
                        variable="soil_moisture",
                        description="ISMN 站点 6AM 土壤水分 MATLAB 格式",
                    )
                    df = _station_records_to_dataframe(am6_records, source_type="ISMN")
                    coordinator.write_table(
                        name=f"{file_path.stem}_am6",
                        df=df,
                        description="ISMN 站点 6AM 土壤水分表格",
                    )

        elif source_type == "CASMOS":
            site_info_path = datasource_selection.get("site_info_csv")
            site_info = load_casmos_site_info(site_info_path) if site_info_path else {}
            input_files = discover_casmos_txt_files(input_dir)
            for file_path in input_files:
                records = parse_casmos_txt_file(file_path, site_info=site_info)
                daily_records = aggregate_station_records_daily(
                    filter_station_records(
                        records,
                        start_time=validation_start,
                        end_time=validation_end,
                        max_depth_cm=max_depth_cm,
                        min_sm=min_sm,
                        max_sm=max_sm,
                        require_good_quality=False,
                    )
                )
                am6_records = aggregate_station_records_daily(
                    filter_station_records(
                        records,
                        start_time=validation_start,
                        end_time=validation_end,
                        max_depth_cm=max_depth_cm,
                        min_sm=min_sm,
                        max_sm=max_sm,
                        require_good_quality=False,
                        hour_filter=validation_hour,
                    )
                )
                validation_records_by_site[file_path.stem] = am6_records or daily_records
                if not daily_records and not am6_records:
                    continue
                site_output = output_dir / file_path.stem
                site_output.mkdir(parents=True, exist_ok=True)

                if daily_records:
                    daily_path = site_output / "daily.mat"
                    savemat(daily_path, {"china_10cm": station_records_to_rows(daily_records)}, do_compression=True)
                    coordinator.add_mat(
                        name=f"{file_path.stem}_daily",
                        path=daily_path,
                        variable="soil_moisture",
                        description="CASMOS 站点日均土壤水分 MATLAB 格式",
                    )
                    df = _station_records_to_dataframe(daily_records, source_type="CASMOS")
                    coordinator.write_table(
                        name=f"{file_path.stem}_daily",
                        df=df,
                        description="CASMOS 站点日均土壤水分表格",
                    )
                    if ctx.logger_adapter is not None:
                        ctx.logger_adapter.emit_artifact("station_daily", str(daily_path), "station_daily_mat")

                if am6_records:
                    am6_path = site_output / "am6.mat"
                    savemat(am6_path, {"china_10cm": station_records_to_rows(am6_records)}, do_compression=True)
                    coordinator.add_mat(
                        name=f"{file_path.stem}_am6",
                        path=am6_path,
                        variable="soil_moisture",
                        description="CASMOS 站点 6AM 土壤水分 MATLAB 格式",
                    )
                    df = _station_records_to_dataframe(am6_records, source_type="CASMOS")
                    coordinator.write_table(
                        name=f"{file_path.stem}_am6",
                        df=df,
                        description="CASMOS 站点 6AM 土壤水分表格",
                    )
        else:
            raise ValueError(f"Unsupported station source_type: {source_type}")

        validation_refs = _write_validation_products(
            datasource_selection=datasource_selection,
            algorithm_params=algorithm_params,
            output_dir=output_dir,
            source_type=source_type,
            records_by_site=validation_records_by_site,
            validation_start=validation_start,
            validation_end=validation_end,
            min_valid_days=min_valid_days,
            enabled=emit_validation_products,
            coordinator=coordinator,
        )

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_end(
                "station_daily",
                f"Generated station products → {output_dir}",
            )

        # 添加诊断信息
        coordinator.add_diagnostic("source_type", source_type)
        coordinator.add_diagnostic("input_dir", str(input_dir))
        coordinator.add_diagnostic("site_count", len(validation_records_by_site))
        coordinator.add_diagnostic("validation_start", validation_start.strftime("%Y%m%d"))
        coordinator.add_diagnostic("validation_end", validation_end.strftime("%Y%m%d"))
        coordinator.add_diagnostic("algorithm_params", algorithm_params)

        # 构建并写出 manifest.json
        manifest_dict = coordinator.build_manifest(extra={
            "module_name": self.name,
            "source_type": source_type,
            "output_dir": str(output_dir),
            "emit_validation_products": emit_validation_products,
            "validation_start": validation_start.strftime("%Y%m%d"),
            "validation_end": validation_end.strftime("%Y%m%d"),
            "validation_hour": validation_hour,
            "validation_max_depth_cm": max_depth_cm,
        })

        manifest = ProductManifest(
            job_id=ctx.request.job_id,
            run_id=ctx.runtime_context.run_id,
            products=[],
            main_layers=["soil_moisture"],
            metadata_uri=manifest_dict.get("manifest_uri"),
            extra={
                "module_name": self.name,
                "source_type": source_type,
                "output_dir": str(output_dir),
                "count": coordinator.product_count,
                "emit_validation_products": emit_validation_products,
                "manifest_path": manifest_dict.get("manifest_path", ""),
            },
        )
        return _store_manifest(
            ctx,
            module_name=self.name,
            manifest=manifest,
            metadata={
                "product_count": coordinator.product_count,
                "manifest_path": manifest_dict.get("manifest_path", ""),
            },
        )

def _station_records_to_dataframe(records: list[StationRecord], source_type: str = "ISMN") -> "pd.DataFrame":
    """
    将 StationRecord 列表转换为 pandas DataFrame（用于 Parquet 写出）。

    前端图表可直接消费此格式。
    """
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas is required for table output. Install: pip install pandas pyarrow")

    rows = []
    for record in records:
        rows.append(
            {
                "year": record.year,
                "month": record.month,
                "day": record.day,
                "hour": record.hour,
                "date": f"{record.year:04d}-{record.month:02d}-{record.day:02d}",
                "lat": record.lat,
                "lon": record.lon,
                "elev": record.elev,
                "depth_upper_cm": round(record.depth_upper * 100, 2),
                "depth_lower_cm": round(record.depth_lower * 100, 2),
                "soil_moisture": record.soil_moisture,
                "quality_flag": record.quality_flag,
                "site_id": record.site_id,
                "source": record.source or source_type,
            }
        )
    return pd.DataFrame(rows)


def _write_validation_products(
    *,
    datasource_selection: dict[str, object],
    algorithm_params: dict[str, object],
    output_dir: Path,
    source_type: str,
    records_by_site: dict[str, list[StationRecord]],
    validation_start: datetime,
    validation_end: datetime,
    min_valid_days: int,
    enabled: bool,
    coordinator: OutputCoordinator,
) -> dict[str, object]:
    from scipy.io import savemat

    if not enabled or not records_by_site:
        return {}
    ancillary_path = datasource_selection.get("smap_grid_mat")
    if ancillary_path is None:
        return {}

    smap_payload = load_mat_file(ancillary_path)
    smap_lat = _pick_first_available(smap_payload, _alias_list(algorithm_params, "smap_lat_aliases", ["lat_smap", "lat", "lat_9km"]))
    smap_lon = _pick_first_available(smap_payload, _alias_list(algorithm_params, "smap_lon_aliases", ["lon_smap", "lon", "lon_9km"]))

    landcover_grid = landcover_lat = landcover_lon = None
    landcover_mat = datasource_selection.get("landcover_mat")
    if landcover_mat is not None:
        payload = load_mat_file(landcover_mat)
        landcover_grid = _pick_first_available(payload, _alias_list(algorithm_params, "landcover_aliases", ["IGBP_9km_12", "LC"]), required=False)
        landcover_lat = _pick_first_available(payload, _alias_list(algorithm_params, "landcover_lat_aliases", ["lat_9km", "lat"]), required=False)
        landcover_lon = _pick_first_available(payload, _alias_list(algorithm_params, "landcover_lon_aliases", ["lon_9km", "lon"]), required=False)

    climate_grid = climate_lat = climate_lon = None
    climate_mat = datasource_selection.get("climate_mat")
    if climate_mat is not None:
        payload = load_mat_file(climate_mat)
        climate_grid = _pick_first_available(payload, _alias_list(algorithm_params, "climate_aliases", ["Koppen_present_083", "Koppen", "climate"]), required=False)
        climate_lat = _pick_first_available(payload, _alias_list(algorithm_params, "climate_lat_aliases", ["lat_kop", "lat"]), required=False)
        climate_lon = _pick_first_available(payload, _alias_list(algorithm_params, "climate_lon_aliases", ["lon_kop", "lon"]), required=False)

    smap_landcover_grid = _pick_first_available(
        smap_payload,
        _alias_list(algorithm_params, "smap_landcover_aliases", ["IGBP_9km_12", "lc_smap", "site_lc_smap"]),
        required=False,
    )
    network_map = None
    network_map_csv = datasource_selection.get("network_map_csv")
    if network_map_csv is not None:
        network_map = _load_network_map(network_map_csv)

    validation_payload = build_station_validation_outputs(
        records_by_site,
        validation_start,
        validation_end,
        smap_lat=smap_lat,
        smap_lon=smap_lon,
        min_valid_days=min_valid_days,
        landcover_grid=landcover_grid,
        landcover_lat=landcover_lat,
        landcover_lon=landcover_lon,
        climate_grid=climate_grid,
        climate_lat=climate_lat,
        climate_lon=climate_lon,
        smap_landcover_grid=smap_landcover_grid,
        network_map=network_map,
    )
    if not validation_payload:
        return {}

    prefix = "ismn" if source_type == "ISMN" else "china"
    for payload_name, payload in validation_payload.items():
        output_path = output_dir / f"{prefix}_{payload_name}.mat"
        savemat(output_path, payload, do_compression=True)
        coordinator.add_mat(
            name=f"{prefix}_{payload_name}",
            path=output_path,
            variable=payload_name,
            description=f"站点{payload_name}验证 MATLAB 格式",
        )

    return {}


def _alias_list(params: dict[str, object], key: str, default_aliases: list[str]) -> list[str]:
    value = params.get(key)
    if value is None:
        return list(default_aliases)
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(item) for item in value]


def _pick_first_available(payload: dict, aliases: list[str], *, required: bool = True):
    for alias in aliases:
        if alias in payload:
            return payload[alias]
    if required:
        raise KeyError(f"Missing aliases: {aliases}")
    return None


def _load_network_map(csv_path: str | Path) -> dict[str, str]:
    import csv

    mapping: dict[str, str] = {}
    with Path(csv_path).open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            site_id = str(row.get("site_id", "")).strip()
            network_id = str(row.get("network_id", "")).strip()
            if site_id:
                mapping[site_id] = network_id
    return mapping


def _coerce_datetime(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    raise ValueError(f"Unsupported datetime value: {value!r}")
