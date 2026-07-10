# 天气网格数据获取与自动管理工作流实施计划

> **状态更新（2026-07-09）**：本计划全部阶段已完成。阶段一（6个渲染节点 grid_data 优先）、阶段二（`api_config.py`）、阶段三（`workflow_manager.py`）、阶段四（`weather_bridge_service.py` 增强）、阶段五（前端 `layers/index.ts` 视口自动刷新）均已落地。此外，`service.py` 的 fallback 分支已将 temperature/precipitation/humidity/pressure/visibility 全部改为调用 `fetch_grid_forecast` + `build_*_geojson_from_grid`（非风场图层不再用数学模拟数据）。

## 1. 需求概述

用户需要实现一个天气图层自动化管理系统，核心功能包括：

1. **懒加载**：按需请求可见区域的网格数据
2. **自动运行/停止工作流**：地图移动/缩放时自动触发数据更新，每类图层只允许一个活跃工作流
3. **视口优先级**：优先生产视口区域数据，然后异步生成外围区域
4. **统一 API 配置管理**：方便切换不同 API（gee、百度、高德、天地图等）

## 2. 当前状态分析

### 2.1 已完成的工作

根据代码探索，以下功能已实现：

- `GridFetchNode`：支持批量网格数据获取和缓存（`client.py`）
- `build_*_geojson_from_grid()` 方法：6个渲染方法已实现在 `service.py`
- `wind_field_render.py`：已支持 `grid_data` 优先逻辑和 artifact 存储
- `temperature_grid_render.py`：已支持 `grid_data` 优先逻辑和 artifact 存储
- 工作流服务 `weather_bridge_service.py`：支持 `viewport_bbox` 注入

### 2.2 待完成的工作（✅ 全部已完成 — 2026-07-09）

| 文件 | 状态 | 说明 |
|------|------|------|
| `precipitation_grid_render.py` | ✅ 已完成 | 已添加 `grid_data` 优先逻辑 + artifact 存储 |
| `humidity_grid_render.py` | ✅ 已完成 | 已添加 `grid_data` 优先逻辑 + artifact 存储 |
| `pressure_grid_render.py` | ✅ 已完成 | 已添加 `grid_data` 优先逻辑 + artifact 存储 |
| `visibility_grid_render.py` | ✅ 已完成 | 已添加 `grid_data` 优先逻辑 + artifact 存储 |
| `app/services/api_config.py` | ✅ 已创建 | 统一 API 配置管理模块，`get_active_provider` 已集成 |
| `app/weatherengine/workflow_manager.py` | ✅ 已创建 | 工作流生命周期管理器，已接入 bridge |
| `app/services/weather_bridge_service.py` | ✅ 已修改 | 支持 viewport_bbox 注入 + lifecycle 注册 |
| `frontend/src/stores/layers/index.ts` | ✅ 已修改 | `refreshActiveWeatherWorkflows` + 防抖 + 显著变化判定 |

## 3. 实施计划

### 阶段一：完成渲染节点修改（支持真实网格数据）

**目标**：让所有网格渲染节点支持从 `GridFetchNode` 接收真实网格数据。

#### 任务 1.1：修改 `precipitation_grid_render.py`

修改文件：`d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\backend\app\weatherengine\nodes\precipitation_grid_render.py`

**修改内容**：
1. 添加 `import logging` 和 `logger`
2. 添加 `_get_result_storage_service()` 函数（延迟导入）
3. 在 `execute()` 方法中添加 `grid_data` 优先逻辑：
   ```python
   grid_data = inputs.get("grid_data")
   if grid_data:
       geojson = weather_engine_service.build_precipitation_geojson_from_grid(grid_data, layer_id)
   else:
       # 降级：使用单点数据 + 模拟算法
   ```
4. 添加 artifact 存储逻辑（与 `temperature_grid_render.py` 相同模式）
5. 添加 `layer_id`、`viewport_bbox`、`bbox` 输入端口到 `build_spec()`
6. 添加 `logging`
7. 返回 `artifacts` 字段

#### 任务 1.2：修改 `humidity_grid_render.py`

修改文件：`d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\backend\app\weatherengine\nodes\humidity_grid_render.py`

**修改内容**：同上，替换 `precipitation` 为 `humidity`

#### 任务 1.3：修改 `pressure_grid_render.py`

修改文件：`d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\backend\app\weatherengine\nodes\pressure_grid_render.py`

**修改内容**：同上，替换 `precipitation` 为 `pressure`

#### 任务 1.4：修改 `visibility_grid_render.py`

修改文件：`d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\backend\app\weatherengine\nodes\visibility_grid_render.py`

**修改内容**：同上，替换 `precipitation` 为 `visibility`

### 阶段二：创建统一 API 配置管理模块

**目标**：创建一个统一的 API 配置管理模块，方便切换不同数据源。

#### 任务 2.1：创建 `api_config.py`

创建文件：`d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\backend\app\services\api_config.py`

**模块职责**：
1. 定义 API 提供商枚举（`OpenMeteo`、`GEE`、`Baidu`、`Gaode`、`Tianditu`）
2. 定义统一的配置模型 `ApiConfig`
3. 提供 `ApiConfigManager` 类管理所有 API 配置
4. 支持从环境变量或配置文件加载配置
5. 提供配置验证和回退机制

**核心代码结构**：

```python
from enum import Enum
from dataclasses import dataclass
from typing import Optional

class ApiProvider(Enum):
    OPEN_METEO = "open-meteo"
    GEE = "gee"
    BAIDU = "baidu"
    GAODE = "gaode"
    TIANDITU = "tianditu"

@dataclass
class ApiEndpoint:
    url: str
    requires_auth: bool = False
    rate_limit: Optional[int] = None
    timeout: int = 15

@dataclass
class ApiConfig:
    provider: ApiProvider
    name: str
    endpoint: ApiEndpoint
    api_key: Optional[str] = None
    enabled: bool = True
    priority: int = 0  # 优先级，数字越小优先级越高

class ApiConfigManager:
    """统一管理所有 API 配置，支持动态切换和回退"""

    def __init__(self):
        self._configs: dict[ApiProvider, ApiConfig] = {}
        self._load_from_env()

    def _load_from_env(self):
        """从环境变量加载配置"""
        # Open-Meteo（无需 API Key）
        self.register_config(ApiConfig(
            provider=ApiProvider.OPEN_METEO,
            name="Open-Meteo",
            endpoint=ApiEndpoint(url="https://api.open-meteo.com/v1/forecast"),
            priority=0,
        ))

        # 其他 API 配置从环境变量加载...

    def get_config(self, provider: ApiProvider) -> Optional[ApiConfig]:
        return self._configs.get(provider)

    def get_best_available(self, required_capabilities: set[str]) -> Optional[ApiConfig]:
        """获取满足需求的最佳可用配置"""
        # 按优先级排序，返回第一个满足条件的
        pass

    def register_config(self, config: ApiConfig):
        self._configs[config.provider] = config

api_config_manager = ApiConfigManager()
```

### 阶段三：创建工作流生命周期管理器

**目标**：管理天气工作流的自动运行/停止，支持视口优先级。

#### 任务 3.1：创建 `workflow_manager.py`

创建文件：`d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\backend\app\weatherengine\workflow_manager.py`

**模块职责**：
1. `WorkflowLifecycleManager` 类：管理所有活跃工作流
2. 维护 `layer_id → workflow_run_id` 映射，确保每类图层只有一个活跃工作流
3. 支持视口优先级调度
4. 处理工作流取消和新工作流替换

**核心代码结构**：

```python
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import asyncio
import logging

logger = logging.getLogger(__name__)

class WorkflowPriority(Enum):
    VIEWPORT = 0      # 视口区域，优先处理
    SURROUNDING = 1   # 外围区域，异步处理
    BACKGROUND = 2    # 后台任务，可被抢占

class WorkflowState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class ManagedWorkflow:
    workflow_id: str
    layer_id: str
    priority: WorkflowPriority
    state: WorkflowState
    created_at: datetime
    run_id: Optional[str] = None
    bbox: Optional[dict] = None  # 空间范围
    metadata: dict = field(default_factory=dict)

class WorkflowLifecycleManager:
    """天气工作流生命周期管理器

    职责：
    1. 维护 layer_id → 活跃工作流映射（每类图层只允许一个活跃工作流）
    2. 支持优先级调度（viewport > surrounding > background）
    3. 自动取消旧工作流，替换为新工作流
    4. 处理视口变化触发的更新
    """

    def __init__(self):
        # layer_id → ManagedWorkflow
        self._active_workflows: dict[str, ManagedWorkflow] = {}
        self._pending_workflows: asyncio.PriorityQueue = None
        self._lock = asyncio.Lock()

    async def submit_workflow(
        self,
        *,
        layer_id: str,
        workflow_def: dict,
        priority: WorkflowPriority,
        bbox: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """提交工作流，自动处理旧工作流替换"""
        async with self._lock:
            # 检查是否已有该 layer_id 的活跃工作流
            existing = self._active_workflows.get(layer_id)
            if existing and existing.state == WorkflowState.RUNNING:
                # 取消旧工作流
                await self._cancel_workflow(existing)
                logger.info(f"[WorkflowLifecycleManager] Cancelled old workflow {existing.workflow_id} for layer {layer_id}")

            # 创建新工作流
            workflow = ManagedWorkflow(
                workflow_id=workflow_def.get("workflow_id", f"wf-{layer_id}-{datetime.now(timezone.utc).timestamp()}"),
                layer_id=layer_id,
                priority=priority,
                state=WorkflowState.PENDING,
                created_at=datetime.now(timezone.utc),
                bbox=bbox,
                metadata=metadata or {},
            )
            self._active_workflows[layer_id] = workflow
            return workflow.workflow_id

    async def update_workflow_state(self, layer_id: str, state: WorkflowState, run_id: Optional[str] = None):
        """更新工作流状态"""
        async with self._lock:
            workflow = self._active_workflows.get(layer_id)
            if workflow:
                workflow.state = state
                if run_id:
                    workflow.run_id = run_id

    async def _cancel_workflow(self, workflow: ManagedWorkflow):
        """取消工作流"""
        workflow.state = WorkflowState.CANCELLED
        # 通知后端取消 workflow-runs

    async def get_active_workflow(self, layer_id: str) -> Optional[ManagedWorkflow]:
        """获取活跃工作流"""
        return self._active_workflows.get(layer_id)

    def get_all_active_workflows(self) -> list[ManagedWorkflow]:
        """获取所有活跃工作流"""
        return [w for w in self._active_workflows.values() if w.state == WorkflowState.RUNNING]

# 全局单例
workflow_lifecycle_manager = WorkflowLifecycleManager()
```

### 阶段四：修改 `weather_bridge_service.py`

**目标**：支持优先级和自动触发机制。

#### 任务 4.1：增强 `weather_bridge_service.py`

修改文件：`d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\backend\app\services\weather_bridge_service.py`

**修改内容**：

1. 添加导入：
   ```python
   from app.weatherengine.workflow_manager import (
       WorkflowLifecycleManager,
       WorkflowPriority,
       WorkflowState,
       workflow_lifecycle_manager,
   )
   ```

2. 修改 `_execute_workflow()` 方法：
   - 从 `weather_request` 中提取 `priority` 字段
   - 调用 `workflow_lifecycle_manager.submit_workflow()` 注册工作流
   - 监控工作流状态并更新

3. 添加自动触发支持：
   - 在 `supports()` 方法中检查是否需要自动运行
   - 处理视口变化时自动触发更新

### 阶段五：修改前端 `layers/index.ts`

**目标**：实现地图视口变化时自动触发工作流更新。

#### 任务 5.1：增强 `layers/index.ts`

修改文件：`d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\frontend\src\stores\layers\index.ts`

**修改内容**：

1. 添加防抖定时器：
   ```typescript
   const viewportDebounceTimer = ref<number | null>(null)
   const VIEWPORT_DEBOUNCE_MS = 500  // 防抖延迟
   ```

2. 添加视口变化处理函数：
   ```typescript
   function handleViewportChange() {
     // 取消之前的防抖定时器
     if (viewportDebounceTimer.value) {
       window.clearTimeout(viewportDebounceTimer.value)
     }

     // 设置新的防抖定时器
     viewportDebounceTimer.value = window.setTimeout(() => {
       // 重新触发活跃的 weatherengine 图层工作流
       refreshActiveWeatherWorkflows()
     }, VIEWPORT_DEBOUNCE_MS)
   }
   ```

3. 添加 `refreshActiveWeatherWorkflows()` 函数：
   ```typescript
   async function refreshActiveWeatherWorkflows() {
     const activeWeatherLayers = activeLayers.value.filter(
       (layer) => isWeatherEngineLayer(layer.catalogId) && layer.jobLayer
     )

     for (const layer of activeWeatherLayers) {
       if (canRunCatalog(layer.catalogId)) {
         // 重新提交工作流，使用新的 viewport_bbox
         await runWorkflowForCatalog(layer.catalogId)
       }
     }
   }
   ```

4. 在 `setMapViewport()` 中调用 `handleViewportChange()`：
   ```typescript
   function setMapViewport(center: { lng: number; lat: number }, bbox: BoundingBox | null) {
     currentMapCenter.value = center
     currentMapBBox.value = bbox
     handleViewportChange()  // 新增
   }
   ```

## 4. 文件变更清单

| 操作 | 文件路径 |
|------|----------|
| 修改 | `app/weatherengine/nodes/precipitation_grid_render.py` |
| 修改 | `app/weatherengine/nodes/humidity_grid_render.py` |
| 修改 | `app/weatherengine/nodes/pressure_grid_render.py` |
| 修改 | `app/weatherengine/nodes/visibility_grid_render.py` |
| 创建 | `app/services/api_config.py` |
| 创建 | `app/weatherengine/workflow_manager.py` |
| 修改 | `app/services/weather_bridge_service.py` |
| 修改 | `frontend/src/stores/layers/index.ts` |

## 5. 假设与决策

1. **工作流替换机制**：新工作流自动替换旧工作流，无需手动取消
2. **视口优先级**：viewport bbox 工作流优先级最高，优先完成
3. **防抖策略**：500ms 防抖延迟，避免频繁触发
4. **缓存策略**：复用现有的网格数据缓存机制（TTL-based）
5. **粒子流独占**：同 `isWeatherEngineLayer` 判断逻辑，`particleFlowCatalogId` 控制

## 6. 验证步骤

1. **单元测试**：确保所有渲染节点在有/无 `grid_data` 时都能正确工作
2. **集成测试**：测试完整工作流（GridFetch → 渲染 → artifact 存储）
3. **手动测试**：
   - 添加天气图层，观察是否自动触发工作流
   - 移动/缩放地图，观察工作流是否自动更新
   - 切换不同天气图层，观察旧工作流是否正确取消

## 7. 实施顺序

1. 阶段一：完成 4 个渲染节点修改（并行进行）
2. 阶段二：创建 `api_config.py`
3. 阶段三：创建 `workflow_manager.py`
4. 阶段四：修改 `weather_bridge_service.py`
5. 阶段五：修改前端 `layers/index.ts`
6. 测试验证
