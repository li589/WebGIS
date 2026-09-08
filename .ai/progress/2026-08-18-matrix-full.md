# Workflow smoke matrix

- Generated: 2026-08-18 13:33 中国标准时间
- API: http://127.0.0.1:8000
- DATA_ROOT: I:\Geograph_DataSet
- Definitions listed: 42

## Matrix

| batch | workflow_id | run_id | status | elapsed_s | blocker / detail |
|-------|-------------|--------|--------|-----------|------------------|
| A | `weather/tiles/temperature` | `` | succeeded | 1.43 | HTTP 200 bytes=99699 |
| A | `weather/tiles/wind-field` | `` | succeeded | 1.35 | HTTP 200 bytes=71789 |
| B | `weather_temperature_grid_demo` | `run-3fa2dc54f4c1` | succeeded | 10.14 |  |
| B | `weather_wind_field_demo` | `run-541b3dc57951` | succeeded | 8.11 |  |
| C | `analysis_histogram` | `run-268732b3c2b9` | succeeded | 6.11 |  |
| C | `raster_timeseries_curve` | `run-2e586fc0c3ff` | succeeded | 2.05 |  |
| C | `raster_zonal_stats_aligned` | `run-f9f42f9fc99f` | succeeded | 2.05 |  |
| D | `smap_soil_moisture_local` | `run-07a50681a756` | succeeded | 2.06 |  |
| D | `open_data_noaa_grib_sample` | `run-60487d30c161` | succeeded | 6.1 | NOMADS GFS filter gfs.20260818/00 http_open_data→variable_extract (t2m; archive skipped; cfgrib ok) |
| E | `open_data_nasa_earthdata_sample` | `run-dfd4778e4fbd` | failed | 16.16 | run_failed NASA LP DAAC MCD43A4 browse jpg (public) download-only (archive/extract/variable skipped) |
| E | `open_data_nsidc_smap_sample` | `run-3bf08c0409a4` | failed | 12.15 | run_failed |
| E | `open_data_esa_product_sample` | `` | skipped | 0.0 | blocked:creds (copernicus profile) + REPLACE_* path |
| F | `omega_block_smap_single` | `run-92e2ca5015d0` | succeeded | 401.89 | time_range overridden to 2025-11-01..02 (available mats); compiled graph timeseries_bundle → omega_block |
| F | `omega_avg_daily_smap_single` | `run-e11759d2d33e` | succeeded | 6.1 | compiled graph → omega_avg_daily; time_range→2025-12-03..05; parallel disabled for smoke; Stage D limited to 2025-12-07..11 (max 5 days) |
| F | `omega_avg_daily_fy_single` | `run-4b2bc21bd16a` | succeeded | 6.09 | compiled graph → omega_avg_daily; time_range→2025-12-03..05; parallel disabled for smoke; Stage D limited to 2025-12-07..11 (max 5 days) |
| F | `omega_avg_daily_smap_dual` | `run-940fddbaf623` | succeeded | 6.08 | compiled graph → omega_avg_daily; time_range→2025-12-03..05; parallel disabled for smoke; Stage D limited to 2025-12-07..11 (max 5 days); DUAL temp_scheme with local GLDAS .mat; use_gldas_template=true |
| F | `omega_avg_daily_smap_online` | `` | skipped | 0.0 | blocked:config (online download template + needs h5→mat bridge; earthdata portal ready; not light-smoke) |
| F | `omega_avg_daily_gldas_online` | `run-e54fd6c92d50` | failed | 22.23 | run_failed compiled graph → omega_avg_daily; time_range→2025-12-03..05; parallel disabled for smoke; Stage D limited to 2025-12-07..11 (max 5 days); gldas_online graph=D2 only (gldas_download/nc4→mat verified separately); use_gldas_template=true |
| F | `omega_sf_fenkuai_smap_single` | `run-c83c0983f6d9` | succeeded | 117.38 | light-smoke: 2025-12-03..10 (1×8d block), bbox 110–115E/20–25N, max_pixels=400, serial; keeps output/map_layer |
| F | `omega_sf_fenkuai_fy_single` | `run-56bad2ce65be` | succeeded | 117.26 | light-smoke: 2025-12-03..10 (1×8d block), bbox 110–115E/20–25N, max_pixels=400, serial; keeps output/map_layer |
| G | `preprocess_clip_reproject_basic` | `run-c4110aa2aedc` | succeeded | 2.03 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / smoke_points.geojson / smoke_pour_points.geojson / smoke_zones.geojson / smoke_timeseries.json / smoke_timeseries_b.json) |
| G | `stats_mean_summary_report_basic` | `run-0455dd70494b` | succeeded | 2.05 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / smoke_points.geojson / smoke_pour_points.geojson / smoke_zones.geojson / smoke_timeseries.json / smoke_timeseries_b.json) |
| G | `fusion_idw_interpolate_basic` | `run-4d283039d5d7` | failed | 6.07 | run_failed stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / smoke_points.geojson / smoke_pour_points.geojson / smoke_zones.geojson / smoke_timeseries.json / smoke_timeseries_b.json) |
| H | `preprocess_mask_resample_basic` | `run-a0c87824ce74` | succeeded | 2.03 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / smoke_points.geojson / smoke_pour_points.geojson / smoke_zones.geojson / smoke_timeseries.json / smoke_timeseries_b.json) |
| H | `stats_trend_anomaly_basic` | `run-61f2ff806ab9` | succeeded | 2.03 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / smoke_points.geojson / smoke_pour_points.geojson / smoke_zones.geojson / smoke_timeseries.json / smoke_timeseries_b.json) |
| H | `fusion_multi_source_merge_basic` | `run-8c6e1fbd92b8` | failed | 8.11 | run_failed stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / smoke_points.geojson / smoke_pour_points.geojson / smoke_zones.geojson / smoke_timeseries.json / smoke_timeseries_b.json) |
| I | `stats_correlation_basic` | `run-2a6b181a0314` | failed | 6.06 | run_failed stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / smoke_points.geojson / smoke_pour_points.geojson / smoke_zones.geojson / smoke_timeseries.json / smoke_timeseries_b.json) |
| I | `stats_correlation_report_basic` | `run-3a85931dabcb` | succeeded | 2.03 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / smoke_points.geojson / smoke_pour_points.geojson / smoke_zones.geojson / smoke_timeseries.json / smoke_timeseries_b.json) |
| I | `stats_summary_chart_basic` | `run-2b39ba22b588` | succeeded | 2.07 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / smoke_points.geojson / smoke_pour_points.geojson / smoke_zones.geojson / smoke_timeseries.json / smoke_timeseries_b.json) |
| X | `analysis_buffer` | `run-ba13ceb8e3d5` | failed | 8.09 | run_failed |
| X | `analysis_clip` | `run-1c955068d948` | failed | 6.11 | run_failed |
| X | `analysis_contour` | `run-ae012f6f3683` | failed | 8.11 | run_failed |
| X | `analysis_raster_calc` | `run-5030cf4bf7f1` | failed | 8.1 | run_failed |
| X | `analysis_raster_to_vector` | `run-c3c47dedce53` | failed | 8.11 | run_failed |
| X | `analysis_reclassify` | `run-e45ef8ad5265` | failed | 6.07 | run_failed |
| X | `analysis_slope_aspect` | `run-a1e941fbc7d4` | failed | 6.11 | run_failed |
| X | `analysis_vector_to_raster` | `run-fd13992fac97` | failed | 6.05 | run_failed |
| X | `analysis_watershed` | `run-2fd6f8fecf46` | failed | 8.06 | run_failed |
| X | `analysis_zonal_stats` | `run-f04da0885144` | failed | 8.1 | run_failed |
| X | `cds_era5_reanalysis_download` | `run-2beb2fdf4ccd` | failed | 18.19 | run_failed request date 2026-08-17 (yesterday UTC); cdsapi queue may take minutes |
| X | `cdse_sentinel_download` | `` | skipped | 0.0 | blocked:creds (no copernicus portal account) |
| X | `fy_tb_local_read` | `run-f44867ac8f58` | failed | 8.11 | run_failed synthetic FY MWRI HDF5 (Brightness_Temperature) under {DATA_ROOT}/_runtime/synthetic/fy_mwri (seed default {DATA_ROOT}/FY absent) |
| X | `fy_tb_online_read` | `run-910ba9eec684` | failed | 2.05 | run_failed single day 2025-12-03 (NAS fy3dhdf2425 window); auto NSMC→NAS fallback |
| X | `ndvi_gee_read` | `` | skipped | 0.0 | blocked:gee-not-configured (accounts=0 enabled=0) |
| X | `ndvi_local_read` | `` | failed | 0.02 | submit_http_422 |
| X | `ndvi_online_read` | `run-c9b8158a7c5a` | failed | 16.2 | run_failed VNP13C1 16-day window 2025-05-01..16, max_results 5→1 (one ~30MB granule) |
| X | `nomads_gfs_grib_download` | `run-745a8dd9e1d3` | failed | 28.39 | run_failed date={YYYYMMDD}→latest; search_string=:TMP:2 m subset |
| X | `omega_avg_daily_fy_online` | `run-e9514615eac5` | succeeded | 151.67 | compiled graph → omega_avg_daily; time_range→2025-12-03..05; parallel disabled for smoke; Stage D limited to 2025-12-07..11 (max 5 days); fy_download {YYYYMMDD}→20251203..05 (aligns D2 window) |
| X | `omega_sf_fenkuai_fy_dual` | `run-2b88be7d46a7` | succeeded | 98.92 | light-smoke: 2025-12-03..10 (1×8d block), bbox 110–115E/20–25N, max_pixels=400, serial; keeps output/map_layer |
| X | `omega_sf_fenkuai_fy_online` | `run-9c81d815e456` | succeeded | 260.31 | light-smoke: 2025-12-03..10 (1×8d block), bbox 110–115E/20–25N, max_pixels=400, serial; keeps output/map_layer |
| X | `omega_sf_fenkuai_smap_dual` | `run-66afc77c5e32` | succeeded | 98.9 | light-smoke: 2025-12-03..10 (1×8d block), bbox 110–115E/20–25N, max_pixels=400, serial; keeps output/map_layer |
| X | `omega_sf_fenkuai_smap_online` | `run-a3f00343a75a` | failed | 308.77 | run_failed light-smoke: 2025-12-03..10 (1×8d block), bbox 110–115E/20–25N, max_pixels=400, serial; keeps output/map_layer |

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

