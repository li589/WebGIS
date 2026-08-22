# 前端 UI 显示与同步审查（2026-08-21）

审查范围：`Code/frontend/src`（组件 / composables / stores / views），专项聚焦「UI 组件显示与状态同步」。
方法：按 6 个维度（异步竞态 / watch 依赖 / 定时器与监听器泄漏 / 加载与错误状态 / store 与本地双份状态 / v-for key）grep 全量扫描 + 逐处读上下文 20-40 行判真伪。只读分析，未改代码。

## P0（状态错乱导致功能破坏 / 白屏）

本轮未发现达到 P0 的问题。整体观察：该前端对异步防护的纪律性较高（点查 `point-weather.ts` 有 AbortController、天气 provider 加载有 AbortController + `signal.aborted` 双重防护、workflow 轮询有 viewport epoch 世代号、MapCanvas 挂载全程有 `_isUnmounted` 守卫、地图模块有集中 `dispose`、App 根部有 `AppErrorBoundary`），未发现会导致白屏或核心功能完全破坏的状态错乱路径。

## P1（数据显示不同步 / 竞态 / 内存泄漏）

### [U-1] 地图点查时序数据竞态：旧点响应覆盖新点数据（`views/dashboard/useMapInspect.ts:157-161, 176-177, 205-207`）

**证据**：`fetchOverlayPointValues` 用 `overlayPointFetchSeq` 序号保护了 `overlayPointValues`（L134-138、L147-151 均有 `if (seq !== overlayPointFetchSeq) return`），但其内部调用的两个子函数完全没有防护：

```ts
// L157-160：seq 未传递给子调用
await Promise.all([
  fetchAllOverlaySeries(lng, lat, states),      // 内部 L177 无条件写入
  fetchSelectedOverlaySeries(lng, lat),          // 内部 L205 无条件写入
])
```

- `fetchAllOverlaySeries`（L164-178）末尾 `allOverlayTimeSeries.value = seriesMap` 无条件覆盖；
- `fetchSelectedOverlaySeries`（L180-208）末尾 `selectedOverlayTimeSeries.value = ...` 无条件覆盖；
- L234-243 的 watch（选中图层 overlayLayerId 变化）与 DashboardView.vue L419-421 暴露给 InfoPanel 的 `@query-overlay-series` 事件直接调用 `fetchSelectedOverlaySeries`，同样无防护。

**复现场景**：选点 A（时序层多、切片多、响应慢）→ 立即改选点 B（响应快）。B 的时序先写入，A 的旧响应后到并覆盖 `allOverlayTimeSeries` / `selectedOverlayTimeSeries` → InfoPanel 折线图/时序表显示的是 A 点的数值，而地图选点标记与坐标栏是 B 点——数值与选点静默不一致，且无任何提示。时序层每次点查会对每个时间片各发一个 `getOverlayValue` 请求（L169-171），点越密集窗口期越长。

**修复建议**：将 `overlayPointFetchSeq` 传入两个子函数，写回前校验 `seq === overlayPointFetchSeq`（与 `overlayPointValues` 同款防护）；或在子函数内各自维护 AbortController 并在再次触发时 abort。

### [U-2] `setOverlayTime` 时间片切换竞态：旧时间片覆盖新状态，且经 linkTime 扩散（`components/map/overlay-image-module.ts:891-970`）

**证据**：`setOverlayTime` 全程无版本号 / 序号 / AbortController 防护。两次并发调用 A(t1)→B(t2) 时各自 `await _fetchTimedBounds(...)`（L896），先发后至时旧响应会继续执行后续全部写回：

```ts
loaded.currentTime = time                                    // L939
overlayTimeStates.value = overlayTimeStates.value.map(...)   // L940-942 更新 currentTime/bounds
```

若 t1 的响应晚于 t2 返回，最终 `loaded.currentTime`、`overlayTimeStates`、raster source URL 全部停留在 t1，而用户时间轴停在 t2。更严重的是 L952-968 的 linkTime 联动：会以错误的 `time` 为基准对**其他所有时间序列图层**再各发一轮 `setOverlayTime`，把过期时间扩散到全部联动层。

**触发路径**：`useTimelineSync.ts:203-211` 的 watch（`[currentHour, currentDate, unifiedTimeLock]`，无防抖）→ `refreshImportedRasterEffectiveTimes`（L171-198）→ 每次 hour/date 变化直接 `void mapCanvasRef.value?.setOverlayTime?.(overlayId, sliceLabel)`。播放模式下 TimelineScrubber 每 2s 步进一次，每次都触发；`raster-xyz` 模式下每次切换还要整体 removeLayer/removeSource 再重建（L910-920），网络稍慢（`_fetchTimedBounds` > 播放间隔）即必然乱序。

**复现场景**：时间序列图层 + 开启图层时间联动 + 播放（或快速拖动滑块），网络延迟 > 2s 时，地图显示的时间片与时间轴 UI 位置不一致，多个联动图层可能停在互不相同的时间片上。

**修复建议**：模块内维护 `timeReqSeq: Map<layerId, number>`，`setOverlayTime` 入口取号，`_fetchTimedBounds` 返回后（以及递归 fallback 前）校验序号是否仍为最新，过期直接 return；linkTime 联动循环同理只携带最新序号。

### [U-3] JobsPanel 卸载后轮询链复活：组件销毁仍每 2-15s 无限轮询（`data-manager/ui/JobsPanel.vue:80-95`）

**证据**：

```ts
function scheduleNext() {
  if (timer) clearTimeout(timer)
  const delay = hasActiveJobs() ? POLL_ACTIVE_MS : POLL_IDLE_MS
  timer = setTimeout(async () => {
    await refresh()      // ← 卸载可发生在此 await 期间
    scheduleNext()       // ← 卸载后仍会重新 setTimeout
  }, delay)
}
onUnmounted(() => { if (timer) clearTimeout(timer) })  // 对已触发的 timer 无效
```

**复现场景**：定时器已触发、`refresh()` 在飞（网络慢）时用户关闭数据工作区 → `onUnmounted` 的 `clearTimeout` 清的是已消费的句柄（no-op）→ `refresh` 返回后 `scheduleNext()` 重新排定下一个 timer → 轮询链在组件销毁后永久自续，每 2s（有活跃任务时）或 15s 请求一次 `listImportJobs`，直到整页刷新。反复开关面板会叠加多条轮询链。

**修复建议**：增加 `let disposed = false`，`onUnmounted` 置位；`scheduleNext` 与回调入口检查 `if (disposed) return`。`data-manager/ui/DataWorkspace.vue` 等同类自续轮询可一并自查。

### [U-4] 在线时间获取集成：cleanupTimer 卸载不清理 + watch 缺 immediate（`views/dashboard/useOnlineTemporalIntegration.ts:139-150`）

**证据**：

```ts
let cleanupTimer: ReturnType<typeof setInterval> | null = null
watch(
  () => orchestrator.currentLayerSupportsOnline.value,
  (supported) => {
    if (supported && !cleanupTimer) {
      cleanupTimer = setInterval(() => orchestrator.cleanupStaleEntries(), 60_000)
    } else if (!supported && cleanupTimer) { clearInterval(cleanupTimer); ... }
  },
  // 无 immediate，也无 onUnmounted / onScopeDispose 清理
)
```

- **泄漏**：该 composable 随 DashboardView 挂载。切换路由离开仪表盘时，若当前选中图层支持在线获取（`supported === true`），`cleanupTimer` 不会被清除——watcher 随组件销毁，但闭包里的 interval 继续每 60s 调用 `cleanupStaleEntries()` 直到刷新页面。SPA 内多次进出仪表盘会累积多条。
- **附带**：watch 无 `immediate: true`，若挂载时选中层已支持在线获取（工作区快照恢复场景），清理定时器根本不会启动，`fetchEntries` 中 failed/cooling 条目只能靠下次触发时惰性清理，长期驻留内存。

**修复建议**：`onScopeDispose(() => { if (cleanupTimer) clearInterval(cleanupTimer) })`；watch 加 `{ immediate: true }`。

## P2（记录不修）

### [U-5] 短延时定时器未随卸载清理（两处）
- `views/dashboard/useMapInspect.ts:270-280`：`pointHourRefetchTimer`（180ms 防抖）无卸载清理。影响极小（至多多发一次点查请求），但不符合工程一致性——同文件其他异步路径都有防护。
- `views/dashboard/useOnlineTemporalIntegration.ts:88-91`：自动触发 watcher 内 `setTimeout(300ms)` 未保存句柄、未清理，组件卸载后 300ms 内仍可能触发一次在线获取工作流提交。

### [U-6] analysis-runner watchRun 30 分钟超时后状态悬挂（`stores/analysis-runner.ts:352-402`）
`while (Date.now() - started < 30 * 60_000)` 循环退出（超时）时直接 return，`activeByKey` 中该条目停留在 `running` 相位，UI 无超时提示、无失败回落。超长分析工具（>30min）会永远显示"运行中"。建议超时后写入 `phase: 'failed', message: '轮询超时'` 或至少给出提示。

### [U-7] 表格类 v-for 使用索引 key（三处）
- `components/info-panel/AnalysisResultCharts.vue:145-146`：`:key="ri"` / `:key="ci"`（表格行/单元格，数据为结果快照，重排风险低）；
- `data-manager/ui/DataImportPanel.vue:1074`：`:key="idx"`（文档预览行）；
- `components/info-panel/InfoPanelMetaTab.vue:330-331`：`:key="\`job-note-${idx}\`"`（事件消息列表，前插场景下可能导致 DOM 复用错位）。
均为低风险静态快照/短列表，记录备查。

### [U-8] WorkflowInspector 本地副本不随节点原地变更刷新（`components/workflow/WorkflowInspector.vue:43-63`）
`watch(() => props.selectedNode, ...)` 只在节点引用变化时重建 `localProperties`。litegraph 内部若原地修改 `node.properties`（如程序化赋值、外部同步）而引用不变，右侧检查器显示旧值。常规编辑路径经 emit 回写无问题，属边缘场景。

### [U-9] 运行时图层目录加载失败无用户可见反馈（`stores/layers/catalog-runtime.ts:277-310` + `views/DashboardView.vue:62-63`）
`ensureRuntimeLayerCatalog` 失败仅 `console.warn` 并 rethrow，DashboardView 用 `void ... .finally(...)` 消费（unhandled rejection），UI 无错误横幅/重试入口。因侧栏库有 `catalog-seeds.generated.json` 静态兜底不至于空白，但 runtime 状态（backendStatus/runReadiness 等）缺失时用户无从得知原因。建议接入 `workflowError` 或日志面板的显式提示。

### [U-10] DashboardView 启动 IIFE 无 catch（`views/DashboardView.vue:67-75`）
`void (async () => { try { await syncWorkspaceOnBoot(); await workflowRun.restoreActiveWorkflows() } finally { ... } })()` 只有 finally 无 catch。`restoreActiveWorkflows` 若抛错（hydrate 内部未全兜底路径）会成为 unhandled rejection；hydration guard 已在 finally 复位，无功能性破坏，仅控制台噪音 + 图层恢复静默失败。建议补 catch 并落日志面板。

### [U-11] GpuPerfTestDialog 关闭后测试循环继续后台运行（`components/settings/GpuPerfTestDialog.vue:600-621, 652-659`）
`handleClose` → 300ms 后 `reset()` 只清 UI 状态；若测试仍在进行，for 循环继续占用 GPU/Canvas 跑完剩余场景（`results` 持续 push）。`props.open=false` 仅隐藏弹窗。建议 `reset` 时置 abort 标志并在循环内检查。

## 已核实为设计如此（不报）

- workflow-poller 1.2s/2.6s/9s 三档轮询间隔、30 分钟 idle 软超时、连续 3 次错误后先问服务端再判死——`workflow-poller.ts` 全部为有意设计；
- `boundsMissCache` 404 负缓存（`overlay-image-module.ts:671,680`）——设计如此；
- 429/AbortError 退避重试逻辑——设计如此；
- maplibre 图层/source 生命周期由 overlay-image-module 集中管理，`dispose()`（L1073-1091）已完整清理 loadedOverlays、map 事件监听（zoomend/moveend/zoom）与 zoomSyncTimer；MapCanvas 经 `map-canvas-teardown-binder.ts` 统一 dispose 各模块——已覆盖，不报；
- `weather-sync-status` / `workspace-sync` / `weather-tile-manager` 等 store 级定时器为应用生命周期设计（`teardownWorkspaceSync` 已由 DashboardView onBeforeUnmount 调用，`cleanupAllRetryTimers` 同理）；
- `useWeatherCoverage`（AbortController + onBeforeUnmount 清理）、`useWeatherProviders`（abort + aborted 双检）、TimelineScrubber（播放定时器 + visibilitychange + 三个 document 监听器成对清理）、WorkflowStatusPanel/WorkflowTimerPanel/SystemResourceMetrics/SystemStatusSettings/OpenMeteoSyncSettings/ServiceConnectivityBanner（均验证 onBeforeUnmount 与 timer 成对）——防护完备，列为正面样例。

## 审查覆盖说明

- **审查路径**：`Code/frontend/src` 全量（约 components / composables / stores / views / data-manager / utils 六大块，重点覆盖任务指定的 LayerSidebar 体系、时间轴（TimelineScrubber/useTimelineSync/useTimelineControls）、overlay-image-module、workflow-poller、online-temporal-orchestrator/useOnlineTemporalIntegration、useMapInspect、DashboardView 编排壳、settings 与 workflow 面板组件、data-manager UI）。
- **扫描模式**：`setInterval(`（13 处 hit 全部核对清理路径）；`onUnmounted|onBeforeUnmount`（40+ 组件比对）；`v-for`（90+ 处核对 :key）；`onMounted(async`（17 处核对 try/catch）；`\.then\(`（7 处核对 catch）；`EventSource|new WebSocket`（无使用）；`echarts init/dispose`（图表为自绘 SVG + VChart autoresize，无手动实例泄漏）；store/本地双份状态（仅 WorkflowInspector 的 prop 本地副本模式，见 U-8）。
- **未覆盖**：`services/` 层 HTTP 客户端内部实现、`utils/` 纯函数正确性（本轮聚焦 UI 状态同步）、E2E 运行时验证（纯静态审查）。
- **统计**：P0 = 0，P1 = 4（U-1 ~ U-4），P2 = 7（U-5 ~ U-11）。
