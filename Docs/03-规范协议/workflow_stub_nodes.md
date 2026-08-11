# Stub 节点启用清单（2026-08）

> 配套设计：工作流 Stub 节点完善计划。活约定仍以 `workflow_seed_conventions.md` 与代码真源为准。

## 启用闸门（每个节点必须同时满足）

1. `Code/algorithms/providers/Python/modules/` 中实现并 `@register_module_decorator`
2. 从 `python_provider_bridge_service._PENDING_IMPLEMENTATION_MODULES` 移除
3. `node_template_registry`：`executable: True`，`engine: python_provider`
4. 单测覆盖正常路径 + ≥2 异常路径

## 已启用模块（原 stub）

| node_class | 分组 | 实现文件 | 备注 |
|------------|------|----------|------|
| preprocess_reproject / resample / clip / mask | 预处理 | `modules/preprocess_ops.py` | float64 计算，float32 COG |
| stats_spatial_mean / temporal_trend / anomaly_detect / correlation | 统计 | `modules/stats_ops.py` | timeseries JSON 契约 |
| fusion_spatial_interpolate / multi_source_merge | 融合 | `modules/fusion_viz_ops.py` | IDW/nearest；weighted；kriging/PCA 护栏 |
| viz_report_export / statistics_summary | 可视化 | `modules/fusion_viz_ops.py` | HTML/Markdown；PDF/DOCX 延后 |
| gis_*（9） | GIS | `modules/gis_ops.py` | watershed 仅 D8 + max_dem_pixels |

共享基础：`modules/_raster_ops.py`（路径解析、对齐、安全表达式 AST、remap、窗口并行入口）。

## 横切约定摘要

- **精度**：计算 float64；存储默认 float32；nodata=非有限值
- **性能**：大栅格护栏（像元上限）；warp 一次成型；`CGDA_MAX_PARALLEL_WORKERS` 约束节点内进程池
- **异常**：`RasterOpsValidationError` → validation；缺文件 → data；非法 AST 拒绝 eval
- **队列**：重投影/重采样/插值/流域倾向 heavy；轻量统计/缓冲 standard（由现有 workflow 路由承接）

## 验证

```text
Env\Python312\python.exe -m pytest Test/algorithms/test_stub_modules.py -q
```
