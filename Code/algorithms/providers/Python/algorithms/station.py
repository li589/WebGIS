from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import math
from typing import Any

from ingest.station import StationRecord


def filter_station_records(
    records: list[StationRecord],
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    max_depth_cm: float | None = None,
    min_sm: float | None = None,
    max_sm: float | None = None,
    require_good_quality: bool = True,
    hour_filter: int | None = None,
) -> list[StationRecord]:
    filtered: list[StationRecord] = []
    for record in records:
        record_time = datetime(record.year, record.month, record.day)
        if start_time is not None and record_time < start_time:
            continue
        if end_time is not None and record_time > end_time:
            continue
        if max_depth_cm is not None and record.depth_lower >= max_depth_cm / 100.0:
            continue
        if hour_filter is not None and record.hour != hour_filter:
            continue
        if require_good_quality and record.quality_flag != 1:
            continue
        if min_sm is not None and (record.soil_moisture != record.soil_moisture or record.soil_moisture <= min_sm):
            continue
        if max_sm is not None and (record.soil_moisture != record.soil_moisture or record.soil_moisture > max_sm):
            continue
        filtered.append(record)
    return filtered


def aggregate_station_records_daily(records: list[StationRecord]) -> list[StationRecord]:
    groups: dict[tuple[int, int, int, float], list[StationRecord]] = defaultdict(list)
    for record in records:
        key = (record.year, record.month, record.day, record.depth_lower)
        groups[key].append(record)

    aggregated: list[StationRecord] = []
    for (_, _, _, _), values in groups.items():
        first = values[0]
        valid_values = [item.soil_moisture for item in values if not math.isnan(item.soil_moisture)]
        if not valid_values:
            continue
        mean_sm = sum(valid_values) / len(valid_values)
        aggregated.append(
            StationRecord(
                year=first.year,
                month=first.month,
                day=first.day,
                hour=first.hour,
                lat=first.lat,
                lon=first.lon,
                elev=first.elev,
                depth_upper=first.depth_upper,
                depth_lower=first.depth_lower,
                soil_moisture=mean_sm,
                quality_flag=1,
                site_id=first.site_id,
                source=first.source,
            )
        )
    aggregated.sort(key=lambda item: (item.year, item.month, item.day, item.depth_lower))
    return aggregated


def build_site_time_series_matrix(
    records: list[StationRecord],
    start_time: datetime,
    end_time: datetime,
) -> dict[str, Any]:
    date_axis: list[datetime] = []
    current = start_time
    while current <= end_time:
        date_axis.append(current)
        current = current.replace(hour=0) + timedelta(days=1)

    date_to_index = {value.strftime("%Y%m%d"): index for index, value in enumerate(date_axis)}
    matrix = [float("nan")] * len(date_axis)
    for record in records:
        key = f"{record.year:04d}{record.month:02d}{record.day:02d}"
        idx = date_to_index.get(key)
        if idx is None:
            continue
        matrix[idx] = record.soil_moisture
    return {
        "date_axis": [value.strftime("%Y%m%d") for value in date_axis],
        "values": matrix,
    }


def station_records_to_rows(records: list[StationRecord]) -> list[list[float | int | str]]:
    rows: list[list[float | int | str]] = []
    for record in records:
        rows.append(
            [
                record.year,
                record.month,
                record.day,
                record.hour,
                record.lat,
                record.lon,
                record.elev,
                record.depth_upper,
                record.depth_lower,
                record.soil_moisture,
                record.quality_flag,
                record.site_id,
                record.source,
            ]
        )
    return rows


def build_station_site_matrix(
    records_by_site: dict[str, list[StationRecord]],
    start_time: datetime,
    end_time: datetime,
    *,
    min_valid_days: int = 1,
) -> dict[str, Any]:
    import numpy as np

    site_ids: list[str] = []
    site_lat: list[float] = []
    site_lon: list[float] = []
    site_elev: list[float] = []
    site_depth: list[float] = []
    site_vali: list[int] = []
    site_matrix_rows: list[Any] = []
    date_axis: list[str] | None = None

    for site_id, records in sorted(records_by_site.items()):
        if not records:
            continue
        matrix_info = build_site_time_series_matrix(records, start_time, end_time)
        values = np.asarray(matrix_info["values"], dtype=np.float64)
        valid_count = int(np.isfinite(values).sum())
        if valid_count < int(min_valid_days):
            continue
        first = records[0]
        site_ids.append(site_id)
        site_lat.append(float(first.lat))
        site_lon.append(float(first.lon))
        site_elev.append(float(first.elev))
        site_depth.append(float(first.depth_lower))
        site_vali.append(valid_count)
        site_matrix_rows.append(values)
        if date_axis is None:
            date_axis = list(matrix_info["date_axis"])

    if not site_matrix_rows:
        empty_axis = build_site_time_series_matrix([], start_time, end_time)["date_axis"]
        return {
            "date_axis": empty_axis,
            "site_matrix": np.empty((0, len(empty_axis)), dtype=np.float64),
            "site_id": [],
            "site_lat": np.empty((0,), dtype=np.float64),
            "site_lon": np.empty((0,), dtype=np.float64),
            "site_elev": np.empty((0,), dtype=np.float64),
            "site_depth": np.empty((0,), dtype=np.float64),
            "site_vali": np.empty((0,), dtype=np.int32),
        }

    return {
        "date_axis": date_axis or [],
        "site_matrix": np.vstack(site_matrix_rows).astype(np.float64, copy=False),
        "site_id": site_ids,
        "site_lat": np.asarray(site_lat, dtype=np.float64),
        "site_lon": np.asarray(site_lon, dtype=np.float64),
        "site_elev": np.asarray(site_elev, dtype=np.float64),
        "site_depth": np.asarray(site_depth, dtype=np.float64),
        "site_vali": np.asarray(site_vali, dtype=np.int32),
    }


def derive_network_ids(site_ids: list[str]) -> list[str]:
    network_ids: list[str] = []
    for site_id in site_ids:
        tokens = str(site_id).replace("-", "_").split("_")
        network_ids.append(tokens[0] if tokens else str(site_id))
    return network_ids


def nearest_grid_indices(
    site_lat: Any,
    site_lon: Any,
    lat_grid: Any,
    lon_grid: Any,
) -> Any:
    import numpy as np

    site_lat = np.asarray(site_lat, dtype=np.float64).reshape(-1)
    site_lon = np.asarray(site_lon, dtype=np.float64).reshape(-1)
    lat_grid = np.asarray(lat_grid, dtype=np.float64)
    lon_grid = np.asarray(lon_grid, dtype=np.float64)
    lat_flat = lat_grid.reshape(-1)
    lon_flat = lon_grid.reshape(-1)
    result = np.full(site_lat.shape, -1, dtype=np.int64)
    for index, (lat_value, lon_value) in enumerate(zip(site_lat, site_lon, strict=False)):
        distance = (lat_flat - lat_value) ** 2 + (lon_flat - lon_value) ** 2
        if np.isfinite(distance).any():
            result[index] = int(np.nanargmin(distance))
    return result


def sample_grid_values(
    sample_indices: Any,
    value_grid: Any,
) -> Any:
    import numpy as np

    indices = np.asarray(sample_indices, dtype=np.int64).reshape(-1)
    values = np.asarray(value_grid, dtype=np.float64).reshape(-1)
    sampled = np.full(indices.shape, np.nan, dtype=np.float64)
    ok = (indices >= 0) & (indices < values.size)
    sampled[ok] = values[indices[ok]]
    return sampled


def aggregate_matrix_by_group(
    values: Any,
    group_ids: Any,
) -> tuple[Any, Any, Any]:
    import numpy as np

    matrix = np.asarray(values, dtype=np.float64)
    group_ids = np.asarray(group_ids).reshape(-1)
    unique_groups: list[Any] = []
    for item in group_ids.tolist():
        if str(item) == "":
            continue
        if item not in unique_groups:
            unique_groups.append(item)
    aggregated = np.full((len(unique_groups), matrix.shape[1]), np.nan, dtype=np.float64)
    valid_counts = np.zeros((len(unique_groups),), dtype=np.int32)
    for group_index, group_id in enumerate(unique_groups):
        rows = np.asarray(group_ids == group_id)
        if not rows.any():
            continue
        with np.errstate(all="ignore"):
            aggregated[group_index, :] = np.nanmean(matrix[rows, :], axis=0)
        valid_counts[group_index] = int(np.isfinite(aggregated[group_index, :]).sum())
    return np.asarray(unique_groups), aggregated, valid_counts


def build_station_validation_outputs(
    records_by_site: dict[str, list[StationRecord]],
    start_time: datetime,
    end_time: datetime,
    *,
    smap_lat: Any,
    smap_lon: Any,
    min_valid_days: int = 1,
    landcover_grid: Any | None = None,
    landcover_lat: Any | None = None,
    landcover_lon: Any | None = None,
    climate_grid: Any | None = None,
    climate_lat: Any | None = None,
    climate_lon: Any | None = None,
    smap_landcover_grid: Any | None = None,
    network_map: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    import numpy as np

    site_payload = build_station_site_matrix(
        records_by_site,
        start_time,
        end_time,
        min_valid_days=min_valid_days,
    )
    site_matrix = np.asarray(site_payload["site_matrix"], dtype=np.float64)
    if site_matrix.size == 0:
        return {}

    site_mesh_idx = nearest_grid_indices(site_payload["site_lat"], site_payload["site_lon"], smap_lat, smap_lon)
    site_payload["site"] = site_matrix
    site_payload["site_mesh"] = site_mesh_idx + 1

    if landcover_grid is not None:
        lc_idx = (
            nearest_grid_indices(site_payload["site_lat"], site_payload["site_lon"], landcover_lat, landcover_lon)
            if landcover_lat is not None and landcover_lon is not None
            else site_mesh_idx
        )
        site_payload["site_lc"] = sample_grid_values(lc_idx, landcover_grid)
    if climate_grid is not None:
        climate_idx = (
            nearest_grid_indices(site_payload["site_lat"], site_payload["site_lon"], climate_lat, climate_lon)
            if climate_lat is not None and climate_lon is not None
            else site_mesh_idx
        )
        site_payload["site_kop"] = sample_grid_values(climate_idx, climate_grid)

    if smap_landcover_grid is not None:
        site_payload["site_lc_smap"] = sample_grid_values(site_mesh_idx, smap_landcover_grid)

    network_source = (
        [network_map.get(site_id, derive_network_ids([site_id])[0]) for site_id in site_payload["site_id"]]
        if network_map is not None
        else derive_network_ids(site_payload["site_id"])
    )

    def _mode_or_nan(values: Any) -> float:
        array = np.asarray(values, dtype=np.float64).reshape(-1)
        array = array[np.isfinite(array)]
        if array.size == 0:
            return float("nan")
        unique, counts = np.unique(array, return_counts=True)
        return float(unique[int(np.argmax(counts))])

    grid_rows: list[Any] = []
    grid_mesh: list[int] = []
    grid_vali: list[int] = []
    grid_id: list[str] = []
    grid_lat: list[float] = []
    grid_lon: list[float] = []
    grid_elev: list[float] = []
    grid_lc: list[float] = []
    grid_kop: list[float] = []
    grid_lc_smap: list[float] = []
    net_id: list[str] = []
    net_rows: list[Any] = []
    net_grid: list[int] = []
    net_lc: list[Any] = []
    net_kop: list[Any] = []

    for network_label in network_source:
        if network_label not in net_id:
            net_id.append(str(network_label))

    site_lat = np.asarray(site_payload["site_lat"], dtype=np.float64)
    site_lon = np.asarray(site_payload["site_lon"], dtype=np.float64)
    site_elev = np.asarray(site_payload["site_elev"], dtype=np.float64)
    site_lc = np.asarray(site_payload.get("site_lc", np.full(site_lat.shape, np.nan, dtype=np.float64)), dtype=np.float64)
    site_kop = np.asarray(site_payload.get("site_kop", np.full(site_lat.shape, np.nan, dtype=np.float64)), dtype=np.float64)
    site_lc_smap = np.asarray(
        site_payload.get("site_lc_smap", np.full(site_lat.shape, np.nan, dtype=np.float64)),
        dtype=np.float64,
    )
    site_mesh_1based = np.asarray(site_payload["site_mesh"], dtype=np.int64).reshape(-1)

    for network_label in net_id:
        network_rows_mask = np.asarray([label == network_label for label in network_source], dtype=bool)
        network_meshes: list[int] = []
        for mesh_value in site_mesh_1based[network_rows_mask].tolist():
            if mesh_value not in network_meshes:
                network_meshes.append(int(mesh_value))

        network_grid_rows: list[Any] = []
        network_grid_lc: list[float] = []
        network_grid_kop: list[float] = []
        for mesh_value in network_meshes:
            rows = network_rows_mask & (site_mesh_1based == mesh_value)
            if not np.any(rows):
                continue
            with np.errstate(all="ignore"):
                grid_row = np.nanmean(site_matrix[rows, :], axis=0)
            grid_rows.append(grid_row)
            grid_mesh.append(int(mesh_value))
            grid_vali.append(int(np.isfinite(grid_row).sum()))
            first_index = int(np.flatnonzero(rows)[0])
            grid_id.append(str(site_payload["site_id"][first_index]))
            grid_lat.append(float(np.nanmean(site_lat[rows])))
            grid_lon.append(float(np.nanmean(site_lon[rows])))
            grid_elev.append(float(np.nanmean(site_elev[rows])))
            lc_value = _mode_or_nan(site_lc[rows])
            kop_value = _mode_or_nan(site_kop[rows])
            grid_lc.append(lc_value)
            grid_kop.append(kop_value)
            grid_lc_smap.append(_mode_or_nan(site_lc_smap[rows]))
            network_grid_rows.append(grid_row)
            network_grid_lc.append(lc_value)
            network_grid_kop.append(kop_value)

        if network_grid_rows:
            with np.errstate(all="ignore"):
                net_rows.append(np.nanmean(np.vstack(network_grid_rows), axis=0))
        else:
            net_rows.append(np.full((site_matrix.shape[1],), np.nan, dtype=np.float64))
        net_grid.append(len(network_grid_rows))
        net_lc.append(np.asarray(network_grid_lc, dtype=np.float64))
        net_kop.append(np.asarray(network_grid_kop, dtype=np.float64))

    grid_payload: dict[str, Any] = {
        "date_axis": site_payload["date_axis"],
        "grid": np.vstack(grid_rows).astype(np.float64, copy=False) if grid_rows else np.empty((0, site_matrix.shape[1]), dtype=np.float64),
        "grid_mesh": np.asarray(grid_mesh, dtype=np.int64),
        "grid_vali": np.asarray(grid_vali, dtype=np.int32),
        "grid_id": np.asarray(grid_id, dtype=object),
        "grid_lat": np.asarray(grid_lat, dtype=np.float64),
        "grid_lon": np.asarray(grid_lon, dtype=np.float64),
        "grid_elev": np.asarray(grid_elev, dtype=np.float64),
    }
    if "site_lc" in site_payload:
        grid_payload["grid_lc"] = np.asarray(grid_lc, dtype=np.float64)
    if "site_kop" in site_payload:
        grid_payload["grid_kop"] = np.asarray(grid_kop, dtype=np.float64)
    if "site_lc_smap" in site_payload:
        grid_payload["grid_lc_smap"] = np.asarray(grid_lc_smap, dtype=np.float64)

    net_payload: dict[str, Any] = {
        "date_axis": site_payload["date_axis"],
        "net": np.vstack(net_rows).astype(np.float64, copy=False) if net_rows else np.empty((0, site_matrix.shape[1]), dtype=np.float64),
        "net_id": np.asarray(net_id, dtype=object),
        "net_grid": np.asarray(net_grid, dtype=np.int32),
    }
    if "site_lc" in site_payload:
        net_payload["net_lc"] = np.asarray(net_lc, dtype=object)
    if "site_kop" in site_payload:
        net_payload["net_kop"] = np.asarray(net_kop, dtype=object)

    return {
        "site": site_payload,
        "grid": grid_payload,
        "net": net_payload,
    }
