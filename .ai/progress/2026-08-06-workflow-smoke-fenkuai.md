# Workflow smoke matrix

- Generated: 2026-08-06 21:09 中国标准时间
- API: http://127.0.0.1:8000
- DATA_ROOT: I:\Geograph_DataSet
- Definitions listed: 24

## Matrix

| batch | workflow_id | run_id | status | elapsed_s | blocker / detail |
|-------|-------------|--------|--------|-----------|------------------|
| F | `omega_sf_fenkuai_smap_single` | `run-28890d9441bd` | succeeded | 135.91 |  |

## Notes

- Batch A is weather tile hot path (not a system seed).
- **Fenkuai light-smoke (this run):** caps `2025-12-03..10` (1×8d), bbox `110–115E / 20–25N`, `max_pixels=400`, serial; stripped `output/map_layer` (avoids `output_map_layer requires data/path or upstream manifest`). First attempt `run-8571efadec08` failed on map_layer; retry `run-28890d9441bd` succeeded (~136s).
- Full global fenkuai remains multi-hour and is not the light-smoke target.
- Heavy omega chains may fail for missing GLDAS / online deps; recorded without inventing production datasets.

