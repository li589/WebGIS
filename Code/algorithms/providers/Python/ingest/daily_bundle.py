from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
import re
from typing import Any, Mapping

from algorithms.omega import _MINERAL_PARTICLE_DENSITY
from contracts.modes import DualTgMode
from ingest.mat_bundle import load_mat_file, normalize_aliases_param


@dataclass(frozen=True, slots=True)
class DailyBundleConfig:
    tb_source: str = "SMAP"
    fy_platform: str = "3D"
    sm_source: str = "SMAP"
    ndvi_mode: str = "DAILY_FILE"
    sf_mode: str = "STATIC"
    sf_invert_mode: str = "POINT1"
    temp_scheme: str = "ORIG_TS"
    ndvi_clim_varname: str = "NDVI_clim"
    dual_tg_mode: str = DualTgMode.PAPER_CT.value
    ct_smref: float = 0.30
    ct_exp: float = 0.30
    tbv_aliases: tuple[str, ...] = ("TBv", "tbv", "tb_v_corrected")
    tbh_aliases: tuple[str, ...] = ("TBh", "tbh", "tb_h_corrected")
    ia_aliases: tuple[str, ...] = ("IA", "Theta", "theta")
    ts_aliases: tuple[str, ...] = ("Ts", "ts", "surface_temperature")
    vwc_aliases: tuple[str, ...] = ("vwc", "vegetation_water_content")
    smap_sm_aliases: tuple[str, ...] = ("sm_dca", "SM", "sm", "soil_moisture")
    ddca_sm_aliases: tuple[str, ...] = ("SM", "sm_dca", "sm")
    ndvi_daily_aliases: tuple[str, ...] = ("NDVI",)
    landcover_aliases: tuple[str, ...] = ("IGBP_9km_12",)
    lat_aliases: tuple[str, ...] = ("lat_9km", "lat", "latitude")
    lon_aliases: tuple[str, ...] = ("lon_9km", "lon", "longitude")
    albedo_aliases: tuple[str, ...] = ("ALBEDO", "Albedo")
    b_aliases: tuple[str, ...] = ("B", "b")
    sf_static_aliases: tuple[str, ...] = ("SF_smap", "SF")
    bulk_density_aliases: tuple[str, ...] = ("BD",)
    h_aliases: tuple[str, ...] = ("H",)
    clay_fraction_aliases: tuple[str, ...] = ("CF", "clay_fraction")
    ndvi_v_max_aliases: tuple[str, ...] = ("NDVI_v_max",)
    ndvi_v_min_aliases: tuple[str, ...] = ("NDVI_v_min",)
    gldas_tc_aliases: tuple[str, ...] = ("Ts_gldas", "TC")
    gldas_tsoil1_aliases: tuple[str, ...] = ("Tsoil1_gldas", "Tsoil1")
    gldas_tsoil2_aliases: tuple[str, ...] = ("Tsoil2_gldas", "Tsoil2")
    gldas_template_slot_index_aliases: tuple[str, ...] = ("slot_index",)
    gldas_template_day_offset_aliases: tuple[str, ...] = ("slot_day_offset",)
    use_gldas_template: bool = False
    save_match_info: bool = False
    fy3d_desc_local_hour: float = 2.0
    fy3b_desc_local_hour: float = 1.6666666666666667
    smap_desc_local_hour: float = 6.0
    gldas_time_tol_hours: float = 1.6


def build_daily_bundle_config(params: Mapping[str, Any]) -> DailyBundleConfig:
    params_dict = dict(params)
    return DailyBundleConfig(
        tb_source=str(params_dict.get("tb_source", "SMAP")),
        fy_platform=str(params_dict.get("fy_platform", "3D")),
        sm_source=str(params_dict.get("sm_source", "SMAP")),
        ndvi_mode=str(params_dict.get("ndvi_mode", "DAILY_FILE")),
        sf_mode=str(params_dict.get("sf_mode", "STATIC")),
        sf_invert_mode=str(params_dict.get("sf_invert_mode", "POINT1")),
        temp_scheme=str(params_dict.get("temp_scheme", "ORIG_TS")),
        ndvi_clim_varname=str(params_dict.get("ndvi_clim_varname", "NDVI_clim")),
        dual_tg_mode=str(params_dict.get("dual_tg_mode", DualTgMode.PAPER_CT.value)),
        ct_smref=float(params_dict.get("ct_smref", 0.30)),
        ct_exp=float(params_dict.get("ct_exp", 0.30)),
        tbv_aliases=normalize_aliases_param(params_dict.get("tbv_aliases"), ("TBv", "tbv", "tb_v_corrected")),
        tbh_aliases=normalize_aliases_param(params_dict.get("tbh_aliases"), ("TBh", "tbh", "tb_h_corrected")),
        ia_aliases=normalize_aliases_param(params_dict.get("ia_aliases"), ("IA", "Theta", "theta")),
        ts_aliases=normalize_aliases_param(params_dict.get("ts_aliases"), ("Ts", "ts", "surface_temperature")),
        vwc_aliases=normalize_aliases_param(params_dict.get("vwc_aliases"), ("vwc", "vegetation_water_content")),
        smap_sm_aliases=normalize_aliases_param(params_dict.get("smap_sm_aliases"), ("sm_dca", "SM", "sm", "soil_moisture")),
        ddca_sm_aliases=normalize_aliases_param(params_dict.get("ddca_sm_aliases"), ("SM", "sm_dca", "sm")),
        ndvi_daily_aliases=normalize_aliases_param(params_dict.get("ndvi_daily_aliases"), ("NDVI",)),
        landcover_aliases=normalize_aliases_param(params_dict.get("landcover_aliases"), ("IGBP_9km_12",)),
        lat_aliases=normalize_aliases_param(params_dict.get("lat_aliases"), ("lat_9km", "lat", "latitude")),
        lon_aliases=normalize_aliases_param(params_dict.get("lon_aliases"), ("lon_9km", "lon", "longitude")),
        albedo_aliases=normalize_aliases_param(params_dict.get("albedo_aliases"), ("ALBEDO", "Albedo")),
        b_aliases=normalize_aliases_param(params_dict.get("b_aliases"), ("B", "b")),
        sf_static_aliases=normalize_aliases_param(params_dict.get("sf_static_aliases"), ("SF_smap", "SF")),
        bulk_density_aliases=normalize_aliases_param(params_dict.get("bulk_density_aliases"), ("BD",)),
        h_aliases=normalize_aliases_param(params_dict.get("h_aliases"), ("H",)),
        clay_fraction_aliases=normalize_aliases_param(params_dict.get("clay_fraction_aliases"), ("CF", "clay_fraction")),
        ndvi_v_max_aliases=normalize_aliases_param(params_dict.get("ndvi_v_max_aliases"), ("NDVI_v_max",)),
        ndvi_v_min_aliases=normalize_aliases_param(params_dict.get("ndvi_v_min_aliases"), ("NDVI_v_min",)),
        gldas_tc_aliases=normalize_aliases_param(
            params_dict.get("gldas_tc_aliases", params_dict.get("gldas_var_tc")),
            ("Ts_gldas", "TC"),
        ),
        gldas_tsoil1_aliases=normalize_aliases_param(
            params_dict.get("gldas_tsoil1_aliases", params_dict.get("gldas_var_tsoil1")),
            ("Tsoil1_gldas", "Tsoil1"),
        ),
        gldas_tsoil2_aliases=normalize_aliases_param(
            params_dict.get("gldas_tsoil2_aliases", params_dict.get("gldas_var_tsoil2")),
            ("Tsoil2_gldas", "Tsoil2"),
        ),
        gldas_template_slot_index_aliases=normalize_aliases_param(
            params_dict.get("gldas_template_slot_index_aliases"),
            ("slot_index",),
        ),
        gldas_template_day_offset_aliases=normalize_aliases_param(
            params_dict.get("gldas_template_day_offset_aliases"),
            ("slot_day_offset",),
        ),
        use_gldas_template=bool(params_dict.get("use_gldas_template", False)),
        save_match_info=bool(params_dict.get("save_match_info", False)),
        fy3d_desc_local_hour=float(params_dict.get("fy3d_desc_local_hour", 2.0)),
        fy3b_desc_local_hour=float(params_dict.get("fy3b_desc_local_hour", 1 + 40 / 60)),
        smap_desc_local_hour=float(params_dict.get("smap_desc_local_hour", 6.0)),
        gldas_time_tol_hours=float(params_dict.get("gldas_time_tol_hours", 1.6)),
    )


def date_keys_from_range(start_time: datetime, end_time: datetime) -> list[str]:
    keys: list[str] = []
    current = start_time
    while current <= end_time:
        keys.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return keys


def _load_mat_payload(file_path: str | Path) -> dict[str, Any]:
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"MAT file not found: {file_path}")
    return load_mat_file(file_path)


def _pick_field(payload: dict[str, Any], aliases: list[str], *, required: bool = True) -> Any:
    for alias in aliases:
        if alias in payload:
            return payload[alias]
    if required:
        raise KeyError(f"Missing field. Tried aliases: {aliases}")
    return None


def _pick_field_or_attr(container: Any, aliases: list[str], *, required: bool = True) -> Any:
    if isinstance(container, dict):
        return _pick_field(container, aliases, required=required)
    for alias in aliases:
        if hasattr(container, alias):
            return getattr(container, alias)
    if required:
        raise KeyError(f"Missing field. Tried aliases: {aliases}")
    return None


def _normalize_selection(lin_pix: list[int] | None) -> Any:
    import numpy as np

    if lin_pix is None:
        return None
    selection = np.asarray(lin_pix, dtype=np.int64)
    if selection.ndim != 1:
        raise ValueError("lin_pix must be a 1-D selection")
    if selection.size == 0:
        return selection
    if selection.min() >= 1:
        selection = selection - 1
    return selection


def _subset_grid(grid: Any, lin_pix: list[int] | None = None) -> Any:
    import numpy as np

    if grid is None:
        return None
    array = np.asarray(grid)
    selection = _normalize_selection(lin_pix)
    if selection is None:
        return array.astype(np.float64, copy=False) if array.dtype.kind in {"i", "u", "f"} else array
    flat = array.reshape(-1)
    return flat[selection]


def _load_selected_mat_var(
    file_path: str | Path,
    aliases: list[str],
    lin_pix: list[int] | None = None,
    *,
    required: bool = True,
) -> Any:
    payload = _load_mat_payload(file_path)
    value = _pick_field(payload, aliases, required=required)
    return _subset_grid(value, lin_pix)


def load_lin_pix_selection(
    lin_pix: list[int] | None = None,
    lin_pix_mat: str | Path | None = None,
    variable_name: str = "lin_pix",
) -> list[int] | None:
    import numpy as np

    if lin_pix is not None:
        return [int(value) for value in lin_pix]
    if lin_pix_mat is None:
        return None
    payload = _load_mat_payload(lin_pix_mat)
    values = _pick_field(payload, [variable_name])
    selection = np.asarray(values).reshape(-1).tolist()
    return [int(value) for value in selection]


def build_sf_row_daily(
    vwc_row: Any,
    ndvi_clim_row: Any,
    ndvi_clim_max_row: Any,
    ndvi_clim_min_row: Any,
    cls_row: Any,
    mode_sf: str,
) -> Any:
    import numpy as np

    vwc_row = np.asarray(vwc_row, dtype=np.float64).reshape(-1)
    ndvi_clim_row = np.asarray(ndvi_clim_row, dtype=np.float64).reshape(-1)
    ndvi_clim_max_row = np.asarray(ndvi_clim_max_row, dtype=np.float64).reshape(-1)
    ndvi_clim_min_row = np.asarray(ndvi_clim_min_row, dtype=np.float64).reshape(-1)
    cls_row = np.asarray(cls_row, dtype=np.float64).reshape(-1)

    sf_row = np.full(vwc_row.shape, np.nan, dtype=np.float64)
    vwc_leaf = 1.9134 * (ndvi_clim_row**2) - 0.3215 * ndvi_clim_row
    vwc_wood = vwc_row - vwc_leaf

    is_crop_grass = (cls_row == 10) | (cls_row == 12)
    is_other = ~is_crop_grass
    is_other[cls_row == 0] = False

    den = np.full(vwc_row.shape, np.nan, dtype=np.float64)
    mode_sf = str(mode_sf).upper()
    if mode_sf == "POINT1":
        den[is_crop_grass] = (ndvi_clim_row[is_crop_grass] - 0.1) / 0.9
        den[is_other] = (ndvi_clim_max_row[is_other] - 0.1) / 0.9
    elif mode_sf == "NDVIMIN":
        den[is_crop_grass] = (
            (ndvi_clim_row[is_crop_grass] - ndvi_clim_min_row[is_crop_grass])
            / (1 - ndvi_clim_min_row[is_crop_grass])
        )
        den[is_other] = (
            (ndvi_clim_max_row[is_other] - ndvi_clim_min_row[is_other])
            / (1 - ndvi_clim_min_row[is_other])
        )
    else:
        raise ValueError(f"Unsupported SF invert mode: {mode_sf}")

    sf_row = vwc_wood / den
    bad = (
        ~np.isfinite(vwc_row)
        | ~np.isfinite(ndvi_clim_row)
        | ~np.isfinite(ndvi_clim_max_row)
        | ~np.isfinite(ndvi_clim_min_row)
        | ~np.isfinite(den)
        | (den <= 0)
        | ~np.isfinite(sf_row)
        | (sf_row < 0)
        | (cls_row == 0)
    )
    sf_row[bad] = np.nan
    return sf_row


def load_static_ancillary_bundle(
    anc_root: str | Path,
    config: DailyBundleConfig,
    *,
    lin_pix: list[int] | None = None,
    ndvi_extrema_mat: str | Path | None = None,
) -> dict[str, Any]:
    anc_root = Path(anc_root)
    landcover_payload = _load_mat_payload(anc_root / "IGBP_9km_12.mat")
    landcover = _pick_field(landcover_payload, list(config.landcover_aliases))

    lat_grid = _pick_field(landcover_payload, list(config.lat_aliases), required=False)
    lon_grid = _pick_field(landcover_payload, list(config.lon_aliases), required=False)

    albedo = _load_selected_mat_var(anc_root / "Albedo.mat", list(config.albedo_aliases), lin_pix)
    b_param = _load_selected_mat_var(anc_root / "B.mat", list(config.b_aliases), lin_pix)
    sf_static = _load_selected_mat_var(anc_root / "SF.mat", list(config.sf_static_aliases), lin_pix)
    bulk_density = _load_selected_mat_var(anc_root / "BD.mat", list(config.bulk_density_aliases), lin_pix)
    h_static = _load_selected_mat_var(anc_root / "H.mat", list(config.h_aliases), lin_pix)
    clay_fraction = _load_selected_mat_var(anc_root / "CF.mat", list(config.clay_fraction_aliases), lin_pix)

    if ndvi_extrema_mat is None:
        ndvi_v_max = None
        ndvi_v_min = None
    else:
        ndvi_v_max = _load_selected_mat_var(ndvi_extrema_mat, list(config.ndvi_v_max_aliases), lin_pix)
        ndvi_v_min = _load_selected_mat_var(ndvi_extrema_mat, list(config.ndvi_v_min_aliases), lin_pix)

    landcover_selected = _subset_grid(landcover, lin_pix)
    porosity = 1.0 - bulk_density / _MINERAL_PARTICLE_DENSITY
    return {
        "LC": landcover_selected,
        "lat_9km": _subset_grid(lat_grid, lin_pix) if lat_grid is not None else None,
        "lon_9km": _subset_grid(lon_grid, lin_pix) if lon_grid is not None else None,
        "Albedo": albedo,
        "B": b_param,
        "SF_static": sf_static,
        "BD": bulk_density,
        "H": h_static,
        "CF": clay_fraction,
        "porosity": porosity,
        "NDVI_v_max": ndvi_v_max,
        "NDVI_v_min": ndvi_v_min,
    }


def load_ndvi_row_for_day(
    date_key: str,
    config: DailyBundleConfig,
    ndvi_folder: str | Path,
    ndvi_clim_folder: str | Path,
    *,
    lin_pix: list[int] | None = None,
) -> Any:
    day_dt = datetime.strptime(date_key, "%Y%m%d")
    ndvi_mode = str(config.ndvi_mode).upper()
    if ndvi_mode == "DAILY_FILE":
        return _load_selected_mat_var(Path(ndvi_folder) / f"{date_key}.mat", list(config.ndvi_daily_aliases), lin_pix)
    if ndvi_mode == "DOY_CLIM":
        doy = day_dt.timetuple().tm_yday
        return _load_selected_mat_var(
            Path(ndvi_clim_folder) / f"{doy}.mat",
            [config.ndvi_clim_varname, "NDVI_clim"],
            lin_pix,
        )
    raise ValueError(f"Unsupported NDVI mode: {ndvi_mode}")


def _resolve_daily_mat_file(folder: str | Path, date_key: str) -> Path:
    folder = Path(folder)
    direct = folder / f"{date_key}.mat"
    if direct.exists():
        return direct
    matches = sorted(folder.glob(f"*{date_key}*.mat"))
    if matches:
        return matches[0]
    raise FileNotFoundError(f"Cannot find daily MAT file for {date_key} under {folder}")


def _format_datetime_token(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%Y-%m-%dT%H:%M:%S")


def _init_match_diagnostics(pixel_count: int) -> dict[str, Any]:
    import numpy as np

    return {
        "match_slot_index": np.full(pixel_count, np.nan, dtype=np.float64),
        "match_day_offset": np.full(pixel_count, np.nan, dtype=np.float64),
        "match_picked_file": np.full(pixel_count, "", dtype=object),
        "match_picked_utc": np.full(pixel_count, "", dtype=object),
    }


@lru_cache(maxsize=8)
def build_gldas_file_index(folder: str) -> dict[str, Any]:
    folder_path = Path(folder)
    matches: list[tuple[datetime, Path]] = []
    for file_path in folder_path.glob("*.mat"):
        parsed = parse_gldas_timestamp_from_name(file_path.name)
        if parsed is not None:
            matches.append((parsed, file_path))
    if not matches:
        raise FileNotFoundError(f"No GLDAS MAT files with YYYYMMDD_HHMM names found under {folder_path}")
    matches.sort(key=lambda item: item[0])
    return {
        "times": [item[0] for item in matches],
        "files": [item[1] for item in matches],
    }


def parse_gldas_timestamp_from_name(file_name: str) -> datetime | None:
    match = re.match(r"^(\d{8})_(\d{4})\.mat$", file_name)
    if match is None:
        return None
    return datetime.strptime("".join(match.groups()), "%Y%m%d%H%M")


@lru_cache(maxsize=8)
def build_gldas_day_slot_table(folder: str) -> dict[datetime.date, list[int]]:
    index = build_gldas_file_index(folder)
    day_slots: dict[datetime.date, list[int]] = {}
    for file_index, gldas_time in enumerate(index["times"]):
        day_slots.setdefault(gldas_time.date(), []).append(file_index)
    return day_slots


def local_overpass_to_utc_vec(day_dt: datetime, lon_vec: Any, local_hour: float) -> list[datetime | None]:
    import numpy as np

    lon_values = np.asarray(lon_vec, dtype=np.float64).reshape(-1)
    base_day = datetime(day_dt.year, day_dt.month, day_dt.day)
    target_times: list[datetime | None] = []
    for lon_value in lon_values:
        if np.isfinite(lon_value):
            target_times.append(base_day + timedelta(hours=float(local_hour) - float(lon_value) / 15.0))
        else:
            target_times.append(None)
    return target_times


def pick_gldas_file_indices(
    gldas_times: list[datetime],
    target_times: list[datetime | None],
    tol_hours: float,
) -> list[int | None]:
    indices: list[int | None] = []
    for target_time in target_times:
        if target_time is None:
            indices.append(None)
            continue
        best_index: int | None = None
        best_delta_hours: float | None = None
        for file_index, gldas_time in enumerate(gldas_times):
            delta_hours = abs((gldas_time - target_time).total_seconds()) / 3600.0
            if best_delta_hours is None or delta_hours < best_delta_hours:
                best_delta_hours = delta_hours
                best_index = file_index
        if best_delta_hours is not None and best_delta_hours <= float(tol_hours):
            indices.append(best_index)
        else:
            indices.append(None)
    return indices


def _infer_gldas_template_names(config: DailyBundleConfig) -> list[str]:
    if config.tb_source.upper() == "FY":
        if config.fy_platform.upper() == "3B":
            return ["FY3B_template"]
        return ["FY3D_template"]
    return ["SMAP_template"]


def _load_gldas_template_container(
    template_path: str | Path,
    config: DailyBundleConfig,
    *,
    template_name: str | None = None,
) -> Any:
    payload = _load_mat_payload(template_path)
    if template_name is not None:
        candidate_names = [template_name]
    else:
        candidate_names = _infer_gldas_template_names(config)

    for candidate_name in candidate_names:
        if candidate_name in payload:
            return payload[candidate_name]

    if any(alias in payload for alias in ["slot_index", "slot_day_offset"]):
        return payload
    raise KeyError(f"Cannot find GLDAS template container in {template_path}")


def _select_gldas_indices_from_template(
    date_key: str,
    lon_values: Any,
    datasource_selection: dict[str, Any],
    config: DailyBundleConfig,
    *,
    lin_pix: list[int] | None = None,
) -> tuple[list[int | None], Any, Any]:
    import numpy as np

    gldas_template_path = datasource_selection.get("gldas_template_file") or datasource_selection.get("gldas_template_mat")
    if gldas_template_path is None:
        raise ValueError("gldas_template_file or gldas_template_mat is required when use_gldas_template=True")

    template_container = _load_gldas_template_container(
        gldas_template_path,
        config,
        template_name=datasource_selection.get("gldas_template_name"),
    )
    slot_index = _subset_grid(_pick_field_or_attr(template_container, list(config.gldas_template_slot_index_aliases)), lin_pix)
    slot_day_offset = _subset_grid(
        _pick_field_or_attr(template_container, list(config.gldas_template_day_offset_aliases)),
        lin_pix,
    )

    slot_index = np.asarray(slot_index, dtype=np.float64).reshape(-1)
    slot_day_offset = np.asarray(slot_day_offset, dtype=np.float64).reshape(-1)
    lon_values = np.asarray(lon_values, dtype=np.float64).reshape(-1)
    if slot_index.size != lon_values.size or slot_day_offset.size != lon_values.size:
        raise ValueError("GLDAS template size does not match selected pixel count")

    gldas_folder = str(datasource_selection.get("gldas_folder") or datasource_selection.get("gldas_mat_folder"))
    day_slots = build_gldas_day_slot_table(gldas_folder)
    base_day = datetime.strptime(date_key, "%Y%m%d")
    picked_indices: list[int | None] = []
    for pixel_index in range(lon_values.size):
        slot_value = slot_index[pixel_index]
        day_offset_value = slot_day_offset[pixel_index]
        if not np.isfinite(slot_value) or not np.isfinite(day_offset_value):
            picked_indices.append(None)
            continue
        target_day = (base_day + timedelta(days=int(round(float(day_offset_value))))).date()
        slot_list = day_slots.get(target_day, [])
        slot_position = int(round(float(slot_value))) - 1
        if 0 <= slot_position < len(slot_list):
            picked_indices.append(slot_list[slot_position])
        else:
            picked_indices.append(None)
    return picked_indices, slot_index, slot_day_offset


def _select_gldas_indices_by_local_overpass(
    date_key: str,
    lon_values: Any,
    datasource_selection: dict[str, Any],
    config: DailyBundleConfig,
) -> tuple[list[int | None], Any, Any]:
    import numpy as np

    base_day = datetime.strptime(date_key, "%Y%m%d")
    if config.tb_source.upper() == "FY":
        local_hour = config.fy3b_desc_local_hour if config.fy_platform.upper() == "3B" else config.fy3d_desc_local_hour
    else:
        local_hour = config.smap_desc_local_hour

    gldas_folder = str(datasource_selection.get("gldas_folder") or datasource_selection.get("gldas_mat_folder"))
    gldas_index = build_gldas_file_index(gldas_folder)
    target_times = local_overpass_to_utc_vec(base_day, lon_values, local_hour)
    picked_indices = pick_gldas_file_indices(gldas_index["times"], target_times, config.gldas_time_tol_hours)
    pixel_count = np.asarray(lon_values, dtype=np.float64).reshape(-1).size
    return (
        picked_indices,
        np.full(pixel_count, np.nan, dtype=np.float64),
        np.full(pixel_count, np.nan, dtype=np.float64),
    )


def _load_dual_temperature_by_gldas_indices(
    picked_indices: list[int | None],
    datasource_selection: dict[str, Any],
    config: DailyBundleConfig,
    *,
    lin_pix: list[int] | None = None,
) -> tuple[Any, Any, Any, dict[str, Any]]:
    import numpy as np

    pixel_count = len(picked_indices)
    tc = np.full(pixel_count, np.nan, dtype=np.float64)
    tsoil1 = np.full(pixel_count, np.nan, dtype=np.float64)
    tsoil2 = np.full(pixel_count, np.nan, dtype=np.float64)
    diagnostics = _init_match_diagnostics(pixel_count)
    source_indices = _normalize_selection(lin_pix)
    if source_indices is None:
        source_indices = np.arange(pixel_count, dtype=np.int64)

    gldas_folder = str(datasource_selection.get("gldas_folder") or datasource_selection.get("gldas_mat_folder"))
    gldas_index = build_gldas_file_index(gldas_folder)
    unique_indices = sorted({index for index in picked_indices if index is not None})

    for gldas_file_index in unique_indices:
        positions = [pos for pos, index in enumerate(picked_indices) if index == gldas_file_index]
        if not positions:
            continue
        payload = _load_mat_payload(gldas_index["files"][gldas_file_index])
        tc_flat = _pick_field(payload, list(config.gldas_tc_aliases), required=False)
        tsoil1_flat = _pick_field(payload, list(config.gldas_tsoil1_aliases), required=False)
        tsoil2_flat = _pick_field(payload, list(config.gldas_tsoil2_aliases), required=False)

        if tc_flat is not None:
            tc_values = np.asarray(tc_flat, dtype=np.float64).reshape(-1)
            tc[positions] = tc_values[source_indices[positions]]
        if tsoil1_flat is not None:
            tsoil1_values = np.asarray(tsoil1_flat, dtype=np.float64).reshape(-1)
            tsoil1[positions] = tsoil1_values[source_indices[positions]]
        if tsoil2_flat is not None:
            tsoil2_values = np.asarray(tsoil2_flat, dtype=np.float64).reshape(-1)
            tsoil2[positions] = tsoil2_values[source_indices[positions]]
        picked_file = str(gldas_index["files"][gldas_file_index].name)
        picked_utc = _format_datetime_token(gldas_index["times"][gldas_file_index])
        diagnostics["match_picked_file"][positions] = picked_file
        diagnostics["match_picked_utc"][positions] = picked_utc
    return tc, tsoil1, tsoil2, diagnostics


def load_dual_temperature_row_for_day(
    date_key: str,
    datasource_selection: dict[str, Any],
    config: DailyBundleConfig,
    *,
    lin_pix: list[int] | None = None,
) -> tuple[Any, Any, Any, dict[str, Any]]:
    import numpy as np

    gldas_folder = datasource_selection.get("gldas_folder") or datasource_selection.get("gldas_mat_folder")
    if gldas_folder is None:
        raise ValueError("gldas_folder or gldas_mat_folder is required when TEMP_SCHEME=DUAL")

    lon_values = _load_selected_mat_var(
        Path(datasource_selection["anc_root"]) / "IGBP_9km_12.mat",
        list(config.lon_aliases),
        lin_pix,
    )
    lon_values = np.asarray(lon_values, dtype=np.float64).reshape(-1)
    match_diagnostics = _init_match_diagnostics(lon_values.size)
    if config.use_gldas_template:
        picked_indices, slot_index, day_offset = _select_gldas_indices_from_template(
            date_key,
            lon_values,
            datasource_selection,
            config,
            lin_pix=lin_pix,
        )
    else:
        picked_indices, slot_index, day_offset = _select_gldas_indices_by_local_overpass(
            date_key,
            lon_values,
            datasource_selection,
            config,
        )
    match_diagnostics["match_slot_index"] = np.asarray(slot_index, dtype=np.float64).reshape(-1)
    match_diagnostics["match_day_offset"] = np.asarray(day_offset, dtype=np.float64).reshape(-1)

    if any(index is not None for index in picked_indices):
        tc, tsoil1, tsoil2, picked_diagnostics = _load_dual_temperature_by_gldas_indices(
            picked_indices,
            datasource_selection,
            config,
            lin_pix=lin_pix,
        )
        match_diagnostics["match_picked_file"] = picked_diagnostics["match_picked_file"]
        match_diagnostics["match_picked_utc"] = picked_diagnostics["match_picked_utc"]
        return tc, tsoil1, tsoil2, match_diagnostics

    pixel_count = lon_values.size
    return (
        np.full(pixel_count, np.nan, dtype=np.float64),
        np.full(pixel_count, np.nan, dtype=np.float64),
        np.full(pixel_count, np.nan, dtype=np.float64),
        match_diagnostics,
    )


def build_effective_soil_temperature_scheme(
    sm_ref: Any,
    tsoil1: Any,
    tsoil2: Any,
    *,
    dual_tg_mode: str,
    ct_smref: float,
    ct_exp: float,
) -> tuple[Any, Any]:
    import numpy as np

    sm_ref = np.asarray(sm_ref, dtype=np.float64).reshape(-1)
    tsoil1 = np.asarray(tsoil1, dtype=np.float64).reshape(-1)
    tsoil2 = np.asarray(tsoil2, dtype=np.float64).reshape(-1)
    ct = np.full(sm_ref.shape, np.nan, dtype=np.float64)
    tg = np.full(sm_ref.shape, np.nan, dtype=np.float64)

    mode = str(dual_tg_mode).upper()
    if mode == DualTgMode.PAPER_CT.value:
        ok = np.isfinite(sm_ref) & (sm_ref >= 0)
        ct[ok] = np.power(sm_ref[ok] / float(ct_smref), float(ct_exp))
        tg = tsoil2 + ct * (tsoil1 - tsoil2)
    elif mode == DualTgMode.TSOIL1_ONLY.value:
        tg = tsoil1
    elif mode == DualTgMode.TSOIL2_ONLY.value:
        tg = tsoil2
    else:
        raise ValueError(f"Unsupported dual TG mode: {dual_tg_mode}")
    return ct, tg


def build_daily_bundle_for_date(
    date_key: str,
    config: DailyBundleConfig,
    datasource_selection: dict[str, Any],
    *,
    lin_pix: list[int] | None = None,
) -> dict[str, Any]:
    tb_source = config.tb_source.upper()
    fy_platform = config.fy_platform.upper()
    sm_source = config.sm_source.upper()
    sf_mode = config.sf_mode.upper()
    temp_scheme = config.temp_scheme.upper()

    anc_root = Path(datasource_selection["anc_root"])
    smap_folder = Path(datasource_selection["smap_folder"])
    ndvi_folder = Path(datasource_selection["ndvi_folder"])
    ndvi_clim_folder = Path(datasource_selection["ndvi_clim_folder"])
    ndvi_extrema_mat = datasource_selection.get("ndvi_extrema_mat")
    ddca_sm_folder = datasource_selection.get("ddca_sm_folder")

    if tb_source == "FY":
        if fy_platform == "3B":
            tb_folder = Path(datasource_selection["fy3b_folder"])
        else:
            tb_folder = Path(datasource_selection["fy3d_folder"])
    else:
        tb_folder = smap_folder

    tb_payload = _load_mat_payload(tb_folder / f"{date_key}.mat")
    smap_payload = _load_mat_payload(smap_folder / f"{date_key}.mat")

    static_bundle = load_static_ancillary_bundle(
        anc_root,
        config,
        lin_pix=lin_pix,
        ndvi_extrema_mat=ndvi_extrema_mat,
    )

    tbv = _subset_grid(_pick_field(tb_payload, list(config.tbv_aliases)), lin_pix)
    tbh = _subset_grid(_pick_field(tb_payload, list(config.tbh_aliases)), lin_pix)
    ia = _subset_grid(_pick_field(tb_payload, list(config.ia_aliases), required=False), lin_pix)
    ts = _subset_grid(_pick_field(smap_payload, list(config.ts_aliases), required=False), lin_pix)
    vwc = _subset_grid(_pick_field(smap_payload, list(config.vwc_aliases), required=False), lin_pix)

    if sm_source == "SMAP":
        sm_ref = _subset_grid(_pick_field(smap_payload, list(config.smap_sm_aliases), required=False), lin_pix)
    elif sm_source == "DDCA":
        if ddca_sm_folder is None:
            raise ValueError("ddca_sm_folder is required when SM_SOURCE=DDCA")
        ddca_payload = _load_mat_payload(Path(ddca_sm_folder) / f"{date_key}.mat")
        sm_ref = _subset_grid(_pick_field(ddca_payload, list(config.ddca_sm_aliases)), lin_pix)
    else:
        raise ValueError(f"Unsupported SM source: {sm_source}")

    ndvi = load_ndvi_row_for_day(
        date_key,
        config,
        ndvi_folder,
        ndvi_clim_folder,
        lin_pix=lin_pix,
    )

    if sf_mode == "STATIC":
        sf = static_bundle["SF_static"]
    elif sf_mode == "INVERTED_DAILY":
        doy = datetime.strptime(date_key, "%Y%m%d").timetuple().tm_yday
        ndvi_clim_row = _load_selected_mat_var(
            Path(ndvi_clim_folder) / f"{doy}.mat",
            [config.ndvi_clim_varname, "NDVI_clim"],
            lin_pix,
        )
        sf = build_sf_row_daily(
            vwc_row=vwc,
            ndvi_clim_row=ndvi_clim_row,
            ndvi_clim_max_row=static_bundle["NDVI_v_max"],
            ndvi_clim_min_row=static_bundle["NDVI_v_min"],
            cls_row=static_bundle["LC"],
            mode_sf=config.sf_invert_mode,
        )
    else:
        raise ValueError(f"Unsupported SF mode: {sf_mode}")

    tc = None
    tsoil1 = None
    tsoil2 = None
    ct = None
    tg = None
    match_slot_index = None
    match_day_offset = None
    match_picked_file = None
    match_picked_utc = None
    if temp_scheme == "DUAL":
        tc, tsoil1, tsoil2, match_diagnostics = load_dual_temperature_row_for_day(
            date_key,
            datasource_selection,
            config,
            lin_pix=lin_pix,
        )
        if config.save_match_info:
            match_slot_index = match_diagnostics["match_slot_index"]
            match_day_offset = match_diagnostics["match_day_offset"]
            match_picked_file = match_diagnostics["match_picked_file"]
            match_picked_utc = match_diagnostics["match_picked_utc"]
        if tc is not None and tsoil1 is not None and tsoil2 is not None and sm_ref is not None:
            ct, tg = build_effective_soil_temperature_scheme(
                sm_ref,
                tsoil1,
                tsoil2,
                dual_tg_mode=config.dual_tg_mode,
                ct_smref=config.ct_smref,
                ct_exp=config.ct_exp,
            )
    elif temp_scheme != "ORIG_TS":
        raise NotImplementedError(f"Unsupported TEMP_SCHEME: {temp_scheme}")

    return {
        "date_str": date_key,
        "TBv": tbv,
        "TBh": tbh,
        "IA": ia,
        "Ts": ts,
        "TC": tc,
        "Tsoil1": tsoil1,
        "Tsoil2": tsoil2,
        "Ct": ct,
        "TG": tg,
        "match_slot_index": match_slot_index,
        "match_day_offset": match_day_offset,
        "match_picked_file": match_picked_file,
        "match_picked_utc": match_picked_utc,
        "SM_ref": sm_ref,
        "NDVI": ndvi,
        "SF": sf,
        "vwc": vwc,
        **static_bundle,
    }
