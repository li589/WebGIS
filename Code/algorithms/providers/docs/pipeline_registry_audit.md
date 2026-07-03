# Pipeline 注册表审计与收口说明

## 1. 文档定位

本文档用于审计 `Python/runner/registry.py` 中保留的兼容 pipeline，明确哪些入口只是旧 API 兼容，哪些入口已经被原生模块或 workflow preset 替代。

## 2. 总体结论

当前注册表中的所有 `pipeline_name` 都应视为兼容入口，而不是未来主执行面。

未来推荐入口只保留三类：

- `module_name=<native module>`
- `workflow_name=<workflow preset>`
- `workflow_definition=<explicit graph>`

## 3. 当前分类

| pipeline_name | 当前角色 | 推荐入口 | 说明 |
|---|---|---|---|
| `smap_daily_pipeline` | `legacy_compat` | `module_name=smap_daily` | 原生模块已落地 |
| `ndvi_daily_pipeline` | `legacy_compat` | `module_name=ndvi_daily` | 原生模块已落地 |
| `fy_daily_pipeline` | `legacy_compat` | `module_name=fy_daily` | 原生模块已落地 |
| `station_daily_pipeline` | `legacy_compat` | `module_name=station_daily` | 原生模块已落地 |
| `inversion_daily_pipeline` | `legacy_compat` | `module_name=inversion_daily` | 原生模块已落地 |
| `daily_bundle_pipeline` | `legacy_compat` | `module_name=daily_bundle` | 原生模块已落地 |
| `timeseries_bundle_pipeline` | `legacy_compat` | `module_name=timeseries_bundle` | 原生模块已落地 |
| `block_inversion_pipeline` | `legacy_compat` | `module_name=block_inversion` | 原生模块已落地 |
| `omega_block_pipeline` | `legacy_compat` | `module_name=omega_block` | 原生模块已落地 |
| `retrieval_workflow_pipeline` | `shim_compat` | `workflow_name=retrieval_workflow` | 仅保留 shim |

## 4. 当前审计结论

### 4.1 兼容入口的存在意义

保留这些 pipeline 的主要原因是：

1. 兼容历史调用方
2. 给迁移期保留平滑过渡
3. 降低一次性切换成本

### 4.2 为什么不应继续扩展 pipeline

pipeline 作为主执行面的问题在于：

1. 它会把新能力继续绑定到旧接口语义上
2. 它会阻碍 module/workflow 的统一收敛
3. 它会让请求模板、字段映射和执行语义持续分叉

## 5. 推荐收口顺序

### 第一阶段

- 保留 `runner/registry.py`
- 保留全部兼容 pipeline
- 新功能只加到 `modules` 或 `workflow preset`

### 第二阶段

- 清点所有外部调用样例
- 文档默认入口全部切换到 `module_name` / `workflow_name`
- 明确 `retrieval_workflow_pipeline` 仅作为 shim

### 第三阶段

- 当外部调用方不再依赖 `pipeline_name` 时，逐步移除 `legacy_compat`
- 最终只保留 `module_name`、`workflow_name` 和 `workflow_definition`

## 6. 代码落点

- 兼容注册表：`Python/runner/registry.py`
- 旧检索 shim：`Python/pipelines/retrieval_workflow_products.py`
- 正式 workflow preset：`Python/workflow/presets.py`

## 7. 结论

pipeline 注册表当前的角色是“迁移过渡层”，不是长期主执行面。随着 module 和 workflow 的稳定，pipeline 应该逐步退场，只保留必要兼容入口。
