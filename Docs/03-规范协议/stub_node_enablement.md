# Stub 节点启用清单（2026-08）

> 工作流编辑器中原 `executable=False` 占位节点的实现与验收约定。
> 实现真源见算法包 `Code/algorithms/providers/Python/modules/`。

## 启用闸门（交付必做）

1. `Code/algorithms/providers/Python/modules/*.py` 实现 `BaseModule` 并 `@register_module_decorator`
2. 从 `Code/backend/app/services/python_provider_bridge_service.py` 的 `_PENDING_IMPLEMENTATION_MODULES` 移除 `node_class`
3. `Code/backend/app/services/node_template_registry.py`：`executable: True`，`engine: python_provider`
4. 产出 `ProductManifest` / COG / GeoJSON；Celery title 纯 ASCII
5. 单测：`Test/algorithms/test_stub_modules.py`、`Test/backend/test_node_template_ports.py`

## 已启用模块（21）

| 分组 | node_class | 实现文件 | 备注 |
|------|------------|----------|------|
| 预处理 | `preprocess_reproject` / `resample` / `clip` / `mask` | `modules/preprocess_ops.py` | float64 计算 → float32 COG |
| 统计 | `stats_spatial_mean` / `temporal_trend` / `anomaly_detect` / `correlation` | `modules/stats_ops.py` | 时序载荷 `{times, values}` |
| 融合 | `fusion_spatial_interpolate` / `multi_source_merge` | `modules/fusion_viz_ops.py` | IDW/nearest；kriging/PCA 二期拒收 |
| 可视化 | `viz_report_export` / `statistics_summary` | `modules/fusion_viz_ops.py` | HTML/Markdown；PDF/DOCX 二期 |
| GIS | `gis_buffer_analysis` … `gis_watershed` | `modules/gis_ops.py` | watershed 仅 D8 + `max_dem_pixels` |

共享库：`Code/algorithms/providers/Python/modules/_raster_ops.py`（路径解析、对齐、COG 写出、AST 白名单表达式、remap、进度）。

## 横切约定

- **精度**：计算 `float64`；存储默认 `float32` COG；统计/趋势/相关全程 float64
- **性能**：大输出护栏（分辨率/像素上限）；warp 单次成型；缓冲用局部等距投影（米）
- **异常**：`RasterOpsValidationError` → 校验失败；缺文件 → `RasterOpsDataError`；非法 AST 拒绝 `eval`
- **并行**：DAG 层用 `WorkflowRunner.node_parallelism`；块并行用 `algorithms._parallel.auto_process_count`（`chunked_map`）

## 验证

```text
Env\Python312\python.exe -m pytest Test/algorithms/test_stub_modules.py Test/backend/test_workflow_graph_compiler.py -q
```

## 明确未做

- GEE `gee/*` 引擎节点（本清单外）
- 克里金 / PCA·贝叶斯融合 / PDF·DOCX 报表 / D∞ 流域

## 后续（2026-08-10 seeds + hardening）

- 代表性 system seeds：`preprocess_clip_reproject_basic` 等 5 条（tags 含 `stub_v1`）
- `FailureCategory`：`RasterOpsValidationError` → validation；缺文件 → not_found；SoftTimeLimit → timeout
- `_meta.resource_profile` + 重模块自动升 `heavy`（`resource_profile_resolver.py`）
- `stats_spatial_mean` 超内存预算走窗口累加；median 超预算拒收并提示 clip/resample

详见 `.ai/progress/2026-08-10-stub-v1-seeds-smoke.md`。
