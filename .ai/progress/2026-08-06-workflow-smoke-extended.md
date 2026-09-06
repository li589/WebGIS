# Workflow smoke matrix

- Generated: 2026-08-06 15:36 中国标准时间
- API: http://127.0.0.1:8000
- DATA_ROOT: I:\Geograph_DataSet
- Definitions listed: 24

## Matrix

| batch | workflow_id | run_id | status | elapsed_s | blocker / detail |
|-------|-------------|--------|--------|-----------|------------------|
| F | `omega_avg_daily_gldas_online` | `` | skipped | 0.0 | blocked:runtime (gldas_download + nc4→mat OK; seed still needs full D1 + multi-day GLDAS mats — not light-smoke) |

## Notes

- Batch A is weather tile hot path (not a system seed).
- Open-data seeds with `REPLACE_*` placeholders were skipped as `blocked:config` / `blocked:creds` (no forged portal paths).
- `raster_histogram_basic` used temp GeoTIFF under `{DATA_ROOT}/_runtime/smoke_hist.tif`.
- `smap_soil_moisture_local` path overridden to `Soil_Moisture/SMAP` (seed default `{DATA_ROOT}/SMAP` missing).
- `omega_block_smap_single` time window overridden to 2025-11-01..02 to match available local mats (seed default Dec 2025).
- Heavy omega chains may fail for missing GLDAS / online deps; recorded without inventing production datasets.

