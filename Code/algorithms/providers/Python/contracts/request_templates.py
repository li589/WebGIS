from __future__ import annotations

from dataclasses import dataclass, field

from contracts.job import JobRequest


@dataclass(frozen=True, slots=True)
class RequestTemplateSpec:
    entry_kind: str
    entry_name: str
    required_datasource_keys: tuple[str, ...] = ()
    accepted_data_access_datasets: tuple[str, ...] = ()
    accepted_data_access_by_required_key: dict[str, tuple[str, ...]] = field(default_factory=dict)
    optional_datasource_keys: tuple[str, ...] = ()
    required_algorithm_keys: tuple[str, ...] = ()
    optional_algorithm_keys: tuple[str, ...] = ()
    allowed_task_types: tuple[str, ...] = ()
    allowed_algorithm_values: dict[str, tuple[object, ...]] = field(default_factory=dict)
    notes: str | None = None


MODULE_REQUEST_TEMPLATES: dict[str, RequestTemplateSpec] = {
    "daily_bundle": RequestTemplateSpec(
        entry_kind="module",
        entry_name="daily_bundle",
        accepted_data_access_datasets=(
            "anc_root",
            "ancillary_mat",
            "smap_daily_mat",
            "ndvi_daily_mat",
            "ndvi_clim_folder",
            "fy3b_folder",
            "fy3d_folder",
            "lin_pix_mat",
            "ndvi_extrema_mat",
            "ddca_sm_folder",
        ),
        optional_datasource_keys=("lin_pix_mat",),
        optional_algorithm_keys=("lin_pix", "lin_pix_varname", "tb_source", "sm_source", "ndvi_mode", "sf_mode", "temp_scheme"),
        allowed_task_types=("daily_bundle", "workflow"),
    ),
    "timeseries_bundle": RequestTemplateSpec(
        entry_kind="module",
        entry_name="timeseries_bundle",
        accepted_data_access_datasets=(
            "daily_mat_sources",
            "ancillary_mat",
            "smap_daily_mat",
            "ndvi_daily_mat",
            "ndvi_clim_folder",
            "fy3b_folder",
            "fy3d_folder",
            "lin_pix_mat",
            "ndvi_extrema_mat",
            "ddca_sm_folder",
        ),
        optional_datasource_keys=("lin_pix_mat",),
        optional_algorithm_keys=("lin_pix", "lin_pix_varname", "tb_source", "sm_source", "ndvi_mode", "sf_mode", "temp_scheme"),
        allowed_task_types=("timeseries_bundle", "workflow"),
    ),
    "ndvi_daily": RequestTemplateSpec(
        entry_kind="module",
        entry_name="ndvi_daily",
        required_datasource_keys=("input_dir",),
        accepted_data_access_datasets=("NDVI_16DAY_RASTER",),
        accepted_data_access_by_required_key={"input_dir": ("NDVI_16DAY_RASTER",)},
        optional_datasource_keys=("ndvi_clim_dir", "ndvi_clim_folder"),
        optional_algorithm_keys=("emit_quality_products", "sg_step_days", "daily_step_days", "gap_threshold_days", "sg_polyorder", "sg_window_length"),
        allowed_task_types=("ndvi_daily", "workflow"),
    ),
    "smap_daily": RequestTemplateSpec(
        entry_kind="module",
        entry_name="smap_daily",
        required_datasource_keys=("input_dir",),
        accepted_data_access_datasets=("SMAP_SPL3SMP_E",),
        accepted_data_access_by_required_key={"input_dir": ("SMAP_SPL3SMP_E",)},
        allowed_task_types=("smap_daily", "workflow"),
    ),
    "station_daily": RequestTemplateSpec(
        entry_kind="module",
        entry_name="station_daily",
        required_datasource_keys=("input_dir",),
        accepted_data_access_datasets=("ISMN_STM_OR_CASMOS_TXT",),
        accepted_data_access_by_required_key={"input_dir": ("ISMN_STM_OR_CASMOS_TXT",)},
        optional_datasource_keys=("site_info_csv", "smap_grid_mat", "landcover_mat", "climate_mat", "network_map_csv"),
        optional_algorithm_keys=(
            "source_type",
            "emit_validation_products",
            "validation_start",
            "validation_end",
            "validation_min_valid_days",
            "validation_hour",
            "validation_network_groups",
            "validation_min_sm",
            "validation_max_sm",
        ),
        allowed_task_types=("station_daily", "workflow"),
    ),
    "fy_daily": RequestTemplateSpec(
        entry_kind="module",
        entry_name="fy_daily",
        required_datasource_keys=("input_dir",),
        accepted_data_access_datasets=("FY_MWRI_HDF",),
        accepted_data_access_by_required_key={"input_dir": ("FY_MWRI_HDF",)},
        optional_algorithm_keys=("orbit_mode", "band_ids", "overlap_option", "spatial_mode", "gdal_bin", "execute_commands"),
        allowed_task_types=("fy_daily", "workflow"),
        allowed_algorithm_values={
            "orbit_mode": ("MWRID", "MWRIA", "Both"),
        },
    ),
    "inversion_daily": RequestTemplateSpec(
        entry_kind="module",
        entry_name="inversion_daily",
        required_datasource_keys=("input_mat",),
        accepted_data_access_datasets=("daily_bundle_mat",),
        accepted_data_access_by_required_key={"input_mat": ("daily_bundle_mat",)},
        optional_algorithm_keys=("freq_ghz",),
        allowed_task_types=("inversion_daily", "workflow"),
        allowed_algorithm_values={"mode": ("dh", "ddca")},
    ),
    "block_inversion": RequestTemplateSpec(
        entry_kind="module",
        entry_name="block_inversion",
        required_datasource_keys=("input_mat",),
        accepted_data_access_datasets=("timeseries_bundle_mat",),
        accepted_data_access_by_required_key={"input_mat": ("timeseries_bundle_mat",)},
        optional_datasource_keys=("dh_mat",),
        optional_algorithm_keys=("freq_ghz", "pixel_chunk_size", "write_daily_files"),
        allowed_task_types=("block_inversion", "retrieval", "workflow"),
        allowed_algorithm_values={"mode": ("dh", "ddca")},
    ),
    "omega_block": RequestTemplateSpec(
        entry_kind="module",
        entry_name="omega_block",
        required_datasource_keys=("input_mat",),
        accepted_data_access_datasets=("timeseries_bundle_mat",),
        accepted_data_access_by_required_key={"input_mat": ("timeseries_bundle_mat",)},
        optional_datasource_keys=("omega_fixed_mat", "exp0_calib_mat"),
        optional_algorithm_keys=("freq_ghz", "temp_scheme", "exp_mode", "write_daily_files"),
        allowed_task_types=("omega_block", "retrieval", "workflow"),
        allowed_algorithm_values={"exp_mode": ("Exp0", "EXP1A", "EXP1B", "EXP2")},
    ),
}


def get_module_request_template(name: str) -> RequestTemplateSpec | None:
    return MODULE_REQUEST_TEMPLATES.get(name)


def build_workflow_request_template(name: str, request: JobRequest) -> RequestTemplateSpec | None:
    if name != "retrieval_workflow":
        return None
    mode = str(request.algorithm_params.get("mode", "dh")).lower()
    required_inputs: list[str] = []
    optional_inputs = ["dh_mat"]
    if mode == "omega":
        required_inputs.extend(["omega_fixed_mat", "exp0_calib_mat"])
    return RequestTemplateSpec(
        entry_kind="workflow",
        entry_name="retrieval_workflow",
        required_datasource_keys=tuple(required_inputs),
        accepted_data_access_datasets=("timeseries_bundle_mat", "omega_fixed_mat", "exp0_calib_mat", "dh_mat"),
        accepted_data_access_by_required_key={
            "omega_fixed_mat": ("omega_fixed_mat",),
            "exp0_calib_mat": ("exp0_calib_mat",),
        },
        optional_datasource_keys=tuple(optional_inputs),
        optional_algorithm_keys=("mode", "freq_ghz", "pixel_chunk_size", "write_daily_files", "exp_mode"),
        allowed_task_types=("retrieval", "workflow", "retrieval_workflow"),
        allowed_algorithm_values={"mode": ("dh", "ddca", "omega")},
        notes="Retrieval workflow switches downstream module by algorithm_params.mode.",
    )
