# Workflow smoke matrix

- Generated: 2026-08-10 22:08 中国标准时间
- API: http://127.0.0.1:8000
- DATA_ROOT: I:\Geograph_DataSet
- Definitions listed: 32

## Matrix

| batch | workflow_id | run_id | status | elapsed_s | blocker / detail |
|-------|-------------|--------|--------|-----------|------------------|
| H | `preprocess_mask_resample_basic` | `run-1da1932393e7` | succeeded | 2.07 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / smoke_points.geojson / smoke_zones.geojson / smoke_timeseries.json) |
| H | `gis_vector_raster_roundtrip_basic` | `run-0932ce1ef5a8` | succeeded | 2.05 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / smoke_points.geojson / smoke_zones.geojson / smoke_timeseries.json) |
| H | `gis_contour_slope_basic` | `run-9dfb2a66263d` | succeeded | 2.06 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / smoke_points.geojson / smoke_zones.geojson / smoke_timeseries.json) |
| H | `stats_trend_anomaly_basic` | `run-12285b93d720` | succeeded | 2.01 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / smoke_points.geojson / smoke_zones.geojson / smoke_timeseries.json) |
| H | `fusion_multi_source_merge_basic` | `run-c657ffb73f53` | succeeded | 2.07 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / smoke_points.geojson / smoke_zones.geojson / smoke_timeseries.json) |

## Notes

- **Batch H (stub_v1)**: 5/5 succeeded against live FastAPI + Celery. Fixtures via `ensure_stub_v1_fixtures()` under `{DATA_ROOT}/_runtime/` (incl. `smoke_dem.tif` / `smoke_stub_b.tif` / `smoke_timeseries.json`).
- Fix: `resolve_raster_path` now treats `dem`/`primary`/`secondary` (and caller `keys`) as manifest artifact ports — required for `gis_contour_slope_basic` (`source.manifest` → `slope.dem`).
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

