<script setup lang="ts">
/**
 * LayerSidebar — 图层侧栏主组件（编排壳）。
 *
 * 职责：调用 composables 获取状态，将各视图委托给子组件渲染。
 * 自身仅保留：catalog 辅助函数、基础操作、滚动管理、symbology 预取。
 *
 * 拆分历史：原 2910 行 → CSS 提取(-1357) → composable 提取(-1100) → 子组件提取(-450)
 */
import { computed, nextTick, ref, watch, onMounted } from 'vue'
import { Diamond } from './ui/icons'

import { useLayerWorkspace, useLayerLifecycle, useWorkflowRun } from '../stores/layers/selectors'
import { useAuthStore } from '../stores/auth'
import type { ActiveLayerDisplay } from '../stores/layers/types'
import { deriveDataStatus, normalizeRunGroupMemberStatus } from '../utils/layer-data-status'
import { resolveCategoryDisplayName } from '../stores/layers/catalog'
import type { SidebarDragDeps, SidebarLayersDeps } from './layer-sidebar/sidebar-layers-deps'
import { useUiStore } from '../stores/ui'
import { useLogStore } from '../stores/log'
import { useTimelineActionBannerStore } from '../stores/timeline-action-banner'
import { useDrawStore } from '../stores/draw-store'
import { useOverlaySymbologyStore } from '../stores/overlay-symbology'
import { useWeatherSourcePrefsStore } from '../stores/weather-source-prefs'
import { isWeatherLayerUnsupportedByModel } from '../stores/weather-tile-manager'
import { useWeatherEngineStore } from '../stores/weather-engine'
import { LAYERS_COPY } from '../ui-copy'
import { useOnlinePlanSessionStore } from '../stores/online-plan-session'
import { useDrawSessionTransition } from '../composables/useDrawSessionTransition'

// ── Composables ───────────────────────────────────────────────────────────
import { useSidebarWeatherProviders } from './layer-sidebar/useSidebarWeatherProviders'
import { useSidebarSearch } from './layer-sidebar/useSidebarSearch'
import { useSidebarDragReorder } from './layer-sidebar/useSidebarDragReorder'
import { useSidebarSymbology } from './layer-sidebar/useSidebarSymbology'
import { useSidebarContextMenu } from './layer-sidebar/useSidebarContextMenu'

// ── 子组件 ─────────────────────────────────────────────────────────────────
import LayerSidebarHeader from './layer-sidebar/LayerSidebarHeader.vue'
import LayerSidebarLibrary from './layer-sidebar/LayerSidebarLibrary.vue'
import LayerGroupManagerDialog from './layer-sidebar/LayerGroupManagerDialog.vue'
import LayerSidebarActive from './layer-sidebar/LayerSidebarActive.vue'
import LayerSidebarContextMenu from './layer-sidebar/LayerSidebarContextMenu.vue'

const emit = defineEmits<{
  selectLayer: [instanceId: string]
  zoomToLayer: [instanceId: string]
}>()

// ── Store 设置 ──────────────────────────────────────────────────────────────
const workspace = useLayerWorkspace()
const workflowRun = useWorkflowRun()
const uiStore = useUiStore()
const logStore = useLogStore()
const onlinePlan = useOnlinePlanSessionStore()
const drawStore = useDrawStore()
const { requestInteractionMode } = useDrawSessionTransition()
const overlaySymbologyStore = useOverlaySymbologyStore()
const weatherSourcePrefs = useWeatherSourcePrefsStore()
const weatherEngine = useWeatherEngineStore()

const {
  activeLayers,
  activeLayersDisplay,
  selectedInstanceId,
  sidebarView,
  activeLayerCount,
  sidebarViewLabel,
  catalogJobStatus,
  layerLibrary,
} = workspace

const { runLayerGroups } = workflowRun

// 图层平台子系统 P1：生命周期查询（侧栏徽标数据源）
const lifecycle = useLayerLifecycle()

const layerCategories = workspace.layerCategories

// ── 图层平台 P1：分组管理入口（管理员） ────────────────────────────────────
const authStore = useAuthStore()
const groupManagerOpen = ref(false)

// ── 侧栏 composable 的 layers 窄依赖（P3 收口：不再传递整店实例）──────────
const sidebarLayersDeps: SidebarLayersDeps = {
  activeLayers,
  canRunCatalog: workspace.canRunCatalog,
  isWeatherEngineLayer: workspace.isWeatherEngineLayer,
  supportsAnalysisWorkflow: workspace.supportsAnalysisWorkflow,
  isOverlayDisplayOnlyLayer: workspace.isOverlayDisplayOnlyLayer,
  bringLayerToFront: workspace.bringLayerToFront,
  sendLayerToBack: workspace.sendLayerToBack,
  removeLayer: workspace.removeLayer,
  setLayerDisplayName: workspace.setLayerDisplayName,
  toggleLayerVisibility: workspace.toggleLayerVisibility,
  dissolveRunGroup: workflowRun.dissolveRunGroup,
  findRunGroupById: workflowRun.findRunGroupById,
  runWorkflowForCatalog: workflowRun.runWorkflowForCatalog,
}

const sidebarDragDeps: SidebarDragDeps = {
  reorderLayers: workflowRun.reorderLayers,
  moveRunGroupBlock: workflowRun.moveRunGroupBlock,
}

// ── Composable 调用 ──────────────────────────────────────────────────────────

const weatherProviders = useSidebarWeatherProviders()

const search = useSidebarSearch(
  layerLibrary,
  layerCategories,
  weatherProviders.ensureWeatherProviders,
)

const drag = useSidebarDragReorder(activeLayersDisplay, runLayerGroups, sidebarDragDeps)

const symbology = useSidebarSymbology(overlaySymbologyStore)

const ctxMenu = useSidebarContextMenu(
  activeLayersDisplay,
  runLayerGroups,
  sidebarLayersDeps,
  uiStore,
  logStore,
  overlaySymbologyStore,
  emit as (event: string, ...args: unknown[]) => void,
  selectItem,
  zoomToItem,
  removeItem,
  drag.runGroupOf,
)

// ── Catalog 辅助函数 ─────────────────────────────────────────────────────────

/** 轻量已添加集合：只读 activeLayers，避开 activeLayersDisplay */
const addedCatalogIds = computed(() => {
  const ids = new Set<string>()
  for (const layer of activeLayers.value) {
    if (!layer.isAdminBoundary) ids.add(layer.catalogId)
  }
  return ids
})

function isAdded(catalogId: string): boolean {
  return addedCatalogIds.value.has(catalogId)
}

function getCatalogJobStatus(catalogId: string): string | undefined {
  return catalogJobStatus.value.get(catalogId)
}

function getCatalogRunBlockReason(catalogId: string): string | null {
  return workspace.getCatalogRunBlockReason(catalogId)
}

function getCatalogAddBlockReason(catalogId: string): string | null {
  return workspace.getCatalogAddBlockReason(catalogId)
}

function isOverlayDisplayOnlyLayer(catalogId: string): boolean {
  return workspace.isOverlayDisplayOnlyLayer(catalogId)
}

function supportsOnlineTemporal(catalogId: string): boolean {
  return workspace.supportsOnlineTemporal(catalogId)
}

function getSourceRouteBadge(
  catalogId: string,
): { key: string; label: string; title: string } | null {
  const desc = workspace.resolveEffectiveDescriptor?.(catalogId) as {
    workflow_variants?: Record<string, { workflow_id?: string } | undefined>
  } | null
  const variants = desc?.workflow_variants
  if (!variants?.local?.workflow_id || !variants?.online?.workflow_id) return null
  const backendId = workspace.resolveBackendLayerId(catalogId)
  const pinned =
    Boolean(workflowRun.isWorkflowVariantPinned?.(backendId)) ||
    Boolean(workflowRun.isWorkflowVariantPinned?.(catalogId))
  const pref =
    workflowRun.getWorkflowVariantPreference?.(catalogId) ??
    workflowRun.getWorkflowVariantPreference?.(backendId)
  if (!pinned) {
    return {
      key: 'auto',
      label: '自动',
      title: '源路由自动：本地有数走本地，否则走在线（点击切换本地→在线→自动）',
    }
  }
  if (pref === 'online') {
    return { key: 'online', label: '在线', title: '已钉死在线（点击切回自动）' }
  }
  return { key: 'local', label: '本地', title: '已钉死本地（点击切换为在线）' }
}

function cycleSourceRoute(catalogId: string) {
  const badge = getSourceRouteBadge(catalogId)
  if (!badge) return
  const backendId = workspace.resolveBackendLayerId(catalogId)
  if (badge.key === 'auto') {
    workflowRun.setWorkflowVariantPreference(catalogId, 'local', { pinned: true })
    if (backendId !== catalogId) {
      workflowRun.setWorkflowVariantPreference(backendId, 'local', { pinned: true })
    }
  } else if (badge.key === 'local') {
    workflowRun.setWorkflowVariantPreference(catalogId, 'online', { pinned: true })
    if (backendId !== catalogId) {
      workflowRun.setWorkflowVariantPreference(backendId, 'online', { pinned: true })
    }
  } else {
    workflowRun.clearWorkflowVariantPin?.(catalogId)
    if (backendId !== catalogId) workflowRun.clearWorkflowVariantPin?.(backendId)
  }
}

function isOnlinePlanPending(catalogId: string): boolean {
  return onlinePlan.isCatalogPendingPlan(catalogId)
}

function openOnlinePlan() {
  onlinePlan.openSession()
}

// ── 图层平台子系统 P1：生命周期徽标（lifecycle 域 → 侧栏卡片） ──
const LIFECYCLE_BADGE_LABELS: Record<string, string> = {
  fresh: '资产就绪',
  stale: '资产陈旧',
  updating: '更新中',
  missing: '资产缺失',
  failed: '更新失败',
}

function getLifecycleBadge(
  catalogId: string,
): { state: string; label: string; message: string | null } | null {
  const entry = lifecycle.getLifecycle(catalogId)
  if (!entry || entry.lifecycleState === 'unknown') return null
  const label = LIFECYCLE_BADGE_LABELS[entry.lifecycleState] ?? entry.lifecycleState
  return { state: entry.lifecycleState, label, message: entry.message }
}

// ── 统一数据状态徽标（2026-08-25 UX 简化）────────────────────────────────
// 三源（availability/lifecycle/job）归并为单枚五态徽标（运行中/排队中/
// 异常/完成/旧数据），替代「数据异常/资产陈旧/失败」三枚堆叠——"资产"
// 术语对地理研究者无意义，统一语义见 utils/layer-data-status.ts。
function isStaticDataLayer(catalogId: string): boolean {
  const item = layerLibrary.value.find((l) => l.catalogId === catalogId)
  if (!item) return false
  return String(item.updateLabel || '').includes('静态') || item.supportsTime === false
}

function getUnifiedDataStatus(layer: ActiveLayerDisplay): ReturnType<typeof deriveDataStatus> {
  const badge = getLifecycleBadge(layer.catalogId)
  const job = layer.jobLayer
  const status = deriveDataStatus({
    jobStatus: job?.status ?? null,
    jobProgress: typeof job?.progress === 'number' ? job.progress : null,
    availabilityState: layer.availabilityState,
    availabilityLabel: layer.availabilityLabel,
    availabilityDescription: layer.availabilityDescription ?? null,
    lifecycleState: badge?.state ?? null,
    lifecycleMessage: badge?.message ?? null,
    isStaticLayer: isStaticDataLayer(layer.catalogId),
  })
  if (!layer.runGroupId) return status
  const group = workflowRun.runLayerGroups.value.find((g) => g.groupId === layer.runGroupId)
  return normalizeRunGroupMemberStatus(status, group?.status === 'computing')
}

// ── 添加即运行（2026-08-25 UX 简化）─────────────────────────────────────
// 点击「+ 添加」后自动完成一切：
// 1. 优先附加既有产物/缓存（成功 run 产物直接上图）
// 2. 无产物 → 自动提交工作流（内部分流：overlay→资产工作流重烘；
//    python_provider→分析运行；weather→瓦片视口按需加载），
//    轮询持续到产出或报错，终态由 poller 物化/呈现
// 3. 时间轴按需加载由 online-temporal-orchestrator 承担
async function ensureLayerDataOrRun(catalogId: string): Promise<void> {
  // 添加即切到图层独立记忆，再挂产物 / 按轴时刻开跑
  uiStore.setUnifiedTimeLock(false)
  if (uiStore.isLayerTimeLocked(catalogId)) {
    uiStore.toggleLayerTimeLock(catalogId)
  }
  // 添加后 snap / attach 会改时间轴——抑制确认卡，避免自触发
  useTimelineActionBannerStore().suppressConfirm(4_000)
  try {
    const attached = await workflowRun.autoAttachProductsForNewLayer(catalogId)
    if (attached > 0) {
      uiStore.rememberLayerTime(catalogId, { force: true })
      return // 已有缓存/数据，直接显示
    }
  } catch {
    // 附加失败不阻断自动运行（后端目录不可用等）
  }
  try {
    await workflowRun.runWorkflowForCatalog(catalogId, {})
  } catch (err) {
    // 预期内的提示性错误静默（天气瓦片提示/无引擎等）；
    // 真实运行失败由 jobLayer 失败态 + 顶栏 notice 呈现
    const message = err instanceof Error ? err.message : String(err)
    logStore.logOperation('layer-add', `图层「${catalogId}」自动运行未启动：${message}`)
  }
}

function getCatalogItem(catalogId: string) {
  return layerLibrary.value.find((item) => item.catalogId === catalogId)
}

function getCatalogSemanticNote(catalogId: string): string | null {
  // overlay 静态/时间序列图层：天然有 PNG 缓存，添加/显示路径不阻断
  if (isOverlayDisplayOnlyLayer(catalogId)) {
    return '静态叠加：已加载缓存影像'
  }
  const blockReason = getCatalogRunBlockReason(catalogId)
  if (blockReason) return blockReason
  const model = weatherEngine.defaultModel
  if (isWeatherLayerUnsupportedByModel(catalogId, model)) {
    return `当前模型（${model}）不提供该图层变量，请切换其他气象模型。`
  }
  const item = getCatalogItem(catalogId)
  if (!item) return null
  if (item.backendStatus === 'sample') {
    return (
      item.runReadinessSummary ??
      item.runReadinessNotes[0] ??
      '实验 provider 链路，可用于算法联调与验收。'
    )
  }
  if (item.backendStatus === 'placeholder') {
    return item.runReadinessSummary ?? item.runReadinessNotes[0] ?? '占位图层，默认数据源尚未接入。'
  }
  return null
}

function catalogSemanticNoteClass(catalogId: string) {
  return getCatalogItem(catalogId)?.backendStatus === 'sample'
    ? 'catalog-note-sample'
    : 'catalog-note-blocked'
}

// ── Catalog 数据源辅助 ───────────────────────────────────────────────────────

function getCatalogSources(catalogId: string) {
  return layerLibrary.value.find((l) => l.catalogId === catalogId)?.sources ?? []
}

function getPrimarySourceName(catalogId: string): string {
  const sources = getCatalogSources(catalogId)
  if (!sources.length) return LAYERS_COPY.noDataSource
  return sources[0]?.name ?? LAYERS_COPY.pleaseSelectSource
}

function getCatalogSourceSummary(catalogId: string): string {
  const sources = getCatalogSources(catalogId)
  if (!sources.length) return LAYERS_COPY.noDataSource
  return sources.map((source) => source.name).join(' / ')
}

// ── 分类辅助 ─────────────────────────────────────────────────────────────────

function getCategoryMeta(categoryId: string) {
  return layerCategories.value.find((c) => c.id === categoryId)
}

function getCategoryName(categoryId: string): string {
  return resolveCategoryDisplayName(categoryId)
}

function availabilityClass(state: string) {
  if (state === 'ready') return 'availability-ready'
  if (state === 'partial') return 'availability-partial'
  return 'availability-empty'
}

// ── 基础操作 ─────────────────────────────────────────────────────────────────

function openLibrary() {
  workspace.setSidebarView('library')
  void nextTick(() => scrollSidebarChromeIntoView())
}

function openActive() {
  workspace.setSidebarView('active')
  void nextTick(() => scrollSidebarChromeIntoView())
}

function addCatalogItem(catalogId: string, isAdminBoundary = false) {
  if (!isAdminBoundary && isAdded(catalogId)) return
  // skipAutoRun：由下方 ensureLayerDataOrRun 统一「先复用产物 / 再提交」，
  // 避免 addLayer 内置 setTimeout 再跑一遍造成双提交与游离层泄漏
  workspace.addLayer(catalogId, isAdminBoundary, undefined, { skipAutoRun: true })
  logStore.logOperation(
    'layer-add',
    `添加图层「${catalogId}」`,
    isAdminBoundary ? '行政区边界' : undefined,
  )
  // 2026-08-25 添加即运行：有缓存/产物直接附加；无则自动提交工作流
  if (catalogId !== 'gebco-dem-cn') {
    void ensureLayerDataOrRun(catalogId)
  }
}

function addAllInCategory(
  items: { catalogId: string; isAdminBoundary?: boolean; sources?: { id: string }[] }[],
) {
  const alreadyAdded = new Set(addedCatalogIds.value)
  for (const item of items) {
    if (item.isAdminBoundary) continue
    const effectiveId =
      item.sources && item.sources.length > 1 ? item.sources[0].id : item.catalogId
    if (alreadyAdded.has(effectiveId)) continue
    alreadyAdded.add(effectiveId)
    addCatalogItem(effectiveId, false)
  }
}

function showAllLayers() {
  workspace.setAllLayerVisibility(true)
}

function hideAllLayers() {
  workspace.setAllLayerVisibility(false)
}

function removeAllLayers() {
  workspace.removeAllLayers()
}

function removeItem(instanceId: string, event: MouseEvent) {
  event.stopPropagation()
  const layer = activeLayersDisplay.value.find((l) => l.instanceId === instanceId)
  const isActiveDrawLayer =
    drawStore.draftLayerId === instanceId || drawStore.editingLayerId === instanceId
  const hasUnsaved = drawStore.features.length > 0
  // 移除当前绘制/编辑图层且含未保存要素时确认，避免误删草稿
  if (isActiveDrawLayer && hasUnsaved) {
    const ok = window.confirm(
      `「${layer?.name ?? instanceId}」是当前绘制图层且包含 ${hasUnsaved ? drawStore.features.length : 0} 个未保存要素，移除后将丢失这些要素。确定移除并退出绘制模式？`,
    )
    if (!ok) return
  }
  workspace.removeLayer(instanceId)
  // 移除的是当前绘制/编辑图层时，退出绘制模式（孤儿草稿安全网会随之清空绘制 store）
  if (isActiveDrawLayer && uiStore.interactionMode === 'draw') {
    void requestInteractionMode('move')
  }
  logStore.logOperation('layer-remove', `移除图层「${layer?.name ?? instanceId}」`)
}

function selectItem(instanceId: string) {
  workspace.selectLayer(instanceId)
  emit('selectLayer', instanceId)
}

function zoomToItem(instanceId: string) {
  selectItem(instanceId)
  emit('zoomToLayer', instanceId)
}

function toggleVisibility(instanceId: string, event: MouseEvent) {
  event.stopPropagation()
  const layer = activeLayersDisplay.value.find((l) => l.instanceId === instanceId)
  workspace.toggleLayerVisibility(instanceId)
  logStore.logOperation(
    'layer-visibility',
    `${layer?.visible ? '隐藏' : '显示'}图层「${layer?.name ?? instanceId}」`,
  )
}

function toggleCategory(categoryId: string) {
  if (search.expandedCategories.value.has(categoryId)) {
    search.expandedCategories.value.delete(categoryId)
  } else {
    search.expandedCategories.value.add(categoryId)
  }
}

// ── 滚动管理 ─────────────────────────────────────────────────────────────────

const sidebarRootEl = ref<HTMLElement | null>(null)

function scrollSidebarChromeIntoView() {
  const root = sidebarRootEl.value
  if (!root) return
  root.scrollTop = 0
  const panelBody = root.closest('.panel-body') as HTMLElement | null
  if (panelBody) panelBody.scrollTop = 0
  const libraryScroll = root.querySelector('.library-scroll') as HTMLElement | null
  if (libraryScroll) libraryScroll.scrollTop = 0
  const layerList = root.querySelector('.layer-list') as HTMLElement | null
  if (layerList) layerList.scrollTop = 0
}

watch(sidebarView, () => {
  void nextTick(() => scrollSidebarChromeIntoView())
})

// ── Symbology 预取 ───────────────────────────────────────────────────────────

watch(
  activeLayersDisplay,
  (layers) => {
    for (const layer of layers) {
      if (layer.isImported || layer.isImportedRaster || layer.isAdminBoundary) continue
      if (!layer.renderHint && !overlaySymbologyStore.shouldSkipFetch(layer.catalogId)) {
        void overlaySymbologyStore.ensureMeta(layer.catalogId)
      }
    }
  },
  { flush: 'post' },
)

onMounted(() => {
  search.prefetchVisibleWeatherProviders()
})
</script>

<template>
  <aside ref="sidebarRootEl" class="panel">
    <!-- ── Header ─────────────────────────────────────────────────────── -->
    <LayerSidebarHeader
      :sidebar-view-label="sidebarViewLabel"
      :sidebar-view="sidebarView"
      :active-layer-count="activeLayerCount"
      :can-manage-groups="authStore.isAdmin"
      @open-library="openLibrary"
      @open-active="openActive"
      @open-group-manager="groupManagerOpen = true"
    />

    <!-- ── EMPTY STATE ────────────────────────────────────────────────── -->
    <div v-if="sidebarView === 'empty'" class="empty-state">
      <Diamond :size="20" class="empty-icon" aria-hidden="true" />
      <p class="empty-title">{{ LAYERS_COPY.emptyTitle }}</p>
      <p class="empty-hint">点击下方按钮打开图层库，<br />添加气象、遥感或边界图层。</p>
      <button class="empty-cta" @click="openLibrary">
        <span aria-hidden="true">+</span>
        打开图层库
      </button>
    </div>

    <!-- ── LIBRARY STATE ──────────────────────────────────────────────── -->
    <LayerSidebarLibrary
      v-else-if="sidebarView === 'library'"
      :search-query="search.searchQuery.value"
      :selected-sub-category="search.selectedSubCategory.value"
      :filtered-library-by-category="search.filteredLibraryByCategory.value"
      :research-sub-category-pills="search.researchSubCategoryPills.value"
      :expanded-categories="search.expandedCategories.value"
      :is-added="isAdded"
      :weather-providers-loading="weatherProviders.weatherProvidersLoading.value"
      :weather-source-prefs-value="(catalogId: string) => weatherSourcePrefs.getProvider(catalogId)"
      :weather-providers-for="weatherProviders.weatherProvidersFor"
      :weather-provider-option-label="weatherProviders.weatherProviderOptionLabel"
      :weather-source-quality-hint="weatherProviders.weatherSourceQualityHint"
      :weather-source-sparse-hint="weatherProviders.weatherSourceSparseHint"
      :get-catalog-job-status="getCatalogJobStatus"
      :get-catalog-run-block-reason="getCatalogRunBlockReason"
      :get-catalog-add-block-reason="getCatalogAddBlockReason"
      :is-overlay-display-only-layer="isOverlayDisplayOnlyLayer"
      :get-catalog-semantic-note="getCatalogSemanticNote"
      :catalog-semantic-note-class="catalogSemanticNoteClass"
      :get-category-meta="getCategoryMeta"
      :get-category-name="getCategoryName"
      :get-catalog-source-summary="getCatalogSourceSummary"
      :get-primary-source-name="getPrimarySourceName"
      :supports-online-temporal="supportsOnlineTemporal"
      @update:search-query="search.searchQuery.value = $event"
      @update:selected-sub-category="search.selectedSubCategory.value = $event"
      @ensure-weather-providers="weatherProviders.ensureWeatherProviders"
      @on-weather-source-change="weatherProviders.onWeatherSourceChange"
      @add-all-in-category="addAllInCategory"
      @add-catalog-item="addCatalogItem"
      @toggle-category="toggleCategory"
    />

    <!-- ── ACTIVE STATE ───────────────────────────────────────────────── -->
    <LayerSidebarActive
      v-else-if="sidebarView === 'active'"
      :active-layers-display="activeLayersDisplay"
      :active-toc-rows="drag.activeTocRows.value"
      :selected-instance-id="selectedInstanceId"
      :drag-over-instance-id="drag.dragOverInstanceId.value"
      :drag-over-group-id="drag.dragOverGroupId.value"
      :run-group-of="drag.runGroupOf"
      :group-status-label="drag.groupStatusLabel"
      :has-color-symbology="symbology.hasColorSymbology"
      :get-color-ramp-style="symbology.getColorRampStyle"
      :get-symbology-unit="symbology.getSymbologyUnit"
      :get-symbology-vmin="symbology.getSymbologyVmin"
      :get-symbology-vmax="symbology.getSymbologyVmax"
      :availability-class="availabilityClass"
      :get-category-name="getCategoryName"
      :supports-online-temporal="supportsOnlineTemporal"
      :get-source-route-badge="getSourceRouteBadge"
      :cycle-source-route="cycleSourceRoute"
      :get-unified-data-status="getUnifiedDataStatus"
      :is-online-plan-pending="isOnlinePlanPending"
      :open-online-plan="openOnlinePlan"
      @select-item="selectItem"
      @zoom-to-item="zoomToItem"
      @toggle-visibility="toggleVisibility"
      @remove-item="removeItem"
      @open-job-report="ctxMenu.openJobReport"
      @show-all-layers="showAllLayers"
      @hide-all-layers="hideAllLayers"
      @remove-all-layers="removeAllLayers"
      @open-library="openLibrary"
      @on-drag-start="drag.onDragStart"
      @on-group-drag-start="drag.onGroupDragStart"
      @on-drag-over="drag.onDragOver"
      @on-group-drag-over="drag.onGroupDragOver"
      @on-drop="drag.onDrop"
      @on-group-drop="drag.onGroupDrop"
      @on-drag-end="drag.onDragEnd"
      @on-layer-context-menu="ctxMenu.onLayerContextMenu"
      @on-group-context-menu="ctxMenu.onGroupContextMenu"
    />

    <!-- ── Footer ─────────────────────────────────────────────────────── -->
    <p class="panel-footnote">
      <template v-if="sidebarView === 'active'">{{ LAYERS_COPY.footerActive }}</template>
      <template v-else-if="sidebarView === 'library'">选择图层添加到地图</template>
      <template v-else></template>
    </p>

    <!-- ── 右键上下文菜单 ──────────────────────────────────────────────── -->
    <LayerSidebarContextMenu
      :context-menu="ctxMenu.contextMenu.value"
      :context-menu-groups="ctxMenu.contextMenuGroups.value"
      @handle-context-action="ctxMenu.handleContextAction"
    />
    <!-- ── 图层平台 P1：分组管理对话框（仅管理员） ─────────────────────── -->
    <LayerGroupManagerDialog
      v-if="authStore.isAdmin"
      :open="groupManagerOpen"
      @close="groupManagerOpen = false"
    />
  </aside>
</template>

<style scoped src="./layer-sidebar/LayerSidebar.styles.css"></style>
