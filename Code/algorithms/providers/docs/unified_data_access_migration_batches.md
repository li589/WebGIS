# 统一数据访问迁移批次表

## 目的

本文档用于把“旧模块逐步迁入统一数据访问链路”的工作拆成可执行批次，避免重复迁移已经完成的模块，也避免把“运行时已支持”和“模板/校验已收口”混为一谈。

当前判定标准分三层：

1. 模板层：`request_templates.py` 已声明 `accepted_data_access_datasets`
2. 消费层：模块或 pipeline 已优先消费 `_prepared_inputs`
3. 测试层：已有请求校验或原生模块回归覆盖

## 批次总览

### 已完成批次

以下模块已完成“模板 + 消费 + 测试”三层闭环，不再列入后续迁移批次：

| 模块 | 数据集入口 | 消费方式 | 当前状态 |
| --- | --- | --- | --- |
| `smap_daily` | `SMAP_SPL3SMP_E` | `resolve_prepared_local_directory()` | 已完成 |
| `ndvi_daily` | `NDVI_16DAY_RASTER` | `resolve_prepared_local_directory()` | 已完成 |
| `station_daily` | `ISMN_STM_OR_CASMOS_TXT` | `resolve_prepared_local_directory()` + `resolve_prepared_local_path()` | 已完成 |
| `fy_daily` | `FY_MWRI_HDF` | `resolve_prepared_local_directory()` | 已完成 |
| `inversion_daily` | `daily_bundle_mat` | `resolve_prepared_local_path()` | 已完成 |
| `block_inversion` | `timeseries_bundle_mat` | `resolve_prepared_local_path()` | 已完成 |
| `omega_block` | `timeseries_bundle_mat` | `resolve_prepared_local_path()` | 已完成 |

## 后续批次

### 批次 1：契约收口

目标：把“运行时已支持，但模板/校验尚未完全收口”的入口补齐。

| 对象 | 现状 | 需要补的工作 | 优先级 |
| --- | --- | --- | --- |
| `daily_bundle` | 运行时已支持 `_prepared_inputs` 回填 | 增加 `accepted_data_access_datasets`，补请求校验测试 | 高 |
| `timeseries_bundle` | pipeline 已支持 `_prepared_inputs` | 增加 `accepted_data_access_datasets`，补请求校验测试 | 高 |
| `retrieval_workflow` | workflow 入口已可走新链路，但模板未声明数据集接受范围 | 为 workflow 模板补 `accepted_data_access_datasets` 或明确映射规则，补 workflow 级校验测试 | 高 |

验收标准：

1. `contracts/request_templates.py` 明确声明新数据访问数据集
2. `tests/test_job_request_validation.py` 或 workflow 测试新增正向校验覆盖
3. `tests/test_native_modules.py` 或 workflow 执行测试覆盖 prepared-input 场景

### 批次 2：工作流级统一

目标：把单模块迁移经验完全收敛到 workflow 入口，减少“模块已支持、workflow 模板未声明”的割裂状态。

| 对象 | 工作内容 | 结果要求 |
| --- | --- | --- |
| `retrieval_workflow` | 根据 `mode=dh/ddca/omega` 声明可接受的数据访问数据集 | workflow 提交时不再依赖旧键名硬编码 |
| `runner.dispatch` / `workflow.bridge` | 复核 `_data_access_requests -> _prepared_inputs` 透传路径 | workflow 节点与单模块入口表现一致 |
| workflow 测试 | 覆盖 `workflow_name` 和 `workflow_definition` 两条路径 | prepared-input 在 workflow 模式下稳定可用 |

### 批次 3：兼容入口清理

目标：在不破坏旧接口的前提下，降低旧键名直连逻辑的扩散风险。

| 对象 | 工作内容 | 结果要求 |
| --- | --- | --- |
| `modules/compat.py` | 继续限制兼容桥只做回填，不新增业务分叉 | 新能力默认只从 `_prepared_inputs` 演进 |
| 请求模板文档 | 标记推荐数据访问数据集名与旧键名的映射 | 平台接入只需面向数据集名 |
| 回归测试 | 增加“旧键回退 + 新链路优先”双覆盖 | 防止后续迁移破坏兼容性 |

## 推荐顺序

建议严格按以下顺序推进：

1. 先完成 `daily_bundle`
2. 再完成 `timeseries_bundle`
3. 最后收口 `retrieval_workflow`

原因：

1. `daily_bundle` / `timeseries_bundle` 已有运行时消费代码，补模板和测试成本最低
2. `retrieval_workflow` 依赖前两者的输入语义，更适合作为最后的 workflow 级收口
3. 这样能先把模块级契约补平，再做 workflow 聚合层的一次性整理

## 本轮建议交付物

本轮非 UI 工作建议至少交付以下三项：

1. `daily_bundle` 模板与校验收口
2. `timeseries_bundle` 模板与校验收口
3. `retrieval_workflow` 的数据访问接受规则与测试补齐

完成以上三项后，可以认为“旧模块迁移批次表”中的高优先级条目已基本清空。
