# Workflow smoke matrix

- Generated: 2026-08-10 21:05 中国标准时间
- API: http://127.0.0.1:8000
- DATA_ROOT: I:\Geograph_DataSet
- Definitions listed: 27

## Matrix

| batch | workflow_id | run_id | status | elapsed_s | blocker / detail |
|-------|-------------|--------|--------|-----------|------------------|
| G | `preprocess_clip_reproject_basic` | `run-7787899bd785` | succeeded | 2.05 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_points.geojson / smoke_zones.geojson) |
| G | `gis_raster_calc_reclassify_basic` | `run-3768ace758fa` | succeeded | 2.06 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_points.geojson / smoke_zones.geojson) |
| G | `gis_buffer_zonal_basic` | `run-b734305fa23a` | succeeded | 2.08 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_points.geojson / smoke_zones.geojson) |
| G | `stats_mean_summary_report_basic` | `run-14bd7605aa00` | succeeded | 2.06 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_points.geojson / smoke_zones.geojson) |
| G | `fusion_idw_interpolate_basic` | `run-58993c2a6a74` | succeeded | 2.04 | stub_v1 fixtures under {DATA_ROOT}/_runtime (smoke_stub.tif / smoke_points.geojson / smoke_zones.geojson) |

## Notes

- **Batch G (stub_v1)**: 5/5 succeeded against live FastAPI + Celery. Fixtures via `ensure_stub_v1_fixtures()` under `{DATA_ROOT}/_runtime/`. Session login (`--login` / auto after write-probe 401) required when DB `backend_auth` differs from env `BACKEND_API_KEY`.
- Seed link slots must account for dimension ports (`time_range`/`bbox` prepended); edges to `bbox`/`time_range` are scraped by the graph compiler (request-level).
- `preprocess_clip_reproject_basic`: clip `bbox` is optional at bind-time; window also on node `properties.bbox` (and smoke injects `algorithm_params` / `spatial_filter`).
- Batch A is weather tile hot path (not a system seed).
- Open-data / omega notes retained from earlier matrix runs (not re-run in this Batch-G-only invocation).

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

