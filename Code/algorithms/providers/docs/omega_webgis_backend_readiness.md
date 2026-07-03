# OMEGA WebGIS Backend Readiness

## 目的

本文档用于统一回答三个问题：

1. OMEGA 当前代码与文档是否已经同步
2. 当前代码距离“可直接接入 WebGIS 后端作业调度器”还有哪些差距
3. 下一阶段最值得补齐的不是性能，而是哪些集成前置条件

## 当前状态

### OMEGA 算法状态

截至当前代码，OMEGA 主链处于以下状态：

1. `Mironov` 标量核已实现
2. `Fresnel` 标量核已实现
3. 单温 TB 标量核已实现
4. 双温 TB 标量核已实现
5. physics 层已具备 `Numba` 可回退装载逻辑
6. residual/solver/Jacobian 的后续深层原型均未保留

换句话说：

- 当前稳定状态是“前向模型内核化已落地”
- 不是“整条 OMEGA 求解链已完成深层性能优化”

### 文档状态

当前需要这样理解：

1. `omega_baseline_and_candidates.md`
   - 作为当前稳定基线和已证伪候选清单

2. `omega_forward_kernel_optimization_plan.md`
   - 作为前向内核化阶段的设计归档

3. `omega_forward_kernel_boundary_design.md`
   - 作为前向边界拆分设计稿，并附带当前落地状态

4. `omega_residual_solver_deep_plan.md`
   - 作为 residual/solver 深层设计稿
   - 当前只保留设计价值，不代表代码已经实现

## 当前接入链路

仓库里当前已经补上了一个最薄 HTTP 服务入口，位于：

- `Python/service/http_server.py`

它当前提供：

1. `GET /health`
2. `GET /schemas/job-request`
3. `GET /schemas/workflow-definition`
4. `POST /jobs/validate`
5. `POST /jobs`

但要注意：

- 这是一层“最小可运行 HTTP adapter”
- 它解决的是“平台如何直接调本仓库”
- 还不是带鉴权、配额、网关治理的生产级服务

现有推荐接入链路是：

```text
WebGIS / Backend Request
  -> JSON payload
  -> JobRequest / WorkflowDefinition 反序列化
  -> run_job()
  -> workflow / module / pipeline 执行
  -> manifest / artifact / scheduler status
```

当前统一入口是：

- `runner.dispatch.run_job()`

当前推荐 OMEGA 任务入口是：

1. `workflow_name = retrieval_workflow`
2. `algorithm_params.mode = omega`

工作流主链是：

```text
timeseries_bundle -> omega_block
```

## 已具备的能力

从“能不能接到后端调度器”这个角度看，当前已经具备以下能力：

1. 已有统一运行入口 `run_job()`
2. 已有 `JobRequest` 契约
3. 已有 `workflow_definition / workflow_name / module_name / pipeline_name` 四级执行模式
4. 已有调度器适配接口：
   - `SchedulerAdapter`
   - `DataSourceAdapter`
   - `LoggerAdapter`
   - `ProductSink`
5. 已有 `retrieval_workflow` 预定义工作流
6. OMEGA 已经作为 `omega_block` 模块进入 workflow 主链
7. 已有 JSON/HTTP 适配与校验文档

因此：

- 从 Python 运行时能力上说，当前已经“可以被后端调用”
- 但还没有达到“可以直接无缝接到 WebGIS 生产调度器”的程度

## 当前主要差距

### 差距 1：没有现成 HTTP 服务层

当前仓库提供的是：

- Python 函数入口
- JSON/契约文档
- 工作流与模块执行器
- 最小 HTTP 服务入口与 schema/validate/submit 路由

没有提供的是：

- 生产级认证、鉴权、请求配额、超时治理
- 平台真实 scheduler adapter / datasource adapter 实现
- 面向生产网关的部署与运维约束

这意味着：

- WebGIS 后端已经可以直接复用仓库内的最小 HTTP adapter 做联调
- 但若要直接上线生产，仍需在外面补平台级 service / gateway 能力

### 差距 2：OMEGA 的外部输入契约对平台仍有门槛

当前 `mode=omega` 时，除了常规 bundle 输入，还要求：

1. `omega_fixed_mat`
2. `exp0_calib_mat`

这两个输入是 workflow 和请求模板层都明确要求的。

当前差距不在算法代码，而在平台侧：

- 是否已有稳定的这两类 MAT 产品来源
- 是否已有对应的数据登记、版本管理和路径解析逻辑
- 是否能在作业提交时稳定注入到 `datasource_selection`

如果平台侧这两类输入还没有固定生产链，那么当前还不能说 OMEGA 已准备好直接上线调度。

### 差距 3：仍需把请求样例与服务入口绑定成接入手册

虽然现在已经补了平台对接文档和最小 HTTP 入口，但对 WebGIS 后端团队来说，仍需把这些资产固化成统一接入手册：

1. OMEGA 最小请求 JSON 样例
2. `retrieval_workflow + mode=omega` 的字段解释表
3. 平台必填输入清单
4. 成功输出 artifact 清单
5. 失败时的常见错误样例
6. HTTP 路由与运行命令说明

当前缺的已经不是“有没有文档”，而是“是否已经形成一页式平台接入手册并纳入部署流程”。

### 差距 4：缺少作业级稳定性与资源预估说明

当前已经有性能基线，但还没有转译成调度器关心的维度：

1. 典型作业运行时长区间
2. 单任务 CPU/内存建议
3. 是否适合并发
4. 是否建议串行 block 级任务
5. 哪些 profile 只能离线运行，哪些适合在线 quick check

对 WebGIS 调度器而言，这些信息比 `cProfile` 更关键。

### 差距 5：缺少“生产就绪状态”判定

当前我们已经知道：

- 前向内核化落地
- 若干 residual/Jacobian 原型失败
- 正式层基线已建立

但还没有一份明确的“接入准入标准”，例如：

1. 哪个提交或分支是对接基线
2. 哪些实验性优化不得带入调度主线
3. 哪些输入模式是支持的
4. 哪些运行模式仍属于实验性质

没有这份判定，平台侧很难确认“现在能接哪个版本”。

## 距离“可直接接入”的判断

如果“可直接接入 WebGIS 后端作业调度器”定义为：

- 平台只需按约定组装请求
- 不必额外猜测算法输入
- 不必额外推断资源与运行特性
- 不必自行补完整套错误映射文档

那么当前距离这个目标还差：

1. 将现有最小 HTTP adapter 升级为生产级 service/gateway
2. 将现有请求样例与运行说明固化进平台接入手册
3. 平台侧落地资源/时长/调度建议
4. 一份生产准入版本说明
5. 平台侧对 `omega_fixed_mat` / `exp0_calib_mat` 的稳定供给链

## 建议优先级

### 第一优先级：补集成文档，不继续做性能试验

建议先补以下文档，而不是继续试新的性能原型：

1. `OMEGA-WebGIS 最小请求样例`
2. `OMEGA 产物与错误响应清单`
3. `OMEGA 调度资源建议`
4. `OMEGA 当前生产准入说明`

### 第二优先级：补平台输入检查清单

重点确认：

1. `omega_fixed_mat` 的来源
2. `exp0_calib_mat` 的来源
3. `timeseries_bundle` 的输入路径规则
4. 作业 workspace 与 artifact 持久化位置

### 第三优先级：最后再决定是否继续深层性能优化

只有当平台接入链路清晰后，才有必要继续判断：

1. 是否还要继续 residual/solver 深层原型
2. 是否要为生产调度场景补更多大规模基线

## 当前建议

当前最合理的下一步不是继续改 `omega.py`，而是：

1. 新增一份 `OMEGA WebGIS 最小接入手册`
2. 新增一份 `OMEGA 调度资源与运行建议`
3. 明确“当前可接入版本”的范围和限制

完成这三步后，才能更准确地回答：

- 当前版本是否可以直接给 WebGIS 后端调度器接入
- 接入时平台还需要补哪些外部能力

## 相关接入文档

当前已补齐以下配套文档，建议与本文一起阅读：

1. [OMEGA WebGIS 最小请求样例](file:///d:/Workspace/mat2py/docs/omega_webgis_minimal_request_examples.md)
2. [OMEGA 调度资源与运行建议](file:///d:/Workspace/mat2py/docs/omega_scheduler_runtime_guidance.md)
3. [OMEGA 当前生产准入说明](file:///d:/Workspace/mat2py/docs/omega_production_readiness.md)
4. [最小 HTTP 作业服务](file:///d:/Workspace/mat2py/docs/minimal_job_http_service.md)
