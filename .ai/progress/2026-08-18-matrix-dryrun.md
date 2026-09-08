# Workflow smoke matrix

- Generated: 2026-08-18 13:02 中国标准时间
- API: http://127.0.0.1:8000
- DATA_ROOT: I:\Geograph_DataSet
- Definitions listed: 42

## Matrix

| batch | workflow_id | run_id | status | elapsed_s | blocker / detail |
|-------|-------------|--------|--------|-----------|------------------|
| B | `weather_temperature_grid_demo` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'layer_id', 'resource_profile', 'weather_request', 'map_context'] |
| B | `weather_wind_field_demo` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'layer_id', 'resource_profile', 'weather_request', 'map_context'] |
| C | `analysis_histogram` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| C | `raster_timeseries_curve` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| C | `raster_zonal_stats_aligned` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| D | `smap_soil_moisture_local` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| D | `open_data_noaa_grib_sample` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| E | `open_data_nasa_earthdata_sample` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| E | `open_data_nsidc_smap_sample` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| E | `open_data_esa_product_sample` | `` | skipped | 0.0 | blocked:creds (copernicus profile) + REPLACE_* path |
| F | `omega_block_smap_single` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| F | `omega_avg_daily_smap_single` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| F | `omega_avg_daily_fy_single` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| F | `omega_avg_daily_smap_dual` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| F | `omega_avg_daily_smap_online` | `` | skipped | 0.0 | blocked:config (online download template + needs h5→mat bridge; earthdata portal ready; not light-smoke) |
| F | `omega_avg_daily_gldas_online` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| F | `omega_sf_fenkuai_smap_single` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'spatial_filter', 'resource_profile'] |
| F | `omega_sf_fenkuai_fy_single` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'spatial_filter', 'resource_profile'] |
| G | `preprocess_clip_reproject_basic` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'spatial_filter', 'resource_profile'] |
| G | `stats_mean_summary_report_basic` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| G | `fusion_idw_interpolate_basic` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'spatial_filter', 'resource_profile'] |
| H | `preprocess_mask_resample_basic` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| H | `stats_trend_anomaly_basic` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| H | `fusion_multi_source_merge_basic` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| I | `stats_correlation_basic` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| I | `stats_correlation_report_basic` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| I | `stats_summary_chart_basic` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| X | `analysis_buffer` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| X | `analysis_clip` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'spatial_filter', 'resource_profile'] |
| X | `analysis_contour` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| X | `analysis_raster_calc` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| X | `analysis_raster_to_vector` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| X | `analysis_reclassify` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| X | `analysis_slope_aspect` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| X | `analysis_vector_to_raster` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| X | `analysis_watershed` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| X | `analysis_zonal_stats` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| X | `cds_era5_reanalysis_download` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| X | `cdse_sentinel_download` | `` | skipped | 0.0 | blocked:creds (no copernicus portal account) |
| X | `fy_tb_local_read` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| X | `fy_tb_online_read` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| X | `ndvi_gee_read` | `` | skipped | 0.0 | blocked:gee-not-configured (accounts=0 enabled=0) |
| X | `ndvi_local_read` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| X | `ndvi_online_read` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| X | `nomads_gfs_grib_download` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| X | `omega_avg_daily_fy_online` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| X | `omega_sf_fenkuai_fy_dual` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'spatial_filter', 'resource_profile'] |
| X | `omega_sf_fenkuai_fy_online` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'spatial_filter', 'resource_profile'] |
| X | `omega_sf_fenkuai_smap_dual` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'spatial_filter', 'resource_profile'] |
| X | `omega_sf_fenkuai_smap_online` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'spatial_filter', 'resource_profile'] |

## Notes

- Batch A is weather tile hot path (not a system seed).
- Batch X = every system seed not in a hardcoded batch; runner
  mappings patch dates/paths per seed (directory scan is the
  source of truth, batches are ordering hints only).
- Template seeds with `{YYYYMMDD}` / `{YYYY-MM-DD}` date
  placeholders get concrete windows patched at submit time
  (cds/cdse/nomads/ndvi_online/fy_online heads).
- Cred-gated seeds (cds/cdse/nsmc/earthdata heads) are skipped
  as `blocked:creds` when the portal store + env are empty;
  `ndvi_gee_read` probes GEE accounts and skips as
  `blocked:gee-not-configured` when none are enabled.
- `fy_tb_local_read` / `ndvi_local_read` run on synthetic
  fixtures under `{DATA_ROOT}/_runtime/synthetic/` (seed default
  paths `{DATA_ROOT}/FY` / `{DATA_ROOT}/NDVI` have no local data).
- Open-data seeds with `REPLACE_*` placeholders were skipped as `blocked:config` / `blocked:creds` (no forged portal paths), except `open_data_noaa_grib_sample` (live NOMADS filter probe) and `open_data_nasa_earthdata_sample` (LP DAAC browse download-only).
- `analysis_histogram` used temp GeoTIFF under `{DATA_ROOT}/_runtime/smoke_hist.tif`.
- `smap_soil_moisture_local` path overridden to `Soil_Moisture/SMAP` (seed default `{DATA_ROOT}/SMAP` missing).
- `omega_block_smap_single` time window overridden to 2025-11-01..02 to match available local mats (seed default Dec 2025).
- `omega_avg_daily` Stage D light-smoke cap enabled (max 5 days) to avoid 365-day long runtimes / OOM.
- Heavy omega chains may fail for missing GLDAS / online deps; recorded without inventing production datasets.

## Verified today (ABCD sprint)

- D1/D2 graph path: `omega_block_*` / `omega_avg_daily_*` submit compiled `workflow_definition` (no smoke flatten).
- fenkuai + `output_map_layer`: SMAP/FY light-smoke keep map_layer (manifest→data accepted).
- NOAA: cfgrib+eccodes available locally → `http_open_data→variable_extract` (`t2m`); CGI `.pl` cache sniff/rename.
- NASA Earthdata: download-only LP DAAC browse JPG.
- `output_map_layer` ArtifactRef-on-`data` fix remains in effect.

## Follow-ups remaining

1. `open_data_nsidc_*` / `esa_*` / `omega_avg_daily_smap_online` (large granules / Copernicus / h5→mat).
2. HPC paper template sync (tunnel/direct still blocked).
3. `omega_avg_daily_gldas_online` may fail when worker lacks Earthdata username/password even if portal token exists in UI.

