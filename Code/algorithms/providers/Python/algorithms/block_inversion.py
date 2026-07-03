from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass
from typing import Any

from algorithms.inversion import ddca_retrieve_grid, retrieve_dynamic_h_grid
from algorithms.physics import tau_from_ndvi
from ingest.mat_bundle import get_first_available, load_mat_file, normalize_aliases_param


@dataclass(frozen=True, slots=True)
class BlockFieldConfig:
    tbv_mat_aliases: tuple[str, ...] = ("TBv_mat",)
    tbh_mat_aliases: tuple[str, ...] = ("TBh_mat",)
    ia_mat_aliases: tuple[str, ...] = ("IA_mat",)
    ts_mat_aliases: tuple[str, ...] = ("Ts_mat",)
    ndvi_mat_aliases: tuple[str, ...] = ("NDVI_mat",)
    sf_mat_aliases: tuple[str, ...] = ("SF_mat",)
    albedo_aliases: tuple[str, ...] = ("Albedo", "ALBEDO")
    b_aliases: tuple[str, ...] = ("B", "b")
    clay_fraction_aliases: tuple[str, ...] = ("CF",)
    porosity_aliases: tuple[str, ...] = ("porosity", "Porosity")
    landcover_aliases: tuple[str, ...] = ("LC", "IGBP_9km_12")
    ndvi_v_max_aliases: tuple[str, ...] = ("NDVI_v_max",)
    ndvi_v_min_aliases: tuple[str, ...] = ("NDVI_v_min",)
    h_static_aliases: tuple[str, ...] = ("H", "h")
    dh_aliases: tuple[str, ...] = ("DH_mat", "DH", "dh_mat")


def build_block_field_config(params: dict[str, Any]) -> BlockFieldConfig:
    return BlockFieldConfig(
        tbv_mat_aliases=normalize_aliases_param(params.get("tbv_mat_aliases"), ("TBv_mat",)),
        tbh_mat_aliases=normalize_aliases_param(params.get("tbh_mat_aliases"), ("TBh_mat",)),
        ia_mat_aliases=normalize_aliases_param(params.get("ia_mat_aliases"), ("IA_mat",)),
        ts_mat_aliases=normalize_aliases_param(params.get("ts_mat_aliases"), ("Ts_mat",)),
        ndvi_mat_aliases=normalize_aliases_param(params.get("ndvi_mat_aliases"), ("NDVI_mat",)),
        sf_mat_aliases=normalize_aliases_param(params.get("sf_mat_aliases"), ("SF_mat",)),
        albedo_aliases=normalize_aliases_param(params.get("albedo_aliases"), ("Albedo", "ALBEDO")),
        b_aliases=normalize_aliases_param(params.get("b_aliases"), ("B", "b")),
        clay_fraction_aliases=normalize_aliases_param(params.get("clay_fraction_aliases"), ("CF",)),
        porosity_aliases=normalize_aliases_param(params.get("porosity_aliases"), ("porosity", "Porosity")),
        landcover_aliases=normalize_aliases_param(params.get("landcover_aliases"), ("LC", "IGBP_9km_12")),
        ndvi_v_max_aliases=normalize_aliases_param(params.get("ndvi_v_max_aliases"), ("NDVI_v_max",)),
        ndvi_v_min_aliases=normalize_aliases_param(params.get("ndvi_v_min_aliases"), ("NDVI_v_min",)),
        h_static_aliases=normalize_aliases_param(params.get("h_static_aliases"), ("H", "h")),
        dh_aliases=normalize_aliases_param(params.get("dh_aliases"), ("DH_mat", "DH", "dh_mat")),
    )


def normalize_date_keys(value: Any, fallback_count: int | None = None) -> list[str]:
    import numpy as np

    if value is None:
        if fallback_count is None:
            return []
        return [f"day_{index + 1:04d}" for index in range(fallback_count)]

    array = np.asarray(value)
    if array.ndim == 0:
        return [str(array.item())]
    flat = array.reshape(-1)
    result: list[str] = []
    for item in flat:
        text = str(item).strip()
        if text:
            result.append(text)
    return result


def _broadcast_matrix(value: Any, target_shape: tuple[int, int], *, name: str) -> Any:
    import numpy as np

    array = np.asarray(value, dtype=np.float64)
    if array.shape == target_shape:
        return array
    if array.ndim == 0:
        return np.full(target_shape, array.item(), dtype=np.float64)
    if array.ndim == 1:
        if array.size == target_shape[1]:
            return np.broadcast_to(array.reshape(1, target_shape[1]), target_shape).astype(np.float64, copy=False)
        if array.size == target_shape[0]:
            return np.broadcast_to(array.reshape(target_shape[0], 1), target_shape).astype(np.float64, copy=False)
        if array.size == target_shape[0] * target_shape[1]:
            return array.reshape(target_shape)
    if array.ndim == 2:
        try:
            return np.broadcast_to(array, target_shape).astype(np.float64, copy=False)
        except ValueError:
            pass
    raise ValueError(f"Cannot broadcast {name} from shape {array.shape} to {target_shape}")


def _as_time_pixel_matrix(value: Any, *, name: str, target_shape: tuple[int, int] | None = None) -> Any:
    import numpy as np

    array = np.asarray(value, dtype=np.float64)
    if array.ndim == 0:
        array = array.reshape(1, 1)
    elif array.ndim == 1:
        array = array.reshape(1, -1)
    elif array.ndim != 2:
        raise ValueError(f"{name} must be a scalar, 1-D, or 2-D array; got shape {array.shape}")
    if target_shape is None:
        return array
    return _broadcast_matrix(array, target_shape, name=name)


def _as_static_vector(value: Any, pixel_count: int, *, name: str) -> Any:
    import numpy as np

    array = np.asarray(value, dtype=np.float64).reshape(-1)
    if array.size == pixel_count:
        return array
    if array.size == 1:
        return np.full(pixel_count, float(array[0]), dtype=np.float64)
    raise ValueError(f"{name} must contain 1 or {pixel_count} values; got {array.size}")


def load_h_matrix(
    payload: dict[str, Any],
    field_config: BlockFieldConfig,
    *,
    dh_mat_path: str | Path | None = None,
    fallback_h: Any | None = None,
    nt: int | None = None,
) -> Any:
    import numpy as np

    if dh_mat_path is not None:
        dh_payload = load_mat_file(dh_mat_path)
        return np.asarray(get_first_available(dh_payload, list(field_config.dh_aliases)), dtype=np.float64)

    try:
        return np.asarray(get_first_available(payload, list(field_config.dh_aliases)), dtype=np.float64)
    except KeyError:
        if fallback_h is None:
            raise
        base = np.asarray(fallback_h, dtype=np.float64).reshape(-1)
        if nt is None:
            return base
        return np.repeat(base[None, :], nt, axis=0)


def execute_block_inversion(
    payload: dict[str, Any],
    *,
    mode: str,
    freq_ghz: float,
    pixel_chunk_size: int = 2000,
    dh_mat_path: str | Path | None = None,
    field_config: BlockFieldConfig | None = None,
) -> dict[str, Any]:
    import numpy as np

    field_config = field_config or BlockFieldConfig()

    tbv_mat = _as_time_pixel_matrix(
        get_first_available(payload, list(field_config.tbv_mat_aliases)),
        name="tbv_mat",
    )
    nt, npix = tbv_mat.shape
    target_shape = (nt, npix)
    tbh_mat = _as_time_pixel_matrix(
        get_first_available(payload, list(field_config.tbh_mat_aliases)),
        name="tbh_mat",
        target_shape=target_shape,
    )
    ia_mat = _as_time_pixel_matrix(
        get_first_available(payload, list(field_config.ia_mat_aliases)),
        name="ia_mat",
        target_shape=target_shape,
    )
    ts_mat = _as_time_pixel_matrix(
        get_first_available(payload, list(field_config.ts_mat_aliases)),
        name="ts_mat",
        target_shape=target_shape,
    )
    ndvi_mat = _as_time_pixel_matrix(
        get_first_available(payload, list(field_config.ndvi_mat_aliases)),
        name="ndvi_mat",
        target_shape=target_shape,
    )
    sf_mat = _as_time_pixel_matrix(
        get_first_available(payload, list(field_config.sf_mat_aliases)),
        name="sf_mat",
        target_shape=target_shape,
    )

    albedo = _as_static_vector(get_first_available(payload, list(field_config.albedo_aliases)), npix, name="albedo")
    b_param = _as_static_vector(get_first_available(payload, list(field_config.b_aliases)), npix, name="b_param")
    clay_fraction = _as_static_vector(
        get_first_available(payload, list(field_config.clay_fraction_aliases)),
        npix,
        name="clay_fraction",
    )
    porosity = _as_static_vector(get_first_available(payload, list(field_config.porosity_aliases)), npix, name="porosity")
    landcover = _as_static_vector(get_first_available(payload, list(field_config.landcover_aliases)), npix, name="landcover")
    ndvi_v_max = _as_static_vector(
        get_first_available(payload, list(field_config.ndvi_v_max_aliases)),
        npix,
        name="ndvi_v_max",
    )
    ndvi_v_min = _as_static_vector(
        get_first_available(payload, list(field_config.ndvi_v_min_aliases)),
        npix,
        name="ndvi_v_min",
    )
    static_h = _as_static_vector(get_first_available(payload, list(field_config.h_static_aliases)), npix, name="static_h")
    tau_ini_mat = np.full((nt, npix), np.nan, dtype=np.float64)
    results: dict[str, Any] = {
        "Tau_ini_mat": tau_ini_mat,
        "date_keys": normalize_date_keys(payload.get("date_keys"), fallback_count=nt),
        "missing_dates": normalize_date_keys(payload.get("missing_dates")),
    }

    if mode == "dh":
        dh_mat = np.full((nt, npix), np.nan, dtype=np.float64)
        results["DH_mat"] = dh_mat
    elif mode == "ddca":
        h_mat = load_h_matrix(payload, field_config, dh_mat_path=dh_mat_path, fallback_h=static_h, nt=nt)
        sm_mat = np.full((nt, npix), np.nan, dtype=np.float64)
        vod_mat = np.full((nt, npix), np.nan, dtype=np.float64)
        results["H_used_mat"] = h_mat
        results["SM_mat"] = sm_mat
        results["VOD_mat"] = vod_mat
    else:
        raise ValueError(f"Unsupported block inversion mode: {mode}")

    chunk_size = max(1, int(pixel_chunk_size))
    for start in range(0, npix, chunk_size):
        end = min(start + chunk_size, npix)
        cols = slice(start, end)

        tau_chunk = tau_from_ndvi(
            ndvi=ndvi_mat[:, cols],
            ndvi_max=ndvi_v_max[cols],
            ndvi_min=ndvi_v_min[cols],
            landcover=landcover[cols],
            b_param=b_param[cols],
            stem_factor=sf_mat[:, cols],
            theta_deg=ia_mat[:, cols],
        )
        tau_ini_mat[:, cols] = tau_chunk

        for day_index in range(nt):
            if mode == "dh":
                results["DH_mat"][day_index, cols] = retrieve_dynamic_h_grid(
                    tbv_mat[day_index, cols],
                    tbh_mat[day_index, cols],
                    ts_mat[day_index, cols],
                    tau_chunk[day_index, :],
                    clay_fraction[cols],
                    albedo[cols],
                    porosity[cols],
                    freq_ghz,
                    ia_mat[day_index, cols],
                )
            else:
                sm_day, vod_day = ddca_retrieve_grid(
                    tbv_mat[day_index, cols],
                    tbh_mat[day_index, cols],
                    ts_mat[day_index, cols],
                    tau_chunk[day_index, :],
                    results["H_used_mat"][day_index, cols],
                    clay_fraction[cols],
                    albedo[cols],
                    porosity[cols],
                    freq_ghz,
                    ia_mat[day_index, cols],
                )
                results["SM_mat"][day_index, cols] = sm_day
                results["VOD_mat"][day_index, cols] = vod_day

    return results
