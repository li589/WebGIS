# 天气图层 workflow 瓦片化 Stage 3 接入与实施计划（修订版）

## 1. 摘要（Summary）

当前天气图层显示异常（首次加载正常、缩放后线条稀疏/忽然变化）的根因是**新旧数据路径并存且坐标系/分辨率不统一**：
- 旧路径：`stores/layers/index.ts` 的自定义虚拟瓦片 + `/workflow-runs` 拉取并合并 GeoJSON；
- 新路径：直接 `/weather/tiles/{z}/{x}/{y}` 拉取标准 Web Mercator 瓦片；
- `MapCanvas` 仍从 `jobLayer.layerAssets` 取数据，导致工作流结果与瓦片结果互相覆盖、分辨率混用。

同时项目硬性约束：**所有引擎模块必须通过 `/workflow-runs` 统一访问**。直接 REST 瓦片接口不符合架构约束。

本计划目标：
1. **后端**：新增 `weather_tile_render` 工作流节点，把标准 Web Mercator z/x/y 瓦片请求接入 `/workflow-runs`；
2. **前端**：`weatherTileManager` 不再直接请求 `/weather/tiles`，而是按 z/x/y/hour 提交 workflow 并轮询结果；
3. **前端**：`MapCanvas` / `LayerSidebar` / `InfoPanel` 彻底切换到 tile manager 数据路径，删除旧虚拟瓦片逻辑；
4. 严谨解决移动/缩放冲突、并发控制、结果拼接问题。

## 2. 现状与问题根因分析（Current State & Root Cause）

### 2.1 已稳定/可复用

| 文件 | 说明 |
|------|------|
| `Code/backend/app/weatherengine/tile_service.py` | 已有 Web Mercator 坐标转换 `tile_bbox`、分辨率表 `zoom_to_resolution`、LRU+Redis 缓存、`_grid_data_for_hour`。可复用其坐标与缓存逻辑。 |
| `Code/backend/app/weatherengine/service.py` | `WeatherEngineService` 已有 `_fetch_layer_grid_data`、`_build_geojson_from_grid`、各图层 `build_*_geojson_from_grid` 方法。 |
| `Code/backend/app/weatherengine/nodes/` | 已有 `GridFetchNode`、`WindFieldRenderNode`、`TemperatureGridRenderNode` 等节点，遵循 `BaseNode` + `build_spec()`。 |
| `Code/backend/app/weatherengine/workflow_service.py` | 已注册节点表，`execute_workflow()` 可执行 DAG。 |
| `Code/backend/app/services/weather_bridge_service.py` | 已桥接 `weather_request` 到 workflow-runs 主链，结果映射为 `WorkflowExecutionResult`。 |
| `Code/frontend/src/services/weather-tile-api.ts` | 已有 `lngLatToTile`、`tilesInBounds`、`tileToLngLatBounds`、`buildTileKey`。 |
| `Code/frontend/src/services/weather-tile-utils.ts` | 已有 `mergeWeatherTiles` 按量化经纬度+height 去重。 |
| `Code/frontend/src/stores/weather-tile-manager.ts` | 已有全局 4 槽位、图层内 priority 0/1、generation 丢弃、BFS 外扩队列。 |
| `Code/frontend/src/components/map/weather-render.ts` | 已有 `WEATHER_RENDER_HINTS` + `buildDefaultWeatherRenderHint`。 |

### 2.2 待改造

| 文件 | 问题 |
|------|------|
| `Code/backend/app/weatherengine/nodes/tile_render.py` | 缺少按 z/x/y/hour 渲染单个瓦片的节点（新建）。 |
| `Code/backend/app/weatherengine/workflow_service.py` | 未注册 tile 节点。 |
| `Code/backend/app/weatherengine/nodes/__init__.py` | 未导出 tile 节点。 |
| `Code/frontend/src/services/weather-tile-api.ts` | `fetchWeatherTile` 直接请求 `/weather/tiles`，需改为提交 workflow。 |
| `Code/frontend/src/stores/weather-tile-manager.ts` | 只做 HTTP fetch，缺少 workflow 提交、轮询、结果提取。 |
| `Code/frontend/src/stores/layers/index.ts` | 仍保留旧虚拟瓦片状态（`weatherTileCache`、`weatherPrefetchQueue` 等）和 `runWorkflowForCatalog` 天气分支。 |
| `Code/frontend/src/stores/layers/types.ts` | `ActiveLayerDisplay` 缺少 `renderHint` 字段。 |
| `Code/frontend/src/components/MapCanvas.vue` | `resolveAllWeatherOverlayStates` 仍从 `jobLayer.layerAssets` 取数据。 |
| `Code/frontend/src/components/LayerSidebar.vue` | `addCatalogItem` 对天气图层仍调用 `runWorkflowForCatalog`。 |
| `Code/frontend/src/components/InfoPanel.vue` | `hasWeatherLayerAsset` / `weatherRenderHint` 依赖旧 jobLayer 路径。 |

### 2.3 用户新观察的问题根因

你提到的两个现象，根因可定位如下：

**现象 A：缩放后只剩一点点流场线条**
- 当前 `weather-tile-manager.ts` 的 `getMergedGeojsonForViewport` 只合并**当前视口 bbox 内**的瓦片。缩放后如果新 zoom 的瓦片还没全部返回，就会用少数已缓存瓦片渲染，导致网格范围变小、粒子数量按面积减少，看起来“只剩一点点”。
- `buildWindGridFromGeoJSON` 在网格范围变小时会重新初始化粒子，而不是保留旧位置，造成视觉上的“突然变少”。

**现象 B：首次加载正常，1 秒内忽然变化**
- 当前 `MapCanvas.vue` 同时存在两条数据路径：
  1. `LayerSidebar.vue` 添加天气图层后自动调用 `runWorkflowForCatalog`，返回的 `jobLayer.mapLayerPayload.layerAssets.geojsonData` 是一个基于旧虚拟瓦片的 GeoJSON；
  2. `weatherTileManager` 随后拉取标准 Web Mercator 瓦片并合并。
- 两条路径的坐标系/分辨率/去重逻辑不同，后返回的 tile 数据会覆盖前者，导致“忽然变化”。
- 旧路径使用的 `WEATHER_REQUEST_BUCKETS` 是非标准瓦片，与标准 z/x/y 混用会出现网格错位、边界重复点，等值线和风羽会出现“短线/菱形”等异常。

**现象 C：外扩与移动冲突**
- 当前 `expandNeighbors` 在单个瓦片成功后立即把 8 邻居入队，但没有检查这些邻居是否仍属于当前 generation 的视口或合理预取范围。
- 快速移动时，旧 generation 的预取队列未被清理，仍会继续占用并发槽位，导致新视口瓦片请求被延迟。

## 3. 关键设计决策（Decisions）

1. **天气图层全部走 `/workflow-runs`**：每个 z/x/y 瓦片对应一次 workflow 提交，符合项目“引擎 workflow-based 访问”约束。
2. **点天气查询 `/weather/point` 保持现有 workflow 不变**：本次仅改造图层渲染。
3. **并发模型沿用“全局槽位 + 图层内优先级队列”**：全局槽位由前端设为 3（为点天气/其他 workflow 留 1），后端 `max_active_runs=4` 为硬性上限，429 时退避并重入队列。
4. **移动/缩放冲突通过 `generation` + `cancelWorkflowRun` 解决**：视口变化时递增 generation，对过期 workflow 调用 cancel API；新请求不会等待旧请求完成。
5. **结果拼接沿用 `weather-tile-utils.ts` 的去重逻辑**：按量化经纬度+height 去重，避免相邻瓦片边界重复点。
6. **多个天气图层可共存**：不再限制“一个天气图层的自动渲染工作流”，粒子流图层仍独占（`particleFlowCatalogId`）。
7. **Tile key 必须包含 `layer_id`、`z`、`x`、`y`、`hour`**：确保时间、缩放维度正确编号与缓存。
8. **后端 `/weather/tiles` REST 接口保留但仅作调试/内部使用**：改造后前端不再依赖，未来可删除。
9. **Tile workflow 结果以内联 `geojson` result_kind 为主**：前端 tile manager 直接从 `run.result_refs` 提取，不经过 `buildJobLayer` 的 `map_layer` 路径，避免与旧路径耦合。
10. **视口瓦片未全部就绪时，保留上一代有效数据**：在 `MapCanvas.vue` 中，如果 `getMergedGeojsonForViewport` 返回 null 或特征数过少，不立即清空已有风场网格，而是保持上一帧直到新数据足够覆盖视口。
11. **BFS 外扩限制在“当前视口外扩 1 圈”**：`expandNeighbors` 入队前检查邻居是否在当前视口外扩 1 圈内，避免无限外扩和移动后旧预取浪费。

## 4. 实施步骤（Proposed Changes）

### 4.1 后端：新建 `weather_tile_render` 节点

**文件**：`Code/backend/app/weatherengine/nodes/tile_render.py`（新建）

**节点职责**：
- 输入：`layer_id`（字符串）、`z`/`x`/`y`（整数）、`hour`（整数，0-23，默认 0）、`model`（可选字符串）。
- 通过 `tile_service.py` 的 `tile_bbox(z, x, y)` 计算 EPSG:4326 bbox。
- 根据 `layer_id` 调用 `WeatherEngineService._fetch_layer_grid_data` 获取网格数据。
- 使用 `tile_service._grid_data_for_hour` 将网格数据切换到指定 hour。
- 调用 `WeatherEngineService._build_geojson_from_grid` 生成 GeoJSON。
- 输出：
  - `geojson`：内联 GeoJSON FeatureCollection；
  - `tile_meta`：`{z, x, y, hour, layer_id, feature_count}`；
  - `artifact`：通过 `result_storage_service.create_artifact_result_ref` 存储的 artifact（可选，供前端直接下载）。

**实现要点**：
```python
from app.weatherengine.tile_service import tile_bbox, zoom_to_resolution, _grid_data_for_hour
from app.weatherengine.constants import WEATHER_LAYER_SPECS
from app.weatherengine.nodes._utils import get_weather_engine_service
from app.workflow_engine.base import BaseNode
from app.workflow_engine.enums import PortKind, RunStatus
from app.workflow_engine.models import ArtifactRecord, NodeExecutionResult, NodeSpec, PortSpec
from shared.contracts.api_contracts import ResultKind

class WeatherTileRenderNode(BaseNode):
    node_type: str = "weather_tile_render"

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        layer_id = str(inputs.get("layer_id", "wind-field"))
        z = int(inputs.get("z", 0))
        x = int(inputs.get("x", 0))
        y = int(inputs.get("y", 0))
        hour = int(inputs.get("hour", 0))
        model = inputs.get("model") or settings.weather_default_model

        spec = WEATHER_LAYER_SPECS.get(layer_id)
        if spec is None:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.failed,
                warnings=[f"Unsupported weather tile layer: {layer_id}"],
            )

        bbox = tile_bbox(z, x, y)
        service = get_weather_engine_service()
        grid_data, cache_status, _ = service._fetch_layer_grid_data(bbox=bbox, spec=spec)
        grid_data = _grid_data_for_hour(grid_data, hour)
        geojson = service._build_geojson_from_grid(grid_data=grid_data, layer_id=layer_id)

        # 注入瓦片元数据
        geojson["_tile_meta"] = {
            "layer_id": layer_id,
            "z": z, "x": x, "y": y,
            "hour": hour,
            "model": model,
            "upstream_cache_status": cache_status,
        }

        # 可选：存储 artifact
        artifact = self._store_geojson_artifact(geojson)

        return NodeExecutionResult(
            node_id=self.spec.node_id,
            status=RunStatus.completed,
            outputs={
                "geojson": geojson,
                "tile_meta": geojson["_tile_meta"],
            },
            artifacts=[artifact] if artifact else [],
        )

    def _store_geojson_artifact(self, geojson: dict[str, Any]) -> ArtifactRecord | None:
        from app.services.result_storage import result_storage_service
        from datetime import datetime, timezone
        run_id = self.context.metadata.get("workflow_run_id", self.context.run_id)
        try:
            ref = result_storage_service.create_artifact_result_ref(
                run_id=run_id,
                result_id=f"weather-tile-{self.spec.node_id}",
                result_kind=ResultKind.file,
                title="Weather Tile GeoJSON",
                mime_type="application/geo+json",
                updated_at=datetime.now(timezone.utc),
                payload=geojson,
            )
            return ArtifactRecord(
                artifact_id=ref.resource_key or "",
                workflow_run_id=run_id,
                node_id=self.spec.node_id,
                artifact_type="weather_tile_geojson",
                storage_uri=ref.resource_url or "",
                content_type="application/geo+json",
            )
        except Exception as exc:
            logger.warning("Failed to store tile GeoJSON artifact: %s", exc)
            return None

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="weather_tile_render",
            node_type="weather_tile_render",
            input_ports=[
                PortSpec(name="layer_id", kind=PortKind.value, required=True),
                PortSpec(name="z", kind=PortKind.value, required=True),
                PortSpec(name="x", kind=PortKind.value, required=True),
                PortSpec(name="y", kind=PortKind.value, required=True),
                PortSpec(name="hour", kind=PortKind.value, required=False),
                PortSpec(name="model", kind=PortKind.value, required=False),
            ],
            output_ports=[
                PortSpec(name="geojson", kind=PortKind.geojson),
                PortSpec(name="tile_meta", kind=PortKind.data),
            ],
        )
```

### 4.2 后端：注册并导出 tile 节点

**文件**：
- `Code/backend/app/weatherengine/workflow_service.py`
- `Code/backend/app/weatherengine/nodes/__init__.py`

在 `WeatherWorkflowService._register_default_nodes()` 的 `default_nodes` 元组中追加 `WeatherTileRenderNode`；在 `nodes/__init__.py` 中导出。

### 4.3 后端：bridge 结果映射兼容

**文件**：`Code/backend/app/services/weather_bridge_service.py`

`WeatherBridgeService._build_result_refs()` 当前遍历 `run_result.outputs` 和 `run_result.artifacts`。需确保 `weather_tile_render` 节点产出的内联 `geojson` 被映射为 `WorkflowResultReference`。

具体做法：
- 在 `_build_result_refs` 中检查 `run_result.outputs.get("geojson")`；
- 若存在，构造 `WorkflowResultReference(result_kind=ResultKind.json, inline_data={"geojson": geojson, "tile_meta": tile_meta})`；
- artifact 列表已由节点产出，`_build_result_refs` 中遍历 `run_result.artifacts` 的逻辑保持不变。

这样前端 `weather-tile-manager.ts` 可直接从 `run.result_refs` 中 `result_kind === 'json'` 且 `inline_data.geojson` 存在的条目提取数据。

### 4.4 前端：改造 `weather-tile-api.ts`

**文件**：`Code/frontend/src/services/weather-tile-api.ts`

新增/替换函数：

```ts
export interface SubmitWeatherTileWorkflowOptions {
  hour?: number
  model?: string
  signal?: AbortSignal
}

export async function submitWeatherTileWorkflow(
  layerId: string,
  z: number,
  x: number,
  y: number,
  options: SubmitWeatherTileWorkflowOptions = {},
): Promise<{ runId: string }> {
  const payload = {
    command_type: 'analysis',
    layer_id: layerId,
    requested_outputs: ['json'],
    parameters: { hour: options.hour ?? 0 },
    weather_request: {
      workflow: {
        workflow_id: `weather-tile-${layerId}-z${z}-x${x}-y${y}-h${options.hour ?? 0}`,
        nodes: [
          {
            node_id: 'tile-render',
            node_type: 'weather_tile_render',
            params: {
              layer_id: layerId,
              z,
              x,
              y,
              hour: options.hour ?? 0,
              model: options.model,
            },
          },
        ],
        edges: [],
      },
    },
  }
  const resp = await submitWorkflow(payload)
  return { runId: resp.run_id }
}
```

保留 `lngLatToTile`、`tilesInBounds`、`tileToLngLatBounds`、`buildTileKey` 等坐标工具；删除或标记 `fetchWeatherTile` 为内部调试函数。

### 4.5 前端：改造 `weather-tile-manager.ts`

**文件**：`Code/frontend/src/stores/weather-tile-manager.ts`

把 `fetchTile` 从 HTTP fetch 改为 workflow 提交 + 轮询：

1. `submitWeatherTileWorkflow` 提交 tile workflow，拿到 `runId`；
2. 将 `runId` 记录到 `TileRequest`；
3. 轮询 `getWorkflowRun(runId)`，间隔约 600-800ms，直到 terminal；
4. 从 `run.result_refs` 中提取 `geojson`：优先查找 `result_kind === 'json'` 且 `inline_data.geojson` 存在的条目；
5. 每轮轮询前检查 `generation` 是否过期，过期则调用 `cancelWorkflowRun(runId)` 并丢弃；
6. 429 时把请求放回队列头部，设置 3s 退避；
7. 成功后 BFS 外扩邻居 tile；
8. 全局并发槽位改为 3，为其他 workflow 留 1 个槽位。

关键改动点：
- `TileRequest` 增加 `runId?: string`；
- `fetchTile` 拆分为 `submitTile` + `pollTile`；
- `drainQueue` 中活跃的“fetch”计数改为活跃的 workflow 提交/轮询计数；
- 瓦片 key 仍包含 `layerId:z:x:y:hour`。

### 4.6 前端：改造 `stores/layers/types.ts`

**文件**：`Code/frontend/src/stores/layers/types.ts`

在 `ActiveLayerDisplay` 接口中新增 `renderHint?: WeatherLayerRenderHint` 字段：

```ts
export interface ActiveLayerDisplay {
  // ... existing fields ...
  renderHint?: WeatherLayerRenderHint
}
```

### 4.7 前端：改造 `stores/layers/index.ts`

**文件**：`Code/frontend/src/stores/layers/index.ts`

**A. 删除旧虚拟瓦片状态与方法**

删除：
- `weatherTileCache`、`weatherCatalogPrimaryTileKey`、`weatherRunTileSpecs`、`weatherPrefetchQueue`、`weatherPrefetchActiveKeys`、`weatherPrefetchBackoffUntil`；
- 旧常量：`WEATHER_REQUEST_*`、`WEATHER_PREFETCH_*`；
- 旧类型/函数：`WeatherTileSpec`、`WeatherTileCacheEntry`、`buildWeatherTileSpec`、`buildNeighborWeatherTileSpecs`、`resolvePrimaryWeatherTileSpec`、`buildDefaultViewportBBox`、缓存/合并/预取相关函数；
- `runWorkflowForCatalog` 中的天气分支（天气图层不再提交 analysis workflow）；
- `refreshActiveWeatherWorkflows`、`handleViewportChange` 中仅用于天气刷新的分支；
- `interruptWorkflowForCatalog` 可简化或删除天气专用逻辑。

**B. 接入 `weatherTileManager`**

- 引入 `useWeatherTileManager`；
- `addLayer`：天气图层调用 `weatherTileManager.setLayerActive(catalogId, true)`；
- `removeLayer`：天气图层调用 `weatherTileManager.clearLayer(catalogId)`；
- `toggleLayerVisibility`：天气图层调用 `weatherTileManager.setLayerActive(catalogId, layer.visible)`；
- `setMapViewport`：更新视口后，对每个可见天气图层调用 `weatherTileManager.setViewport(layer.catalogId, center, zoom, currentHour.value)`；
- `setCurrentHour`：小时变化时，对所有可见天气图层重新触发 `setViewport`。

**C. 扩展 `ActiveLayerDisplay.renderHint`**

在 `activeLayersDisplay` computed 中，为天气图层填充：
```ts
renderHint: layer.isAdminBoundary
  ? undefined
  : (buildDefaultWeatherRenderHint(layer.catalogId) ?? layer.jobLayer?.mapLayerPayload?.renderHint),
```

**D. 保留非天气图层的 workflow 能力**

- `runWorkflowForCatalog` 对非天气图层保持原有逻辑；
- `isWeatherEngineLayer`、`supportsMapLayerResult` 保留仅用于判断。

### 4.8 前端：改造 `MapCanvas.vue`

**文件**：`Code/frontend/src/components/MapCanvas.vue`

**A. 引入依赖**

```ts
import { useWeatherTileManager } from '../stores/weather-tile-manager'
const weatherTileManager = useWeatherTileManager()
```

**B. 修改 `resolveAllWeatherOverlayStates`**

对每个可见图层：
- 若是天气图层（`isWeatherEngineCatalogId(layer.catalogId)`）：
  ```ts
  const geojsonData = weatherTileManager.getMergedGeojsonForViewport(layer.catalogId)
  const renderHint = layer.renderHint ?? buildDefaultWeatherRenderHint(layer.catalogId)
  if (!renderHint) continue
  states.push({
    catalogId: layer.catalogId,
    geojsonUrl: null,
    geojsonData,
    cogPreviewUrl: null,
    cogBbox: null,
    renderHint,
    opacity: layer.opacity,
  })
  ```
- 非天气图层保持原 `jobLayer.layerAssets` 逻辑。

**C. 修改 `syncWindParticleFlow`**

- 当 `geojsonData` 为内联数据时，判断内容是否变化（比较 feature 数量 + 采样坐标），避免同一份数据反复触发 `updateGeoJSON` 导致粒子重置；
- 保持 `enableBarbLayer = paint_mode === 'barb'`。

**D. 扩展 watcher**

在现有 watcher 数组中追加 `weatherTileManager.dataVersion`：
```ts
watch(
  () => [
    JSON.stringify(layersStore.activeLayersDisplay.map(...)),
    layersStore.particleFlowCatalogId,
    props.currentHour,
    weatherTileManager.dataVersion,
  ],
  () => scheduleSyncWeatherOverlay(),
)
```

### 4.9 前端：改造 `LayerSidebar.vue`

**文件**：`Code/frontend/src/components/LayerSidebar.vue`

**A. 修改 `addCatalogItem`**

天气图层不再调用 `runWorkflowForCatalog`：
```ts
function addCatalogItem(catalogId: string, isAdminBoundary = false) {
  layersStore.addLayer(catalogId, isAdminBoundary)
  if (!isAdminBoundary && layersStore.isWeatherEngineLayer(catalogId)) {
    // 瓦片由 MapCanvas / tile manager 按需拉取，不再自动提交 analysis workflow
    return
  }
}
```

**B. 调整 library 卡片状态徽标**

天气图层不显示 running/queued/succeeded 等 job 徽标，改为显示“已添加”或 tile manager 的 `pending/cached` 统计。非天气图层保留原徽标逻辑。

### 4.10 前端：改造 `InfoPanel.vue`

**文件**：`Code/frontend/src/components/InfoPanel.vue`

**A. 修改 `weatherRenderHint`**

优先使用 `displayLayer.renderHint`：
```ts
const weatherRenderHint = computed(
  () => displayLayer.value?.renderHint
    ?? jobLayer.value?.mapLayerPayload?.renderHint
    ?? props.pointWeather?.render_hint
    ?? null,
)
```

**B. 修改 `hasWeatherLayerAsset`**

改为判断 tile manager 中该图层已有缓存或进行中：
```ts
const weatherTileManager = useWeatherTileManager()
const hasWeatherLayerAsset = computed(() => {
  if (!isRealtimeWeatherLayerId(displayLayer.value.catalogId)) return false
  const stats = weatherTileManager.getStats(displayLayer.value.catalogId)
  return stats.cached > 0 || stats.pending > 0
})
```

**C. 调整粒子流按钮可用性**

`particleFlowButtonDisabled` 基于新的 `hasWeatherLayerAsset`，不再依赖 `geojsonUrl`。

## 5. 假设与依赖（Assumptions & Dependencies）

- 后端 `weather_tile_render` 节点能在 5s 内完成单个瓦片（Open-Meteo 网格请求已缓存时更快）。
- 前端 `weatherTileManager` 的轮询在视口快速变化时通过 `generation` 及时取消旧 workflow。
- 后端 `max_active_runs=4` 是硬性上限，前端通过 429 退避和全局槽位（3）避免持续撞击。
- 粒子流独占逻辑保持不变：同一时间只启用一个风场图层的粒子流。
- 非天气图层（如 `lab-output`）的 workflow 逻辑不受本次改造影响。
- 直接 `/weather/tiles` 接口在改造期间保留，仅用于调试，前端不再调用。

## 6. 验证步骤（Verification）

### 6.1 后端单元测试

```powershell
cd Code/backend
pytest tests/test_weather_tile_service.py -v
```

新增/更新测试：
- `WeatherTileRenderNode` 对 wind-field / temperature / precipitation 的输入输出；
- 节点注册表包含 `weather_tile_render`；
- bridge 提交含 `weather_tile_render` 的 workflow 后返回正确 `result_refs`；
- `tile_service._grid_data_for_hour` 对 hour=0/hour>0 的切换行为。

### 6.2 后端冒烟测试

```powershell
curl -X POST "http://localhost:8000/workflow-runs" `
  -H "Content-Type: application/json" `
  -d '{"command_type":"analysis","layer_id":"wind-field","requested_outputs":["json"],"weather_request":{"workflow":{"workflow_id":"test-tile","nodes":[{"node_id":"tile","node_type":"weather_tile_render","params":{"layer_id":"wind-field","z":3,"x":2,"y":1,"hour":12}}],"edges":[]}}}'
```

### 6.3 前端类型检查

```powershell
cd Code/frontend
npx vue-tsc --noEmit
```

### 6.4 浏览器运行时验证

- 添加 `wind-field` 图层后，Network 面板出现 `/workflow-runs` POST 请求（无 `/weather/tiles` 请求）；
- 同一视口内并发 workflow 请求数 ≤ 3；
- 缩放后新 z 级别的 tile workflow 被提交，旧 generation 的 workflow 被取消；
- 粒子流持续 10 秒无变短线/消失；
- 平移地图时新视口瓦片加载，旧数据平滑过渡；
- 同时添加风场 + 温度 + 降水，各图层独立请求 workflow，结果正确叠加；
- 切换 hour 后，所有瓦片按新 hour 重新提交；
- Console 中 `[WeatherTileManager]` 日志显示过期 generation 的结果被丢弃。

## 7. 风险与缓解（Risks & Mitigations）

| 风险 | 影响 | 缓解 |
|------|------|------|
| 单 tile workflow 延迟高于直接 HTTP | 首次加载变慢 | 后端复用 Open-Meteo 缓存；前端优先渲染视口 tile，预取外扩。 |
| 后端 max_active_runs=4 导致大量 429 | 卡顿/请求失败 | 前端全局槽位设为 3，429 时 3s 退避并重入队列。 |
| 旧 workflow 逻辑残留导致重复拉取 | 资源浪费、数据覆盖 | 彻底删除 `stores/layers/index.ts` 中的旧虚拟瓦片状态与方法。 |
| 非天气图层渲染被误改 | 回归 | `resolveAllWeatherOverlayStates` 中保留非天气图层的原分支。 |
| 快速缩放导致大量 workflow 积压 | 后端压力过大 | generation 机制 + cancelWorkflowRun + 全局槽位。 |
| 粒子流在数据未就绪时启用 | 按钮可点击但无数据 | `hasWeatherLayerAsset` 改用 tile manager stats 判断。 |
| 相邻瓦片边界去重不彻底 | 边界处数值重复/异常 | 使用 `weather-tile-utils.ts` 的量化去重（factor=1000）。 |
