# Workflow smoke matrix

- Generated: 2026-08-06 21:37 中国标准时间
- API: http://127.0.0.1:8000
- DATA_ROOT: I:\Geograph_DataSet
- Definitions listed: 24

## Matrix

| batch | workflow_id | run_id | status | elapsed_s | blocker / detail |
|-------|-------------|--------|--------|-----------|------------------|
| E | `open_data_nasa_earthdata_sample` | `run-e503f4028da1` | succeeded | 6.08 |  |

## Notes

- **NASA verification (this run):** download-only `nasa_earthdata` preset with public LP DAAC MCD43A4 browse JPG (~1.5KB). Portal Earthdata basic auth is present locally; public object does not require it. Diagnostics via `run-e503f4028da1`.
- HPC template sync still blocked (tunnel/direct/jump unreachable this session).
- NSIDC SMAP sample skipped: Earthdata ready but granules too large for light smoke.

