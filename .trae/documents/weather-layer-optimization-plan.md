# 天气图层性能优化计划

## 问题总结

### 问题 1：移动位置后边缘连接不上 + 风场密度突然下降

**现象：**
- 移动地图后，风场粒子流在瓦片边缘出现错位、不连续
- 风场密度突然下降，很多区域粒子变得稀少
- 疑似二次加载数据不完整导致部分区域数据被冲掉

**根因分析：**

1. **瓦片合并逻辑缺陷** (`buildMergedGeojsonForCatalog`)
   - 去重 key 使用 `${coordinates[0]}:${coordinates[1]}:${properties?.height}:${properties?.value}`
   - 问题：如果两个瓦片在边缘有相同坐标但不同 value（由于插值或时间变化），会被错误地合并
   - 更严重：新瓦片数据到达时，`applyMergedWeatherTileData` 会用新的 merged geojson **完全替换**旧的 geojson
   - 如果新瓦片数据不完整（比如只有部分区域），会导致整个区域的粒子密度下降

2. **工作流重复提交** (`refreshActiveWeatherWorkflows`)
   - 视口变化时触发工作流重新提交
   - `isSignificantViewportChange` 会绕过最小间隔限制
   - 每次视口显著变化都会：
     - 取消旧工作流（`interruptWorkflowForCatalog`）
     - 提交新工作流
     - 新工作流完成后用新数据替换旧数据
     - 如果新瓦片数据不完整，导致显示问题

3. **瓦片缓存淘汰时机不当** (`evictDistantWeatherTiles`)
   - 新瓦片数据还没到达时，旧瓦片可能已经被淘汰
   - 导致数据缺失，粒子密度下降

### 问题 2：响应速度慢

**现象：**
- 工作流执行耗时长
- 多图层并发时响应更慢

**根因分析：**

1. **后端性能瓶颈**
   - Open-Meteo API 调用是主要耗时点（每次工作流都会调用）
   - 没有跨工作流缓存相同的点位天气数据
   - 虽然有 `cache_ttl_seconds` 参数，但默认可能没有启用

2. **前端轮询策略**
   - `EVENT_POLL_ACTIVE_INTERVAL_MS = 1200ms` 轮询间隔较长
   - 工作流完成后需要等待下一次轮询才能获取结果

3. **瓦片预取策略**
   - `WEATHER_PREFETCH_CONCURRENCY = 2` 并发度较低
   - 429 错误时设置 3 秒退避，进一步降低速度

---

## 优化方案

### 阶段 1：性能测试与基准建立

#### 1.1 后端 Open-Meteo API 性能测试

**目标：** 测量 Open-Meteo API 的响应时间和传输速度

**测试内容：**
- 单点位天气查询延迟（p50, p95, p99）
- 不同 bbox 大小的数据传输量
- 并发请求下的性能表现
- 缓存命中率对性能的影响

**测试脚本：** `Code/backend/tests/test_open_meteo_performance.py`

**预期输出：**
- API 响应时间基准
- 数据传输速度基准
- 并发性能基准

#### 1.2 前端工作流性能测试

**目标：** 测量单工作流和并发工作流的端到端耗时

**测试内容：**
- 单工作流从提交到完成的总耗时
- 多图层并发工作流的性能
- 瓦片预取的效率
- 429 错误重试的频率和耗时

**测试方法：**
- 在浏览器控制台添加性能监控
- 记录关键时间戳：
  - 工作流提交时间
  - 工作流完成时间
  - 瓦片数据到达时间
  - UI 更新时间

**预期输出：**
- 工作流耗时基准
- 并发性能基准
- 性能瓶颈点识别

---

### 阶段 2：瓦片合并逻辑优化

#### 2.1 改进瓦片去重逻辑

**文件：** `Code/frontend/src/stores/layers/index.ts`

**当前问题：**
```typescript
const dedupeKey = `${coordinates[0]}:${coordinates[1]}:${properties?.height}:${properties?.value}`
```

**修复方案：**
- 使用更精确的去重 key：`${coordinates[0]}:${coordinates[1]}:${properties?.height}`
- 移除 `properties?.value`，因为相同坐标和高度应该被视为同一点
- 如果 value 不同，保留最新的值（而不是第一个）

**代码修改：**
```typescript
const dedupeKey = `${coordinates[0]}:${coordinates[1]}:${properties?.height ?? ''}`
// 如果已经存在，保留最新的值
if (seen.has(dedupeKey)) {
  // 更新已存在的 feature 的 value
  const existingIndex = featureIndexMap.get(dedupeKey)
  if (existingIndex !== undefined) {
    features[existingIndex] = feature
  }
  continue
}
seen.add(dedupeKey)
featureIndexMap.set(dedupeKey, features.length)
features.push(feature)
```

#### 2.2 优化瓦片数据替换策略

**当前问题：**
- `applyMergedWeatherTileData` 用新的 merged geojson 完全替换旧的 geojson
- 如果新瓦片数据不完整，会导致整个区域的粒子密度下降

**修复方案：**
- 增量更新：只更新变化的区域，而不是完全替换
- 数据完整性检查：在替换前检查新数据的覆盖范围
- 回退机制：如果新数据不完整，保留旧数据

**代码修改：**
```typescript
function applyMergedWeatherTileData(catalogId: string, zoomBucketKey: string) {
  const mergedGeojson = buildMergedGeojsonForCatalog(catalogId, zoomBucketKey)
  if (!mergedGeojson) return false
  
  const existingLayer = activeLayers.value.find((layer) => layer.catalogId === catalogId)
  const existingGeojson = existingLayer?.jobLayer?.mapLayerPayload?.layerAssets?.geojsonData
  
  // 数据完整性检查：新数据应该至少覆盖旧数据的 80%
  if (existingGeojson && !isGeojsonCoverageAdequate(mergedGeojson, existingGeojson)) {
    console.warn('[LayersStore] New geojson coverage is inadequate, keeping old data')
    return false
  }
  
  patchCatalogJobLayerGeojson(catalogId, mergedGeojson)
  return true
}

function isGeojsonCoverageAdequate(newGeojson: any, oldGeojson: any): boolean {
  const newFeatures = newGeojson.features?.length ?? 0
  const oldFeatures = oldGeojson.features?.length ?? 0
  // 新数据应该至少覆盖旧数据的 80%
  return newFeatures >= oldFeatures * 0.8
}
```

#### 2.3 优化瓦片缓存淘汰策略

**当前问题：**
- 新瓦片数据还没到达时，旧瓦片可能已经被淘汰
- 导致数据缺失

**修复方案：**
- 延迟淘汰：只在新瓦片数据成功到达后才淘汰旧瓦片
- 保留关键瓦片：始终保留当前视口中心的瓦片

**代码修改：**
```typescript
function evictDistantWeatherTiles(
  catalogId: string, 
  currentCenter: { lng: number; lat: number }, 
  currentZoomBucketKey: string
) {
  // 1. 淘汰其他 zoom bucket 的瓦片（只保留当前 bucket）
  for (const [key, entry] of weatherTileCache.entries()) {
    if (entry.catalogId === catalogId && entry.spec.zoomBucketKey !== currentZoomBucketKey) {
      // 只淘汰成功的瓦片，保留进行中的
      if (entry.status === 'succeeded') {
        weatherTileCache.delete(key)
      }
    }
  }
  
  // 2. 当前 bucket 超过上限时，按距离淘汰最远的瓦片
  const sameBucketEntries: Array<{ key: string; dist: number }> = []
  for (const [key, entry] of weatherTileCache.entries()) {
    if (entry.catalogId !== catalogId || entry.spec.zoomBucketKey !== currentZoomBucketKey) continue
    if (entry.status !== 'succeeded') continue  // 只淘汰已完成的，不淘汰进行中的
    const dLng = entry.spec.center.lng - currentCenter.lng
    const dLat = entry.spec.center.lat - currentCenter.lat
    sameBucketEntries.push({ key, dist: dLng * dLng + dLat * dLat })
  }
  
  if (sameBucketEntries.length <= WEATHER_TILE_CACHE_MAX_PER_BUCKET) return
  
  // 保留距离最近的 50% 瓦片，淘汰最远的 50%
  sameBucketEntries.sort((a, b) => a.dist - b.dist)
  const keepCount = Math.max(1, Math.floor(sameBucketEntries.length * 0.5))
  const toEvict = sameBucketEntries.slice(keepCount)
  
  for (const item of toEvict) {
    weatherTileCache.delete(item.key)
  }
}
```

---

### 阶段 3：工作流提交策略优化

#### 3.1 减少不必要的工作流重复提交

**文件：** `Code/frontend/src/stores/layers/index.ts`

**当前问题：**
- `refreshActiveWeatherWorkflows` 在视口变化时频繁触发
- `isSignificantViewportChange` 会绕过最小间隔限制
- 导致工作流被频繁取消和重新提交

**修复方案：**
- 增加最小提交间隔：从 2 秒增加到 5 秒
- 改进显著变化判断：只有当视口中心移动超过 50% 或缩放级别变化时才认为是显著变化
- 添加提交冷却期：工作流完成后 10 秒内不再重新提交

**代码修改：**
```typescript
const WORKFLOW_REFRESH_MIN_INTERVAL_MS = 5000  // 从 2000 增加到 5000
const WORKFLOW_COOLDOWN_MS = 10000  // 工作流完成后 10 秒冷却期
const SIGNIFICANT_VIEWPORT_MOVE_THRESHOLD = 0.5  // 视口中心移动 50% 才算显著变化

function isSignificantViewportChange(catalogId: string, newBBox: BoundingBox): boolean {
  const lastBBox = lastWorkflowBBox.get(catalogId)
  if (!lastBBox) return true
  
  // 检查缩放级别变化
  const lastZoomBucketKey = resolvePrimaryWeatherTileSpec(
    catalogId,
    { lng: (lastBBox.west + lastBBox.east) / 2, lat: (lastBBox.south + lastBBox.north) / 2 },
    lastBBox,
    currentMapZoom.value
  )?.zoomBucketKey
  
  const newZoomBucketKey = resolvePrimaryWeatherTileSpec(
    catalogId,
    currentMapCenter.value,
    newBBox,
    currentMapZoom.value
  )?.zoomBucketKey
  
  if (lastZoomBucketKey !== newZoomBucketKey) return true
  
  // 检查视口中心移动距离
  const lastCenterLng = (lastBBox.west + lastBBox.east) / 2
  const lastCenterLat = (lastBBox.south + lastBBox.north) / 2
  const newCenterLng = currentMapCenter.value.lng
  const newCenterLat = currentMapCenter.value.lat
  
  const lastBBoxWidth = lastBBox.east - lastBBox.west
  const lastBBoxHeight = lastBBox.north - lastBBox.south
  
  const moveLngRatio = Math.abs(newCenterLng - lastCenterLng) / lastBBoxWidth
  const moveLatRatio = Math.abs(newCenterLat - lastCenterLat) / lastBBoxHeight
  
  return moveLngRatio > SIGNIFICANT_VIEWPORT_MOVE_THRESHOLD 
    || moveLatRatio > SIGNIFICANT_VIEWPORT_MOVE_THRESHOLD
}

// 在 refreshActiveWeatherWorkflows 中添加冷却期检查
const lastCompleteTime = workflowLastCompleteTime.get(layer.catalogId) ?? 0
if (now - lastCompleteTime < WORKFLOW_COOLDOWN_MS) continue
```

#### 3.2 优化工作流轮询策略

**文件：** `Code/frontend/src/stores/layers/index.ts`

**当前问题：**
- `EVENT_POLL_ACTIVE_INTERVAL_MS = 1200ms` 轮询间隔较长
- 工作流完成后需要等待下一次轮询才能获取结果

**修复方案：**
- 自适应轮询间隔：工作流刚开始时 500ms，运行中 1200ms，接近完成时 300ms
- 工作流完成后立即获取结果，不等待下一次轮询

**代码修改：**
```typescript
async function pollWorkflowRun(jobId: string, catalogId: string, startTime = Date.now(), consecutiveErrors = 0) {
  if (Date.now() - startTime > EVENT_POLL_MAX_DURATION_MS) {
    stopWorkflowPolling(jobId)
    activeWorkflowCatalogIds.delete(catalogId)
    workflowError.value = `工作流 ${jobId} 事件等待超时（${EVENT_POLL_MAX_DURATION_MS / 1000}s）`
    return
  }

  try {
    const run = await getWorkflowRun(jobId)
    const jobLayer = await buildJobLayer(run, catalogId, { previousJobLayer: jobLayers.value.find((item) => item.jobId === jobId) })
    
    upsertJobLayer(catalogId, jobLayer)
    
    if (isTerminalStatus(jobLayer.status)) {
      stopWorkflowPolling(jobId)
      activeWorkflowCatalogIds.delete(catalogId)
      workflowLastCompleteTime.set(catalogId, Date.now())  // 记录完成时间
      
      // 工作流完成后立即触发数据更新，不等待下一次轮询
      const tileRunSpec = weatherRunTileSpecs.get(jobId)
      if (tileRunSpec && jobLayer.status === 'succeeded') {
        weatherCatalogPrimaryTileKey.set(catalogId, tileRunSpec.spec.tileKey)
        applyMergedWeatherTileData(catalogId, tileRunSpec.spec.zoomBucketKey)
        evictDistantWeatherTiles(catalogId, currentMapCenter.value, tileRunSpec.spec.zoomBucketKey)
        expandWeatherTilePrefetch(catalogId, tileRunSpec.spec)
      }
      return
    }
    
    // 自适应轮询间隔
    const elapsed = Date.now() - startTime
    let pollInterval = EVENT_POLL_ACTIVE_INTERVAL_MS
    if (elapsed < 3000) {
      pollInterval = 500  // 前 3 秒快速轮询
    } else if (jobLayer.progress > 80) {
      pollInterval = 300  // 接近完成时快速轮询
    }
    
    workflowPollTimers.set(jobId, window.setTimeout(() => {
      void pollWorkflowRun(jobId, catalogId, startTime, 0)
    }, pollInterval))
  } catch (error) {
    // ... 错误处理
  }
}
```

---

### 阶段 4：后端性能优化

#### 4.1 添加 Open-Meteo API 响应缓存

**文件：** `Code/backend/app/weatherengine/service.py`

**当前问题：**
- 每次工作流都会调用 `get_point_weather`，没有跨工作流缓存
- 相同的点位天气数据被重复获取

**修复方案：**
- 使用 Redis 缓存 Open-Meteo API 响应
- 缓存 key：`weather:{layer_id}:{lat}:{lon}:{hour}`
- 缓存 TTL：1 小时（与 Open-Meteo 数据更新频率一致）

**代码修改：**
```python
from app.core.redis_client import get_redis_client
import json

class WeatherEngineService:
    def __init__(self):
        self.redis_client = get_redis_client()
        self.cache_ttl = 3600  # 1 小时
    
    def get_point_weather(
        self,
        *,
        layer_id: str,
        latitude: float,
        longitude: float,
        model: str | None = None,
        forecast_hours: list[int] | None = None,
        place_name: str | None = None,
        cache_ttl_seconds: int | None = None,
    ) -> PointWeather:
        # 生成缓存 key
        cache_key = f"weather:{layer_id}:{latitude:.4f}:{longitude:.4f}:{forecast_hours}"
        
        # 尝试从缓存获取
        ttl = cache_ttl_seconds or self.cache_ttl
        cached = self.redis_client.get(cache_key)
        if cached:
            try:
                return PointWeather.model_validate_json(cached)
            except Exception:
                pass
        
        # 缓存未命中，调用 API
        weather = self._fetch_point_weather_from_api(
            layer_id=layer_id,
            latitude=latitude,
            longitude=longitude,
            model=model,
            forecast_hours=forecast_hours,
            place_name=place_name,
        )
        
        # 写入缓存
        try:
            self.redis_client.setex(cache_key, ttl, weather.model_dump_json())
        except Exception as e:
            logger.warning(f"Failed to cache weather data: {e}")
        
        return weather
```

#### 4.2 提高瓦片预取并发度

**文件：** `Code/frontend/src/stores/layers/index.ts`

**当前配置：**
```typescript
const WEATHER_PREFETCH_CONCURRENCY = 2
const WEATHER_PREFETCH_MAX_QUEUE = 30
```

**优化配置：**
```typescript
const WEATHER_PREFETCH_CONCURRENCY = 4  // 从 2 增加到 4
const WEATHER_PREFETCH_MAX_QUEUE = 50   // 从 30 增加到 50
```

**理由：**
- 现代浏览器支持 6 个并发 HTTP 请求
- 后端 Celery worker 有 32 个并发
- 提高并发度可以加快瓦片预取速度

---

### 阶段 5：验证与测试

#### 5.1 功能验证

**测试场景：**
1. 单图层打开和关闭
2. 多图层并发打开
3. 地图平移和缩放
4. 视口显著变化（跨越多个瓦片）
5. 429 错误重试

**验证指标：**
- 风场粒子流边缘连续，无错位
- 风场密度稳定，不会突然下降
- 工作流响应时间 < 5 秒
- 多图层并发时响应时间 < 10 秒

#### 5.2 性能基准测试

**测试脚本：** `Code/backend/tests/test_weather_performance.py`

**测试内容：**
1. Open-Meteo API 响应时间
2. 工作流端到端耗时
3. 瓦片预取效率
4. 缓存命中率

**预期结果：**
- Open-Meteo API 响应时间 p95 < 2 秒
- 工作流端到端耗时 p95 < 5 秒
- 瓦片预取效率 > 80%
- 缓存命中率 > 60%

---

## 实施顺序

1. **阶段 1：性能测试与基准建立**（1-2 天）
   - 编写性能测试脚本
   - 运行测试并记录基准数据
   - 识别性能瓶颈

2. **阶段 2：瓦片合并逻辑优化**（2-3 天）
   - 改进瓦片去重逻辑
   - 优化瓦片数据替换策略
   - 优化瓦片缓存淘汰策略

3. **阶段 3：工作流提交策略优化**（1-2 天）
   - 减少不必要的工作流重复提交
   - 优化工作流轮询策略

4. **阶段 4：后端性能优化**（2-3 天）
   - 添加 Open-Meteo API 响应缓存
   - 提高瓦片预取并发度

5. **阶段 5：验证与测试**（1-2 天）
   - 功能验证
   - 性能基准测试
   - 对比优化前后的性能数据

**总预计时间：** 7-12 天

---

## 风险与注意事项

1. **向后兼容性**
   - 确保修改不影响现有的工作流逻辑
   - 保留原有的缓存机制，只是优化策略

2. **数据一致性**
   - 瓦片合并逻辑修改后，确保数据完整性
   - 添加数据完整性检查，防止不完整数据替换完整数据

3. **性能回退**
   - 每个阶段完成后进行性能测试
   - 如果发现性能回退，立即回滚

4. **代码审查**
   - 每个阶段的代码修改都需要审查
   - 特别注意之前修复的 bug（如纬度插值翻转、mapLayerPayload 丢失等）

---

## 相关文件清单

### 前端
- `Code/frontend/src/stores/layers/index.ts` - 瓦片缓存、工作流提交、轮询逻辑
- `Code/frontend/src/components/MapCanvas.vue` - 粒子流渲染
- `Code/frontend/src/components/map/wind-particle-canvas.ts` - 粒子流动画
- `Code/frontend/src/stores/layers/result-adapter.ts` - 工作流结果适配

### 后端
- `Code/backend/app/weatherengine/service.py` - 天气工作流核心服务
- `Code/backend/app/services/weather_bridge_service.py` - 天气桥接服务
- `Code/backend/app/core/celery_app.py` - Celery 配置
- `Code/backend/app/core/redis_client.py` - Redis 客户端（需要确认是否存在）

### 测试
- `Code/backend/tests/test_weather_performance.py`（新建）
- `Code/backend/tests/test_open_meteo_performance.py`（新建）
