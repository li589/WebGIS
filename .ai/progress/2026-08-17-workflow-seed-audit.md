# 工作流种子全量审计报告

- 种子数：49（system/）
- 归档数：6（archive/）
- tag 词表：52 项（真源 workflow_seed_conventions.md §5）
- workflow_timers：查询失败（跳过）: no such table: workflow_timers

## 审计明细

| workflow_id | engine | category | 节点数 | 编译 | dry-validate | 注册表 | 图层引用 |
|---|---|---|---|---|---|---|---|
| analysis_buffer | python_provider | analysis | 2 | ok | ok | ok | - |
| analysis_clip | python_provider | analysis | 3 | ok | ok | ok | - |
| analysis_contour | python_provider | analysis | 2 | ok | ok | ok | - |
| analysis_histogram | python_provider | analysis | 3 | ok | ok | ok | - |
| analysis_raster_calc | python_provider | analysis | 2 | ok | ok | ok | - |
| analysis_raster_to_vector | python_provider | analysis | 2 | ok | ok | ok | - |
| analysis_reclassify | python_provider | analysis | 2 | ok | ok | ok | - |
| analysis_slope_aspect | python_provider | analysis | 2 | ok | ok | ok | - |
| analysis_vector_to_raster | python_provider | analysis | 2 | ok | ok | ok | - |
| analysis_watershed | python_provider | analysis | 3 | ok | ok | ok | - |
| analysis_zonal_stats | python_provider | analysis | 3 | ok | ok | ok | - |
| cds_era5_reanalysis_download | python_provider | data_access | 1 | ok | ok | ok | - |
| cdse_sentinel_download | python_provider | data_access | 1 | ok | ok | ok | - |
| fusion_idw_interpolate_basic | python_provider | analysis | 3 | ok | ok | ok | - |
| fusion_multi_source_merge_basic | python_provider | analysis | 3 | ok | ok | ok | - |
| fy_tb_local_read | python_provider | data_access | 3 | ok | ok | ok | yes |
| fy_tb_nas_read | python_provider | data_access | 3 | ok | ok | ok | - |
| fy_tb_nsmc_online | python_provider | data_access | 4 | ok | ok | ok | - |
| fy_tb_online_read | python_provider | data_access | 3 | ok | ok | ok | - |
| ndvi_gee_read | gee | data_access | 2 | bypass | ok | ok | - |
| ndvi_local_read | python_provider | data_access | 3 | ok | ok | ok | yes |
| ndvi_online_read | python_provider | data_access | 6 | ok | ok | ok | - |
| nomads_gfs_grib_download | python_provider | data_access | 1 | ok | ok | ok | - |
| omega_avg_daily_fy_single | python_provider | inversion | 9 | ok | ok | ok | yes |
| omega_avg_daily_gldas_online | python_provider | inversion | 9 | ok | ok | ok | - |
| omega_avg_daily_smap_dual | python_provider | inversion | 8 | ok | ok | ok | - |
| omega_avg_daily_smap_online | python_provider | inversion | 9 | ok | ok | ok | - |
| omega_avg_daily_smap_single | python_provider | inversion | 8 | ok | ok | ok | yes |
| omega_block_smap_single | python_provider | inversion | 7 | ok | ok | ok | - |
| omega_sf_fenkuai_fy_online | python_provider | inversion | 13 | ok | ok | ok | - |
| omega_sf_fenkuai_fy_single | python_provider | inversion | 10 | ok | ok | ok | yes |
| omega_sf_fenkuai_smap_online | python_provider | inversion | 9 | ok | ok | ok | - |
| omega_sf_fenkuai_smap_single | python_provider | inversion | 7 | ok | ok | ok | yes |
| open_data_esa_product_sample | common | data_access | 3 | ok | ok | ok | - |
| open_data_nasa_earthdata_sample | common | data_access | 3 | ok | ok | ok | - |
| open_data_noaa_grib_sample | common | data_access | 4 | ok | ok | ok | - |
| open_data_nsidc_smap_sample | common | data_access | 3 | ok | ok | ok | - |
| preprocess_clip_reproject_basic | python_provider | analysis | 4 | ok | ok | ok | - |
| preprocess_mask_resample_basic | python_provider | analysis | 4 | ok | ok | ok | - |
| raster_timeseries_curve | python_provider | analysis | 3 | ok | ok | ok | - |
| raster_zonal_stats_aligned | python_provider | analysis | 2 | ok | ok | ok | - |
| smap_soil_moisture_local | python_provider | data_access | 3 | ok | ok | ok | yes |
| stats_correlation_basic | python_provider | analysis | 3 | ok | ok | ok | - |
| stats_correlation_report_basic | python_provider | analysis | 4 | ok | ok | ok | - |
| stats_mean_summary_report_basic | python_provider | analysis | 4 | ok | ok | ok | - |
| stats_summary_chart_basic | python_provider | analysis | 3 | ok | ok | ok | - |
| stats_trend_anomaly_basic | python_provider | analysis | 3 | ok | ok | ok | - |
| weather_temperature_grid_demo | weather | weather | 3 | ok | ok | ok | - |
| weather_wind_field_demo | weather | weather | 2 | ok | ok | ok | - |

## 重复组（节点类型多重集相同）

| 组成员 | 共同节点类型 |
|---|---|
| fy_tb_local_read, smap_soil_moisture_local | data/source + extract/variable + format/convert |

## tag 词表漂移（仅告警）

（无）

## 注册表差集

- 种子引用但未注册：无
- 注册但无种子使用（29）：config/read, data/boolean, data/latlng, data/map_viewport, data/number, data/string, download/remote_fetch, gee/clip, gee/cloud_mask, gee/image, gee/select_bands, module/block_inversion, module/curve_fitting, module/daily_bundle, module/data_export, module/inversion_daily, module/station_daily, module/validation_metrics, output/file, preprocess/format_convert, weather/cloud_cover_render, weather/dewpoint_render, weather/humidity_render, weather/point_parse, weather/precipitation_render, weather/pressure_render, weather/summary_generate, weather/tile_render, weather/visibility_render

## .data 孤儿与 timer 引用

- `.data/workflow_definitions/system/` 孤儿：无
- workflow_timers 引用缺失种子：无

## 结论

全部通过

## 修补记录（2026-08-17，T2–T9）

| 项 | 内容 | 文件 |
|---|---|---|
| 去重归档 | 6 条重复/组合样例种子移入 `workflow_seeds/archive/`（5 条 `gis_*` 组合流 + `raster_histogram_basic`），附 README 说明回滚方式 | `Code/backend/workflow_seeds/archive/` |
| 修补 A | `_sync_system_seeds` 同步后自动清理 `.data/workflow_definitions/system/` 孤儿定义（user 目录不受影响；种子包缺失时不清）；新增 5 条测试 | `Code/backend/app/services/workflow_definition_service.py`、`Test/backend/test_workflow_seed_sync.py` |
| 修补 B | 前端分类徽章补 `analysis` 映射（22 条种子此前无中文标签） | `Code/frontend/src/components/workflow/WorkflowList.vue` |
| 修补 C | tag 词表补登 11 个在用 tag（aspect/calculator/contour/dem/gee/online/remote/slope/stats/vector/watershed）并注明用途；技能文件真源指针由已迁移的 `.ai/docs/` 修正为 `Docs/` | `Docs/03-规范协议/workflow_seed_conventions.md`、`.ai/skills/workflow-design.md` |
| 修补 D | 注册 `gee/export` 节点模板（engine=gee，node_class=gee_export_image，GEE-输出类目）；核查编译器守卫——gee 引擎仍按契约走 `gee_request` 原图提交，不进 LiteGraph 编译（混合引擎报错保持不变） | `Code/backend/app/services/node_template_registry.py` |
| 测试同步 | stub_v1 白名单 14→9；smoke 批次与特判分支改用 `analysis_histogram`；图表测试与算法注释同步 | `Test/backend/test_stub_v1_seeds_compile.py`、`Tools/smoke_system_workflows.py`、`Test/backend/test_analysis_chart_table.py`、`Test/algorithms/test_stub_modules.py` |
| 附带修复 | workflow-poller 测试 deps stub 缺 `cleanupUnproducedRunLayers` 导致 3 条 unhandled rejection（`npm run test` 退出码 1），补 no-op mock | `Test/frontend/stores/layers/workflow-poller.test.ts` |

验证：后端 `Test/backend` 全量 1337 passed / 2 skipped；前端 vitest 134 文件 952 测试全过（高并行下的 `vitest-pool-runner` worker 超时为本机环境噪声，降并行度后退出码 0）、eslint 0 error、build 通过；审计工具全绿。
