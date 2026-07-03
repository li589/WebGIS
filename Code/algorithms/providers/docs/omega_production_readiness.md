# OMEGA 当前生产准入说明

## 目的

本文档用于回答一个具体问题：

当前仓库中的 OMEGA，是否已经达到“可直接接入 WebGIS 后端作业调度器”的状态？

结论先行：

1. 已经达到“可由 Python 后端稳定调用”的状态
2. 已经达到“可进入受控调度联调”的状态
3. 还没有达到“平台零适配即可直接生产上线”的状态

## 当前可作为接入基线的范围

当前可作为对接基线的，是以下稳定路径：

1. `run_job()` 统一执行入口
2. `JobRequest` 请求契约
3. `workflow_name = retrieval_workflow`
4. `module_name = omega_block`
5. `retrieval_workflow -> timeseries_bundle -> omega_block`
6. `ApiErrorResponse` 标准错误响应
7. `ProductManifest` 产物清单输出

从算法状态看，当前稳定保留的是：

1. `Mironov` 标量核
2. `Fresnel` 标量核
3. 单温 TB 前向核
4. 双温 TB 前向核
5. physics 层 `Numba` 可回退装载逻辑

## 当前不应带入生产主线的内容

以下内容虽然做过原型验证，但当前明确不属于生产准入范围：

1. residual helper 深层实验原型
2. Jacobian `x_trial` 顺序评估原型
3. evaluator 对象边界原型
4. 任何未通过 `formal96` 正式回归的临时性能分支

原因很明确：

1. 它们没有改变语义错误
2. 但在正式层面出现了明显性能退化
3. 因此当前只保留设计认知，不保留生产代码路径

## 当前支持的推荐入口

### 推荐入口

建议平台首发只开放：

1. `pipeline_name = "workflow"`
2. `workflow_name = "retrieval_workflow"`
3. `task_type = "retrieval"` 或 `task_type = "workflow"`
4. `algorithm_params.mode = "omega"`

### 可选入口

当平台已经能自己先产出 `timeseries_bundle_*.mat` 时，可以开放：

1. `pipeline_name = "workflow"`
2. `module_name = "omega_block"`
3. `task_type = "omega_block"`

### 不建议首发开放的入口

当前不建议平台首发就暴露：

1. 显式 `workflow_definition` 自由编排
2. 旧兼容 `pipeline_name = "retrieval_workflow_pipeline"` 作为主入口
3. 任何 profiling 或性能实验型开关

## 当前仍然缺失的生产前置条件

### 缺失 1：HTTP 服务层

当前仓库提供的是：

1. Python 契约
2. JSON 反序列化能力
3. 运行分发入口
4. workflow 和 module 执行器
5. 最小 HTTP 服务入口

当前最小 HTTP 服务入口已经提供：

1. `GET /health`
2. `GET /schemas/job-request`
3. `GET /schemas/workflow-definition`
4. `POST /jobs/validate`
5. `POST /jobs`

当前没有直接提供：

1. 生产级鉴权
2. 认证
3. 配额
4. 网关超时治理
5. 平台部署与运维集成

因此当前状态应理解为：

1. 已具备最薄可运行 service adapter
2. 但平台仍需补一层生产级 gateway / service 治理能力

### 缺失 2：平台级输入供给链

对 OMEGA 而言，真正影响能否上线的关键不是代码，而是平台是否已稳定管理以下输入：

1. `omega_fixed_mat`
2. `exp0_calib_mat`

需要明确的不是“理论上能不能传”，而是：

1. 数据从哪里来
2. 谁维护版本
3. 如何按区域和时间关联
4. 路径如何注入 `datasource_selection`
5. 失效时如何告警和回滚

如果这条供给链未稳定，就不应宣称 OMEGA 已可直接生产上线。

### 缺失 3：平台级运行制度

当前仍需由平台补齐：

1. 调度超时
2. 重试策略
3. 失败告警
4. 产物持久化
5. 日志归档
6. manifest 生命周期管理

### 缺失 4：生产版本冻结说明

当前还需要明确：

1. 哪个提交或 tag 是平台对接基线
2. 之后哪些分支属于实验
3. 谁有权限把实验分支合入调度主线

没有这层版本制度，平台很难确保自己接到的是“稳定 OMEGA”而不是“正在试验的 OMEGA”。

## 当前可以做出的工程判断

### 可以说的

当前可以明确说：

1. OMEGA 已经进入统一的 `run_job()` 调用链
2. OMEGA 已经进入 `retrieval_workflow` 预定义 workflow 主链
3. OMEGA 已经具备标准请求校验、标准错误响应、标准 manifest 输出
4. 当前稳定代码可以支持后端联调和受控调度试运行

### 不能说的

当前还不能说：

1. WebGIS 后端无需任何适配即可直接上线
2. 当前所有 OMEGA 相关实验分支都适合进入生产
3. 平台已经自动具备 `omega_fixed_mat` 和 `exp0_calib_mat` 的稳定供给能力
4. 当前离线 profile 结果已经等同于生产 SLA

## 生产准入 checklist

建议平台在准入评审时至少逐项确认以下内容。

### A. 请求入口

1. 是否固定使用 `workflow_name = retrieval_workflow` 作为默认入口
2. 是否明确了 `module_name = omega_block` 的使用边界
3. 是否禁止前端直接暴露实验型入口

### B. 输入供给

1. 是否已有 `omega_fixed_mat` 的稳定来源
2. 是否已有 `exp0_calib_mat` 的稳定来源
3. 是否已验证 `smap_daily_mat`、`ndvi_daily_mat`、`ancillary_mat` 的路径解析逻辑
4. 是否能在任务提交时稳定写入 `datasource_selection`

### C. 运行保障

1. 是否已配置默认资源档位
2. 是否已配置超时策略
3. 是否已限制首发并发
4. 是否已定义失败重试和人工介入条件

### D. 输出消费

1. 是否以 `ProductManifest` 作为唯一成功依据
2. 是否已接住 `omega_block_mat`
3. 如果开启逐日输出，是否已接住 `omega_daily_mat`
4. 是否已处理 `qc_flag_mat`、`qc_condk_mat`、`qc_sratio_mat`

### E. 错误治理

1. 是否已接入标准 `ApiErrorResponse`
2. 是否按 `400 / 422 / 500` 做错误分类
3. 是否能把 `issues[].field_path` 映射回平台表单或任务配置项

### F. 版本治理

1. 是否明确了当前准入基线版本
2. 是否明确实验分支不得直接进入调度主线
3. 是否有回滚策略

## 当前建议的上线结论

如果以上 checklist 还没全部完成，当前最合理的结论应是：

1. 允许进入后端联调
2. 允许进入受控灰度调度
3. 不建议直接宣称为零适配生产就绪

如果平台已经补齐：

1. 生产级 HTTP service / gateway 能力
2. `omega_fixed_mat` / `exp0_calib_mat` 供给链
3. 调度资源和超时策略
4. manifest 和错误响应接入
5. 基线版本冻结

那么就可以把状态提升为：

1. 可受控生产接入

但即便如此，仍建议先经历一轮灰度和回归观察，而不是直接全量放开。

## 当前最合理的下一步

按优先级，建议现在这样推进：

1. 先完成平台请求模板和路径注入封装
2. 再完成调度资源、超时和错误响应接入
3. 再冻结一个 OMEGA 对接基线版本
4. 最后进入灰度试运行

这条路径比继续做新的性能试验更直接、更接近真正的 WebGIS 接入目标。
