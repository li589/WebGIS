# 端到端在线数据集成升级 — 实施计划

## 摘要

为部分算法图层（`python_provider` / `gee` 引擎）增加"在线时间获取"能力：用户在时间轴选择时间点后，系统自动检查本地缓存，未命中则提交工作流在线拉取/处理数据，完成后动态刷新地图显示并反馈时间轴状态。同时支持相邻时间点的后台预获取，并通过时间轴四态（可获取 / 获取中 / 就绪 / 失败）向用户反馈数据可用性。

**核心决策**：复用现有 `workflow-runs` 提交 / 轮询 / 产物物化链路，新增一个前端编排器模块 + 一个后端发现端点 + 一个段状态 + 一个能力标记字段，不新建并行系统。

---

## 一、当前状态分析

### 1.1 已验证的架构基线

| 组件 | 现状 | 文件 |
|------|------|------|
| 时间轴 | `ui.ts` (currentHour/currentDate) → `workspace-domain.ts` (currentHour ref) → `useTimelineSync.ts` 桥接 → `index.ts` watch → 天气瓦片 flush | `stores/ui.ts`, `stores/layers/workspace-domain.ts`, `views/dashboard/useTimelineSync.ts` |
| 时间轴段状态 | `'empty' | 'partial' | 'ready' | 'static' | 'error'`，来自本地 timeList / coverage | `utils/layer-timeline.ts` L11 |
| 天气在线获取 | `source_type=weather`, `is_realtime=true` → `GET /weather/tiles` 热路径 → `fetch_gateway` → providers | `app/weatherengine/`, `stores/weather-tile-manager.ts` |
| 算法层工作流 | 手动提交：`runWorkflowForCatalog` → `POST /workflow-runs` → 轮询 → `attachAlgorithmProductOverlays` | `stores/layers/workflow-runner.ts` L756 |
| 工作流提交 | `WorkflowSubmitRequest` 已有 `time_range: TimeRange | None` 和 `parameters: dict` | `Code/shared/contracts/api_contracts.py` L473-483 |
| 外部 run 注册 | `registerExternalWorkflowRun(runId, catalogIdHint)` 可注册外部触发的工作流并启动轮询 | `stores/layers/workflow-runner.ts` L230 |
| 时间键追踪 | `JobLayerItem` 已有 `inFlightTimeKeys?: string[]` 和 `failedTimeKeys?: string[]` | `stores/layers/types.ts` L247-249 |
| Payload 构建 | `buildWorkflowPayloadForCatalog` 返回普通对象，可扩展 `time_range` | `stores/layers/run-layers.ts` L273-313 |
| 动态刷新 | `scienceTimeListSignature` watcher 监控 timeList 增长 → 自动 snap + `setOverlayTime` | `views/dashboard/useTimelineSync.ts` L252-292 |
| 工作流定时器 | 支持 cron / interval / event 三种触发，Celery Beat 每分钟 tick | `app/services/workflow_timer_service.py` |

### 1.2 关键差距

| 差距 | 说明 |
|------|------|
| 无 `online_temporal` 能力标记 | 图层 descriptor 无法声明"可在线获取历史时间点" |
| 无在线时间范围发现端点 | 前端无法知道哪些时间点可在线获取 |
| 段状态缺 `'fetchable'` | 时间轴无法区分"无数据"与"可获取但未获取" |
| 时间点选择不触发获取 | `setOverlayTime` 仅切换已有切片，未命中时不触发工作流 |
| 无预获取机制 | 相邻时间点不会后台自动拉取 |
| `runWorkflowForCatalog` 有中断逻辑 | 调用 `interruptWorkflowForCatalog(catalogId)` 会取消同 catalogId 的活跃 run，与多时间点并行获取冲突 |

### 1.3 设计约束

- 单机构 / 单 API Key / SQLite 发布边界
- `Env/Python312` 唯一解释器；前端 Vue3 + TS + Vite + Pinia
- 提交信息遵循 Conventional Commits
- WorkBuddy 内跑后端测试需 `CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID=` 前缀
- `demo` 角色只读，不可提交工作流

---

## 二、架构决策（ADR）

### 决策问题

如何让算法图层支持"用户选时间点 → 自动在线获取 → 动态刷新"，同时与现有视口驱动工作流互不干扰？

### 上下文与驱动力

| 驱动力 | 说明 |
|--------|------|
| 用户体验 | 用户拖时间轴到无数据时间点时，应自动获取而非手动运行工作流 |
| 资源约束 | 单机构 / SQLite，worker 池有限，预取不能压垮系统 |
| 架构一致性 | 复用 workflow-runs 链路，不新建并行系统 |
| 状态可观测 | 时间轴需反馈四态：可获取 / 获取中 / 就绪 / 失败 |

### 决策

**新增前端编排器**，绕过 `runWorkflowForCatalog` 的中断逻辑，直接调 `submitWorkflow` + `registerExternalWorkflowRun`，按 `catalogId::timeKey` 去重提交。用 `queue_tag: 'temporal-fetch'` + `priority: 'low'` 与用户主动触发的工作流区分。

### 被拒绝的替代方案

| 方案 | 拒绝原因 |
|------|---------|
| 复用 `runWorkflowForCatalog` | 内部调 `interruptWorkflowForCatalog(catalogId)`，会取消同 catalogId 的活跃 run，无法为不同时间点并行/排队提交 |
| 扩展天气瓦片模式到算法层 | 算法层产出完整数据集而非瓦片，需要工作流执行（可能数分钟），不适合瓦片热路径 |
| 新建后端定时器 event 触发预取 | 预取是客户端行为（由用户时间轴操作触发），引入跨进程事件传递增加复杂性 |
| 新增 `'fetching'` 段状态 | `'partial'` 已映射 `inFlightTimeKeys` 且 UI 已有加载中样式，复用减少改动 |

### 后果

| 正面 | 负面 |
|------|------|
| 复用现有提交/轮询/物化链路，改动最小 | 编排器需自行管理 `fetchStates` Map 做去重 |
| `queue_tag` 区分便于后端限流与监控 | 同 catalogId 可能有多个活跃 run，UI 需适配 |
| 预取参考天气瓦片并发槽位模式，成熟可靠 | 预取失败需冷却重试机制 |

### 可逆性

**两向门（可逆）**：`online_temporal` 字段为 `None` 时该层退回纯手动模式；编排器为独立模块，移除不影响现有功能。`queue_tag` 仅影响提交参数，不改变后端执行逻辑。

### 责任

前端编排器 + 时间轴联动：`online-temporal-orchestrator.ts` + `useTimelineSync.ts`；后端发现端点：`layer_router.py`；本地验证：`npm run test` + `pytest Test/backend`。

---

## 三、系统映射

### 数据流（完整链路）

```
用户拖动时间轴 → currentDate/currentHour 变更
  → useTimelineSync watcher
  → onlineTemporalOrchestrator.ensureTimePointAvailable(catalogId, timeKey)
      ├─ 检查 local time_list（命中则返回）
      ├─ 检查 fetchStates 去重（inFlight 则返回）
      ├─ buildWorkflowPayloadForCatalog + time_range = [timeKey, timeKey+step]
      ├─ submitWorkflow (queue_tag=temporal-fetch, priority=low)
      ├─ registerExternalWorkflowRun(runId, catalogId) → poller 启动轮询
      └─ addInFlightTimeKey → 时间轴段变 'partial'（获取中）
          ↓
  [后台 Celery worker 执行算法]
          ↓
  轮询检测终态
  ├─ succeeded: attachAlgorithmProductOverlays → time_list 增长
  │   → removeInFlightTimeKey → 时间轴段变 'ready'
  │   → scienceTimeListSignature watcher → snapTimelineToLayerLatest
  │   → setOverlayTime → 地图显示新切片
  └─ failed: addFailedTimeKey → 时间轴段变 'error'

并行：prefetchAdjacent(catalogId, timeKey)
  → 对前后 N 步时间点调 ensureTimePointAvailable（并发槽位 2 + 冷却 10s）
```

### 依赖方向

```
layer_descriptors.json (online_temporal)
  ↓
api_contracts.py (OnlineTemporalCapability)
  ↓
layer_router.py (GET /layers/{id}/online-temporal)
  ↓
catalog-runtime.ts (supportsOnlineTemporal / getOnlineTemporalConfig)
  ↓
online-temporal-orchestrator.ts (ensureTimePointAvailable / prefetchAdjacent)
  ↓ (复用)
workflow-runner.ts (registerExternalWorkflowRun)
run-layers.ts (buildWorkflowPayloadForCatalog / addInFlightTimeKey)
workflow-poller.ts (终态时间键更新)
useTimelineSync.ts (时间变更触发 + 段状态)
layer-timeline.ts + run-timeline-availability.ts (四态段)
```

---

## 四、分阶段实施

### 阶段 1：契约与后端基础

#### 1.1 新增契约模型

**文件**：`Code/shared/contracts/api_contracts.py`
**改什么**：新增 `OnlineTemporalCapability` 模型，并在 `LayerDescriptor` 中增加 `online_temporal` 字段
**为什么**：声明式标记哪些图层支持在线时间获取及获取参数
**怎么改**：

```python
class OnlineTemporalCapability(BaseModel):
    enabled: bool = False
    coverage_start: str | None = None   # ISO 日期或 'YYYY-MM'
    coverage_end: str | None = None
    native_step: str = "1d"             # '1d' / '8d' / '1M' / '1Y'
    max_batch: int = 12
    prefetch_depth: int = 1             # 前后各 N 步
    queue_tag: str = "temporal-fetch"
    priority: str = "low"               # 'low' | 'normal'
```

在 `LayerDescriptor` 类中增加：`online_temporal: OnlineTemporalCapability | None = None`

#### 1.2 新增后端发现端点

**文件**：`Code/backend/app/api/routers/layer_router.py`
**改什么**：新增 `GET /layers/{layer_id}/online-temporal` 端点
**为什么**：前端查询某图层可在线获取的时间范围与步长
**怎么改**：

```python
@router.get("/layers/{layer_id}/online-temporal", tags=["catalog"])
def get_layer_online_temporal(layer_id: str, cred=Depends(get_request_user)) -> dict:
    check_resource_access(cred, "layer", layer_id)
    descriptor = get_layer_descriptor(layer_id)
    cap = descriptor.online_temporal if descriptor else None
    if cap is None or not cap.enabled:
        return {"layer_id": layer_id, "available": False}
    return {"layer_id": layer_id, "available": True, **cap.model_dump()}
```

#### 1.3 更新图层种子

**文件**：`Code/backend/app/catalog_seeds/layer_descriptors.json`
**改什么**：为符合条件的算法图层（如 `ndvi`）添加 `online_temporal` 配置
**怎么改**：以 `ndvi` 为例：

```json
"online_temporal": {
  "enabled": true,
  "coverage_start": "2000-01",
  "coverage_end": "2025-06",
  "native_step": "1M",
  "max_batch": 12,
  "prefetch_depth": 1,
  "queue_tag": "temporal-fetch",
  "priority": "low"
}
```

#### 1.4 前端契约同步

**文件**：`Code/frontend/openapi.json` + `Code/frontend/src/types/api-reexports.ts`
**怎么改**：运行 `npm run check:openapi` 驱动同步

**验证**：
- `Env/Python312/python.exe -m pytest Test/backend/test_config_security.py -q`
- `cd Code/frontend && npm run check:openapi && npm run check:catalog`
- 启动后端后 `GET /layers/ndvi/online-temporal` 返回 `available: true`

---

### 阶段 2：前端类型与能力判定

#### 2.1 能力判定函数

**文件**：`Code/frontend/src/services/layer-capabilities.ts`
**改什么**：新增 `supportsOnlineTemporalCapability` 和 `getOnlineTemporalConfig`
**怎么改**：

```typescript
export function supportsOnlineTemporalCapability(descriptor?: LayerDescriptor | null): boolean {
  return Boolean(descriptor?.online_temporal?.enabled)
}
export function getOnlineTemporalConfig(descriptor?: LayerDescriptor | null) {
  return descriptor?.online_temporal ?? null
}
```

#### 2.2 catalog-runtime 集成

**文件**：`Code/frontend/src/stores/layers/catalog-runtime.ts`
**改什么**：在 slice 接口与实现中新增 `supportsOnlineTemporal(catalogId)` 和 `getOnlineTemporalConfig(catalogId)` 方法
**怎么改**：通过 `resolveBackendLayerId` + `getRuntimeLayerDescriptor` 查询 descriptor，调上述能力判定函数

**验证**：
- `cd Code/frontend && npm run test -- layer-capabilities && npm run lint`

---

### 阶段 3：时间轴四态 segments

#### 3.1 段状态扩展

**文件**：`Code/frontend/src/utils/layer-timeline.ts`
**改什么**：`TimelineAvailabilitySegment.state` 类型增加 `'fetchable'`；`labelFor` 增加对应标签
**怎么改**：

```typescript
state: 'empty' | 'fetchable' | 'partial' | 'ready' | 'static' | 'error'
// labelFor 增加：
if (state === 'fetchable') return '可在线获取'
```

各粒度分支的 `availabilityLabel` 也需增加 `fetchable` 文案。

#### 3.2 在线时间轴可用性构建器

**文件**：`Code/frontend/src/utils/run-timeline-availability.ts`
**改什么**：新增 `buildOnlineTemporalAvailability` 函数
**为什么**：将本地缓存（ready）、获取中（inFlight→partial）、失败（failed→error）、可获取（fetchable）四态合并
**怎么改**：

```typescript
export function buildOnlineTemporalAvailability(input: {
  windowDate: Date
  granularity: 'day' | 'month' | 'year'
  readyTimeList: string[]
  inFlightTimeKeys: string[]
  failedTimeKeys: string[]
  onlineCoverage: { coverageStart: string; coverageEnd: string; nativeStep: string } | null
}): Record<number, 'empty' | 'fetchable' | 'partial' | 'ready' | 'error'>
```

优先级：`empty < fetchable < partial < ready < error`。复用现有 `availabilityFromKeys` + `paintKeysOntoMap` 内部函数，新增 `paintFetchableFromCoverage`：将 coverage 范围按 native_step 展开为时间键，对未占据的槽标 `'fetchable'`。

#### 3.3 useTimelineSync 集成

**文件**：`Code/frontend/src/views/dashboard/useTimelineSync.ts`
**改什么**：在 `timelineSegments` computed 的 day/month/year 分支中，当 `supportsOnlineTemporal(catalogId)` 为 true 时，改用 `buildOnlineTemporalAvailability`
**怎么改**：

```typescript
if (isOnlineTemporal) {
  const map = buildOnlineTemporalAvailability({
    windowDate: currentDate.value,
    granularity: gran,
    readyTimeList: scienceTimes,
    inFlightTimeKeys: jobForTimeline?.inFlightTimeKeys ?? [],
    failedTimeKeys: jobForTimeline?.failedTimeKeys ?? [],
    onlineCoverage: onlineConfig ? { ... } : null,
  })
  return generateTimelineSegments(currentDate.value, gran, map)
}
```

**验证**：
- `cd Code/frontend && npm run test -- layer-timeline run-timeline-availability`
- 手动验证：选中 online_temporal 图层，时间轴显示 fetchable（蓝）/ partial（黄）/ ready（绿）/ error（红）

---

### 阶段 4：在线时间获取编排器（核心）

#### 4.1 新增编排器模块

**新增文件**：`Code/frontend/src/stores/layers/online-temporal-orchestrator.ts`
**职责**：
- `ensureTimePointAvailable(catalogId, timeKey)`：检查缓存 → 未命中则提交工作流
- `prefetchAdjacent(catalogId, currentTimeKey)`：预获取相邻时间点
- `retryTimePoint(catalogId, timeKey)`：清除失败状态并重新提交
- 提交去重：按 `catalogId::timeKey` 去重（非 catalogId）
- 状态追踪：`Map<string, TemporalFetchState>`

**依赖注入接口**：

```typescript
interface OnlineTemporalOrchestratorDeps {
  submitWorkflow: (payload: any) => Promise<{ run_id: string }>
  registerExternalWorkflowRun: (runId: string, catalogIdHint?: string) => Promise<void>
  buildWorkflowPayloadForCatalog: (catalogId: string, ...) => Record<string, unknown>
  getRuntimeLayerDescriptor: (catalogId: string) => LayerDescriptor | null
  resolveBackendLayerId: (catalogId: string) => string
  supportsAnalysisWorkflow: (catalogId: string) => boolean
  getLocalTimeList: (catalogId: string) => string[]
  getInFlightTimeKeys: (catalogId: string) => string[]
  getFailedTimeKeys: (catalogId: string) => string[]
  addInFlightTimeKey: (catalogId: string, timeKey: string) => void
  removeInFlightTimeKey: (catalogId: string, timeKey: string) => void
  addFailedTimeKey: (catalogId: string, timeKey: string) => void
  clearFailedTimeKey: (catalogId: string, timeKey: string) => void
  isPlaying: () => boolean
  logOperation: (type: string, message: string, details?: string) => void
}
```

**核心逻辑**：

```typescript
async function ensureTimePointAvailable(catalogId: string, timeKey: string) {
  // 1. 本地缓存命中则返回
  if (deps.getLocalTimeList(catalogId).includes(timeKey)) return
  // 2. 去重检查
  const key = `${catalogId}::${timeKey}`
  const existing = fetchStates.get(key)
  if (existing?.status === 'submitting' || existing?.status === 'inFlight') return
  // 3. 检查 online_temporal 能力
  const config = deps.getRuntimeLayerDescriptor(catalogId)?.online_temporal
  if (!config?.enabled) return
  // 4. 构建并提交工作流
  const payload = deps.buildWorkflowPayloadForCatalog(catalogId, ...)
  payload.time_range = { start_at: timeKey, end_at: addStep(timeKey, config.native_step) }
  payload.queue_tag = config.queue_tag
  payload.priority = config.priority
  payload.command_label = `在线获取 ${catalogId} @ ${timeKey}`
  deps.addInFlightTimeKey(catalogId, timeKey)
  fetchStates.set(key, { status: 'submitting', ... })
  try {
    const accepted = await deps.submitWorkflow(payload)
    fetchStates.set(key, { status: 'inFlight', runId: accepted.run_id, ... })
    await deps.registerExternalWorkflowRun(accepted.run_id, catalogId)
  } catch (err) {
    deps.removeInFlightTimeKey(catalogId, timeKey)
    deps.addFailedTimeKey(catalogId, timeKey)
    fetchStates.set(key, { status: 'failed', ... })
  }
}
```

#### 4.2 时间键操作辅助

**文件**：`Code/frontend/src/stores/layers/run-layers.ts`
**改什么**：新增 `addInFlightTimeKey` / `removeInFlightTimeKey` / `addFailedTimeKey` / `clearFailedTimeKey` 辅助函数
**怎么改**：查找 `jobLayers` 中匹配 catalogId 的 job，更新其 `inFlightTimeKeys` / `failedTimeKeys` 数组

#### 4.3 轮询终态处理

**文件**：`Code/frontend/src/stores/layers/workflow-poller.ts`
**改什么**：在终态处理中（`syncWorkflowRunSnapshot` 成功/失败路径后），更新时间键状态
**怎么改**：

```typescript
// succeeded: attachAlgorithmProductOverlays 后 time_list 增长
// 从 inFlightTimeKeys 移除已成功的 timeKey
if (run.status === 'succeeded' && run.time_range) {
  const timeKey = extractTimeKeyFromRange(run.time_range)
  if (timeKey) removeInFlightTimeKey(catalogId, timeKey)
}
// failed: 移入 failedTimeKeys
if (run.status === 'failed' && run.time_range) {
  const timeKey = extractTimeKeyFromRange(run.time_range)
  if (timeKey) {
    removeInFlightTimeKey(catalogId, timeKey)
    addFailedTimeKey(catalogId, timeKey)
  }
}
```

仅 `queue_tag === 'temporal-fetch'` 的 run 走此路径，避免影响视口驱动工作流。

#### 4.4 时间轴变更触发获取

**文件**：`Code/frontend/src/views/dashboard/useTimelineSync.ts`
**改什么**：在时间变更 watcher 中（L199 附近），增加在线时间获取触发
**怎么改**：

```typescript
// 在现有 watcher 中追加
const catalogId = selectedCatalogId.value
if (catalogId && workspace.supportsOnlineTemporal(catalogId)) {
  const timeKey = resolveTimeKeyFromTimeline(currentDate.value, currentHour.value, activeLayerGranularity.value)
  if (timeKey) {
    void onlineTemporalOrchestrator.ensureTimePointAvailable(catalogId, timeKey)
    void onlineTemporalOrchestrator.prefetchAdjacent(catalogId, timeKey)
  }
}
```

#### 4.5 编排器集成到 domain

**文件**：`Code/frontend/src/stores/layers/workflow-run-domain.ts`
**改什么**：在 `createWorkflowRunDomain` 中实例化编排器，注入 deps
**怎么改**：将编排器实例挂到 domain 返回值上，供 `useTimelineSync` 通过 `workspace` 或 `workflowRun` 访问

**验证**：
- `cd Code/frontend && npm run test -- online-temporal-orchestrator workflow-poller workflow-runner`
- `Env/Python312/python.exe -m pytest Test/backend/test_workflow_routes.py -q`
- 手动验证：选 online_temporal 图层 → 拖到无数据时间点 → 段变"获取中" → 完成后自动显示

---

### 阶段 5：预获取与限流

#### 5.1 预获取逻辑

**文件**：`Code/frontend/src/stores/layers/online-temporal-orchestrator.ts`（继续扩展）
**改什么**：新增 `prefetchAdjacent` 函数
**怎么改**：

```typescript
function prefetchAdjacent(catalogId: string, currentTimeKey: string) {
  const config = deps.getRuntimeLayerDescriptor(catalogId)?.online_temporal
  if (!config?.enabled) return
  if (deps.isPlaying()) return  // 播放中禁用预取
  const candidates = []
  for (let i = 1; i <= config.prefetch_depth; i++) {
    candidates.push(shiftTimeKey(currentTimeKey, config.native_step, i))
    candidates.push(shiftTimeKey(currentTimeKey, config.native_step, -i))
  }
  for (const key of candidates) {
    if (activeFetchCount >= MAX_CONCURRENT_PREFETCH) break
    if (isInCooldown(catalogId, key)) continue
    void ensureTimePointAvailable(catalogId, key)
  }
}
```

#### 5.2 限流机制

**文件**：同上
**怎么改**：

```typescript
const MAX_CONCURRENT_PREFETCH = 2     // 预取并发上限
const PREFETCH_COOLDOWN_MS = 10_000   // 失败后冷却
const cooldownMap = new Map<string, number>()
```

参考 `weather-tile-manager.ts` 的并发槽位模式。

**验证**：
- `cd Code/frontend && npm run test -- online-temporal-orchestrator`
- 手动验证：选时间点后观察相邻段从 fetchable → partial → ready 渐变
- `Env/Python312/python.exe -m pytest Test/backend/test_celery_tasks.py -q`

---

### 阶段 6：时间轴 UI 反馈与边界处理

#### 6.1 段状态视觉

**文件**：`Code/frontend/src/components/TimelineScrubber.vue`
**改什么**：为 `'fetchable'` 状态增加视觉样式（蓝色半透明 / 虚线），为 `'partial'` 增加"获取中"脉冲动画
**怎么改**：在段渲染 CSS class 中增加 `fetchable` 分支

#### 6.2 手动触发获取

**文件**：`Code/frontend/src/components/TimelineScrubber.vue` 或 `useTimelineControls.ts`
**改什么**：点击 `'fetchable'` 段时触发 `ensureTimePointAvailable`；点击 `'error'` 段时触发 `retryTimePoint`
**怎么改**：在段点击处理中增加状态分支

#### 6.3 播放中禁用预取

已在阶段 5.1 中处理（`isPlaying()` 检查）。

**验证**：
- `cd Code/frontend && npm run test && npm run lint && npm run build`
- `Env/Python312/python.exe -m pytest Test/backend/test_workflow_routes.py Test/backend/test_interaction_hub.py -q`
- `Env/Python312/python.exe -m pre_commit run --all-files`

---

## 五、新增文件清单

| 文件路径 | 职责 |
|---------|------|
| `Code/frontend/src/stores/layers/online-temporal-orchestrator.ts` | 在线时间获取编排器（核心） |

## 六、改动文件汇总

| 文件 | 阶段 | 改动类型 |
|------|------|---------|
| `Code/shared/contracts/api_contracts.py` | 1 | 新增 model + 字段 |
| `Code/backend/app/api/routers/layer_router.py` | 1 | 新增端点 |
| `Code/backend/app/catalog_seeds/layer_descriptors.json` | 1 | 新增配置 |
| `Code/frontend/openapi.json` + `src/types/api-reexports.ts` | 1 | 契约同步 |
| `Code/frontend/src/services/layer-capabilities.ts` | 2 | 新增函数 |
| `Code/frontend/src/stores/layers/catalog-runtime.ts` | 2 | 新增方法 |
| `Code/frontend/src/utils/layer-timeline.ts` | 3 | 类型扩展 |
| `Code/frontend/src/utils/run-timeline-availability.ts` | 3 | 新增函数 |
| `Code/frontend/src/views/dashboard/useTimelineSync.ts` | 3,4,5 | 新增分支 + watcher |
| `Code/frontend/src/stores/layers/run-layers.ts` | 4 | 新增辅助函数 |
| `Code/frontend/src/stores/layers/workflow-poller.ts` | 4 | 终态时间键更新 |
| `Code/frontend/src/stores/layers/workflow-run-domain.ts` | 4 | 编排器集成 |
| `Code/frontend/src/components/TimelineScrubber.vue` | 6 | 段状态视觉 + 交互 |

## 七、Fitness Functions（架构不变量）

| 属性 | 指标 | 阈值/规则 | 测量来源 | 评估频率 | 失败响应 | 本地检查 |
|------|------|----------|---------|---------|---------|---------|
| 依赖方向 | online-temporal-orchestrator 不被 workflow-runner 反向依赖 | 无 import 循环 | eslint import/no-cycle | CI/pre-commit | 阻止合并 | `npm run lint` |
| 公共契约兼容 | `OnlineTemporalCapability` 新增字段不破坏现有 `LayerDescriptor` 消费者 | Pydantic 向后兼容 | `check:openapi` | CI | 阻止合并 | `npm run check:openapi` |
| 提交隔离 | temporal-fetch 工作流不取消视口驱动工作流 | `queue_tag` 区分 + 编排器不调 `interruptWorkflowForCatalog` | 单元测试 | CI | 测试失败 | `npm run test -- online-temporal-orchestrator` |
| 预取限流 | 并发预取不超过 2 | `MAX_CONCURRENT_PREFETCH` 常量 | 单元测试 | CI | 测试失败 | `npm run test -- online-temporal-orchestrator` |
| 段状态完整性 | 所有段状态有对应 UI 样式 | CSS class 覆盖所有 state 值 | vitest + 手动 | CI | 阻止合并 | `npm run test -- layer-timeline` |

## 八、风险登记

| 风险 | 可能性 | 影响 | 缓解 |
|------|--------|------|------|
| 预取风暴压垮 worker | 中 | 高 | 并发槽位 2 + 冷却 10s + 播放中禁用 + low priority |
| 同一时间点重复提交 | 中 | 中 | `fetchStates` Map 按 `catalogId::timeKey` 去重 |
| 工作流失败导致段永久 error | 低 | 中 | 段点击重试 + `clearFailedTimeKey` |
| 时间键格式不匹配 | 中 | 高 | 复用 `buildExpectedSlotKeys` 格式约定；单元测试覆盖格式转换 |
| 契约漂移 | 低 | 中 | `check:openapi` + `check:catalog` 纳入 CI |
| WorkBuddy 测试假阳性 | 中 | 低 | 后端测试加 `CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID=` 前缀 |
| 同 catalogId 多活跃 run 混淆 UI | 中 | 中 | `WorkflowStatusPanel` 按 runId 区分；`queue_tag` 标记来源 |

## 九、"改 X 则跑 Y" 映射（新增）

| 改动区域 (X) | 定位模块 | 验证命令 (Y) |
|-------------|---------|-------------|
| 在线时间获取编排 | `online-temporal-orchestrator.ts`、`useTimelineSync.ts` | `cd Code/frontend && npm run test -- online-temporal-orchestrator useTimelineSync` |
| 在线时间轴段 | `run-timeline-availability.ts`、`layer-timeline.ts` | `cd Code/frontend && npm run test -- run-timeline-availability layer-timeline` |
| 在线时间能力标记 | `layer-capabilities.ts`、`catalog-runtime.ts` | `cd Code/frontend && npm run test -- layer-capabilities`；`npm run check:catalog` |
| 在线时间发现端点 | `layer_router.py`、`api_contracts.py` | `Env/Python312/python.exe -m pytest Test/backend/test_config_security.py -q`；`npm run check:openapi` |

## 十、假设与决策

1. **假设**：`buildWorkflowPayloadForCatalog` 返回的普通对象可被编排器扩展 `time_range` / `queue_tag` / `priority` / `command_label` 字段（已验证 L283-312 返回 `Record<string, unknown>`）
2. **假设**：`registerExternalWorkflowRun` 可被编排器复用来启动轮询（已验证 L230 存在且接受 runId + catalogIdHint）
3. **假设**：`JobLayerItem.inFlightTimeKeys` / `failedTimeKeys` 已在类型中定义（已验证 types.ts L247-249），需在 run-layers 中增加写入辅助
4. **决策**：编排器不调 `runWorkflowForCatalog`，而是直接调 `submitWorkflow` + `registerExternalWorkflowRun`，避免中断逻辑冲突
5. **决策**：段状态仅新增 `'fetchable'` 一态，`'partial'` 复用为"获取中"
6. **决策**：预取并发上限 2，冷却 10s，播放中禁用
7. **决策**：后端不新增 worker 池，用 `queue_tag` + `priority` 复用现有 workflow 池
