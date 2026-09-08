# X1/D2 阶段三B 执行蓝图：workflow-runner.ts 抽离

> 状态：**设计就绪，待专注执行**（2026-08-08 制定）
> 前置：阶段三A（workflow-poller.ts）已完成并推送（`e62de01`）
> 目标：将提交/取消/重试 + 恢复编排从 `stores/layers/index.ts` 抽离为 `workflow-runner.ts` slice

## 1. 范围与归属

从 index.ts 移入 `workflow-runner.ts`（~1000 行，当前行号为三A 完成后）：

| 函数 | 行号(约) | 职责 |
|------|---------|------|
| `restoreActiveWorkflows` | 2152 | 恢复主流程（启动/刷新时） |
| `registerExternalWorkflowRun` | 2093 | 外部触发 run 注册+启动轮询 |
| `resolveRestoredCatalogId` | 2115 | 恢复 run 的 catalog 推断 |
| `hydrateJobLayerFromEvents` | 2137 | 事件→jobLayer 水合 |
| `resolveRestoreWorkflowBridge` | 2350 | 恢复桥接（调 restore-workflow-bridge.ts） |
| `ensureRestoredRunGroup` | 2414 | 恢复时确保 run group 存在 |
| `interruptWorkflowForCatalog` | 2476 | 中断旧提交（清 429 定时器+取消） |
| `runWorkflowForCatalog` | 2499 | **提交主流程（270 行）** |
| `scheduleWorkflowRetry` | 2769 | 429 容量自动重试 |
| `cancelWorkflowRunForJob` | 2802 | 取消 |
| `retryWorkflowRunForJob` | 2844 | 重试 |
| tracked runs helpers | 223-258 / 1595-1640 | loadTrackedWorkflowRuns / saveTrackedWorkflowRuns / rememberTrackedWorkflowRun / forgetTrackedWorkflowRun |

**保留在 index.ts**（store 状态本身 + 被多处共享的写函数）：`activeLayers`/`jobLayers`/`runLayerGroups` 等 ref、`upsertJobLayer`、`syncJobLayerToActiveLayer`、`updateRunGroupForCatalog`、`addLayer`、`scheduleWorkspacePersist`、`cleanupUnproducedRunLayers`。

## 2. 模块骨架

```ts
// layers/workflow-runner.ts
import type { ... } from './types'
import { createWorkflowPoller } from './workflow-poller'  // 仅类型参考，实例由 store 传入

export interface WorkflowRunnerDeps {
  // ── poller（三A 产物，store 实例化后传入方法）──
  startPolling: (jobId: string, catalogId: string, epoch?: number) => void
  stopWorkflowPolling: (jobId: string) => void
  isPolling: (jobId: string) => boolean
  syncWorkflowRunSnapshot: (jobId: string, catalogId: string, force?: boolean, epoch?: number) => Promise<boolean>

  // ── 状态读（getter，避免直接持有 ref）──
  getActiveLayers: () => ActiveLayer[]
  getJobLayers: () => JobLayerItem[]
  getRunLayerGroups: () => ActiveRunLayerGroup[]
  getRuntimeLayerCatalog: () => Record<string, RuntimeLayerDescriptor>
  getCurrentHour: () => number
  getMapCenter: () => { lng: number; lat: number }
  getMapZoom: () => number
  getMapBBox: () => BoundingBox | null
  getSubmittingIds: () => Set<string>
  getActiveCatalogIds: () => Set<string>

  // ── 状态写（store 写函数注入）──
  upsertJobLayer: (catalogId: string, jobLayer: JobLayerItem) => void
  removeJobLayerById: (jobId: string) => void
  setWorkflowError: (msg: string | null) => void
  addLayer: (catalogId: string, visible?: boolean, jobLayer?: JobLayerItem) => void
  updateRunGroupForCatalog: (catalogId: string, jobLayer: JobLayerItem) => void
  cleanupUnproducedRunLayers: (runId: string) => void
  scheduleWorkspacePersist: () => void

  // ── 业务判定 / 载荷构建（store 内既有函数注入）──
  isTerminalStatus: (s: string) => boolean
  isLocalSubmitJobId: (id: string) => boolean
  isRunDismissed: (runId: string) => boolean
  forgetDismissedLayer: (q: { runId: string }) => void
  isWeatherEngineLayer: (catalogId: string) => boolean
  getRuntimeLayerDescriptor: (catalogId: string) => RuntimeLayerDescriptor | null
  getCatalogDisplayName: (catalogId: string) => string
  getCatalogRunBlockReason: (catalogId: string) => string | null
  supportsAnalysisWorkflow: (catalogId: string) => boolean
  supportsMapLayerResult: (catalogId: string) => boolean
  resolveBackendLayerId: (catalogId: string) => string
  buildWorkflowPayloadForCatalog: (...args) => unknown
  weatherProviderArg: (catalogId: string) => string
  emitWorkflowProgressTimeSeek: (...) => void
  attachAlgorithmProductOverlays: (refs, catalogId, runId?, opts?) => Promise<number>
  claimOrphanWorkflowRun: (...) => unknown
  isSubmitTimeoutError: (e: unknown) => boolean
  resolveRestoreWorkflowBridgeFromCatalog: (...) => unknown
  normalizeWorkflowProgress: (p?: number, detail?) => number
  debugLog: (module: string, ...args: unknown[]) => void

  // ── 快照恢复（workspace-persist / 快照水合）──
  hydrateWorkspaceFromSnapshot: () => Map<string, string>
  hydrateVectorLayersFromSnapshot: (m: Map<string, string>) => Promise<void>
  reconcileOmegaBlockLayers: () => void

  // ── API（services/runtime-api，直接 import 或注入）──
  // listActiveWorkflowRuns / listRecentSucceededRuns / submitWorkflow /
  // cancelWorkflowRun / retryWorkflowRun / materializeWorkflowMapLayers /
  // getWorkflowRun / getWorkflowEvents —— 建议直接 import（无 store 依赖）
}

export function createWorkflowRunner(deps: WorkflowRunnerDeps) {
  // tracked runs helpers（loadTrackedWorkflowRuns 等）随模块移入，
  // localStorage key TRACKED_RUNS_STORAGE_KEY 一并移入
  // ... 恢复簇 + 提交簇函数体（从 index.ts 平移，内部调用改 deps.xxx）
  return {
    restoreActiveWorkflows,
    registerExternalWorkflowRun,
    runWorkflowForCatalog,
    cancelWorkflowRunForJob,
    retryWorkflowRunForJob,
    interruptWorkflowForCatalog,
    scheduleWorkflowRetry,
    // 内部辅助不导出：resolveRestoredCatalogId / hydrateJobLayerFromEvents /
    //   resolveRestoreWorkflowBridge / ensureRestoredRunGroup / tracked helpers
  }
}
```

## 3. 接线要点（index.ts）

1. **实例化顺序**：`workflowPoller`（三A）→ `workflowRunner`（deps 传 `workflowPoller.startPolling` 等）。runner 必须在 poller 之后创建。
2. **状态 getter**：runner 不持有 ref，经 `getActiveLayers: () => activeLayers.value` 等注入，避免响应式断裂。
3. **写函数**：`upsertJobLayer` 等保留在 store（它们操作多状态 + tracked + persist），runner 经 deps 调用。
4. **tracked runs helpers**：`loadTrackedWorkflowRuns`/`saveTrackedWorkflowRuns` 是顶层纯 localStorage 函数（223-258 行），随 runner 移入；`rememberTrackedWorkflowRun`/`forgetTrackedWorkflowRun`（1595-1640）依赖 runLayerGroups/activeLayers，改为 deps 注入读接口。
5. **函数互相调用**：runner 内部函数相互调用直接用本地引用（同模块）；跨到 poller 用 deps.startPolling。
6. **导出接口不变**：index.ts `return {}` 中 `runWorkflowForCatalog` 等名字经解构 runner 保持。

## 4. 分步验证计划

- **B-1**：先移恢复簇（restoreActiveWorkflows + registerExternal + resolve* + hydrate + ensureRestoredRunGroup + tracked helpers），提交簇暂留 index.ts → tsc + vitest 516 验证
- **B-2**：再移提交簇（runWorkflowForCatalog + interrupt + scheduleRetry + cancel + retry）→ tsc + vitest 516 验证
- 每步独立 commit，便于回滚定位

## 5. 风险提示

- `runWorkflowForCatalog` 含乐观提交（localSubmitJobId）+ 429 重试 + 超时认领（claimOrphanWorkflowRun）三条支路，平移时勿改条件分支顺序。
- `restoreActiveWorkflows` 的「succeededByWorkflow 僵尸压制」逻辑（2172-2206）是用户近期 bug 修复（9c5c9af/55ec64d），平移保持原样。
- 全部用 `function` 声明的 store 函数有提升，deps 注入可用；`const x = () =>` 箭头函数（如 slice 解构出的）必须在其实例化之后才能引用——runner 实例化放最后。
