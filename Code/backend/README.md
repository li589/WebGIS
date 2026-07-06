# Backend

`Code/backend/` 是本项目的后端服务根目录，当前已经从早期的接口原型演进为以工作流为中心的服务层。它负责承接前端请求、组织任务运行、管理状态与事件、回传结果，并作为 Python 算法包与 Web 平台之间的桥梁。

## 当前后端定位

后端的核心职责已经不是单纯提供 CRUD API，而是组织一条稳定的任务执行链：

- 接收前端或外部系统请求
- 校验并标准化工作流提交参数
- 创建运行记录、状态流和事件流
- 选择同步执行或 Celery 异步执行
- 调用 Python provider bridge 执行算法任务
- 管理 artifact、结果引用和日志输出
- 向前端提供查询、元数据和结果读取接口

## 当前可用能力

- `GET /health`
- `POST /workflow-runs`
- `GET /workflow-runs/{run_id}`
- `GET /workflow-runs/{run_id}/view`
- `GET /workflow-runs/{run_id}/events`
- `POST /workflow-runs/{run_id}/cancel`
- `POST /workflow-runs/{run_id}/retry`
- `GET /runtime/status`
- `GET /artifacts/{artifact_id}`
- `GET /artifacts/{artifact_id}/preview.png`
- `GET /weather/point`
- `GET /algorithm/workflows`
- `GET /algorithm/workflows/{workflow_name}`
- `GET /algorithm/workflows/{workflow_name}/panel-schema`
- `GET /algorithm/workflows/{workflow_name}/ui-schema`
- `GET /geo/transform`：用于私有坐标系到展示坐标的基础转换入口
- 支持 `sync / celery` 两种工作流执行模式
- 支持结构化日志、结果大对象落盘与旧 `/tasks` 桥接

## 当前新增后端事实

当前后端除了基础 workflow 主链，还已经稳定存在以下实现：

- `retry_pending` 中间态与自动重试语义
- `FailureCategory` 失败分类
- `BridgeExecutionError` 作为 bridge 层统一失败协议
- `source_fetcher` 驱动的真实下载抓取链
- `weatherengine fallback` 与 `weather workflow DAG` 双路径天气执行面
- artifact preview 路由，供前端以 PNG 方式读取 COG 结果

## 当前实现备注

- `python_provider_bridge_service.py` 已接入工作流主链，用于把 Python provider 的结果映射成统一结果引用
- 坐标转换服务当前提供 `GCJ-02 / BD-09 / EPSG:3857` 的基础入口，后续如需精确投影应继续按数据源补充

## 目录结构

```text
backend/
├─ app/
│  ├─ api/          # REST API 路由
│  ├─ core/         # 配置、日志、异常处理、运行时基础能力
│  ├─ services/     # 业务服务层、工作流编排、存储与桥接
│  ├─ tasks/        # Celery 任务定义
│  └─ main.py       # FastAPI 应用入口
└─ tests/           # 后端测试
```

## 当前核心模块

### `app/api/`
负责暴露 HTTP 接口，只处理参数接收、调用服务层和返回响应。

### `app/core/`
负责后端基础设施能力，包括配置、日志、异常处理和运行时相关设置。

### `app/services/`
这里是后端的主业务层，当前已经包含工作流执行、任务仓储、结果存储、对象存储、缓存、Python provider bridge、download/analysis workflow 等职责。

其中最近变化较大的模块包括：

- `interaction_hub.py`：统一工作流状态流转，已支持失败分类和自动重试
- `failure_classifier.py`：负责异常到 `FailureCategory` 的映射
- `bridge_protocol.py`：定义 `BridgeExecutionError`
- `source_fetcher.py`：提供 `http / minio / local file` 抓取实现
- `download_service.py`：已支持 `partial_success`、`retry_pending` 和真实 artifact 抓取
- `python_provider_bridge_service.py`：已开始消费 provider manifest / template 校验结果
- `weather_bridge_service.py`：把 workflow 主链路由到天气 DAG

### `app/tasks/`
负责长耗时任务的 Celery 任务定义与调度入口。

当前任务侧除了通用 workflow task，还已包含天气刷新等定时任务入口。

### `tests/`
覆盖后端服务、工作流、任务与集成路径的测试。

## 后端运行模型

当前后端采用“控制流 + 数据流”双通道模型：

1. 前端提交 workflow request
2. 后端创建 run 记录与事件流
3. 调用同步执行器或 Celery worker
4. worker / service 调用 Python 算法包
5. 运行状态通过 `workflow-runs/{run_id}` / `events` 这类控制流接口回传
6. 展示结果通过 `workflow-runs/{run_id}/view` 这类数据流接口回传
7. 大对象通过 artifact 接口按需访问

控制流负责状态机与编排，数据流负责展示与资源访问，二者保持分离以降低耦合。

补充说明：

- 控制流状态当前不止 `accepted/running/succeeded/failed`，还包含 `retry_pending`
- 数据流不止有原始 artifact，还包含 `/artifacts/{artifact_id}/preview.png` 这种面向前端展示的预览接口
- `ResultKind.map_layer` 已经成为天气图层、GeoJSON 和栅格预览链的重要数据面入口

## 当前天气执行结构

天气相关代码当前不是单点实现，而是两条路径并存：

1. `weatherengine/service.py`
   - 负责 `/weather/point`
   - 负责 fallback `map_layer` 产物
   - 负责 `GeoJSON / COG / preview` 资产组织
2. `weatherengine/workflow_service.py` + `weatherengine/nodes/*`
   - 负责天气 DAG
   - 当前节点已覆盖风场、温度、降水、湿度、气压、能见度与摘要生成

这两条路径通过 `weather_bridge_service.py` 与 `workflow_tasks.py` 接入现有 `workflow-runs` 主链。

## 当前与 Python provider 契约层的关系

后端现在不只是调用 provider 执行函数，还开始消费 provider 契约层：

- `algorithms/providers/Python/contracts/provider_manifest.py`
- `algorithms/providers/Python/contracts/template_deriver.py`

这意味着 provider 的模板导出、请求校验和 list/describe 结果，正在从分散实现收口到统一入口。

## 与 Python 算法包的关系

后端并不直接承担科学计算本体，而是通过 provider bridge 和工作流服务调用 `Code/algorithms/providers/Python` 中的统一入口。这样可以让：

- 前端保持轻量
- 后端保持工作流编排清晰
- 算法层保持独立演进
- 结果模型保持一致

## 运行与部署

本地开发优先使用仓库内的环境脚本。后续若切换到 Celery、Redis 或 MinIO，需要与 `Env/backend/` 中的启动脚本和环境变量保持一致。

## 推荐阅读顺序

如果你在接手后端，建议按下面顺序阅读：

1. `Code/backend/README.md`
2. `Code/shared/contracts/README.md`
3. `Code/algorithms/providers/Python/README.md`
4. `Code/algorithms/providers/docs/backend_integration_contract.md`
5. `Code/algorithms/providers/docs/detailed_design.md`

## 说明

- 当前后端已经进入工作流化阶段，旧的“单接口任务模型”不再是主叙事
- `workflow-runs` 是当前更重要的主线，`/tasks` 仅作为兼容桥接存在
- 文档与代码需要持续保持一致，尤其是路由名称、任务模型和结果模型
