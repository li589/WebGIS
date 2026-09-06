# Workflow smoke matrix

- Generated: 2026-08-06 20:47 中国标准时间
- API: http://127.0.0.1:8000
- DATA_ROOT: I:\Geograph_DataSet
- Definitions listed: 24

## Matrix

| batch | workflow_id | run_id | status | elapsed_s | blocker / detail |
|-------|-------------|--------|--------|-----------|------------------|
| F | `omega_avg_daily_smap_single` | `run-e1486b27a771` | succeeded | 117.49 |  |

## Notes

- Batch A is weather tile hot path (not a system seed).
- Open-data seeds with `REPLACE_*` placeholders were skipped as `blocked:config` / `blocked:creds` (no forged portal paths).
- `raster_histogram_basic` used temp GeoTIFF under `{DATA_ROOT}/_runtime/smoke_hist.tif`.
- `smap_soil_moisture_local` path overridden to `Soil_Moisture/SMAP` (seed default `{DATA_ROOT}/SMAP` missing).
- `omega_block_smap_single` time window overridden to 2025-11-01..02 to match available local mats (seed default Dec 2025).
- **D2 graph-path verification (this run):** smoke no longer flattens to `module_name`; submits compiled `workflow_definition`. Diagnostics: `entry_name=workflow_definition`, `algorithm_status=success`, `product_count=1`. Unit: `test_compile_omega_avg_daily_seed_graph_path` (fan-in scraped; `request:datasource_selection` / `request:algorithm_params` bindings).
- Heavy omega chains may fail for missing GLDAS / online deps; recorded without inventing production datasets.

