# Pipeline 注册表收口清单

本文用于收口 `Python/runner/registry.py` 的职责边界，明确哪些 `pipeline_name` 仍保留兼容意义，哪些已经退化为 shim，以及后续可移除方向。

## 结论

当前注册表中的全部 pipeline 都应视为旧 API 面的兼容入口，而不是未来主执行面。

未来推荐入口只保留两类：

- `module_name=<native module>`
- `workflow_name=<workflow preset>` 或直接传 `workflow_definition`

其中：

- 大多数 `*_pipeline` 已有对应原生 module，可归类为 `legacy_compat`
- `retrieval_workflow_pipeline` 已不再承担真实编排职责，可归类为 `shim_compat`

## 分类表

| pipeline_name | 当前角色 | 推荐入口 | 后续方向 |
| --- | --- | --- | --- |
| `smap_daily_pipeline` | `legacy_compat` | `module_name=smap_daily` | 等外部调用面迁移后再考虑移除 |
| `ndvi_daily_pipeline` | `legacy_compat` | `module_name=ndvi_daily` | 等外部调用面迁移后再考虑移除 |
| `fy_daily_pipeline` | `legacy_compat` | `module_name=fy_daily` | 等外部调用面迁移后再考虑移除 |
| `station_daily_pipeline` | `legacy_compat` | `module_name=station_daily` | 等外部调用面迁移后再考虑移除 |
| `inversion_daily_pipeline` | `legacy_compat` | `module_name=inversion_daily` | 等外部调用面迁移后再考虑移除 |
| `daily_bundle_pipeline` | `legacy_compat` | `module_name=daily_bundle` | 等外部调用面迁移后再考虑移除 |
| `timeseries_bundle_pipeline` | `legacy_compat` | `module_name=timeseries_bundle` | 等外部调用面迁移后再考虑移除 |
| `block_inversion_pipeline` | `legacy_compat` | `module_name=block_inversion` | 等外部调用面迁移后再考虑移除 |
| `omega_block_pipeline` | `legacy_compat` | `module_name=omega_block` | 等外部调用面迁移后再考虑移除 |
| `retrieval_workflow_pipeline` | `shim_compat` | `workflow_name=retrieval_workflow` | 优先保留兼容名，但不再扩展功能 |

## 分阶段建议

### 第一阶段

- 保留 `runner/registry.py`
- 保留全部 `pipeline_name` 兼容入口
- 新功能只加到 `module` 或 `workflow preset`

### 第二阶段

- 统计调度侧还在使用哪些 `pipeline_name`
- 把调用样例、配置模板、文档默认入口全部改成 `module_name` / `workflow_name`
- 明确 `retrieval_workflow_pipeline` 只作为 shim，不再新增任何独立逻辑

### 第三阶段

- 当外部调用方不再依赖 `pipeline_name` 时，逐步移除 `legacy_compat`
- 最终只保留：
  - `module_name`
  - `workflow_name`
  - `workflow_definition`

## 当前代码落点

- 注册表兼容状态元数据：`Python/runner/registry.py`
- 旧检索编排 shim：`Python/pipelines/retrieval_workflow_products.py`
- 正式 workflow preset：`Python/workflow/presets.py`
