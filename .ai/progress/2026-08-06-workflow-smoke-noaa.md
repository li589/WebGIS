# Workflow smoke matrix

- Generated: 2026-08-06 20:58 中国标准时间
- API: http://127.0.0.1:8000
- DATA_ROOT: I:\Geograph_DataSet
- Definitions listed: 24

## Matrix

| batch | workflow_id | run_id | status | elapsed_s | blocker / detail |
|-------|-------------|--------|--------|-----------|------------------|
| D | `open_data_noaa_grib_sample` | `run-1456e607422f` | succeeded | 4.07 |  |

## Notes

- Batch A is weather tile hot path (not a system seed).
- **NOAA verification (this run):** smoke discovers latest GFS cycle on NOMADS, patches `http_open_data` with `cgi-bin/filter_gfs_0p25.pl` + tiny Guangzhou TMP subset (~200B GRIB2), download-only graph (archive/extract/variable skipped — local Env lacks cfgrib/eccodes). Diagnostics: `entry_name=workflow_definition`, `algorithm_status=success`, `product_count=1`.
- NASA/NSIDC/ESA samples remain blocked without portal tokens.
- Heavy omega chains may fail for missing GLDAS / online deps; recorded without inventing production datasets.

