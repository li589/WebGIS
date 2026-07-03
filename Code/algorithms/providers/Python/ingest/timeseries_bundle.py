from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ingest.daily_bundle import (
    DailyBundleConfig,
    build_daily_bundle_for_date,
    date_keys_from_range,
    load_static_ancillary_bundle,
)


@dataclass(frozen=True, slots=True)
class TimeSeriesBundle:
    date_keys: list[str]
    data: dict[str, Any]
    missing_dates: list[str]
    pixel_count: int


def build_timeseries_bundle(
    date_keys: list[str],
    config: DailyBundleConfig,
    datasource_selection: dict[str, Any],
    *,
    lin_pix: list[int] | None = None,
) -> TimeSeriesBundle:
    import numpy as np

    static_bundle = load_static_ancillary_bundle(
        datasource_selection["anc_root"],
        config,
        lin_pix=lin_pix,
        ndvi_extrema_mat=datasource_selection.get("ndvi_extrema_mat"),
    )
    pixel_count = int(np.asarray(static_bundle["LC"]).reshape(-1).size)
    nt = len(date_keys)

    tbv_mat = np.full((nt, pixel_count), np.nan, dtype=np.float64)
    tbh_mat = np.full((nt, pixel_count), np.nan, dtype=np.float64)
    ia_mat = np.full((nt, pixel_count), np.nan, dtype=np.float64)
    ts_mat = np.full((nt, pixel_count), np.nan, dtype=np.float64)
    tc_mat = np.full((nt, pixel_count), np.nan, dtype=np.float64)
    tsoil1_mat = np.full((nt, pixel_count), np.nan, dtype=np.float64)
    tsoil2_mat = np.full((nt, pixel_count), np.nan, dtype=np.float64)
    ct_mat = np.full((nt, pixel_count), np.nan, dtype=np.float64)
    tg_mat = np.full((nt, pixel_count), np.nan, dtype=np.float64)
    match_slot_index_mat = np.full((nt, pixel_count), np.nan, dtype=np.float64)
    match_day_offset_mat = np.full((nt, pixel_count), np.nan, dtype=np.float64)
    match_picked_file_mat = np.full((nt, pixel_count), "", dtype=object)
    match_picked_utc_mat = np.full((nt, pixel_count), "", dtype=object)
    smref_mat = np.full((nt, pixel_count), np.nan, dtype=np.float64)
    ndvi_mat = np.full((nt, pixel_count), np.nan, dtype=np.float64)
    sf_mat = np.full((nt, pixel_count), np.nan, dtype=np.float64)
    vwc_mat = np.full((nt, pixel_count), np.nan, dtype=np.float64)

    missing_dates: list[str] = []

    for index, date_key in enumerate(date_keys):
        try:
            bundle = build_daily_bundle_for_date(
                date_key=date_key,
                config=config,
                datasource_selection=datasource_selection,
                lin_pix=lin_pix,
            )
        except FileNotFoundError:
            missing_dates.append(date_key)
            continue

        tbv_mat[index, :] = np.asarray(bundle["TBv"], dtype=np.float64).reshape(-1)
        tbh_mat[index, :] = np.asarray(bundle["TBh"], dtype=np.float64).reshape(-1)
        ia_value = bundle.get("IA")
        ts_value = bundle.get("Ts")
        tc_value = bundle.get("TC")
        tsoil1_value = bundle.get("Tsoil1")
        tsoil2_value = bundle.get("Tsoil2")
        ct_value = bundle.get("Ct")
        tg_value = bundle.get("TG")
        match_slot_index_value = bundle.get("match_slot_index")
        match_day_offset_value = bundle.get("match_day_offset")
        match_picked_file_value = bundle.get("match_picked_file")
        match_picked_utc_value = bundle.get("match_picked_utc")
        smref_value = bundle.get("SM_ref")
        ndvi_value = bundle.get("NDVI")
        sf_value = bundle.get("SF")
        vwc_value = bundle.get("vwc")

        if ia_value is not None:
            ia_mat[index, :] = np.asarray(ia_value, dtype=np.float64).reshape(-1)
        if ts_value is not None:
            ts_mat[index, :] = np.asarray(ts_value, dtype=np.float64).reshape(-1)
        if tc_value is not None:
            tc_mat[index, :] = np.asarray(tc_value, dtype=np.float64).reshape(-1)
        if tsoil1_value is not None:
            tsoil1_mat[index, :] = np.asarray(tsoil1_value, dtype=np.float64).reshape(-1)
        if tsoil2_value is not None:
            tsoil2_mat[index, :] = np.asarray(tsoil2_value, dtype=np.float64).reshape(-1)
        if ct_value is not None:
            ct_mat[index, :] = np.asarray(ct_value, dtype=np.float64).reshape(-1)
        if tg_value is not None:
            tg_mat[index, :] = np.asarray(tg_value, dtype=np.float64).reshape(-1)
        if match_slot_index_value is not None:
            match_slot_index_mat[index, :] = np.asarray(match_slot_index_value, dtype=np.float64).reshape(-1)
        if match_day_offset_value is not None:
            match_day_offset_mat[index, :] = np.asarray(match_day_offset_value, dtype=np.float64).reshape(-1)
        if match_picked_file_value is not None:
            match_picked_file_mat[index, :] = np.asarray(match_picked_file_value, dtype=object).reshape(-1)
        if match_picked_utc_value is not None:
            match_picked_utc_mat[index, :] = np.asarray(match_picked_utc_value, dtype=object).reshape(-1)
        if smref_value is not None:
            smref_mat[index, :] = np.asarray(smref_value, dtype=np.float64).reshape(-1)
        if ndvi_value is not None:
            ndvi_mat[index, :] = np.asarray(ndvi_value, dtype=np.float64).reshape(-1)
        if sf_value is not None:
            sf_mat[index, :] = np.asarray(sf_value, dtype=np.float64).reshape(-1)
        if vwc_value is not None:
            vwc_mat[index, :] = np.asarray(vwc_value, dtype=np.float64).reshape(-1)

    data = {
        "date_keys": date_keys,
        "TBv_mat": tbv_mat,
        "TBh_mat": tbh_mat,
        "IA_mat": ia_mat,
        "Ts_mat": ts_mat,
        "TC_mat": tc_mat,
        "Tsoil1_mat": tsoil1_mat,
        "Tsoil2_mat": tsoil2_mat,
        "Ct_mat": ct_mat,
        "TG_mat": tg_mat,
        "match_slot_index_mat": match_slot_index_mat,
        "match_day_offset_mat": match_day_offset_mat,
        "match_picked_file_mat": match_picked_file_mat,
        "match_picked_utc_mat": match_picked_utc_mat,
        "SMref_mat": smref_mat,
        "NDVI_mat": ndvi_mat,
        "SF_mat": sf_mat,
        "vwc_mat": vwc_mat,
        "Albedo": static_bundle["Albedo"],
        "B": static_bundle["B"],
        "CF": static_bundle["CF"],
        "BD": static_bundle["BD"],
        "H": static_bundle["H"],
        "porosity": static_bundle["porosity"],
        "LC": static_bundle["LC"],
        "NDVI_v_max": static_bundle["NDVI_v_max"],
        "NDVI_v_min": static_bundle["NDVI_v_min"],
        "lat_9km": static_bundle["lat_9km"],
        "lon_9km": static_bundle["lon_9km"],
    }
    return TimeSeriesBundle(
        date_keys=date_keys,
        data=data,
        missing_dates=missing_dates,
        pixel_count=pixel_count,
    )


def build_timeseries_bundle_from_range(
    start_time: Any,
    end_time: Any,
    config: DailyBundleConfig,
    datasource_selection: dict[str, Any],
    *,
    lin_pix: list[int] | None = None,
) -> TimeSeriesBundle:
    date_keys = date_keys_from_range(start_time, end_time)
    return build_timeseries_bundle(
        date_keys=date_keys,
        config=config,
        datasource_selection=datasource_selection,
        lin_pix=lin_pix,
    )
