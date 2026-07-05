# WebGIS 上层接入示例与接口契约说明

## 1. 目标

本文档说明 `core` 模块如何被 WebGIS 上层的 FastAPI、Celery、Redis 作业体系接入，并补充当前已经落地的接口安全边界。

模块边界保持不变：

- `core` 只提供 GEE 工作流能力、账号池、存储、导出轮询、资源治理、诊断和薄契约层
- FastAPI 路由组织、Celery 编排、Redis 队列、用户鉴权、任务持久化和业务权限控制由 WebGIS 上层实现

## 2. 推荐接入方式

当前推荐通过 [facade.py](file:///d:/Workspace/gee/core/src/webgis_gee/api/facade.py) 中的 `WorkflowApiFacade` 对接路由层；如果 WebGIS 上层使用 FastAPI，可直接复用 [routes.py](file:///d:/Workspace/gee/core/src/webgis_gee/api/routes.py) 中的 `create_api_router()` 和 `WorkflowApiHandlers`。

对上层暴露的 3 个稳定入口：

1. `submit_workflow(workflow, context)`
2. `get_export_task_status(manifest_uri, update_manifest=False)`
3. `run_workflow_job(payload)`

其中：

- `submit_workflow()` 适合 FastAPI 同步入口或上层预处理后的直接提交
- `run_workflow_job()` 适合 Celery worker 直接消费序列化 payload
- `get_export_task_status()` 适合上层轮询导出状态；默认只读，只有显式传 `update_manifest=True` 时才会回写 manifest

## 3. 核心安全约束

这一节是本轮文档补充的重点。上层接入时应当把这些约束视为接口契约的一部分。

### 3.1 `manifest_uri` 不是任意文件路径

当前 `manifest_uri` 只允许指向受系统托管的导出 manifest，不允许把任意本地文件或任意对象存储 key 当作轮询目标。

- `file://` 路径必须是绝对路径
- `file://` 路径必须落在 `Settings.local_storage_root` 下
- `file://` 路径必须位于受管的 `exports/` 目录下
- `s3://` 路径必须与当前配置的 bucket 一致
- `s3://` 路径必须位于受管的 `exports/` 前缀下

这意味着上层应当持久化并传递由 `core` 生成的 `manifest_uri`，而不是自己拼装或接受用户任意输入的 URI。

### 3.2 导出状态查询默认只读

`get_export_task_status()` 现在默认 `update_manifest=False`。

- `GET /exports:status` 默认不写回 manifest
- 需要把轮询结果持久化回 manifest 时，必须显式传 `update_manifest=True`
- 上层如果希望把“查询”和“状态落盘”拆开，可以将默认 GET 保持只读，在 worker 或定时任务中使用显式写回

### 3.3 路由错误信息最小暴露

[routes.py](file:///d:/Workspace/gee/core/src/webgis_gee/api/routes.py) 已做统一异常收口：

- 业务校验类错误保留可读信息
- 参数校验和普通输入错误返回通用客户端错误文案
- 未分类内部异常只返回通用服务端错误文案，并写日志

上层如果继续包一层自己的 API 错误模型，应保持同样的最小信息暴露原则，不要重新把底层 `str(exc)` 直接透出给客户端。

## 4. 契约结构

### 4.1 `submit_workflow(workflow, context)`

最小请求示例：

```python
workflow = {
    "workflow_id": "demo",
    "nodes": [
        {"node_id": "n1", "node_type": "literal", "params": {"value": "gee"}},
        {"node_id": "n2", "node_type": "identity"},
    ],
    "edges": [
        {
            "source_node_id": "n1",
            "source_port": "value",
            "target_node_id": "n2",
            "target_port": "value",
        }
    ],
}

context = {
    "workflow_id": "demo",
    "account_id": None,
    "storage_backend": None,
    "metadata": {
        "request_id": "req-1",
    },
}
```

`WorkflowApiFacade.submit_workflow()` 返回 `WorkflowExecutionResponse`，包含：

- `run_id`
- `workflow_id`
- `status`
- `node_results`
- `outputs`
- `artifacts`
- `warnings`
- `errors`
- `saveback_terminal_plan`
- `saveback_terminal_plans`

### 4.2 `run_workflow_job(payload)`

Celery worker 推荐直接消费如下结构：

```python
payload = {
    "workflow": workflow_dict,
    "context": context_dict,
}
```

它与 `submit_workflow()` 的差别仅在于更适合消息队列中的统一序列化传输。

### 4.3 `get_export_task_status(manifest_uri, update_manifest=False)`

最小请求示例：

```python
status = adapter.get_export_task_status(
    manifest_uri="file:///data/exports/demo/run-1/export/export.json",
)
```

显式写回示例：

```python
status = adapter.get_export_task_status(
    manifest_uri="file:///data/exports/demo/run-1/export/export.json",
    update_manifest=True,
)
```

`WorkflowApiFacade.get_export_task_status()` 返回 `ExportTaskStatusResponse`，当前结构包含：

- `status`
- `state`
- `task_id`
- `started`
- `manifest_uri`
- `polled_at`
- `error_message`
- `raw`

## 5. FastAPI 接入示例

### 5.1 直接挂载 `create_api_router()`

```python
from fastapi import FastAPI

from webgis_gee.api.routes import create_api_router

app = FastAPI()
app.include_router(create_api_router())
```

默认路由行为：

- `POST /gee/workflows:validate`
- `POST /gee/workflows:submit`
- `POST /gee/workflow-jobs:run`
- `GET /gee/exports:status`，其中 `update_manifest` 默认 `False`
- `GET /gee/diagnostics`

### 5.2 自定义依赖注入时复用 `WorkflowApiHandlers`

```python
from fastapi import APIRouter

from webgis_gee.api.contracts import WorkflowSubmissionPayload, WorkflowExecutionResponse
from webgis_gee.api.routes import WorkflowApiHandlers

router = APIRouter(prefix="/gee")
handlers = WorkflowApiHandlers()


@router.post("/workflows:submit", response_model=WorkflowExecutionResponse)
def submit_workflow(payload: WorkflowSubmissionPayload) -> WorkflowExecutionResponse:
    return handlers.submit_workflow(payload)
```

如果上层要统一包装异常，建议只映射为自己的错误码或通用文案，不要直接暴露内部异常文本。

## 6. Celery 接入示例

```python
from celery import Celery

from webgis_gee.api.facade import create_default_contract_adapter

celery_app = Celery("webgis")
adapter = create_default_contract_adapter()


@celery_app.task(name="webgis.gee.run_workflow_job")
def run_workflow_job(payload: dict) -> dict:
    result = adapter.run_workflow_job(payload)
    return result.model_dump(mode="json")


@celery_app.task(name="webgis.gee.poll_export_task")
def poll_export_task(manifest_uri: str) -> dict:
    return adapter.get_export_task_status(
        manifest_uri=manifest_uri,
        update_manifest=True,
    )
```

推荐做法：

- WebGIS 上层负责任务重试、队列优先级和 worker 路由
- `core` 不感知 Celery task id
- 上层数据库保存 `run_id`、`workflow_id`、`manifest_uri`、业务任务 id 的映射关系
- 轮询 worker 如果需要持久化状态，显式传 `update_manifest=True`

## 7. 依赖注入建议

### 7.1 基础注入

```python
from webgis_gee.application.services import WorkflowService
from webgis_gee.config.settings import Settings

service = WorkflowService(
    settings=Settings(
        storage_backend="minio",
        minio_endpoint="127.0.0.1:9000",
        minio_access_key="minio",
        minio_secret_key="minio123",
        minio_bucket="gee",
    )
)
```

### 7.2 外部日志与指标注入

```python
from webgis_gee.application.services import WorkflowService
from webgis_gee.runtime.observability import StructuredEventSink, MetricsSink


class WebGISLogSink(StructuredEventSink):
    def emit(self, payload, *, level: int, logger_name: str) -> None:
        pass


class WebGISMetricsSink(MetricsSink):
    def record_counter(self, name: str, value: int = 1) -> None:
        pass

    def record_duration(self, name: str, duration_ms: float) -> None:
        pass


service = WorkflowService(
    event_sink=WebGISLogSink(),
    metrics_sink=WebGISMetricsSink(),
)
```

### 7.3 账号池注入

```python
from webgis_gee.accounts.pool import InMemoryAccountPool

service = WorkflowService(
    account_pool=InMemoryAccountPool(["acc-1", "acc-2"]),
)
```

### 7.4 Redis 配额协调器注入

```python
from webgis_gee.application.services import WorkflowService
from webgis_gee.runtime.resources import RedisResourceQuotaCoordinator

quota_coordinator = RedisResourceQuotaCoordinator(
    redis_url="redis://127.0.0.1:6379/0",
    key_prefix="webgis:gee:quota",
    lease_ttl_seconds=300,
)

service = WorkflowService(
    quota_coordinator=quota_coordinator,
)
```

## 8. 诊断接口建议

WebGIS 上层可以直接把 `service.diagnose()` 暴露为内部健康检查接口，例如：

```python
@router.get("/gee/diagnostics")
def gee_diagnostics():
    return service.diagnose().model_dump(mode="json")
```

当前诊断输出已经覆盖：

- 节点注册状态
- 存储后端状态
- GEE 依赖状态
- 账号池健康
- 资源控制快照
- 进程内指标快照
- 外部可观测性接线状态
- 工作流版本支持与迁移诊断
- `schema_version 1.12` 的 `saveback_terminal_plan` 终态摘要

## 9. 上层持久化建议

建议 WebGIS 数据库至少保存以下字段：

- `biz_job_id`
- `workflow_id`
- `run_id`
- `manifest_uri`
- `account_id`
- `status`
- `created_at`
- `updated_at`
- `error_message`

另外建议增加以下约束：

- 只保存由 `core` 返回的 `manifest_uri`
- 不接受前端或第三方系统直接提交任意 `manifest_uri`
- 如果需要多租户隔离，上层应把 `manifest_uri` 与租户、业务任务和权限模型绑定

## 10. 行为变更提示

如果上层之前按旧文档或旧默认值接入，需要注意以下变化：

1. `get_export_task_status()` 默认从“读写”改为“只读”
2. `GET /gee/exports:status` 默认不会回写 manifest
3. 想保留轮询即落盘的旧行为，必须显式传 `update_manifest=True`
4. `manifest_uri` 现在必须是受系统托管的 `exports/` manifest，任意本地路径或任意对象 key 都会被拒绝

## 11. 当前不在 `core` 内实现的内容

以下能力仍由 WebGIS 上层负责：

- FastAPI 鉴权与权限控制
- Celery 重试策略、路由和并发模型
- Redis 队列与分布式锁
- 业务任务持久化
- 多租户隔离
- 审计日志与用户操作链路

## 12. 当前推荐的下一步

1. WebGIS 上层按本文档更新 `get_export_task_status()` 的默认值使用方式
2. 在上层持久化层只存储 `core` 返回的受管 `manifest_uri`
3. 将 `create_api_router()` 实际挂入 WebGIS 后端，并补认证、中间件和统一错误模型适配
