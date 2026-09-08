# Workflow smoke matrix

- Generated: 2026-08-07 00:21 中国标准时间
- API: http://127.0.0.1:8000
- DATA_ROOT: I:\Geograph_DataSet
- Definitions listed: 24

## Matrix

| batch | workflow_id | run_id | status | elapsed_s | blocker / detail |
|-------|-------------|--------|--------|-----------|------------------|
| A | `weather/tiles/temperature` | `` | succeeded | 1.54 | HTTP 200 bytes=99693 |
| A | `weather/tiles/wind-field` | `` | succeeded | 1.37 | HTTP 200 bytes=71792 |
| B | `weather_temperature_grid_demo` | `run-a59b84f7db82` | succeeded | 22.24 |  |
| B | `weather_wind_field_demo` | `run-cbe51ba50297` | succeeded | 20.22 |  |
| C | `raster_histogram_basic` | `run-b771749bd8f0` | succeeded | 4.05 |  |
| C | `raster_timeseries_curve` | `run-4ffa210913d8` | succeeded | 2.05 |  |
| C | `raster_zonal_stats_aligned` | `run-58b438675b59` | succeeded | 2.01 |  |
| D | `smap_soil_moisture_local` | `run-de9763a6c0a2` | succeeded | 2.05 |  |
| D | `open_data_noaa_grib_sample` | `run-1aa13b1cc19b` | failed | 12.15 | run_failed |
| E | `open_data_nasa_earthdata_sample` | `run-42038cf12a79` | succeeded | 4.04 |  |
| E | `open_data_nsidc_smap_sample` | `` | skipped | 0.0 | blocked:runtime (Earthdata ready; NSIDC SMAP granules too large for light smoke — needs curated small path) |
| E | `open_data_esa_product_sample` | `` | skipped | 0.0 | blocked:creds (copernicus profile) + REPLACE_* path |
| F | `omega_block_smap_single` | `run-badd58750590` | timeout | 1200.83 | timeout |
| F | `omega_avg_daily_smap_single` | `run-252870bf0eb0` | succeeded | 274.42 |  |
| F | `omega_avg_daily_fy_single` | `run-b52c5ba614fa` | succeeded | 600.96 |  |
| F | `omega_avg_daily_smap_dual` | `run-75da6a8d1733` | succeeded | 306.71 |  |
| F | `omega_avg_daily_smap_online` | `` | skipped | 0.0 | blocked:config (online download template + needs h5→mat bridge; earthdata portal ready; not light-smoke) |
| F | `omega_avg_daily_gldas_online` | `run-ebda2953191e` | failed | 405.31 | run_failed |
| F | `omega_sf_fenkuai_smap_single` | `run-dae33bc7a16e` | succeeded | 312.36 |  |
| F | `omega_sf_fenkuai_fy_single` | `run-c4b28b59fc8e` | succeeded | 291.67 |  |

## Notes

- Batch A is weather tile hot path (not a system seed).
- Open-data seeds with `REPLACE_*` placeholders were skipped as `blocked:config` / `blocked:creds` (no forged portal paths).
- `raster_histogram_basic` used temp GeoTIFF under `{DATA_ROOT}/_runtime/smoke_hist.tif`.
- `smap_soil_moisture_local` path overridden to `Soil_Moisture/SMAP` (seed default `{DATA_ROOT}/SMAP` missing).
- `omega_block_smap_single` time window overridden to 2025-11-01..02 to match available local mats (seed default Dec 2025).
- Heavy omega chains may fail for missing GLDAS / online deps; recorded without inventing production datasets.

