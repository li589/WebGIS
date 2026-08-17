# 归档工作流种子

本目录存放因**功能重复**而移出加载路径的系统种子。加载器
（`app/services/workflow_definition_service._sync_system_seeds`）仅扫描
`workflow_seeds/system/*.json`，本目录中的种子不会出现在 `/workflow-definitions`
列表，也不可提交运行。

归档于 2026-08-17（全量审计见 `.ai/progress/2026-08-17-workflow-seed-audit.md`）：

| 种子 | 归档原因 | 功能保留于 |
|------|----------|-----------|
| `raster_histogram_basic` | 节点序列与 `analysis_histogram` 完全相同 | `analysis_histogram` |
| `gis_watershed_basic` | 节点序列与 `analysis_watershed` 完全相同 | `analysis_watershed` |
| `gis_buffer_zonal_basic` | `analysis_buffer` + `analysis_zonal_stats` 拼接组合 | 同左两个单元流 |
| `gis_contour_slope_basic` | `analysis_slope_aspect` + `analysis_contour` 拼接组合 | 同左两个单元流 |
| `gis_raster_calc_reclassify_basic` | `analysis_raster_calc` + `analysis_reclassify` 拼接组合 | 同左两个单元流 |
| `gis_vector_raster_roundtrip_basic` | `analysis_vector_to_raster` + `analysis_raster_to_vector` 拼接组合 | 同左两个单元流 |

回滚方式：将 JSON 文件移回 `system/` 即可，下次 `list_definitions()` 会自动
重新同步到 `.data/workflow_definitions/system/`。
