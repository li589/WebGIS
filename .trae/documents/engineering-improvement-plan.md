# 天气图层系统工程级改进计划

## 问题诊断

### 1. 性能瓶颈

**日志分析发现的问题：**
- Open-Meteo API 频繁超时（多次重试失败，每次等待 30 秒）
- 请求 bbox 过大（120°x80° 范围导致 384 个网格点，URL 长度 3226 字符）
- 缓存未生效（相同请求重复调用外部 API）
- URL 长度可能导致 414 URI Too Long 错误

**根因分析：**
1. **URL 过长问题**：当 bbox 很大时，网格点数过多，URL 长度超过服务器限制
2. **缓存策略不足**：文件缓存在并发场景下效率低，且缓存 key 可能不够精确
3. **视口变化频繁触发**：每次视口变化都会触发工作流刷新，导致大量请求
4. **错误处理不完善**：API 失败时没有降级到缓存数据

### 2. 架构问题

**当前架构：**
```
前端 → FastAPI → WeatherBridgeService → WeatherEngineService → OpenMeteoClient → Open-Meteo API
```

**问题：**
- 单点依赖 Open-Meteo API，无备用数据源
- 缓存层薄弱（仅文件缓存）
- 无请求去重机制
- 无断路器模式

---

## 改进方案

### 阶段 1：性能优化（高优先级）

#### 1.1 限制 bbox 大小，避免 URL 过长

**问题：** 当前 bbox 可达 120°x80°，导致 384 个网格点，URL 长度 3226 字符

**解决方案：**
- 在前端限制最大 bbox 范围为 60°x40°
- 在后端添加 bbox 范围校验
- 动态调整分辨率：bbox 越大，分辨率越低

**修改文件：**
- `Code/frontend/src/stores/layers/index.ts` - 限制 bbox 大小
- `Code/backend/app/weatherengine/service.py` - 添加 bbox 校验
- `Code/backend/app/weatherengine/client.py` - 动态调整分辨率

**代码示例：**
```typescript
// 前端：限制 bbox 大小
const MAX_BBOX_SPAN = { lon: 60, lat: 40 }

function clampBBox(bbox: BoundingBox): BoundingBox {
  const lonSpan = bbox.east - bbox.west
  const latSpan = bbox.north - bbox.south
  
  if (lonSpan > MAX_BBOX_SPAN.lon || latSpan > MAX_BBOX_SPAN.lat) {
    const centerLng = (bbox.west + bbox.east) / 2
    const centerLat = (bbox.south + bbox.north) / 2
    return {
      west: centerLng - MAX_BBOX_SPAN.lon / 2,
      south: centerLat - MAX_BBOX_SPAN.lat / 2,
      east: centerLng + MAX_BBOX_SPAN.lon / 2,
      north: centerLat + MAX_BBOX_SPAN.lat / 2,
      crs: bbox.crs,
    }
  }
  return bbox
}
```

```python
# 后端：动态调整分辨率
def compute_dynamic_resolution(bbox: BoundingBox, target_points: int = 200) -> float:
    """根据 bbox 大小动态调整分辨率，控制网格点数量"""
    lon_span = bbox.east - bbox.west
    lat_span = bbox.north - bbox.south
    area = lon_span * lat_span
    # 分辨率 = sqrt(area / target_points)
    resolution = math.sqrt(area / target_points)
    # 限制在合理范围内
    return max(0.1, min(resolution, 2.0))
```

#### 1.2 改进缓存策略，使用 Redis 缓存

**问题：** 文件缓存在并发场景下效率低

**解决方案：**
- 使用 Redis 替代文件缓存
- 添加缓存预热机制
- 实现缓存分层（短期缓存 + 长期缓存）

**修改文件：**
- `Code/backend/app/core/redis_client.py` - 添加 Redis 缓存客户端
- `Code/backend/app/weatherengine/client.py` - 使用 Redis 缓存
- `Code/backend/app/core/config.py` - 添加缓存配置

**代码示例：**
```python
# Redis 缓存客户端
class WeatherCacheService:
    def __init__(self, redis_client):
        self.redis = redis_client
        self.short_ttl = 3600  # 1 小时
        self.long_ttl = 86400  # 24 小时
    
    async def get_or_fetch(self, key: str, fetch_func, ttl: int = None):
        """获取缓存或执行查询"""
        cached = await self.redis.get(key)
        if cached:
            return json.loads(cached), "hit"
        
        result = await fetch_func()
        ttl = ttl or self.short_ttl
        await self.redis.setex(key, ttl, json.dumps(result))
        return result, "miss"
    
    async def warm_cache(self, layer_ids: list[str], bbox: BoundingBox):
        """缓存预热：提前获取常用数据"""
        # 预取常用图层的数据
        pass
```

#### 1.3 添加请求去重机制

**问题：** 并发请求相同数据时，会重复调用 API

**解决方案：**
- 使用请求去重锁，相同请求只执行一次
- 其他请求等待第一个请求完成

**修改文件：**
- `Code/backend/app/weatherengine/client.py` - 添加请求去重

**代码示例：**
```python
from asyncio import Lock
from typing import Dict, Tuple

class RequestDeduplicator:
    def __init__(self):
        self._locks: Dict[str, Lock] = {}
        self._results: Dict[str, Any] = {}
    
    async def deduplicate(self, key: str, fetch_func):
        if key not in self._locks:
            self._locks[key] = Lock()
        
        async with self._locks[key]:
            if key in self._results:
                return self._results[key]
            
            result = await fetch_func()
            self._results[key] = result
            return result
```

### 阶段 2：可靠性提升（高优先级）

#### 2.1 改进错误处理和重试逻辑

**问题：** API 失败时没有降级到缓存数据

**解决方案：**
- 实现断路器模式
- API 失败时自动降级到缓存数据
- 添加指数退避重试

**修改文件：**
- `Code/backend/app/weatherengine/client.py` - 添加断路器模式

**代码示例：**
```python
from enum import Enum

class CircuitState(Enum):
    CLOSED = "closed"      # 正常状态
    OPEN = "open"          # 断路器打开，拒绝请求
    HALF_OPEN = "half_open" # 半开状态，尝试恢复

class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = CircuitState.CLOSED
    
    def can_execute(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        elif self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        else:  # HALF_OPEN
            return True
    
    def record_success(self):
        self.failure_count = 0
        self.state = CircuitState.CLOSED
    
    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
```

#### 2.2 添加多数据源支持

**问题：** 单点依赖 Open-Meteo API

**解决方案：**
- 利用已有的 `api_config_manager` 实现多数据源切换
- 添加备用数据源（如 Visual Crossing、WeatherAPI）
- 实现数据源优先级和故障转移

**修改文件：**
- `Code/backend/app/services/api_config.py` - 添加更多数据源配置
- `Code/backend/app/weatherengine/client.py` - 实现数据源切换

**代码示例：**
```python
class MultiSourceWeatherClient:
    def __init__(self, clients: list[WeatherClient]):
        self.clients = clients  # 按优先级排序
        self.circuit_breakers = {id(c): CircuitBreaker() for c in clients}
    
    async def fetch_forecast(self, **kwargs):
        for client in self.clients:
            breaker = self.circuit_breakers[id(client)]
            if breaker.can_execute():
                try:
                    result = await client.fetch_forecast(**kwargs)
                    breaker.record_success()
                    return result
                except Exception as e:
                    breaker.record_failure()
                    logger.warning(f"Data source {client.__class__.__name__} failed: {e}")
                    continue
        
        # 所有数据源都失败，尝试使用缓存
        return await self._fallback_to_cache(**kwargs)
```

### 阶段 3：功能增强（中优先级）

#### 3.1 添加数据预取机制

**功能：** 在用户可能访问的区域提前获取数据

**实现方案：**
- 根据用户移动方向预测下一个视口
- 提前获取预测区域的数据
- 使用 Web Worker 在后台执行预取

**修改文件：**
- `Code/frontend/src/stores/layers/index.ts` - 添加预取逻辑
- `Code/frontend/src/services/runtime-api.ts` - 添加预取 API

**代码示例：**
```typescript
// 预测下一个视口
function predictNextViewport(
  currentCenter: { lng: number; lat: number },
  velocity: { dLng: number; dLat: number }
): BoundingBox {
  const predictedCenter = {
    lng: currentCenter.lng + velocity.dLng * 2,  // 预测 2 秒后的位置
    lat: currentCenter.lat + velocity.dLat * 2,
  }
  return buildBBoxAroundCenter(predictedCenter, currentZoom)
}

// 预取数据
async function prefetchWeatherData(bbox: BoundingBox, layerIds: string[]) {
  for (const layerId of layerIds) {
    const key = buildCacheKey(layerId, bbox)
    if (!weatherTileCache.has(key)) {
      // 后台获取数据
      void runWorkflowForCatalog(layerId, { bbox, isPrefetch: true })
    }
  }
}
```

#### 3.2 添加离线模式

**功能：** 在网络不可用时使用缓存数据

**实现方案：**
- 检测网络状态
- 网络不可用时自动切换到离线模式
- 使用 Service Worker 缓存关键数据

**修改文件：**
- `Code/frontend/src/services/runtime-api.ts` - 添加网络状态检测
- `Code/frontend/src/stores/layers/index.ts` - 添加离线模式逻辑

#### 3.3 添加性能监控和诊断

**功能：** 收集性能指标，帮助诊断问题

**实现方案：**
- 添加请求耗时统计
- 添加缓存命中率监控
- 添加错误率监控
- 提供性能仪表板

**修改文件：**
- `Code/backend/app/core/logging.py` - 添加性能日志
- `Code/backend/app/api/routes.py` - 添加性能指标端点
- `Code/frontend/src/services/runtime-api.ts` - 添加前端性能监控

**代码示例：**
```python
# 性能指标收集
class PerformanceMetrics:
    def __init__(self, redis_client):
        self.redis = redis_client
    
    async def record_request(self, endpoint: str, duration: float, status: str):
        key = f"metrics:{endpoint}:{datetime.now().strftime('%Y%m%d')}"
        await self.redis.hincrbyfloat(key, "total_duration", duration)
        await self.redis.hincrby(key, "request_count", 1)
        await self.redis.hincrby(key, f"status_{status}", 1)
        await self.redis.expire(key, 86400)  # 保留 24 小时
    
    async def get_metrics(self, endpoint: str, date: str = None):
        date = date or datetime.now().strftime('%Y%m%d')
        key = f"metrics:{endpoint}:{date}"
        return await self.redis.hgetall(key)
```

### 阶段 4：架构优化（低优先级）

#### 4.1 引入消息队列

**问题：** 当前使用 Celery，但配置不够优化

**优化方案：**
- 优化 Celery worker 配置
- 添加优先级队列
- 实现任务超时控制

**修改文件：**
- `Code/backend/app/core/celery_app.py` - 优化配置
- `Code/backend/app/tasks/weather_tasks.py` - 添加优先级

#### 4.2 实现微服务拆分

**长期目标：** 将天气引擎拆分为独立服务

**架构：**
```
前端 → API Gateway → Weather Service (独立服务)
                    → Algorithm Service (独立服务)
                    → GEE Service (独立服务)
```

**优势：**
- 独立部署和扩展
- 故障隔离
- 技术栈灵活

---

## 实施计划

### 第一阶段（1-2 周）：性能优化
- [ ] 限制 bbox 大小，避免 URL 过长
- [ ] 改进缓存策略，使用 Redis 缓存
- [ ] 添加请求去重机制
- [ ] 性能测试和验证

### 第二阶段（1-2 周）：可靠性提升
- [ ] 改进错误处理和重试逻辑
- [ ] 添加断路器模式
- [ ] 添加多数据源支持
- [ ] 故障转移测试

### 第三阶段（2-3 周）：功能增强
- [ ] 添加数据预取机制
- [ ] 添加离线模式
- [ ] 添加性能监控和诊断
- [ ] 用户体验测试

### 第四阶段（长期）：架构优化
- [ ] 优化 Celery 配置
- [ ] 微服务拆分评估
- [ ] 架构重构

---

## 验证指标

### 性能指标
- API 响应时间 P95 < 2 秒
- 缓存命中率 > 80%
- 请求去重率 > 50%

### 可靠性指标
- API 成功率 > 99%
- 故障恢复时间 < 30 秒
- 数据源切换成功率 > 95%

### 用户体验指标
- 页面加载时间 < 3 秒
- 图层渲染时间 < 1 秒
- 视口变化响应时间 < 500 毫秒

---

## 风险和注意事项

1. **向后兼容性**：确保修改不影响现有功能
2. **数据一致性**：缓存策略变更可能导致数据不一致
3. **性能回退**：新引入的机制可能带来额外开销
4. **复杂度增加**：多数据源和断路器模式增加系统复杂度

---

## 下一步行动

1. **立即执行**：限制 bbox 大小，解决 URL 过长问题
2. **本周完成**：改进缓存策略，使用 Redis 缓存
3. **下周完成**：添加请求去重和断路器模式
4. **持续改进**：收集性能数据，持续优化
