# 全局工作流状态指示器与综合面板

## Summary

在标题栏（ModeToolbar）添加一个工作流状态指示按钮，用颜色表示当前所有工作流的整体状态（空闲/运行中/成功/失败）。点击按钮打开一个全屏覆盖的综合工作流状态面板，展示所有 job layers 的详细状态、进度、错误信息和操作入口。面板作为独立新文件创建，为后续扩展丰富功能预留空间。

## Current State Analysis

### 标题栏结构（ModeToolbar.vue）
- `.toolbar` 为 flex 容器，左侧 `.brand`，右侧 `.toolbar-main`
- `.toolbar-main` 包含两个 `.toolbar-strip`：
  - 第一个 strip：style tabs、source selector、screenshot button、quick-stats
  - 第二个 strip：status chips（2D-first、图层名、可用性、图层数量、警告）
- 现有按钮样式参考 `.screenshot-btn`（inline-flex, border, rounded pill, 0.62rem font）

### 模态弹窗模式（ScreenshotExport.vue）
- `position: fixed; z-index: 999;` 全屏覆盖
- `@click.self="emit('close')"` 点击背景关闭
- 内部 `.screenshot-panel` 为内容容器
- 由父组件 `ref(false)` + `v-if` 控制

### Store 工作流状态数据（stores/layers/index.ts）
- `jobLayers: ref<JobLayerItem[]>` — 所有作业层数据
- `JobLayerItem.status: JobStatus` — `'running' | 'succeeded' | 'failed' | 'queued' | 'cancelled' | 'retry_pending'`
- `JobLayerItem.progress: number` — 0-100
- `JobLayerItem.jobId, name, message, createdAt, updatedAt, diagnosticNotes, eventMessages`
- `isSubmitting: computed` — 是否有工作流正在提交
- `workflowError: ref<string | null>` — 最近错误
- `activeWorkflowCatalogIds: Set<string>` — 正在轮询的 catalogId
- **不存在全局工作流状态汇总计算属性** — 需新增

### Store 导出（index.ts L1647-1700）
- 已导出 `jobLayers`, `isSubmitting`, `workflowError`
- 已导出 actions: `cancelWorkflowRunForJob`, `retryWorkflowRunForJob`

## Proposed Changes

### 1. 新增 Store 计算属性 `workflowSummary`

**文件**: `Code/frontend/src/stores/layers/index.ts`

在 store setup 函数内（约 L610 附近，`isSubmitting` 之后）添加计算属性：

```typescript
export interface WorkflowSummary {
  total: number
  running: number
  queued: number
  succeeded: number
  failed: number
  cancelled: number
  retryPending: number
  /** 整体状态：idle | active | succeeded | failed | mixed */
  overall: 'idle' | 'active' | 'succeeded' | 'failed' | 'mixed'
  /** 用于按钮配色的状态键 */
  tone: 'idle' | 'active' | 'success' | 'warning' | 'error'
  hasError: boolean
}

const workflowSummary = computed<WorkflowSummary>(() => {
  const layers = jobLayers.value
  if (layers.length === 0) {
    return { total: 0, running: 0, queued: 0, succeeded: 0, failed: 0, cancelled: 0, retryPending: 0, overall: 'idle', tone: 'idle', hasError: false }
  }
  const counts = { running: 0, queued: 0, succeeded: 0, failed: 0, cancelled: 0, retryPending: 0 }
  for (const layer of layers) {
    if (layer.status in counts) counts[layer.status as keyof typeof counts]++
  }
  const active = counts.running + counts.queued + counts.retryPending
  let overall: WorkflowSummary['overall'] = 'idle'
  let tone: WorkflowSummary['tone'] = 'idle'
  if (active > 0) {
    overall = 'active'
    tone = 'active'
  } else if (counts.failed > 0 && counts.succeeded > 0) {
    overall = 'mixed'
    tone = 'warning'
  } else if (counts.failed > 0) {
    overall = 'failed'
    tone = 'error'
  } else if (counts.succeeded > 0) {
    overall = 'succeeded'
    tone = 'success'
  }
  return {
    total: layers.length,
    ...counts,
    retryPending: counts.retryPending,
    overall,
    tone,
    hasError: !!workflowError.value || counts.failed > 0,
  }
})
```

在 return 语句中导出 `workflowSummary`。

同时导出接口 `WorkflowSummary` 供组件使用（从 types.ts 或直接从 store 导出）。

### 2. 创建 WorkflowStatusButton.vue（标题栏按钮）

**文件**: `Code/frontend/src/components/workflow/WorkflowStatusButton.vue`（新建）

按钮组件，参考 `.screenshot-btn` 样式，显示工作流整体状态：

- **props**: `summary: WorkflowSummary`
- **emit**: `click`
- **显示**: 一个彩色圆点 + 文字（如 "工作流" 或计数），颜色随 `tone` 变化
- **tone → 颜色映射**:
  - `idle`: `#6e8ba0`（灰蓝，静态）
  - `active`: `#5ad5ff`（亮蓝，运行中，带脉冲动画）
  - `success`: `#9ff8cf`（绿，全部成功）
  - `warning`: `#ffd38a`（橙，部分失败）
  - `error`: `#ff8a8a`（红，全部失败）
- 运行中时圆点有 `pulse` 动画（CSS keyframes）
- 按钮样式与 `.screenshot-btn` 一致（inline-flex, border, rounded pill）

### 3. 创建 WorkflowStatusPanel.vue（综合状态面板）

**文件**: `Code/frontend/src/components/workflow/WorkflowStatusPanel.vue`（新建）

全屏覆盖面板，参考 ScreenshotExport.vue 的模态模式：

- **props**: 无（直接从 store 读取数据）
- **emit**: `close`
- **布局**:
  - 顶部：标题 "工作流状态总览" + 关闭按钮
  - 汇总区：6 个状态计数卡片（运行中/排队/成功/失败/已取消/重试等待）+ 错误提示
  - 列表区：每个 `jobLayer` 一行，显示：
    - 图层名称（`name`）
    - 状态 chip（颜色对应 status）
    - 进度条（`progress`，仅 running 时显示）
    - 更新时间（`updatedAt`）
    - 消息（`message`）
    - 诊断摘要（`diagnosticNotes` 前 2 条）
    - 操作按钮：取消（running/queued 时）、重试（failed/cancelled 时）
  - 空状态：`jobLayers` 为空时显示提示
- **样式**: 与项目一致的深色玻璃态（`backdrop-filter: blur(18px)`，深色背景，蓝色边框）
- **交互**:
  - 点击背景 `@click.self="emit('close')"` 关闭
  - ESC 键关闭
  - 取消/重试调用 `layersStore.cancelWorkflowRunForJob` / `retryWorkflowRunForJob`

### 4. 集成到 ModeToolbar.vue

**文件**: `Code/frontend/src/components/ModeToolbar.vue`

- 新增 import `WorkflowStatusButton` 和 `useLayersStore`
- 新增 `storeToRefs(layersStore)` 获取 `workflowSummary`
- 新增 emit `openWorkflowStatus`
- 在模板第一个 `.toolbar-strip` 中，screenshot button 之后、quick-stats 之前插入：
  ```html
  <WorkflowStatusButton
    :summary="workflowSummary"
    @click="emit('openWorkflowStatus')"
  />
  ```

### 5. 集成到 DashboardView.vue

**文件**: `Code/frontend/src/views/DashboardView.vue`

- 新增 import `WorkflowStatusPanel`
- 新增 `const workflowStatusOpen = ref(false)`
- ModeToolbar 添加 `@open-workflow-status="() => workflowStatusOpen = true"`
- 在 ScreenshotExport 旁边添加：
  ```html
  <WorkflowStatusPanel
    v-if="workflowStatusOpen"
    @close="workflowStatusOpen = false"
  />
  ```

## Assumptions & Decisions

1. **按钮位置**：放在第一个 toolbar-strip（与截图按钮同排），而非第二个 status row，因为第一个 strip 更稳定可见（会 wrap 但不会 overflow hidden）
2. **面板作为独立文件**：用户明确要求创建新文件，便于后续扩展（如历史趋势、队列详情、API 健康检查等）
3. **组件目录**：新建 `components/workflow/` 子目录，与 `components/info-panel/` 模式一致
4. **数据源**：直接从 `useLayersStore()` 读取，不通过 props 透传（面板作为全局状态查看器，数据源唯一）
5. **配色**：复用现有 `.availability-ready/partial/empty` 的色调体系，保持视觉一致
6. **不引入第三方 modal 库**：项目无 UI 组件库依赖，沿用 ScreenshotExport 的原生 fixed overlay 模式

## Verification Steps

1. **TypeScript 编译检查**：`cd Code/frontend && npx vue-tsc --noEmit` 无错误
2. **视觉检查**：
   - 标题栏按钮与截图按钮对齐，颜色随工作流状态变化
   - 运行中时有脉冲动画
   - 点击按钮打开面板，面板覆盖全屏，背景模糊
   - 面板内每个 job layer 行信息完整
   - 取消/重试按钮可点击且状态正确
3. **功能检查**：
   - 无工作流时按钮灰色，面板显示空状态
   - 有工作流运行时按钮蓝色脉冲
   - 工作流失败时按钮红色
   - ESC 键和背景点击关闭面板
4. **响应式检查**：面板在窄屏（<820px）下正常显示
