# Workflow smoke matrix

- Generated: 2026-08-06 21:22 中国标准时间
- API: http://127.0.0.1:8000
- DATA_ROOT: I:\Geograph_DataSet
- Definitions listed: 24

## Matrix

| batch | workflow_id | run_id | status | elapsed_s | blocker / detail |
|-------|-------------|--------|--------|-----------|------------------|
| F | `omega_sf_fenkuai_fy_single` | `run-af306580f609` | succeeded | 145.94 |  |

## Notes

- Batch A is weather tile hot path (not a system seed).
- **Fenkuai FY light-smoke (this run):** same caps as SMAP fenkuai (`2025-12-03..10`, bbox `110–115E/20–25N`, `max_pixels=400`, serial, `output/map_layer` stripped). Local FY3D/FY3B mats present under `Soil_Moisture/`. Diagnostics: `entry_name=workflow_definition`, `algorithm_status=success`.
- Full global fenkuai remains multi-hour and is not the light-smoke target.

