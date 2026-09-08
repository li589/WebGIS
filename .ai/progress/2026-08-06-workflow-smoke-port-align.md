# Workflow smoke matrix

- Generated: 2026-08-06 19:49 中国标准时间
- API: http://127.0.0.1:8000
- DATA_ROOT: I:\Geograph_DataSet
- Definitions listed: 24

## Matrix

| batch | workflow_id | run_id | status | elapsed_s | blocker / detail |
|-------|-------------|--------|--------|-----------|------------------|
| F | `omega_block_smap_single` | `run-3e80dbc627b0` | succeeded | 537.06 |  |

## Notes

- Batch A is weather tile hot path (not a system seed).
- Open-data seeds with `REPLACE_*` placeholders were skipped as `blocked:config` / `blocked:creds` (no forged portal paths).
- `raster_histogram_basic` used temp GeoTIFF under `{DATA_ROOT}/_runtime/smoke_hist.tif`.
- `smap_soil_moisture_local` path overridden to `Soil_Moisture/SMAP` (seed default `{DATA_ROOT}/SMAP` missing).
- `omega_block_smap_single` time window overridden to 2025-11-01..02 to match available local mats (seed default Dec 2025).
- **Port-align verification (this run):** smoke submitted compiled `workflow_definition` (no flatten). Diagnostics: `entry_name=workflow_definition`, `algorithm_status=success`, `product_count=3`. Unit: `Test/backend/test_workflow_graph_compiler.py::test_compile_omega_block_seed_graph_path` (edge `n5.output_path→n6.input_mat`, output `node:n6.manifest`).
- Heavy omega chains may fail for missing GLDAS / online deps; recorded without inventing production datasets.

