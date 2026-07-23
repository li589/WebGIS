from __future__ import annotations

from datetime import datetime
from pathlib import Path

from algorithms.station import (
    aggregate_station_records_daily,
    build_station_validation_outputs,
    filter_station_records,
    station_records_to_rows,
)
from contracts.job import JobRequest
from contracts.product import ProductManifest, ProductRef
from contracts.runtime import RuntimeContext
from data_access import resolve_prepared_local_directory, resolve_prepared_local_path
from ingest.mat_bundle import load_mat_file
from ingest.station import (
    discover_casmos_txt_files,
    discover_ismn_stm_files,
    load_casmos_site_info,
    parse_casmos_txt_file,
    parse_ismn_stm_file,
)
from pipelines.base import BasePipeline, PipelinePlan


_STATION_PREPARED_DATASET_MAP: dict[str, tuple[str, ...]] = {
    "input_dir": ("ISMN_STM_OR_CASMOS_TXT", "input_dir"),
    "site_info_csv": ("site_info_csv",),
    "smap_grid_mat": ("smap_grid_mat",),
    "landcover_mat": ("landcover_mat",),
    "climate_mat": ("climate_mat",),
    "network_map_csv": ("network_map_csv",),
}


def _resolve_station_datasource_selection(
    datasource_selection: dict[str, object],
) -> dict[str, object]:
    resolved = dict(datasource_selection)
    input_dir = resolve_prepared_local_directory(
        resolved, _STATION_PREPARED_DATASET_MAP["input_dir"]
    )
    if input_dir is not None:
        resolved["input_dir"] = str(input_dir)
    for key in (
        "site_info_csv",
        "smap_grid_mat",
        "landcover_mat",
        "climate_mat",
        "network_map_csv",
    ):
        local_path = resolve_prepared_local_path(
            resolved, _STATION_PREPARED_DATASET_MAP[key]
        )
        if local_path is not None:
            resolved[key] = str(local_path)
    return resolved


class StationDailyPipeline(BasePipeline):
    name = "station_daily_pipeline"

    def plan(self, request: JobRequest, ctx: RuntimeContext) -> PipelinePlan:
        return PipelinePlan(
            required_datasets=["ISMN_STM_OR_CASMOS_TXT"],
            required_variables=["soil_moisture", "lat", "lon", "elev", "depth"],
            estimated_outputs=["station_daily_mat", "station_am6_mat"],
            parallelizable=True,
            chunk_strategy="site_file",
            cache_requirement="partial",
        )

    def execute(self, request: JobRequest, ctx: RuntimeContext) -> ProductManifest:
        from scipy.io import savemat

        datasource_selection = _resolve_station_datasource_selection(
            request.datasource_selection
        )
        source_type = request.algorithm_params.get("source_type", "ISMN").upper()
        input_dir = Path(datasource_selection["input_dir"])
        output_dir = Path(
            request.output_spec.extra.get(
                "output_dir", ctx.workspace / "products" / "station_daily"
            )
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        emit_validation_products = bool(
            request.algorithm_params.get("emit_validation_products", True)
        )
        validation_start = _coerce_datetime(
            request.algorithm_params.get("validation_start", request.time_range.start)
        )
        validation_end = _coerce_datetime(
            request.algorithm_params.get("validation_end", request.time_range.end)
        )
        min_valid_days = int(
            request.algorithm_params.get("validation_min_valid_days", 30)
        )
        validation_hour = int(request.algorithm_params.get("validation_hour", 6))
        max_depth_cm = float(
            request.algorithm_params.get(
                "validation_max_depth_cm",
                5.1 if source_type == "ISMN" else 11.0,
            )
        )
        min_sm = float(request.algorithm_params.get("validation_min_sm", 0.001))
        max_sm = float(request.algorithm_params.get("validation_max_sm", 0.601))
        validation_records_by_site: dict[str, list] = {}

        if self.logger_adapter is not None:
            self.logger_adapter.emit_stage_start(
                "station_daily",
                f"Process {source_type} station records from {input_dir}",
            )

        product_refs: list[ProductRef] = []
        if source_type == "ISMN":
            input_files = discover_ismn_stm_files(input_dir)
            for file_path in input_files:
                records = parse_ismn_stm_file(file_path)
                # daily.mat: aggregate all valid records regardless of validation time window
                daily_records = aggregate_station_records_daily(
                    filter_station_records(
                        records,
                        max_depth_cm=max_depth_cm,
                        min_sm=min_sm,
                        max_sm=max_sm,
                        require_good_quality=True,
                    )
                )
                # am6.mat: aggregate records within the validation time window and at validation_hour
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
                validation_records_by_site[file_path.stem] = (
                    am6_records or daily_records
                )
                if not daily_records and not am6_records:
                    continue
                site_output = output_dir / file_path.stem
                site_output.mkdir(parents=True, exist_ok=True)
                daily_path = site_output / "daily.mat"
                am6_path = site_output / "am6.mat"
                if daily_records:
                    savemat(
                        daily_path,
                        {"ismn": station_records_to_rows(daily_records)},
                        do_compression=True,
                    )
                    product_refs.append(
                        ProductRef(
                            name=f"{file_path.stem}_daily",
                            type="station_daily_mat",
                            uri=str(daily_path),
                            variable="soil_moisture",
                        )
                    )
                if am6_records:
                    savemat(
                        am6_path,
                        {"ismn": station_records_to_rows(am6_records)},
                        do_compression=True,
                    )
                    product_refs.append(
                        ProductRef(
                            name=f"{file_path.stem}_am6",
                            type="station_am6_mat",
                            uri=str(am6_path),
                            variable="soil_moisture",
                        )
                    )

        elif source_type == "CASMOS":
            site_info_path = datasource_selection.get("site_info_csv")
            site_info = load_casmos_site_info(site_info_path) if site_info_path else {}
            input_files = discover_casmos_txt_files(input_dir)
            for file_path in input_files:
                records = parse_casmos_txt_file(file_path, site_info=site_info)
                # daily.mat: aggregate all valid records regardless of validation time window
                daily_records = aggregate_station_records_daily(
                    filter_station_records(
                        records,
                        max_depth_cm=max_depth_cm,
                        min_sm=min_sm,
                        max_sm=max_sm,
                        require_good_quality=False,
                    )
                )
                # am6.mat: aggregate records within the validation time window and at validation_hour
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
                validation_records_by_site[file_path.stem] = (
                    am6_records or daily_records
                )
                if not daily_records and not am6_records:
                    continue
                site_output = output_dir / file_path.stem
                site_output.mkdir(parents=True, exist_ok=True)
                daily_path = site_output / "daily.mat"
                am6_path = site_output / "am6.mat"
                if daily_records:
                    savemat(
                        daily_path,
                        {"china_10cm": station_records_to_rows(daily_records)},
                        do_compression=True,
                    )
                    product_refs.append(
                        ProductRef(
                            name=f"{file_path.stem}_daily",
                            type="station_daily_mat",
                            uri=str(daily_path),
                            variable="soil_moisture",
                        )
                    )
                if am6_records:
                    savemat(
                        am6_path,
                        {"china_10cm": station_records_to_rows(am6_records)},
                        do_compression=True,
                    )
                    product_refs.append(
                        ProductRef(
                            name=f"{file_path.stem}_am6",
                            type="station_am6_mat",
                            uri=str(am6_path),
                            variable="soil_moisture",
                        )
                    )
        else:
            raise ValueError(f"Unsupported station source_type: {source_type}")

        validation_refs = self._write_validation_products(
            request,
            output_dir,
            source_type=source_type,
            records_by_site=validation_records_by_site,
            validation_start=validation_start,
            validation_end=validation_end,
            min_valid_days=min_valid_days,
            enabled=emit_validation_products,
        )
        product_refs.extend(validation_refs)

        if self.logger_adapter is not None:
            for product in product_refs:
                self.logger_adapter.emit_artifact(
                    "station_daily", product.uri, product.type
                )
            self.logger_adapter.emit_stage_end(
                "station_daily", f"Generated {len(product_refs)} station products"
            )

        return ProductManifest(
            job_id=request.job_id,
            run_id=ctx.run_id,
            products=product_refs,
            main_layers=["soil_moisture"],
            metadata_uri=None,
            extra={
                "pipeline_name": self.name,
                "source_type": source_type,
                "output_dir": str(output_dir),
                "count": len(product_refs),
                "emit_validation_products": emit_validation_products,
                "validation_start": validation_start.strftime("%Y%m%d"),
                "validation_end": validation_end.strftime("%Y%m%d"),
                "validation_hour": validation_hour,
                "validation_max_depth_cm": max_depth_cm,
                "validation_min_sm": min_sm,
                "validation_max_sm": max_sm,
            },
        )

    def _write_validation_products(
        self,
        request: JobRequest,
        output_dir: Path,
        *,
        source_type: str,
        records_by_site: dict[str, list],
        validation_start,
        validation_end,
        min_valid_days: int,
        enabled: bool,
    ) -> list[ProductRef]:
        from scipy.io import savemat

        if not enabled or not records_by_site:
            return []
        datasource_selection = _resolve_station_datasource_selection(
            request.datasource_selection
        )
        ancillary_path = datasource_selection.get("smap_grid_mat")
        if ancillary_path is None:
            return []

        smap_payload = load_mat_file(ancillary_path)
        smap_lat = _pick_first_available(
            smap_payload,
            _alias_list(
                request.algorithm_params,
                "smap_lat_aliases",
                ["lat_smap", "lat", "lat_9km"],
            ),
        )
        smap_lon = _pick_first_available(
            smap_payload,
            _alias_list(
                request.algorithm_params,
                "smap_lon_aliases",
                ["lon_smap", "lon", "lon_9km"],
            ),
        )

        landcover_grid = landcover_lat = landcover_lon = None
        landcover_mat = datasource_selection.get("landcover_mat")
        if landcover_mat is not None:
            payload = load_mat_file(landcover_mat)
            landcover_grid = _pick_first_available(
                payload,
                _alias_list(
                    request.algorithm_params, "landcover_aliases", ["IGBP_9km_12", "LC"]
                ),
                required=False,
            )
            landcover_lat = _pick_first_available(
                payload,
                _alias_list(
                    request.algorithm_params,
                    "landcover_lat_aliases",
                    ["lat_9km", "lat"],
                ),
                required=False,
            )
            landcover_lon = _pick_first_available(
                payload,
                _alias_list(
                    request.algorithm_params,
                    "landcover_lon_aliases",
                    ["lon_9km", "lon"],
                ),
                required=False,
            )

        climate_grid = climate_lat = climate_lon = None
        climate_mat = datasource_selection.get("climate_mat")
        if climate_mat is not None:
            payload = load_mat_file(climate_mat)
            climate_grid = _pick_first_available(
                payload,
                _alias_list(
                    request.algorithm_params,
                    "climate_aliases",
                    ["Koppen_present_083", "Koppen", "climate"],
                ),
                required=False,
            )
            climate_lat = _pick_first_available(
                payload,
                _alias_list(
                    request.algorithm_params, "climate_lat_aliases", ["lat_kop", "lat"]
                ),
                required=False,
            )
            climate_lon = _pick_first_available(
                payload,
                _alias_list(
                    request.algorithm_params, "climate_lon_aliases", ["lon_kop", "lon"]
                ),
                required=False,
            )

        smap_landcover_grid = _pick_first_available(
            smap_payload,
            _alias_list(
                request.algorithm_params,
                "smap_landcover_aliases",
                ["IGBP_9km_12", "lc_smap", "site_lc_smap"],
            ),
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
            return []

        prefix = "ismn" if source_type == "ISMN" else "china"
        product_refs: list[ProductRef] = []
        for payload_name, payload in validation_payload.items():
            output_path = output_dir / f"{prefix}_{payload_name}.mat"
            savemat(output_path, payload, do_compression=True)
            product_refs.append(
                ProductRef(
                    name=f"{prefix}_{payload_name}",
                    type=f"station_{payload_name}_validation_mat",
                    uri=str(output_path),
                    variable=payload_name,
                )
            )
        return product_refs


def _alias_list(params: dict, key: str, default_aliases: list[str]) -> list[str]:
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
    with Path(csv_path).open(
        "r", encoding="utf-8", errors="ignore", newline=""
    ) as handle:
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
