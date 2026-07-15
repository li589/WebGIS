# 天气图层 Workflow 瓦片化 Stage 3 修复实施计划

## 1. 摘要（Summary）

针对当前天气图层“首次加载正常、随后忽然变短线/稀疏/消失，缩放后只剩少量流场线条”的问题，本计划定位为 **Stage 3 接入的真正落地执行**：

- **后端**：修复 `weather_tile_render` 节点，强制按 `zoom_to_resolution(z)` 固定分辨率输出，解决相邻瓦片网格不一致导致的拼接缝隙/重叠。
- **前端**：彻底完成 `MapCanvas.vue`、`stores/layers/index.ts`、`LayerSidebar.vue`、`InfoPanel.vue` 向 `weatherTileManager` 的切换。
- **清理**：删除 `stores/layers/index.ts` 中仍在运行的旧虚拟瓦片路径（`WEATHER_REQUEST_BUCKETS`、自动 workflow 提交、BFS 预取队列），消除两条数据 pipeline 互相覆盖。
- **并发**：每个天气图层独立走 workflow，不限制“一个图层自动 workflow”；全局 3 槽位 + 图层内 priority 队列 + generation 机制保证多图层并发可控。
- **移动/缩放冲突**：视口变化时 generation++，过期 workflow 立即取消；BFS 外扩请求必须通过当前 generation 校验，避免旧预取占用槽位。
- **结果拼接**：前端 `mergeWeatherTiles` 按量化经纬度 + `height` 去重；后端固定分辨率保证采样点对齐。
- **调试**：前后端增加完整 tile meta、feature count、resolution、generation 日志，便于在浏览器中定位“忽然变化”的根因。

所有天气图层数据仍统一走 `/workflow-runs`，符合项目架构约束。

## 2. 现状与根因分析（Current State & Root Cause）

### 2.1 已完成的可复用代码

| 文件 | 状态 | 说明 |
|------|------|------|
| `Code/backend/app/weatherengine/nodes/tile_render.py` | 已创建 | `WeatherTileRenderNode` 已按 `z/x/y/hour` 渲染单瓦片 GeoJSON，但当前调用 `service._fetch_layer_grid_data`，分辨率不固定。 |
| `Code/backend/app/weatherengine/workflow_service.py` | 已注册 | 节点已加入 `_register_default_nodes`。 |
| `Code/backend/app/weatherengine/nodes/__init__.py` | 已导出 | `WeatherTileRenderNode` 已在 `__all__`。 |
| `Code/backend/app/weatherengine/tile_service.py` | 已稳定 | 提供 `tile_bbox`、`zoom_to_resolution`、LRU+Redis 缓存、`_grid_data_for_hour`。 |
| `Code/backend/app/services/weather_bridge_service.py` | 已改造 | `_extract_tile_geojson` + `WorkflowResultReference(json)` 已存在，可正确输出 tile GeoJSON。 |
| `Code/frontend/src/services/weather-tile-api.ts` | 已改造 | 提供 `submitWeatherTileWorkflow` 及 Web Mercator 坐标工具。 |
| `Code/frontend/src/stores/weather-tile-manager.ts` | 已改造 | 具备全局 3 槽位、图层内 priority 0/1、generation 丢弃、BFS 外扩、429 退避，但尚未被 MapCanvas 消费。 |
| `Code/frontend/src/services/weather-tile-utils.ts` | 已稳定 | 按量化经纬度 + `height` 合并多瓦片并去重。 |
| `Code/frontend/src/components/map/weather-render.ts` | 已稳定 | `WEATHER_RENDER_HINTS` + `buildDefaultWeatherRenderHint`。 |
| `Code/frontend/src/stores/layers/types.ts` | 已扩展 | `ActiveLayerDisplay.renderHint` 已存在。 |

### 2.2 当前异常根因

**根因 A：MapCanvas 仍未接入 tile manager（最关键）**
- `resolveAllWeatherOverlayStates` 仍读取 `layer.jobLayer?.mapLayerPayload?.layerAssets`；
- 天气图层的 workflow 结果有两条来源：
  1. `LayerSidebar.addCatalogItem` 调用 `runWorkflowForCatalog` 走旧虚拟瓦片路径；
  2. `weatherTileManager` 通过 workflow 提交标准 `z/x/y` 瓦片；
- `MapCanvas` 只消费来源 1，但来源 2 的请求仍在后台运行并更新 `weatherTileManager` 缓存，不被渲染；
- 当旧路径数据先到 → 显示正常；若 tile manager 路径的数据未渲染，缩放/移动时 `MapCanvas` 只拿到旧 jobLayer 数据，范围不匹配 → “缩放后只剩一点点线条”。

**根因 B：后端 tile 节点分辨率不统一（坐标转换/数据组装问题）**
- `WeatherTileRenderNode.execute` 调用 `service._fetch_layer_grid_data(bbox=bbox, spec=spec)`；
- `_fetch_layer_grid_data` 内部使用 `compute_dynamic_resolution(bbox)`，根据每个瓦片的 bbox 大小动态计算分辨率；
- 同一 `z` 下不同 `x/y` 的瓦片 bbox 大小相同，但跨 `z` 切换或前后端分辨率表不一致时，会出现相邻瓦片网格行列数不同；
- 前端 `mergeWeatherTiles` 按经纬度去重，但不同分辨率的瓦片在边界处采样点不完全对齐，导致边界重复点或空隙、风场粒子流网格范围忽大忽小。

**根因 C：新旧数据路径并存（首次正常、1 秒内忽然变化）**
- `LayerSidebar.addCatalogItem` 对天气图层仍调用 `runWorkflowForCatalog`；
- `runWorkflowForCatalog` 走旧的 `WEATHER_REQUEST_BUCKETS` 虚拟瓦片路径，生成一份非标准瓦片 GeoJSON；
- 同时 `weatherTileManager` 通过 workflow 提交标准 `z/x/y` 瓦片；
- `MapCanvas` 尚未接入 tile manager，仍从 `jobLayer.mapLayerPayload.layerAssets.geojsonData` 取数据；
- 旧数据先到 → 显示正常；新 tile 数据返回后若被错误渲染（例如通过 `syncJobLayerToActiveLayer` 覆盖）→ 显示忽然变化。

**根因 D：外扩与移动冲突**
- `weatherTileManager` 的 `expandNeighbors` 已限制在当前视口外扩 1 圈，但：
  - 单个瓦片成功后立即触发外扩，若此时用户正在移动，旧 generation 的预取会占用全局槽位；
  - 需要更严格的“外扩请求也必须属于当前 generation 的允许集合”检查。

## 3. 关键设计决策（Decisions）

1. **后端 tile 节点必须使用 `zoom_to_resolution(z)`**：同一 zoom 下所有瓦片采用固定分辨率，保证网格行列一致、边界对齐。
2. **后端 tile 节点直接复用 `OpenMeteoClient.fetch_grid_forecast`**：绕过 `WeatherEngineService._fetch_layer_grid_data` 的动态分辨率逻辑，避免两套分辨率并存。
3. **前端删除旧虚拟瓦片路径**：`stores/layers/index.ts` 中的 `weatherTileCache`、`weatherPrefetchQueue`、`runWorkflowForCatalog` 天气分支、`refreshActiveWeatherWorkflows` 天气分支等全部移除。
4. **天气图层添加后不再自动提交 analysis workflow**：由 `MapCanvas` 视口变化驱动 `weatherTileManager.setViewport` 按需拉取。
5. **保留 `particleFlowCatalogId` 独占机制**：同一时间仍只允许一个风场图层启用粒子流，但多个天气图层可独立请求 workflow。
6. **全局并发槽位保持 3**：为点天气/其他 workflow 留 1 个槽位；429 时 3 秒退避并重入队列头部。
7. **generation + cancelWorkflowRun 解决移动冲突**：视口变化时递增 generation，过期 workflow 立即取消；外扩请求也必须通过 generation 校验。
8. **视口瓦片未就绪时保留上一代渲染**：`syncWindParticleFlow` 在 `geojsonData` 为 null 或特征数不足时不销毁现有 Canvas，避免“忽然变少/消失”。
9. **tile key 必须包含 `layer_id:z:x:y:hour`**：时间、缩放、瓦片编号全部参与缓存键。
10. **结果拼接沿用量化去重**：`weather-tile-utils.ts` 的 `quantizeFactor=1000` 足以消除相邻瓦片边界浮点误差。

## 4. 实施步骤（Proposed Changes）

### 4.1 后端：修复 `WeatherTileRenderNode` 的分辨率一致性

**文件**：`Code/backend/app/weatherengine/nodes/tile_render.py`

**改造内容**：
- 不再直接调用 `service._fetch_layer_grid_data(bbox=bbox, spec=spec)`；
- 改为直接调用 `OpenMeteoClient.fetch_grid_forecast`，并传入 `tile_service.zoom_to_resolution(z)`；
- 复用 `tile_service._grid_data_for_hour` 进行时次切换；
- 复用 `service._build_geojson_from_grid` 生成 GeoJSON；
- 注入更完整的 `_tile_meta`，包括 `resolution`、`feature_count`、`bbox`。

**关键代码形态**：
```python
from app.weatherengine.tile_service import tile_bbox, zoom_to_resolution, _grid_data_for_hour
from app.weatherengine.client import OpenMeteoClient
from app.weatherengine.nodes._utils import get_weather_engine_service
from app.core.config import settings

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
        resolution = zoom_to_resolution(z)

        # 使用固定分辨率，避免相邻瓦片网格不一致
        client = OpenMeteoClient()
        grid_data, cache_status = client.fetch_grid_forecast(
            bbox=bbox,
            resolution=resolution,
            layer_spec=spec,
            model=model,
            ttl_seconds=settings.weather_cache_ttl_seconds,
            pressure_levels=spec.pressure_levels or None,
        )
        grid_data = _grid_data_for_hour(grid_data, hour)

        service = get_weather_engine_service()
        geojson = service._build_geojson_from_grid(grid_data=grid_data, layer_id=layer_id)

        geojson["_tile_meta"] = {
            "layer_id": layer_id,
            "z": z, "x": x, "y": y,
            "hour": hour,
            "model": model,
            "resolution": resolution,
            "bbox": bbox.model_dump(mode="json"),
            "feature_count": len(geojson.get("features", [])),
            "upstream_cache_status": cache_status,
        }

        artifact = self._store_geojson_artifact(geojson)
        return NodeExecutionResult(
            node_id=self.spec.node_id,
            status=RunStatus.completed,
            outputs={"geojson": geojson, "tile_meta": geojson["_tile_meta"]},
            artifacts=[artifact] if artifact else [],
        )
```

### 4.2 后端：确保 bridge 正确映射 tile GeoJSON

**文件**：`Code/backend/app/services/weather_bridge_service.py`

**当前状态**：`_extract_tile_geojson` 与 `WorkflowResultReference(json)` 已存在，基本可用。

**改造内容**：
- 在 `_extract_tile_geojson` 增加调试日志，输出提取到的 `tile_meta`；
- 确保 `inline_data.geojson` 是完整 FeatureCollection（含 `features` 数组）；
- 若节点输出无 `_tile_meta`，则不追加 tile result_ref，避免误把普通 weather workflow 结果当瓦片。

### 4.3 前端：完成 `MapCanvas.vue` 接入 tile manager

**文件**：`Code/frontend/src/components/MapCanvas.vue`

**改造内容**：

A. 引入依赖：
```ts
import { useWeatherTileManager } from '../stores/weather-tile-manager'
import { buildDefaultWeatherRenderHint } from './map/weather-render'
const weatherTileManager = useWeatherTileManager()
```

B. 修改 `resolveAllWeatherOverlayStates`：
- 对每个可见图层，判断是否为天气图层（`isRealtimeWeatherLayerId(layer.catalogId)`）；
- 天气图层：
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

C. 修改 `syncWindParticleFlow`：
- 当 `geojsonData` 为内联数据时，比较 feature 数量 + 采样坐标，避免同一份数据反复触发 `updateGeoJSON`；
- 当新数据为 null 或 feature 数量过少（如不足当前网格的 50%）时，不销毁现有 Canvas，保持上一帧；
- 保留 `enableBarbLayer = paint_mode === 'barb'`。

D. 扩展 watcher：
在现有 watcher 依赖数组末尾追加 `weatherTileManager.dataVersion`。

### 4.4 前端：清理 `stores/layers/index.ts` 旧虚拟瓦片逻辑

**文件**：`Code/frontend/src/stores/layers/index.ts`

**删除内容**：
- `WEATHER_REQUEST_*`、`WEATHER_PREFETCH_*`、`WEATHER_TILE_CACHE_MAX_PER_BUCKET`、`WEATHER_REQUEST_BUCKETS` 常量；
- `WeatherTileSpec`、`WeatherTileCacheEntry` 类型；
- `weatherTileCache`、`weatherCatalogPrimaryTileKey`、`weatherRunTileSpecs`、`weatherPrefetchQueue`、`weatherPrefetchActiveKeys`、`weatherPrefetchBackoffUntil` 状态；
- `buildWeatherTileSpec`、`buildNeighborWeatherTileSpecs`、`resolvePrimaryWeatherTileSpec`、`buildDefaultViewportBBox`、`getWeatherTileCacheKey`、`getWeatherTileCacheEntry`、`setWeatherTileCacheEntry`、`evictDistantWeatherTiles`、`extractGeojsonDataFromJobLayer`、`buildMergedGeojsonForCatalog`、`patchCatalogJobLayerGeojson`、`applyMergedWeatherTileData`、`cacheWeatherTileJobLayer`、`pollHiddenWeatherTileRun`、`drainWeatherPrefetchQueue`、`trimWeatherPrefetchQueueForCatalog`、`enqueueWeatherTilePrefetch`、`expandWeatherTilePrefetch`、`interruptWorkflowForCatalog` 等函数；
- `runWorkflowForCatalog` 中的天气分支：天气图层不再提交 analysis workflow；
- `refreshActiveWeatherWorkflows` 和 `handleViewportChange` 中仅用于天气刷新的分支；
- `syncWorkflowRunSnapshot` 中 `weatherRunTileSpecs` 相关逻辑。

**保留内容**：
- 非天气图层的 `runWorkflowForCatalog` 逻辑；
- `isWeatherEngineLayer`、`supportsMapLayerResult`、`supportsViewportDrivenRefresh` 等判断函数；
- `particleFlowCatalogId` 及 `toggleParticleFlow`/`setParticleFlow`；
- 点天气查询逻辑。

**接入 tile manager**：
- 引入 `useWeatherTileManager`；
- `addLayer`：天气图层调用 `weatherTileManager.setLayerActive(catalogId, true)`；
- `removeLayer`：天气图层调用 `weatherTileManager.clearLayer(catalogId)`；
- `toggleLayerVisibility`：天气图层调用 `weatherTileManager.setLayerActive(catalogId, layer.visible)`；
- `setMapViewport`：更新视口后，对每个可见天气图层调用：
  ```ts
  weatherTileManager.setViewport(
    layer.catalogId,
    center,
    currentMapZoom.value,
    currentHour.value,
    undefined,
    bbox,
  )
  ```
- `setCurrentHour`：小时变化时，对所有可见天气图层重新触发 `setViewport`。

**扩展 `activeLayersDisplay`**：
```ts
renderHint: layer.isAdminBoundary
  ? undefined
  : (buildDefaultWeatherRenderHint(layer.catalogId) ?? layer.jobLayer?.mapLayerPayload?.renderHint),
```

### 4.5 前端：改造 `LayerSidebar.vue`

**文件**：`Code/frontend/src/components/LayerSidebar.vue`

**改造内容**：
- `addCatalogItem` 中移除天气图层的 `runWorkflowForCatalog` 调用：
  ```ts
  function addCatalogItem(catalogId: string, isAdminBoundary = false) {
    layersStore.addLayer(catalogId, isAdminBoundary)
    // 天气图层由 tile manager 按需拉取，不再自动提交 analysis workflow
  }
  ```
- library 卡片状态徽标：天气图层不再显示 running/queued/succeeded 等 job 徽标；可改为显示 tile manager 的 `pending/cached/visible` 统计（可选，后续迭代）。

### 4.6 前端：改造 `InfoPanel.vue`

**文件**：`Code/frontend/src/components/InfoPanel.vue`

**改造内容**：
- 引入 `useWeatherTileManager`；
- `weatherRenderHint` 优先使用 `displayLayer.value?.renderHint`：
  ```ts
  const weatherRenderHint = computed(
    () => displayLayer.value?.renderHint
      ?? jobLayer.value?.mapLayerPayload?.renderHint
      ?? props.pointWeather?.render_hint
      ?? null,
  )
  ```
- `hasWeatherLayerAsset` 改为基于 tile manager 统计：
  ```ts
  const weatherTileManager = useWeatherTileManager()
  const hasWeatherLayerAsset = computed(() => {
    if (!isRealtimeWeatherLayerId(displayLayer.value.catalogId)) return false
    const stats = weatherTileManager.getStats(displayLayer.value.catalogId)
    return stats.cached > 0 || stats.pending > 0
  })
  ```
- `particleFlowButtonDisabled` 基于新的 `hasWeatherLayerAsset`。

### 4.7 前端：强化 `weather-tile-manager.ts` 的移动/缩放冲突处理

**文件**：`Code/frontend/src/stores/weather-tile-manager.ts`

**改造内容**：
- `expandNeighbors` 增加对当前 generation 的二次校验：
  ```ts
  if (state.generation !== generation) return
  ```
- 外扩邻居入队前，检查该邻居是否仍属于当前 `viewportTiles` 或 `prefetchRing`；
- `setViewport` 中清理 pending 后，立即对仍在目标集合内的请求保留，不重复入队；
- 429 退避时，被退回的请求重新入队，并在日志中打印 `backoffUntil`；
- 增加 `getTileDebugInfo(layerId)` 方法，返回当前 `generation`、`pending` 数量、`cached` 数量、`viewportTiles` 列表，便于 MapCanvas/浏览器调试。

### 4.8 增加端到端调试信息

**前端**：
- `weather-tile-manager.ts` 在 `setViewport`、`submitTile`、`pollTile`、`expandNeighbors` 中保持现有 `debugLog`；
- `MapCanvas.vue` 在 `resolveAllWeatherOverlayStates` 中打印每个天气图层的 `geojsonData` 来源、feature 数量、renderHint；
- `syncWindParticleFlow` 中打印 `enableBarb`、`urlChanged`、`featureCount`。

**后端**：
- `WeatherTileRenderNode` 在生成 GeoJSON 后打印 `layer_id`、`z/x/y`、`hour`、`resolution`、`feature_count`、`bbox`；
- `weather_bridge_service.py` 在映射到 `WorkflowResultReference` 时打印 `run_id`、`tile_meta`。

## 5. 假设与依赖（Assumptions & Dependencies）

- 后端 `OpenMeteoClient.fetch_grid_forecast` 在固定分辨率下对同一 bbox 多次调用结果稳定。
- 后端 `max_active_runs=4` 是硬性上限，前端 3 槽位 + 429 退避可避免持续撞击。
- 粒子流独占逻辑保持不变：同一时间只启用一个风场图层的粒子流。
- 非天气图层（如 `lab-output`）的 workflow 逻辑不受本次改造影响。
- 点天气查询 `/weather/point` 保持现有路径不变。
- 浏览器端支持 `AbortController` 和 `crypto.randomUUID`。

## 6. 验证步骤（Verification）

### 6.1 后端单元测试

```powershell
cd Code/backend
pytest tests/test_weather_tile_service.py -v
```

新增/更新测试：
- `WeatherTileRenderNode` 对 `wind-field`/`temperature`/`precipitation` 返回正确 `_tile_meta`；
- 同一 `z` 下不同 `x/y` 瓦片的 `_tile_meta.resolution` 相同；
- 节点注册表包含 `weather_tile_render`；
- bridge 提交含 `weather_tile_render` 的 workflow 后，`result_refs` 中包含 `result_kind=json` 且 `inline_data.geojson` 存在的条目。

### 6.2 后端冒烟测试

```powershell
curl -X POST "http://localhost:8000/workflow-runs" `
  -H "Content-Type: application/json" `
  -d '{"command_type":"analysis","layer_id":"wind-field","requested_outputs":["json"],"weather_request":{"workflow":{"workflow_id":"test-tile","nodes":[{"node_id":"tile","node_type":"weather_tile_render","params":{"layer_id":"wind-field","z":3,"x":2,"y":1,"hour":12}}],"edges":[]}}}'
```

验证返回的 `result_refs[0].inline_data.geojson._tile_meta` 包含 `resolution` 且与 `zoom_to_resolution(3)` 一致。

### 6.3 前端类型检查

```powershell
cd Code/frontend
npx vue-tsc --noEmit
```

### 6.4 浏览器运行时验证

- 添加 `wind-field` 图层后，Network 面板只出现 `/workflow-runs` POST 请求，无 `/weather/tiles` 请求；
- Console 中 `[WeatherTileManager:setViewport]` 显示正确的 `z` 和 `viewport/prefetch` 瓦片数量；
- 同一视口内并发 workflow 请求数 ≤ 3；
- 缩放后新 `z` 级别的 tile workflow 被提交，旧 generation 的 workflow 被取消（日志中可见 `pollTile generation expired` 或 `submitTile discard stale`）；
- 风场粒子流持续 10 秒无变短线/消失；
- 平移地图时新视口瓦片加载，旧数据平滑过渡（不闪白、不突然清空）；
- 同时添加风场 + 温度 + 降水，各图层独立请求 workflow，结果正确叠加；
- 切换 hour 后，所有瓦片按新 hour 重新提交；
- 快速缩放/平移时，429 退避生效，无大量失败 workflow。

## 7. 风险与缓解（Risks & Mitigations）

| 风险 | 影响 | 缓解 |
|------|------|------|
| 固定分辨率导致小 zoom 瓦片数据量过大 | 首次加载慢 | 限制 `z <= 12`，低 zoom 使用较大分辨率（如 `zoom_to_resolution` 的 5°/2°）。 |
| 删除旧虚拟瓦片路径后非天气图层异常 | 回归 | `resolveAllWeatherOverlayStates` 中保留非天气图层分支；`runWorkflowForCatalog` 仅对非天气图层生效。 |
| 快速缩放产生大量 workflow 积压 | 后端压力过大 | generation + cancelWorkflowRun + 3 槽位 + 429 退避。 |
| 相邻瓦片边界仍有轻微重复 | 边界短线 | 前端量化去重 factor=1000；后端固定分辨率保证采样对齐。 |
| `MapCanvas` 在数据未就绪时启用粒子流 | 按钮可点击但无数据 | `InfoPanel.hasWeatherLayerAsset` 改用 tile manager stats 判断。 |
| 并发 workflow 管理复杂 | 调试困难 | 前后端增加完整日志，tile meta 包含 bbox/resolution/generation。 |
