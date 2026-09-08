# 全量流水线健康复查矩阵（2026-08-11）

## 结论

**种子健康：32/32 通过**（compile + linked_layer + module 静态扫描；live dry-run 无 `compile_failed` / `definition_missing`）。

**提交链：** 复查中发现并修复多模块 DAG normalize 后再写入 `module_name` 导致与 `workflow_definition` 互斥（`workflow_request_resolver._populate_python_provider_request` 在保留 definition 后提前返回）。修复后抽样执行恢复。

**抽样执行：**

| 样本 | run_id | 结果 |
|------|--------|------|
| `gis_buffer_zonal_basic` | `run-f957cf83dbe1` | succeeded（~2s），终态稳定 |
| `omega_sf_fenkuai_smap_single`（smoke 轻量：1×8d + bbox + max_pixels=400） | `run-bbb6f44d4ddb` | succeeded（~129s），终态稳定 |

## 自动化门禁

- pytest（stub / raster / graph compiler / gldas / placeholder / resolver / watchdog / routes）：**28 passed**（resolver 后续补测后 **4 passed**）
- `npm run check:catalog`：**OK**（FE=37 BE=41）

## 32 种子矩阵

判定列：`static` = compile+linked+modules；`dry` = smoke `--dry-run`；`exec` = 本次真实跑（仅抽样）。

| workflow_id | pipeline | static | dry | exec | 备注 |
|-------------|----------|--------|-----|------|------|
| fusion_idw_interpolate_basic | | PASS | dry_run | — | |
| fusion_multi_source_merge_basic | | PASS | dry_run | — | |
| gis_buffer_zonal_basic | | PASS | dry_run | **succeeded** | run-f957cf83dbe1 |
| gis_contour_slope_basic | | PASS | dry_run | — | |
| gis_raster_calc_reclassify_basic | | PASS | dry_run | — | |
| gis_vector_raster_roundtrip_basic | | PASS | dry_run | — | |
| gis_watershed_basic | | PASS | dry_run | — | |
| omega_avg_daily_fy_single | Y | PASS | dry_run | — | |
| omega_avg_daily_gldas_online | Y | PASS | dry_run | — | |
| omega_avg_daily_smap_dual | Y | PASS | dry_run | — | |
| omega_avg_daily_smap_online | Y | PASS | skipped | — | 数据面：online/h5→mat，非种子故障 |
| omega_avg_daily_smap_single | Y | PASS | dry_run | — | |
| omega_block_smap_single | Y | PASS | dry_run | — | |
| omega_sf_fenkuai_fy_single | Y | PASS | dry_run | — | |
| omega_sf_fenkuai_smap_single | Y | PASS | dry_run | **succeeded** | run-bbb6f44d4ddb |
| open_data_esa_product_sample | | PASS | skipped | — | 数据面：Copernicus 凭证 + REPLACE_* |
| open_data_nasa_earthdata_sample | | PASS | dry_run | — | |
| open_data_noaa_grib_sample | | PASS | dry_run | — | |
| open_data_nsidc_smap_sample | | PASS | skipped | — | 数据面：颗粒过大，非种子故障 |
| preprocess_clip_reproject_basic | | PASS | dry_run | — | |
| preprocess_mask_resample_basic | | PASS | dry_run | — | |
| raster_histogram_basic | | PASS | dry_run | — | |
| raster_timeseries_curve | | PASS | dry_run | — | |
| raster_zonal_stats_aligned | | PASS | dry_run | — | |
| smap_soil_moisture_local | | PASS | dry_run | — | |
| stats_correlation_basic | | PASS | dry_run | — | |
| stats_correlation_report_basic | | PASS | dry_run | — | |
| stats_mean_summary_report_basic | | PASS | dry_run | — | |
| stats_summary_chart_basic | | PASS | dry_run | — | |
| stats_trend_anomaly_basic | | PASS | dry_run | — | |
| weather_temperature_grid_demo | | PASS | dry_run | — | 另：瓦片 A 批 temperature/wind 200 |
| weather_wind_field_demo | | PASS | dry_run | — | |

**汇总：** 种子故障 **0**；dry-run 主动 skip（数据/凭证）**3**；抽样执行 **2/2 succeeded**。

## 复查中修复

- [`workflow_request_resolver.py`](Code/backend/app/services/workflow_request_resolver.py)：多模块保留 `workflow_definition` 后不得再 `setdefault(module_name)`（bridge 互斥）。
- 单测：`Test/backend/test_workflow_request_resolver.py` 覆盖该路径。

## 产物

- 静态扫描：`_pipeline_health_static.json` / `Tools/_pipeline_health_static_scan.py`
- Dry-run 明细：`.ai/progress/2026-08-11-pipeline-health-dry-run.md`
- 本汇总：`.ai/progress/2026-08-11-pipeline-health-recheck.md`
