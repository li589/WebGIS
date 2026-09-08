# Workflow smoke matrix

- Generated: 2026-08-11 03:34 中国标准时间
- API: http://127.0.0.1:8000
- DATA_ROOT: I:\Geograph_DataSet
- Definitions listed: 36

## Matrix

| batch | workflow_id | run_id | status | elapsed_s | blocker / detail |
|-------|-------------|--------|--------|-----------|------------------|
| A | `weather/tiles/temperature` | `` | succeeded | 1.5 | HTTP 200 bytes=99690 |
| A | `weather/tiles/wind-field` | `` | succeeded | 1.54 | HTTP 200 bytes=71801 |
| B | `weather_temperature_grid_demo` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'layer_id', 'resource_profile', 'weather_request', 'map_context'] |
| B | `weather_wind_field_demo` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'layer_id', 'resource_profile', 'weather_request', 'map_context'] |
| C | `raster_histogram_basic` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| C | `raster_timeseries_curve` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| C | `raster_zonal_stats_aligned` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| D | `smap_soil_moisture_local` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| D | `open_data_noaa_grib_sample` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| E | `open_data_nasa_earthdata_sample` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| E | `open_data_nsidc_smap_sample` | `` | skipped | 0.0 | blocked:runtime (Earthdata ready; NSIDC SMAP granules too large for light smoke — needs curated small path) |
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
| G | `gis_raster_calc_reclassify_basic` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| G | `gis_buffer_zonal_basic` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| G | `stats_mean_summary_report_basic` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| G | `fusion_idw_interpolate_basic` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'spatial_filter', 'resource_profile'] |
| H | `preprocess_mask_resample_basic` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| H | `gis_vector_raster_roundtrip_basic` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'spatial_filter', 'resource_profile'] |
| H | `gis_contour_slope_basic` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| H | `stats_trend_anomaly_basic` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| H | `fusion_multi_source_merge_basic` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| I | `gis_watershed_basic` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| I | `stats_correlation_basic` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| I | `stats_correlation_report_basic` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |
| I | `stats_summary_chart_basic` | `` | dry_run | 0.0 | payload_keys=['command_type', 'command_label', 'parameters', 'requested_outputs', 'client', 'algorithm_request', 'time_range', 'resource_profile'] |

## Notes

- Batch A is weather tile hot path (not a system seed).
- Open-data seeds with `REPLACE_*` placeholders were skipped as `blocked:config` / `blocked:creds` (no forged portal paths), except `open_data_noaa_grib_sample` (live NOMADS filter probe) and `open_data_nasa_earthdata_sample` (LP DAAC browse download-only).
- `raster_histogram_basic` used temp GeoTIFF under `{DATA_ROOT}/_runtime/smoke_hist.tif`.
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

