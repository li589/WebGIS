<script setup lang="ts">
import { computed, nextTick, ref, watch, onMounted, onUnmounted } from 'vue'
import { storeToRefs } from 'pinia'

import { useLayersStore } from '../stores/layers'
import { useUiStore } from '../stores/ui'
import { useLogStore } from '../stores/log'
import type { RuntimeLayerLibraryItem, WeatherLayerRenderHint } from '../stores/layers/types'
import { buildWeatherLegendGradient, resolveSymbologyColors } from './map/layer-symbology'
import { resolveEffectiveLayerSymbology } from './map/effective-layer-symbology'
import { useOverlaySymbologyStore } from '../stores/overlay-symbology'
import { useWeatherSourcePrefsStore } from '../stores/weather-source-prefs'
import { isWeatherLayerUnsupportedByModel } from '../stores/weather-tile-manager'
import { useWeatherEngineStore } from '../stores/weather-engine'
import { getWeatherProvidersForLayer, type WeatherProviderForLayer } from '../services/runtime-api'
import { LAYERS_COPY, INSPECT_COPY } from '../ui-copy'
import { ORG_LABEL } from '../ui-copy/brand'
import { openDataWorkspace, openDatedExportForLayer } from '../data-manager/core/workspace-store'
import { exportLayer } from '../data-manager/adapters/export'
import {
  buildLayerContextMenu,
  buildGroupContextMenu,
  type LayerContextActionId,
} from './layer-sidebar/layer-context-menu'

const emit = defineEmits<{
  selectLayer: [instanceId: string]
  zoomToLayer: [instanceId: string]
}>()

const layersStore = useLayersStore()
const uiStore = useUiStore()
const logStore = useLogStore()
const overlaySymbologyStore = useOverlaySymbologyStore()
const weatherSourcePrefs = useWeatherSourcePrefsStore()
const weatherEngine = useWeatherEngineStore()
const orgLabel = ORG_LABEL

const weatherProvidersCache = ref<Record<string, WeatherProviderForLayer[]>>({})
const weatherProvidersLoading = ref<Record<string, boolean>>({})

async function ensureWeatherProviders(catalogId: string) {
  if (weatherProvidersCache.value[catalogId] || weatherProvidersLoading.value[catalogId]) return
  weatherProvidersLoading.value = { ...weatherProvidersLoading.value, [catalogId]: true }
  try {
    const res = await getWeatherProvidersForLayer(catalogId, { includeDisabled: true })
    const providers = res.providers ?? []
    weatherProvidersCache.value = {
      ...weatherProvidersCache.value,
      [catalogId]: providers,
    }
    // 与 InfoPanel 一致：禁用/未知钉源回退 auto，避免瓦片 503
    const pref = weatherSourcePrefs.getProvider(catalogId)
    if (pref && pref !== 'auto') {
      const match = providers.find((p) => p.provider_id === pref)
      if (!match || !match.enabled) {
        layersStore.applyWeatherProviderPreference(catalogId, 'auto')
      }
    }
  } catch (error) {
    logStore.logOperation(
      'warn',
      `天气源列表加载失败 (${catalogId}): ${error instanceof Error ? error.message : String(error)}`,
    )
    weatherProvidersCache.value = { ...weatherProvidersCache.value, [catalogId]: [] }
  } finally {
    weatherProvidersLoading.value = { ...weatherProvidersLoading.value, [catalogId]: false }
  }
}

function weatherProvidersFor(catalogId: string): WeatherProviderForLayer[] {
  return weatherProvidersCache.value[catalogId] ?? []
}

function onWeatherSourceChange(catalogId: string, value: string) {
  layersStore.applyWeatherProviderPreference(catalogId, value || 'auto')
}

function weatherSourceSparseHint(catalogId: string): boolean {
  const pref = weatherSourcePrefs.getProvider(catalogId)
  if (!pref || pref === 'auto') return false
  const row = weatherProvidersFor(catalogId).find((p) => p.provider_id === pref)
  return row?.grid_mode === 'sparse' || row?.data_quality === 'sparse'
}

function weatherSourceQualityHint(catalogId: string): string | null {
  const pref = weatherSourcePrefs.getProvider(catalogId)
  if (!pref || pref === 'auto') return null
  const row = weatherProvidersFor(catalogId).find((p) => p.provider_id === pref)
  if (!row?.hint) return null
  if (row.data_quality === 'observed') return null
  return row.hint
}

function weatherProviderOptionLabel(p: WeatherProviderForLayer): string {
  const bits = [p.display_name]
  if (!p.enabled) bits.push('（未启用）')
  if (p.data_quality === 'extrapolated') bits.push(' · 外推')
  else if (p.data_quality === 'sparse' || p.grid_mode === 'sparse') bits.push(' · 稀疏')
  return bits.join('')
}

// Use storeToRefs only for reactive state
const {
  activeLayers,
  activeLayersDisplay,
  runLayerGroups,
  selectedInstanceId,
  sidebarView,
  activeLayerCount,
  sidebarViewLabel,
  catalogJobStatus,
  layerLibrary,
} = storeToRefs(layersStore)

const layerCategories = layersStore.layerCategories

const searchQuery = ref('')
const expandedCategories = ref<Set<string>>(new Set(layerCategories.map((c) => c.id)))
const draggedInstanceId = ref<string | null>(null)
const draggedGroupId = ref<string | null>(null)
const dragOverInstanceId = ref<string | null>(null)
const dragOverGroupId = ref<string | null>(null)
/** 侧栏根节点：切换视图时滚回顶部，避免页签滚出视口后「点不动」 */
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

// ── Filter library items by search ────────────────────────────────────────────

const selectedSubCategory = ref<string>('all')

const filteredLibrary = computed(() => {
  if (!searchQuery.value.trim()) return layerLibrary.value
  const q = searchQuery.value.toLowerCase()
  return layerLibrary.value.filter(
    (item) =>
      item.name.toLowerCase().includes(q) ||
      item.category.toLowerCase().includes(q) ||
      (item.subCategory && item.subCategory.toLowerCase().includes(q)) ||
      item.sourceLabel.toLowerCase().includes(q) ||
      item.description.toLowerCase().includes(q),
  )
})

/** 二级分类 pills：从当前可见图层的 subCategory 去重生成（保留「全部」） */
const researchSubCategoryPills = computed(() => {
  const values = new Set<string>()
  for (const item of filteredLibrary.value) {
    if (item.category === 'research-group' && item.subCategory?.trim()) {
      values.add(item.subCategory.trim())
    }
  }
  return ['all', ...Array.from(values).sort((a, b) => a.localeCompare(b, 'zh-CN'))]
})

watch(researchSubCategoryPills, (pills) => {
  if (!pills.includes(selectedSubCategory.value)) {
    selectedSubCategory.value = 'all'
  }
})

const filteredLibraryByCategory = computed(() => {
  const map = new Map(
    layerCategories.map((c) => [c.id, { category: c, items: [] as RuntimeLayerLibraryItem[] }]),
  )
  for (const item of filteredLibrary.value) {
    if (map.has(item.category)) {
      if (
        item.category === 'research-group' &&
        selectedSubCategory.value !== 'all' &&
        item.subCategory !== selectedSubCategory.value
      ) {
        continue
      }
      map.get(item.category)!.items.push(item)
    }
  }
  return Array.from(map.values()).filter((g) => {
    if (g.category.id === 'research-group') return true
    return g.items.length > 0
  })
})

function prefetchVisibleWeatherProviders() {
  for (const group of filteredLibraryByCategory.value) {
    if (group.category.id !== '气象场') continue
    for (const item of group.items) {
      void ensureWeatherProviders(item.catalogId)
    }
  }
}

watch(filteredLibraryByCategory, () => prefetchVisibleWeatherProviders(), { deep: true })

// ── Check if layer already added ───────────────────────────────────────────────
/** 轻量已添加集合：只读 activeLayers，避开 activeLayersDisplay（含瓦片 stats，风场加载时会卡住） */
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

/** 获取 catalogId 对应的工作流状态（用于 library 卡片自动运行反馈） */
function getCatalogJobStatus(catalogId: string): string | undefined {
  return catalogJobStatus.value.get(catalogId)
}

function getCatalogRunBlockReason(catalogId: string): string | null {
  return layersStore.getCatalogRunBlockReason(catalogId)
}

function getCatalogItem(catalogId: string) {
  return layerLibrary.value.find((item) => item.catalogId === catalogId)
}

function getCatalogSemanticNote(catalogId: string): string | null {
  const blockReason = getCatalogRunBlockReason(catalogId)
  if (blockReason) return blockReason
  // 模型 × 图层 结构性不支持（如 visibility × ecmwf_ifs025）：目录直接标注，
  // 与瓦片链路的 data-empty 短路同一语义
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

// ── Actions ───────────────────────────────────────────────────────────────────

function openLibrary() {
  layersStore.setSidebarView('library')
  void nextTick(() => scrollSidebarChromeIntoView())
}

function openActive() {
  // 显式切到已添加列表；即使当前已是 active 也再写一次，并滚回页签可见区
  layersStore.setSidebarView('active')
  void nextTick(() => scrollSidebarChromeIntoView())
}

function addCatalogItem(catalogId: string, isAdminBoundary = false) {
  if (!isAdminBoundary && isAdded(catalogId)) {
    return
  }
  // 天气图层由 tile manager 按需拉取瓦片，不再自动提交 analysis workflow
  layersStore.addLayer(catalogId, isAdminBoundary)
  logStore.logOperation(
    'layer-add',
    `添加图层「${catalogId}」`,
    isAdminBoundary ? '行政区边界' : undefined,
  )
}

/**
 * 批量添加某分类下所有未添加的图层。
 * 关键：在循环前一次性快照已添加的 catalogId 集合，避免在每次 addLayer 后
 * 重新求值 activeLayersDisplay 计算属性（它会对每个天气图层调用
 * weatherTileManager.getStats()，在紧密循环中会导致明显的卡顿）。
 */
function addAllInCategory(items: { catalogId: string; isAdminBoundary?: boolean }[]) {
  const alreadyAdded = new Set(addedCatalogIds.value)

  for (const item of items) {
    if (item.isAdminBoundary) continue
    if (alreadyAdded.has(item.catalogId)) continue
    alreadyAdded.add(item.catalogId)
    addCatalogItem(item.catalogId, false)
  }
}

/** 批量显示所有图层 */
function showAllLayers() {
  layersStore.setAllLayerVisibility(true)
}

/** 批量隐藏所有图层 */
function hideAllLayers() {
  layersStore.setAllLayerVisibility(false)
}

/** 批量移除所有图层 */
function removeAllLayers() {
  layersStore.removeAllLayers()
}

function removeItem(instanceId: string, event: MouseEvent) {
  event.stopPropagation()
  const layer = activeLayersDisplay.value.find((l) => l.instanceId === instanceId)
  layersStore.removeLayer(instanceId)
  logStore.logOperation('layer-remove', `移除图层「${layer?.name ?? instanceId}」`)
}

function selectItem(instanceId: string) {
  layersStore.selectLayer(instanceId)
  emit('selectLayer', instanceId)
}

function zoomToItem(instanceId: string) {
  selectItem(instanceId)
  emit('zoomToLayer', instanceId)
}

function zoomToLayerFromMenu() {
  if (!contextMenu.value?.instanceId) return
  const id = contextMenu.value.instanceId
  zoomToItem(id)
  closeContextMenu()
}

function openJobReport(instanceId: string) {
  // 先请求滚动目标，再选中图层，避免 InfoPanel 默认滚到「当前对象」盖住报告区
  uiStore.requestAnalysisFocus(['report-section', 'result-section', 'scheduler-status'])
  selectItem(instanceId)
}

function toggleVisibility(instanceId: string, event: MouseEvent) {
  event.stopPropagation()
  const layer = activeLayersDisplay.value.find((l) => l.instanceId === instanceId)
  layersStore.toggleLayerVisibility(instanceId)
  logStore.logOperation(
    'layer-visibility',
    `${layer?.visible ? '隐藏' : '显示'}图层「${layer?.name ?? instanceId}」`,
  )
}

function toggleCategory(categoryId: string) {
  if (expandedCategories.value.has(categoryId)) {
    expandedCategories.value.delete(categoryId)
  } else {
    expandedCategories.value.add(categoryId)
  }
}

// ── Drag to reorder ────────────────────────────────────────────────────────────

type ActiveTocRow =
  | { kind: 'group'; groupId: string; key: string }
  | {
      kind: 'layer'
      layer: (typeof activeLayersDisplay.value)[number]
      key: string
      indented: boolean
    }

/** 组头 + 缩进成员的 Active TOC 行 */
const activeTocRows = computed<ActiveTocRow[]>(() => {
  const rows: ActiveTocRow[] = []
  const seen = new Set<string>()
  for (const layer of activeLayersDisplay.value) {
    if (layer.runGroupId && !seen.has(layer.runGroupId)) {
      seen.add(layer.runGroupId)
      rows.push({ kind: 'group', groupId: layer.runGroupId, key: `g-${layer.runGroupId}` })
    }
    rows.push({
      kind: 'layer',
      layer,
      key: layer.instanceId,
      indented: Boolean(layer.runGroupId),
    })
  }
  return rows
})

function runGroupOf(groupId: string) {
  return runLayerGroups.value.find((g) => g.groupId === groupId) ?? null
}

function groupStatusLabel(groupId: string): string {
  const g = runGroupOf(groupId)
  if (!g) return ''
  if (g.status === 'computing') {
    if (g.message) return g.message
    return `${LAYERS_COPY.computingGroupBusy}${typeof g.progress === 'number' ? ` ${g.progress}%` : ''}`
  }
  if (g.status === 'ready') return LAYERS_COPY.computingGroupReady
  if (g.status === 'failed') return '失败'
  if (g.status === 'cancelled') return '已取消'
  return g.status
}

function onDragStart(instanceId: string) {
  draggedInstanceId.value = instanceId
  draggedGroupId.value = null
}

function onGroupDragStart(groupId: string, event: DragEvent) {
  event.stopPropagation()
  draggedGroupId.value = groupId
  draggedInstanceId.value = null
}

function onDragOver(instanceId: string, event: DragEvent) {
  event.preventDefault()
  dragOverInstanceId.value = instanceId
  dragOverGroupId.value = null
}

function onGroupDragOver(groupId: string, event: DragEvent) {
  event.preventDefault()
  dragOverGroupId.value = groupId
  dragOverInstanceId.value = null
}

function onDrop(targetInstanceId: string) {
  if (draggedGroupId.value) {
    const group = runGroupOf(draggedGroupId.value)
    const target = activeLayersDisplay.value.find((l) => l.instanceId === targetInstanceId)
    if (group && target && target.runGroupId !== draggedGroupId.value) {
      const sorted = activeLayersDisplay.value
      const groupMembers = new Set(group.memberInstanceIds)
      const firstMember = sorted.find((l) => groupMembers.has(l.instanceId))
      const targetIdx = sorted.findIndex((l) => l.instanceId === targetInstanceId)
      const firstIdx = firstMember
        ? sorted.findIndex((l) => l.instanceId === firstMember.instanceId)
        : -1
      const placeAfter = firstIdx >= 0 ? targetIdx < firstIdx : true
      layersStore.moveRunGroupBlock(draggedGroupId.value, targetInstanceId, placeAfter)
    }
    onDragEnd()
    return
  }
  if (!draggedInstanceId.value || draggedInstanceId.value === targetInstanceId) {
    onDragEnd()
    return
  }
  const sorted = activeLayersDisplay.value
  const fromIndex = sorted.findIndex((d) => d.instanceId === draggedInstanceId.value)
  const toIndex = sorted.findIndex((d) => d.instanceId === targetInstanceId)
  if (fromIndex === -1 || toIndex === -1) {
    onDragEnd()
    return
  }
  layersStore.reorderLayers(fromIndex, toIndex)
  onDragEnd()
}

function onGroupDrop(groupId: string) {
  if (draggedGroupId.value && draggedGroupId.value !== groupId) {
    const targetGroup = runGroupOf(groupId)
    const anchor = targetGroup?.memberInstanceIds[0] ?? null
    if (anchor) {
      layersStore.moveRunGroupBlock(draggedGroupId.value, anchor, false)
    }
  }
  onDragEnd()
}

function onDragEnd() {
  draggedInstanceId.value = null
  draggedGroupId.value = null
  dragOverInstanceId.value = null
  dragOverGroupId.value = null
}

// ── Helper: availability chip class ───────────────────────────────────────────

function availabilityClass(state: string) {
  if (state === 'ready') return 'availability-ready'
  if (state === 'partial') return 'availability-partial'
  return 'availability-empty'
}

// ── Get category meta ─────────────────────────────────────────────────────────

function getCategoryMeta(categoryId: string) {
  return layerCategories.find((c) => c.id === categoryId)
}

function getCategoryName(categoryId: string): string {
  return layerCategories.find((c) => c.id === categoryId)?.name ?? categoryId
}

// ── 数据源选择 ─────────────────────────────────────────────────────────────────
// 友好且无冲突的方案：
//   - 0 数据源：显示 "暂无可用数据源" 提示
//   - 1 数据源：直接展示数据源信息（无展开按钮），简洁友好
//   - 多数据源：显示当前选中源 + 展开按钮，可单选切换

function getCatalogSources(catalogId: string) {
  return layerLibrary.value.find((l) => l.catalogId === catalogId)?.sources ?? []
}

function getPrimarySourceId(catalogId: string): string {
  const sources = getCatalogSources(catalogId)
  return sources[0]?.id ?? ''
}

function getPrimarySourceName(catalogId: string): string {
  const sources = getCatalogSources(catalogId)
  const id = getPrimarySourceId(catalogId)
  return (
    sources.find((s) => s.id === id)?.name ??
    (sources.length === 0 ? LAYERS_COPY.noDataSource : LAYERS_COPY.pleaseSelectSource)
  )
}

function getCatalogSourceSummary(catalogId: string): string {
  const sources = getCatalogSources(catalogId)
  if (!sources.length) return LAYERS_COPY.noDataSource
  return sources.map((source) => source.name).join(' / ')
}

// ── 右键菜单 ─────────────────────────────────────────────────────────────────

interface ContextMenuState {
  instanceId?: string
  groupId?: string
  x: number
  y: number
}

const contextMenu = ref<ContextMenuState | null>(null)

const contextMenuLayer = computed(() => {
  if (!contextMenu.value?.instanceId) return null
  return (
    activeLayersDisplay.value.find((l) => l.instanceId === contextMenu.value!.instanceId) ?? null
  )
})

/** 右键图层条目时弹出上下文菜单 */
function onLayerContextMenu(instanceId: string, event: MouseEvent) {
  event.preventDefault()
  const MENU_W = 200
  const MENU_H = 360
  const vw = window.innerWidth
  const vh = window.innerHeight
  const x = Math.min(event.clientX, vw - MENU_W - 8)
  const y = Math.min(event.clientY, vh - MENU_H - 8)
  contextMenu.value = { instanceId, x: Math.max(8, x), y: Math.max(8, y) }
}

function onGroupContextMenu(groupId: string, event: MouseEvent) {
  event.preventDefault()
  event.stopPropagation()
  const MENU_W = 200
  const MENU_H = 200
  const vw = window.innerWidth
  const vh = window.innerHeight
  const x = Math.min(event.clientX, vw - MENU_W - 8)
  const y = Math.min(event.clientY, vh - MENU_H - 8)
  contextMenu.value = { groupId, x: Math.max(8, x), y: Math.max(8, y) }
}

function closeContextMenu() {
  contextMenu.value = null
}

const contextMenuGroups = computed(() => {
  if (contextMenu.value?.groupId) {
    const g = runGroupOf(contextMenu.value.groupId)
    if (!g) return []
    const members = g.memberInstanceIds
      .map((id) => layersStore.activeLayers.find((l) => l.instanceId === id))
      .filter(Boolean)
    return buildGroupContextMenu({
      dissolvable: g.dissolvable,
      computing: g.status === 'computing',
      anyVisible: members.some((m) => m?.visible),
    })
  }
  const layer = contextMenuLayer.value
  if (!layer) return []
  const canRun =
    !layer.isImported &&
    !layer.isImportedRaster &&
    !layer.isAdminBoundary &&
    layersStore.canRunCatalog(layer.catalogId)
  return buildLayerContextMenu({
    visible: layer.visible,
    isAdminBoundary: layer.isAdminBoundary,
    isImported: layer.isImported,
    isImportedRaster: layer.isImportedRaster,
    hasJobReport: Boolean(layer.jobLayer?.reportSummary),
    canRunWorkflow: canRun,
    canDissolveGroup: Boolean(
      layer.runGroupId && layersStore.findRunGroupById(layer.runGroupId)?.dissolvable,
    ),
  })
})

/** 右键「样式…」→ 分析面板样式 Tab（符号/透明度/配色等统一入口） */
function openStyleInAnalysis() {
  if (!contextMenu.value?.instanceId) return
  const id = contextMenu.value.instanceId
  const layer = activeLayersDisplay.value.find((l) => l.instanceId === id)
  uiStore.requestAnalysisFocus(['layer-style'])
  selectItem(id)
  if (
    layer &&
    !layer.isImported &&
    !layer.isImportedRaster &&
    !layer.isAdminBoundary &&
    !layer.renderHint
  ) {
    void overlaySymbologyStore.ensureMeta(layer.catalogId)
  }
  closeContextMenu()
}

async function exportActiveFromMenu(format: 'geojson' | 'csv' | 'png' | 'tif') {
  if (!contextMenu.value) return
  const active = layersStore.activeLayers.find(
    (l) => l.instanceId === contextMenu.value?.instanceId,
  )
  if (!active) {
    closeContextMenu()
    return
  }
  // 栅格 GeoTIFF/PNG：汇合到数据导出框（带日期时刻选择）
  if ((format === 'tif' || format === 'png') && active.importedRaster) {
    const times = active.importedRaster.timeList ?? []
    let time: string | null = null
    if (times.length) {
      const eff = active.importedRaster.effectiveTimeLabel
      time =
        (eff && times.find((t) => eff === t || eff.startsWith(t))) ||
        times[times.length - 1] ||
        null
    }
    openDatedExportForLayer(active.instanceId, time)
    closeContextMenu()
    return
  }
  try {
    await exportLayer(active, format)
    logStore.logOperation(`export-${format}`, `导出 ${format.toUpperCase()}「${active.name}」`)
  } catch (e) {
    logStore.logOperation(
      'export-fail',
      `导出 ${format.toUpperCase()} 失败: ${active.name}`,
      e instanceof Error ? e.message : String(e),
    )
  }
  closeContextMenu()
}

function renameLayerFromMenu() {
  if (!contextMenu.value?.instanceId) return
  const id = contextMenu.value.instanceId
  const layer = activeLayersDisplay.value.find((l) => l.instanceId === id)
  const next = window.prompt(LAYERS_COPY.renamePrompt, layer?.name ?? '')
  if (next != null && next.trim()) {
    layersStore.setLayerDisplayName(id, next)
    logStore.logOperation('layer-rename', `重命名图层「${next.trim()}」`)
  }
  closeContextMenu()
}

function handleContextAction(action: LayerContextActionId) {
  if (!contextMenu.value) return
  const groupId = contextMenu.value.groupId
  if (groupId) {
    const g = runGroupOf(groupId)
    switch (action) {
      case 'toggleGroupVisible': {
        const members = g?.memberInstanceIds ?? []
        const anyVisible = members.some(
          (id) => layersStore.activeLayers.find((l) => l.instanceId === id)?.visible,
        )
        for (const id of members) {
          const layer = layersStore.activeLayers.find((l) => l.instanceId === id)
          if (!layer) continue
          if (layer.visible === anyVisible) {
            layersStore.toggleLayerVisibility(id)
          }
        }
        closeContextMenu()
        return
      }
      case 'dissolveGroup':
        if (g?.dissolvable) {
          layersStore.dissolveRunGroup(groupId)
          logStore.logOperation('layer-dissolve-group', `拆分计算组 ${groupId}`)
        }
        closeContextMenu()
        return
      case 'removeGroup': {
        const members = [...(g?.memberInstanceIds ?? [])]
        for (const id of members) {
          layersStore.removeLayer(id)
        }
        logStore.logOperation('layer-remove-group', `移除计算组 ${groupId}`)
        closeContextMenu()
        return
      }
      default:
        closeContextMenu()
        return
    }
  }
  const id = contextMenu.value.instanceId
  if (!id) return
  switch (action) {
    case 'zoom':
      zoomToLayerFromMenu()
      return
    case 'toggleVisible':
      layersStore.toggleLayerVisibility(id)
      closeContextMenu()
      return
    case 'viewDetails':
      selectItem(id)
      closeContextMenu()
      return
    case 'bringToFront':
      layersStore.bringLayerToFront(id)
      closeContextMenu()
      return
    case 'sendToBack':
      layersStore.sendLayerToBack(id)
      closeContextMenu()
      return
    case 'rename':
      renameLayerFromMenu()
      return
    case 'openAttributes':
      selectItem(id)
      openDataWorkspace({ tab: 'attributes', layerInstanceId: id })
      closeContextMenu()
      return
    case 'openDetails':
      selectItem(id)
      openDataWorkspace({ tab: 'details', layerInstanceId: id })
      closeContextMenu()
      return
    case 'openStyle':
      openStyleInAnalysis()
      return
    case 'exportGeoJson':
      void exportActiveFromMenu('geojson')
      return
    case 'exportCsv':
      void exportActiveFromMenu('csv')
      return
    case 'exportPng':
      void exportActiveFromMenu('png')
      return
    case 'exportTif':
      void exportActiveFromMenu('tif')
      return
    case 'viewReport':
      openJobReport(id)
      closeContextMenu()
      return
    case 'runWorkflow': {
      const layer = activeLayersDisplay.value.find((l) => l.instanceId === id)
      if (layer) {
        void layersStore.runWorkflowForCatalog(layer.catalogId)
      }
      closeContextMenu()
      return
    }
    case 'runWorkflowNoCache': {
      // 不使用节点缓存：全量重算，规避复用旧输出目录带来的时间片污染
      const layer = activeLayersDisplay.value.find((l) => l.instanceId === id)
      if (layer) {
        void layersStore.runWorkflowForCatalog(layer.catalogId, { reuseBlockCache: false })
      }
      closeContextMenu()
      return
    }
    case 'dissolveGroup': {
      const layer = activeLayersDisplay.value.find((l) => l.instanceId === id)
      if (layer?.runGroupId) {
        layersStore.dissolveRunGroup(layer.runGroupId)
        logStore.logOperation('layer-dissolve-group', `拆分计算组 ${layer.runGroupId}`)
      }
      closeContextMenu()
      return
    }
    case 'remove':
      removeItem(id, new MouseEvent('click'))
      closeContextMenu()
      return
  }
}

/** 点击页面空白处关闭菜单 */
function onGlobalClick(event: MouseEvent) {
  const target = event.target as HTMLElement
  if (contextMenu.value && !target.closest('.ctx-menu')) {
    closeContextMenu()
  }
}

/** ESC 关闭菜单 */
function onGlobalKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    closeContextMenu()
  }
}

onMounted(() => {
  document.addEventListener('click', onGlobalClick)
  document.addEventListener('keydown', onGlobalKeydown)
  prefetchVisibleWeatherProviders()
})
onUnmounted(() => {
  document.removeEventListener('click', onGlobalClick)
  document.removeEventListener('keydown', onGlobalKeydown)
})

/** 当 active 图层变化时，预取 overlay 元数据（用于颜色图例） */
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

/** 判断图层是否支持颜色图例显示（参考 ArcGIS：仅有符号化数据的图层显示色带） */
function hasColorSymbology(layer: ActiveLayerDisplayLike): boolean {
  if (layer.isAdminBoundary) return false
  if (layer.renderHint) return true
  // 依赖 store.version，保证 meta 拉取后色带刷新
  void overlaySymbologyStore.version
  const meta = overlaySymbologyStore.getMeta(layer.catalogId)
  return !!meta?.palette
}

function getSymbologyUnit(layer: ActiveLayerDisplayLike): string {
  if (layer.renderHint?.unit_label) return layer.renderHint.unit_label
  void overlaySymbologyStore.version
  const meta = overlaySymbologyStore.getMeta(layer.catalogId)
  if (meta?.unit) return meta.unit
  return ''
}

function getSymbologyVmin(layer: ActiveLayerDisplayLike): string {
  const ticks = layer.renderHint?.legend_ticks
  if (ticks && ticks.length > 0) return String(ticks[0])
  return ''
}

function getSymbologyVmax(layer: ActiveLayerDisplayLike): string {
  const ticks = layer.renderHint?.legend_ticks
  if (ticks && ticks.length > 1) return String(ticks[ticks.length - 1])
  if (ticks && ticks.length === 1) return String(ticks[0])
  return ''
}

function getColorRampStyle(layer: ActiveLayerDisplayLike): Record<string, string> {
  void overlaySymbologyStore.version
  // 与 InfoPanel 同源：resolveEffectiveLayerSymbology + buildWeatherLegendGradient
  const { hint } = resolveEffectiveLayerSymbology({
    paletteOverride: layer.paletteOverride,
    renderHint: (layer.renderHint ?? null) as WeatherLayerRenderHint | null,
    overlayMeta: overlaySymbologyStore.getMeta(layer.catalogId),
  })
  if (hint) {
    return { background: buildWeatherLegendGradient(hint) }
  }
  const colors = resolveSymbologyColors({
    paletteOverride: layer.paletteOverride,
    renderHint: layer.renderHint,
    overlayMeta: overlaySymbologyStore.getMeta(layer.catalogId),
    fallbackAccent: layer.accentColor,
  })
  return {
    background: `linear-gradient(90deg, ${colors.join(', ')})`,
  }
}

// 类型别名：对齐 WeatherLayerRenderHint 实际 schema（legend_ticks 而非 vmin/vmax）
type ActiveLayerDisplayLike = {
  instanceId: string
  catalogId: string
  metricLabel: string
  accentColor: string
  opacity: number
  isAdminBoundary?: boolean
  isImported?: boolean
  isImportedRaster?: boolean
  paletteOverride?: string | null
  renderHint?: {
    palette: string
    unit_label?: string
    /** 天气图层的图例刻度，首末项作为 vmin/vmax 展示 */
    legend_ticks?: (number | string)[]
  } | null
}
</script>

<template>
  <aside ref="sidebarRootEl" class="panel">
    <!-- ── Header ─────────────────────────────────────────────────────────── -->
    <div class="panel-topline">
      <div class="panel-header">
        <div class="header-copy">
          <h2>{{ sidebarViewLabel }}</h2>
          <p v-if="sidebarView !== 'active'" class="panel-subtitle">
            {{ sidebarView === 'empty' ? '开始添加图层' : '从库中选择' }}
          </p>
        </div>
        <div class="header-actions">
          <button
            v-if="activeLayerCount > 0"
            class="badge"
            type="button"
            title="查看已添加图层"
            @click="openActive"
          >
            {{ activeLayerCount }}
          </button>
          <div class="view-tabs" role="tablist">
            <button
              class="view-tab"
              :class="{ active: sidebarView === 'library' }"
              role="tab"
              title="图层库"
              @click="openLibrary"
            >
              +
            </button>
            <button
              class="view-tab"
              :class="{ active: sidebarView === 'active' }"
              role="tab"
              :aria-selected="sidebarView === 'active'"
              title="已添加图层"
              @click="openActive"
            >
              ≡
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ── EMPTY STATE ─────────────────────────────────────────────────────── -->
    <div v-if="sidebarView === 'empty'" class="empty-state">
      <div class="empty-icon" aria-hidden="true">◇</div>
      <p class="empty-title">{{ LAYERS_COPY.emptyTitle }}</p>
      <p class="empty-hint">点击下方按钮打开图层库，<br />添加气象、遥感或边界图层。</p>
      <button class="empty-cta" @click="openLibrary">
        <span aria-hidden="true">+</span>
        打开图层库
      </button>
    </div>

    <!-- ── LIBRARY STATE ───────────────────────────────────────────────────── -->
    <template v-else-if="sidebarView === 'library'">
      <!-- Search -->
      <div class="search-row">
        <input v-model="searchQuery" class="search-input" placeholder="搜索图层..." type="search" />
      </div>

      <!-- Category groups -->
      <div class="library-scroll">
        <div
          v-for="group in filteredLibraryByCategory"
          :key="group.category.id"
          class="category-group"
        >
          <div
            class="category-header-row"
            :style="{ '--cat-color': getCategoryMeta(group.category.id)?.accentColor ?? '#88d8ff' }"
          >
            <button
              class="category-header"
              type="button"
              @click="toggleCategory(group.category.id)"
            >
              <span class="cat-icon" aria-hidden="true">{{
                getCategoryMeta(group.category.id)?.icon ?? '◈'
              }}</span>
              <span class="cat-name">{{
                getCategoryMeta(group.category.id)?.name ?? group.category.id
              }}</span>
            </button>
            <div class="cat-header-actions">
              <span class="cat-count">{{ group.items.length }}</span>
              <button
                class="cat-batch-add"
                type="button"
                title="添加此分类下所有图层"
                @click="addAllInCategory(group.items)"
              >
                +全部
              </button>
              <button
                class="cat-expand"
                type="button"
                :aria-expanded="expandedCategories.has(group.category.id)"
                :title="expandedCategories.has(group.category.id) ? '收起' : '展开'"
                @click="toggleCategory(group.category.id)"
              >
                <span
                  class="cat-arrow"
                  :class="{ expanded: expandedCategories.has(group.category.id) }"
                  >▸</span
                >
              </button>
            </div>
          </div>

          <div v-if="expandedCategories.has(group.category.id)" class="category-items">
            <!-- 课题组数据二级分类筛选 Pills -->
            <div
              v-if="group.category.id === 'research-group' && researchSubCategoryPills.length > 1"
              class="subcategory-pills-bar"
            >
              <button
                v-for="sub in researchSubCategoryPills"
                :key="sub"
                type="button"
                class="sub-pill"
                :class="{ active: selectedSubCategory === sub }"
                @click.stop="selectedSubCategory = sub"
              >
                {{ sub === 'all' ? '全部' : sub }}
              </button>
            </div>
            <div v-if="group.items.length === 0" class="empty-subcategory-hint">
              暂无匹配【{{ selectedSubCategory === 'all' ? '全部' : selectedSubCategory }}】的{{
                orgLabel
              }}图层
            </div>
            <div
              v-for="item in group.items"
              :key="item.catalogId"
              class="library-card"
              :class="{ added: isAdded(item.catalogId) }"
              :style="{
                '--accent': item.accentColor,
                '--glow': item.accentGlow,
              }"
            >
              <div class="card-top">
                <div class="card-title-row">
                  <strong>{{ item.name }}</strong>
                  <div class="chips-group">
                    <span class="card-chip" :style="{ background: item.chipTone }">{{
                      getCategoryName(item.category)
                    }}</span>
                    <span
                      v-if="item.subCategory"
                      class="card-chip subcategory-chip"
                      style="
                        background: rgba(255, 255, 255, 0.08);
                        margin-left: 4px;
                        color: #a4caf6;
                      "
                      >{{ item.subCategory }}</span
                    >
                  </div>
                </div>
                <p class="card-source">{{ item.sourceLabel }}</p>
              </div>

              <!-- 数据源区域：天气图层用运行时 Provider；其它图层仍用目录静态 sources -->
              <div class="source-area">
                <template v-if="item.category === '气象场'">
                  <div class="source-weather-live">
                    <label class="weather-src-label">
                      <span class="src-dot" :style="{ background: item.accentColor }"></span>
                      <select
                        class="weather-src-select"
                        :value="weatherSourcePrefs.getProvider(item.catalogId)"
                        :disabled="!!weatherProvidersLoading[item.catalogId]"
                        @focus="ensureWeatherProviders(item.catalogId)"
                        @change="
                          onWeatherSourceChange(
                            item.catalogId,
                            ($event.target as HTMLSelectElement).value,
                          )
                        "
                      >
                        <option value="auto">{{ INSPECT_COPY.providerAuto }}</option>
                        <option
                          v-for="p in weatherProvidersFor(item.catalogId)"
                          :key="p.provider_id"
                          :value="p.provider_id"
                          :disabled="!p.enabled"
                        >
                          {{ weatherProviderOptionLabel(p) }}
                        </option>
                      </select>
                    </label>
                    <p v-if="weatherSourceQualityHint(item.catalogId)" class="src-sparse-hint">
                      {{ weatherSourceQualityHint(item.catalogId) }}
                    </p>
                    <p v-else-if="weatherSourceSparseHint(item.catalogId)" class="src-sparse-hint">
                      点查可用；瓦片将回落 dense 源（Open-Meteo）
                    </p>
                    <p
                      v-else-if="
                        !weatherProvidersLoading[item.catalogId] &&
                        weatherProvidersFor(item.catalogId).length === 0
                      "
                      class="src-sparse-hint"
                    >
                      展开或聚焦时加载可用源…
                    </p>
                  </div>
                </template>
                <template v-else>
                  <div
                    v-if="item.sources.length === 0"
                    class="source-empty"
                    :title="'该图层暂未接入数据源'"
                  >
                    <span class="src-empty-icon" aria-hidden="true">ⓘ</span>
                    <span>{{ LAYERS_COPY.noDataSource }}</span>
                  </div>
                  <div v-else-if="item.sources.length === 1" class="source-single">
                    <div class="src-line">
                      <span class="src-dot" :style="{ background: item.accentColor }"></span>
                      <span class="src-name">{{ item.sources[0].name }}</span>
                    </div>
                    <div class="src-meta">
                      <span class="src-badge">{{ item.sources[0].updateFrequency }}</span>
                      <span class="src-coord">{{ item.sources[0].coordSys }}</span>
                      <span v-if="item.sources[0].needsAuth" class="src-auth" title="需要认证"
                        >🔒</span
                      >
                      <span
                        v-if="item.sources[0].needsBackendTransform"
                        class="src-tfm"
                        title="后端转换"
                        >⚙</span
                      >
                    </div>
                  </div>
                  <div v-else class="source-multi">
                    <div class="source-summary" :title="getCatalogSourceSummary(item.catalogId)">
                      <span class="src-dot" :style="{ background: item.accentColor }"></span>
                      <span class="src-current">{{ getPrimarySourceName(item.catalogId) }}</span>
                      <span class="src-count">{{ item.sources.length }} 个候选源</span>
                    </div>
                    <div class="source-list source-list-static">
                      <div
                        v-for="src in item.sources"
                        :key="src.id"
                        class="source-option source-option-static"
                        :title="src.description"
                      >
                        <div class="src-opt-top">
                          <span class="src-name">{{ src.name }}</span>
                        </div>
                        <div class="src-meta">
                          <span class="src-badge">{{ src.updateFrequency }}</span>
                          <span class="src-coord">{{ src.coordSys }}</span>
                          <span v-if="src.needsAuth" class="src-auth" title="需要认证">🔒</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </template>
              </div>

              <div class="card-actions">
                <span class="card-metric">{{ item.metricLabel }}: {{ item.metricUnit }}</span>
                <button
                  v-if="!isAdded(item.catalogId)"
                  class="add-btn"
                  :disabled="isAdded(item.catalogId)"
                  :title="getCatalogRunBlockReason(item.catalogId) ?? ''"
                  @click="addCatalogItem(item.catalogId)"
                >
                  + 添加
                </button>
                <!-- 已添加：显示工作流状态徽标 -->
                <span
                  v-else-if="getCatalogJobStatus(item.catalogId) === 'running'"
                  class="job-status-chip job-status-running"
                >
                  <span class="spin-dot" aria-hidden="true"></span>运行中
                </span>
                <span
                  v-else-if="getCatalogJobStatus(item.catalogId) === 'queued'"
                  class="job-status-chip job-status-queued"
                >
                  排队中
                </span>
                <span
                  v-else-if="getCatalogJobStatus(item.catalogId) === 'retry_pending'"
                  class="job-status-chip job-status-queued"
                >
                  等待重试
                </span>
                <span
                  v-else-if="getCatalogJobStatus(item.catalogId) === 'succeeded'"
                  class="job-status-chip job-status-succeeded"
                >
                  已就绪 ✓
                </span>
                <span
                  v-else-if="getCatalogJobStatus(item.catalogId) === 'failed'"
                  class="job-status-chip job-status-failed"
                >
                  运行失败
                </span>
                <span
                  v-else-if="getCatalogJobStatus(item.catalogId) === 'cancelled'"
                  class="job-status-chip job-status-cancelled"
                >
                  已取消
                </span>
                <span v-else class="added-label">已添加 ✓</span>
              </div>
              <div
                v-if="getCatalogSemanticNote(item.catalogId)"
                class="run-block-note"
                :class="catalogSemanticNoteClass(item.catalogId)"
              >
                {{ getCatalogSemanticNote(item.catalogId) }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- ── ACTIVE STATE ───────────────────────────────────────────────────── -->
    <div v-else-if="sidebarView === 'active'" class="active-state">
      <div v-if="activeLayersDisplay.length === 0" class="no-layers">
        <p>{{ LAYERS_COPY.emptyActive }}</p>
        <button type="button" class="empty-cta" @click="openLibrary">
          {{ LAYERS_COPY.emptyActiveCta }}
        </button>
      </div>

      <template v-else>
        <!-- 批量操作工具栏 -->
        <div class="batch-toolbar">
          <button class="batch-btn" title="显示所有图层" @click="showAllLayers">
            <span aria-hidden="true">◉</span> 全部显示
          </button>
          <button class="batch-btn" title="隐藏所有图层" @click="hideAllLayers">
            <span aria-hidden="true">◯</span> 全部隐藏
          </button>
          <button class="batch-btn batch-btn-danger" title="移除所有图层" @click="removeAllLayers">
            <span aria-hidden="true">✕</span> 全部移除
          </button>
        </div>

        <!-- 图层列表：组头 + 成员；按内容高度排列 -->
        <ul class="layer-list" role="listbox" aria-label="已添加图层">
          <template v-for="row in activeTocRows" :key="row.key">
            <li
              v-if="row.kind === 'group'"
              class="layer-group-header"
              :class="{
                'drag-over': row.groupId === dragOverGroupId,
                computing: runGroupOf(row.groupId)?.status === 'computing',
              }"
              draggable="true"
              @dragstart="onGroupDragStart(row.groupId, $event)"
              @dragover="onGroupDragOver(row.groupId, $event)"
              @drop="onGroupDrop(row.groupId)"
              @dragend="onDragEnd"
              @contextmenu.prevent="onGroupContextMenu(row.groupId, $event)"
            >
              <span class="drag-handle" title="拖动整组">☰</span>
              <span class="group-accent" aria-hidden="true"></span>
              <strong class="group-title">{{
                runGroupOf(row.groupId)?.title || LAYERS_COPY.computingGroup
              }}</strong>
              <span class="group-status-chip">{{ groupStatusLabel(row.groupId) }}</span>
              <span
                v-if="typeof runGroupOf(row.groupId)?.progress === 'number'"
                class="group-progress-track"
                :title="`${runGroupOf(row.groupId)?.progress}%`"
              >
                <span
                  class="group-progress-fill"
                  :style="{
                    width: `${Math.max(0, Math.min(100, runGroupOf(row.groupId)?.progress ?? 0))}%`,
                  }"
                ></span>
              </span>
              <span class="group-count"
                >{{ runGroupOf(row.groupId)?.memberInstanceIds.length ?? 0 }} 层</span
              >
            </li>
            <li
              v-else
              class="layer-item"
              :class="{
                active: row.layer.instanceId === selectedInstanceId,
                hidden: !row.layer.visible,
                'drag-over': row.layer.instanceId === dragOverInstanceId,
                'in-run-group': row.indented,
                'group-locked': row.layer.runGroupLocked,
              }"
              :style="{
                '--accent': row.layer.accentColor,
                '--glow': row.layer.accentGlow,
              }"
              :draggable="true"
              role="option"
              :aria-selected="row.layer.instanceId === selectedInstanceId"
              @click="selectItem(row.layer.instanceId)"
              @dblclick.stop="zoomToItem(row.layer.instanceId)"
              @contextmenu="onLayerContextMenu(row.layer.instanceId, $event)"
              @dragstart="onDragStart(row.layer.instanceId)"
              @dragover="onDragOver(row.layer.instanceId, $event)"
              @drop="onDrop(row.layer.instanceId)"
              @dragend="onDragEnd"
            >
              <div class="layer-row-top">
                <span
                  class="drag-handle"
                  :title="row.layer.runGroupLocked ? '仅可在组内排序' : '拖动排序'"
                  >☰</span
                >
                <button
                  class="vis-btn"
                  :title="row.layer.visible ? '隐藏图层' : '显示图层'"
                  @click="toggleVisibility(row.layer.instanceId, $event)"
                >
                  <span aria-hidden="true">{{ row.layer.visible ? '◉' : '◯' }}</span>
                </button>
                <span
                  class="layer-color-dot"
                  :style="{ background: row.layer.accentColor }"
                  aria-hidden="true"
                ></span>
                <strong class="layer-name">{{ row.layer.name }}</strong>
                <span class="layer-chip" :style="{ background: row.layer.chipTone }">{{
                  getCategoryName(row.layer.category)
                }}</span>
                <button
                  class="del-btn"
                  title="移除图层"
                  @click="removeItem(row.layer.instanceId, $event)"
                >
                  <span aria-hidden="true">✕</span>
                </button>
              </div>

              <div v-if="hasColorSymbology(row.layer)" class="layer-legend">
                <div class="legend-ramp" :style="getColorRampStyle(row.layer)"></div>
                <div class="legend-labels">
                  <span class="legend-min">{{ getSymbologyVmin(row.layer) }}</span>
                  <span class="legend-unit">{{ getSymbologyUnit(row.layer) }}</span>
                  <span class="legend-max">{{ getSymbologyVmax(row.layer) }}</span>
                </div>
              </div>

              <div class="layer-row-bottom">
                <span
                  class="availability-chip"
                  :class="availabilityClass(row.layer.availabilityState)"
                >
                  {{ row.layer.availabilityLabel }}
                </span>
                <span v-if="row.layer.isAdminBoundary" class="admin-tip-inline"
                  >边界 · 静态矢量</span
                >
                <span v-else-if="row.layer.isImported" class="admin-tip-inline"
                  >导入 · {{ row.layer.importedGeometryType }} ·
                  {{ row.layer.importedFeatureCount }} 要素</span
                >
                <span v-else-if="row.layer.isImportedRaster" class="admin-tip-inline"
                  >导入 · 栅格{{
                    row.layer.importedRasterTimeCount
                      ? ` · ${row.layer.importedRasterTimeCount} 块`
                      : ' · TIF'
                  }}{{
                    row.layer.importedRasterEffectiveTime
                      ? ` · ${row.layer.importedRasterEffectiveTime}`
                      : ''
                  }}</span
                >
                <span
                  v-else-if="row.layer.runGroupId && !row.layer.isImportedRaster"
                  class="admin-tip-inline"
                  >计算占位{{
                    row.layer.runGroupProductTag ? ` · ${row.layer.runGroupProductTag}` : ''
                  }}</span
                >
                <template v-if="row.layer.jobLayer">
                  <span class="job-status-badge" :class="`job-${row.layer.jobLayer.status}`">
                    {{
                      row.layer.jobLayer.status === 'running'
                        ? row.layer.jobLayer.message
                          ? row.layer.jobLayer.message
                          : `运行中 ${row.layer.jobLayer.progress}%`
                        : row.layer.jobLayer.status === 'queued'
                          ? '排队中'
                          : row.layer.jobLayer.status === 'retry_pending'
                            ? '等待重试'
                            : row.layer.jobLayer.status === 'succeeded'
                              ? '已完成'
                              : row.layer.jobLayer.status === 'failed'
                                ? '失败'
                                : row.layer.jobLayer.status === 'cancelled'
                                  ? '已取消'
                                  : row.layer.jobLayer.status
                    }}
                  </span>
                  <button
                    v-if="row.layer.jobLayer.reportSummary"
                    class="job-report-hint"
                    type="button"
                    @click.stop="openJobReport(row.layer.instanceId)"
                  >
                    查看报告
                  </button>
                </template>
                <span class="order-hint"
                  >顺序
                  {{
                    activeLayersDisplay.findIndex((l) => l.instanceId === row.layer.instanceId) + 1
                  }}
                  / {{ activeLayersDisplay.length }}</span
                >
              </div>
            </li>
          </template>
        </ul>
      </template>
    </div>

    <!-- ── Footer ──────────────────────────────────────────────────────────── -->
    <p class="panel-footnote">
      <template v-if="sidebarView === 'active'">{{ LAYERS_COPY.footerActive }}</template>
      <template v-else-if="sidebarView === 'library'">选择图层添加到地图</template>
      <template v-else></template>
    </p>

    <!-- ── 右键上下文菜单（Teleport 到 body） ─────────────────────────────── -->
    <Teleport to="body">
      <div
        v-if="contextMenu"
        class="ctx-menu"
        :style="{ left: contextMenu.x + 'px', top: contextMenu.y + 'px' }"
        @click.stop
      >
        <template v-for="(group, gi) in contextMenuGroups" :key="group.id">
          <div v-if="gi > 0" class="ctx-sep" role="separator"></div>
          <button
            v-for="item in group.items"
            :key="item.id"
            class="ctx-item"
            :class="{ 'ctx-danger': item.danger }"
            type="button"
            :disabled="item.disabled"
            @click="handleContextAction(item.id)"
          >
            <span class="ctx-icon" aria-hidden="true">{{ item.icon }}</span>
            <span>{{ item.label }}</span>
          </button>
        </template>
      </div>
    </Teleport>
  </aside>
</template>

<style scoped>
/* ── Base panel ──────────────────────────────────────────────────────────── */
.panel {
  --sidebar-card-radius: 0.72rem;
  --sidebar-soft-radius: 0.6rem;
  --sidebar-section-padding: 0.46rem;
  --sidebar-inner-padding: 0.32rem;
  display: flex;
  flex-direction: column;
  gap: 0.42rem;
  padding: 0.46rem;
  border: 1px solid rgba(148, 163, 184, 0.15);
  border-radius: 0.88rem;
  background: linear-gradient(180deg, rgba(13, 21, 36, 0.42), rgba(8, 15, 28, 0.3));
  backdrop-filter: blur(18px);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.03),
    0 12px 26px rgba(1, 8, 16, 0.14);
  overflow: hidden;
  width: 100%;
  height: min(100%, calc(100vh - 12rem));
  max-height: min(100%, calc(100vh - 12rem));
  box-sizing: border-box;
}

.panel,
.panel * {
  box-sizing: border-box;
  min-width: 0;
}

/* ── Header ──────────────────────────────────────────────────────────────── */
.panel-topline {
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
  padding: 0.08rem;
  flex: 0 0 auto;
  /* 不要 sticky 实色底：会盖住面板顶部圆角，看起来像直角矩形 */
  background: transparent;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
}

.header-copy {
  min-width: 0;
  flex: 1 1 auto;
}

.header-actions {
  display: inline-flex;
  align-items: center;
  gap: 0.42rem;
  flex: 0 0 auto;
  flex-wrap: nowrap;
  justify-content: flex-end;
}

h2 {
  margin: 0;
  color: #eef6ff;
  font-size: 0.76rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.panel-subtitle {
  margin: 0.14rem 0 0;
  color: #7f93a9;
  font-size: 0.62rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  min-width: 1rem;
  height: 1rem;
  padding: 0 0.22rem;
  border: 1px solid rgba(103, 212, 255, 0.22);
  border-radius: 999px;
  background: rgba(103, 212, 255, 0.14);
  color: #8fe7ff;
  /* 勿用 font: inherit，会继承面板大字号把徽标撑爆 */
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.5rem;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
  line-height: 1;
  letter-spacing: -0.02em;
  flex: 0 1 auto;
  cursor: pointer;
  white-space: nowrap;
}

.badge:hover {
  background: rgba(103, 212, 255, 0.22);
}

/* ── View tabs ──────────────────────────────────────────────────────────── */
.view-tabs {
  display: inline-flex;
  gap: 0.22rem;
  padding: 0.14rem;
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: 999px;
  background: rgba(4, 12, 23, 0.6);
  align-self: flex-start;
  flex: 0 0 auto;
  min-width: max-content;
  position: relative;
  z-index: 1;
}

.view-tab {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.6rem;
  height: 1.6rem;
  min-width: 1.6rem;
  min-height: 1.6rem;
  flex: 0 0 auto;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: #6e8ba0;
  cursor: pointer;
  font-size: 0.64rem;
  pointer-events: auto;
  transition:
    background-color 0.18s ease,
    color 0.18s ease;
}

.view-tab:hover {
  background: rgba(136, 192, 255, 0.1);
  color: #c8dff0;
}

.view-tab.active {
  background: rgba(10, 132, 255, 0.24);
  color: #5ad5ff;
  box-shadow: inset 0 0 0 1px rgba(90, 213, 255, 0.2);
}

/* ── Empty state ────────────────────────────────────────────────────────── */
.empty-state {
  display: grid;
  gap: 0.42rem;
  padding: 1.8rem 0.8rem;
  text-align: center;
  align-items: center;
}

.empty-icon {
  font-size: 2.4rem;
  color: rgba(103, 212, 255, 0.2);
  animation: pulse-glow 3s ease-in-out infinite;
}

@keyframes pulse-glow {
  0%,
  100% {
    opacity: 0.4;
    transform: scale(1);
  }
  50% {
    opacity: 0.8;
    transform: scale(1.08);
  }
}

.empty-title {
  margin: 0;
  color: #c8dff0;
  font-size: 0.82rem;
  font-weight: 600;
}

.empty-hint {
  margin: 0;
  color: #7f93a9;
  font-size: 0.62rem;
  line-height: 1.45;
}

.empty-cta {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.28rem;
  padding: 0.42rem 0.9rem;
  border: 1px solid rgba(90, 213, 255, 0.3);
  border-radius: 999px;
  background: rgba(10, 132, 255, 0.24);
  color: #a8e8ff;
  cursor: pointer;
  font: inherit;
  font-size: 0.64rem;
  font-weight: 600;
  align-self: center;
  margin-top: 0.2rem;
  /* 性能优化：GPU 动画，移除内联阴影计算 */
  transition:
    background 0.2s ease,
    border-color 0.2s ease,
    color 0.2s ease,
    transform 0.18s cubic-bezier(0.25, 0.46, 0.45, 0.94);
}

.empty-cta:hover {
  background: rgba(10, 132, 255, 0.38);
  border-color: rgba(90, 213, 255, 0.5);
  color: #d0f0ff;
  transform: translateY(-2px);
}

.empty-cta.small {
  padding: 0.32rem 0.7rem;
  font-size: 0.6rem;
}

/* ── Search ─────────────────────────────────────────────────────────────── */
.search-row {
  padding: 0.12rem;
}

.search-input {
  width: 100%;
  padding: 0.34rem 0.52rem;
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: 0.68rem;
  background: rgba(4, 12, 23, 0.5);
  color: #d8e4ef;
  font: inherit;
  font-size: 0.66rem;
  outline: none;
  transition:
    border-color 0.18s ease,
    background 0.18s ease;
  box-sizing: border-box;
}

.search-input::placeholder {
  color: #5a7080;
}

.search-input:focus {
  border-color: rgba(90, 213, 255, 0.3);
  background: rgba(4, 12, 23, 0.7);
}

.search-input::-webkit-search-cancel-button {
  cursor: pointer;
}

/* ── Library scroll area ────────────────────────────────────────────────── */
.library-scroll {
  overflow-y: auto;
  padding: 0 0.08rem 0 0;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

/* ── Category group ─────────────────────────────────────────────────────── */
.category-group {
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
}

.category-header-row {
  display: flex;
  align-items: center;
  gap: 0.28rem;
  min-width: 0;
}

.category-header {
  display: flex;
  align-items: center;
  gap: 0.32rem;
  flex: 1;
  min-width: 0;
  padding: 0.3rem 0.42rem;
  border: none;
  border-radius: 0.6rem;
  background: rgba(4, 12, 23, 0.3);
  color: var(--cat-color, #88d8ff);
  cursor: pointer;
  font: inherit;
  font-size: 0.62rem;
  font-weight: 600;
  transition:
    background 0.16s ease,
    transform 0.14s ease;
  text-align: left;
}

.category-header:hover {
  background: rgba(4, 12, 23, 0.5);
  transform: translateX(2px);
}

.cat-icon {
  font-size: 0.7rem;
  flex-shrink: 0;
}

.cat-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cat-arrow {
  display: inline-block;
  transition: transform 0.18s ease;
  font-size: 0.58rem;
  flex-shrink: 0;
}

.cat-header-actions {
  display: inline-flex;
  align-items: center;
  gap: 0.28rem;
  flex-shrink: 0;
  margin-left: auto;
}

.cat-count {
  padding: 0.05rem 0.22rem;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
  color: #8ea3b8;
  font-size: 0.52rem;
  flex-shrink: 0;
}

.cat-expand {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin: 0;
  padding: 0.1rem 0.18rem;
  border: none;
  border-radius: 0.35rem;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
  line-height: 1;
}

.cat-expand:hover {
  background: rgba(255, 255, 255, 0.06);
}

/* 分类标题行内「+全部」小按键（在数量右侧） */
.cat-batch-add {
  flex-shrink: 0;
  margin: 0;
  padding: 0.14rem 0.36rem;
  /* rgba — avoid color-mix() (html2canvas cannot parse it) */
  border: 1px solid rgba(136, 216, 255, 0.35);
  border-radius: 999px;
  background: rgba(136, 216, 255, 0.1);
  color: var(--cat-color, #88d8ff);
  cursor: pointer;
  font: inherit;
  font-size: 0.5rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  white-space: nowrap;
  transition:
    background 0.14s ease,
    border-color 0.14s ease,
    color 0.14s ease;
}

.cat-batch-add:hover {
  background: rgba(136, 216, 255, 0.22);
  border-color: rgba(136, 216, 255, 0.55);
}

/* ── Batch toolbar (active state) ────────────────────────────────────────── */
.batch-toolbar {
  display: flex;
  gap: 0.32rem;
  padding: 0.32rem 0.4rem;
  border: 1px solid rgba(148, 163, 184, 0.12);
  border-radius: 0.6rem;
  background: rgba(4, 12, 23, 0.32);
  margin-bottom: 0.4rem;
}

.batch-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.22rem;
  padding: 0.32rem 0.2rem;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 0.42rem;
  background: rgba(13, 24, 42, 0.4);
  color: #b8c8d8;
  cursor: pointer;
  font: inherit;
  font-size: 0.58rem;
  font-weight: 500;
  transition:
    background 0.14s ease,
    border-color 0.14s ease,
    color 0.14s ease;
}

.batch-btn:hover {
  background: rgba(34, 52, 78, 0.5);
  border-color: rgba(103, 212, 255, 0.34);
  color: #d8e8f8;
}

.batch-btn-danger:hover {
  background: rgba(78, 24, 34, 0.4);
  border-color: rgba(255, 111, 145, 0.4);
  color: #ffb0c0;
}

.cat-arrow.expanded {
  transform: rotate(90deg);
}

.category-items {
  display: grid;
  gap: 0.22rem;
  padding-left: 0.42rem;
}

/* ── Library card ───────────────────────────────────────────────────────── */
.library-card {
  display: grid;
  gap: 0.32rem;
  padding: var(--sidebar-section-padding) 0.5rem;
  border: 1px solid rgba(136, 192, 255, 0.08);
  border-radius: var(--sidebar-card-radius);
  background: linear-gradient(135deg, rgba(8, 18, 33, 0.6), rgba(8, 18, 33, 0.4));
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease,
    transform 0.18s ease;
}

.library-card:hover {
  border-color: rgba(136, 192, 255, 0.45);
  box-shadow: 0 8px 18px -8px var(--glow);
  transform: translateY(-1px);
}

.library-card.added {
  border-color: rgba(90, 213, 255, 0.18);
  background: linear-gradient(135deg, rgba(8, 18, 33, 0.7), rgba(10, 132, 255, 0.06));
}

.card-top {
  display: grid;
  gap: 0.12rem;
  /* 与 source-area 的 padding 对齐，保证三块内容左右边距一致 */
  padding: 0 0.32rem;
}

.card-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.32rem;
}

.card-title-row strong {
  color: #f3fbff;
  font-size: 0.72rem;
  font-weight: 600;
}

.card-chip {
  padding: 0.08rem 0.28rem;
  border-radius: 999px;
  color: #d9effd;
  font-size: 0.5rem;
  flex-shrink: 0;
}

.card-source {
  margin: 0;
  color: #7f93a9;
  font-size: 0.58rem;
}

/* ── Source area (数据源区域) ──────────────────────────────────────────── */
.source-area {
  display: grid;
  gap: 0.18rem;
  padding: var(--sidebar-inner-padding);
  border: 1px solid rgba(136, 192, 255, 0.06);
  border-radius: var(--sidebar-soft-radius);
  background: rgba(4, 12, 23, 0.32);
}

.source-weather-live {
  display: grid;
  gap: 0.2rem;
}

.weather-src-label {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  min-width: 0;
}

.weather-src-select {
  flex: 1;
  min-width: 0;
  font-size: 0.68rem;
  padding: 0.18rem 0.32rem;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(0, 0, 0, 0.28);
  color: inherit;
}

.src-sparse-hint {
  margin: 0;
  font-size: 0.58rem;
  opacity: 0.72;
  line-height: 1.3;
}

.source-empty {
  display: flex;
  align-items: center;
  gap: 0.32rem;
  color: #6a7e8e;
  font-size: 0.56rem;
}

.src-empty-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1rem;
  height: 1rem;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.05);
  color: #8a9eb0;
  font-size: 0.62rem;
}

.source-single {
  display: grid;
  gap: 0.18rem;
}

.src-line {
  display: flex;
  align-items: center;
  gap: 0.3rem;
}

.src-dot {
  width: 0.42rem;
  height: 0.42rem;
  border-radius: 50%;
  flex-shrink: 0;
  box-shadow: 0 0 6px currentColor;
}

.src-name {
  color: #d4e4f4;
  font-size: 0.6rem;
  font-weight: 500;
}

.src-meta {
  display: flex;
  align-items: center;
  gap: 0.24rem;
  flex-wrap: wrap;
  padding-left: 0.72rem;
}

.src-badge {
  padding: 0.06rem 0.28rem;
  border-radius: 999px;
  background: rgba(136, 192, 255, 0.1);
  color: #8fc8e8;
  font-size: 0.5rem;
}

.src-coord {
  color: #5a7080;
  font-size: 0.5rem;
  font-family: ui-monospace, 'SF Mono', monospace;
}

.src-auth,
.src-tfm {
  color: #8a9eb0;
  font-size: 0.56rem;
}

.source-multi {
  display: grid;
  gap: 0.18rem;
}

.source-summary {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  width: 100%;
  padding: 0.24rem 0.36rem;
  border: 1px solid rgba(136, 192, 255, 0.12);
  border-radius: 0.44rem;
  background: rgba(4, 12, 23, 0.4);
  color: #c8dff0;
  cursor: default;
  font: inherit;
  font-size: 0.58rem;
}

.src-current {
  flex: 1;
  text-align: left;
  color: #d4e4f4;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.src-count {
  padding: 0.04rem 0.24rem;
  border-radius: 999px;
  background: rgba(136, 192, 255, 0.14);
  color: #8fc8e8;
  font-size: 0.48rem;
  flex-shrink: 0;
}

.source-list {
  display: grid;
  gap: 0.12rem;
  padding: 0.12rem 0;
}

.source-option {
  display: grid;
  gap: 0.14rem;
  padding: 0.28rem 0.36rem;
  border: 1px solid rgba(136, 192, 255, 0.08);
  border-radius: 0.42rem;
  background: rgba(4, 12, 23, 0.3);
  color: #c8dff0;
  cursor: default;
  font: inherit;
  text-align: left;
}

.source-option-static {
  opacity: 0.92;
}

.src-opt-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.32rem;
}

.src-check {
  color: #5ad5ff;
  font-size: 0.58rem;
  flex-shrink: 0;
}

/* ── Card actions ───────────────────────────────────────────────────────── */
.card-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.3rem;
  /* 与 source-area 的 padding 对齐，保证三块内容左右边距一致 */
  padding: 0 0.32rem;
}

.run-block-note {
  padding: 0 0.32rem;
  color: #ffd38a;
  font-size: 0.54rem;
  line-height: 1.35;
}

.catalog-note-sample {
  color: #ffb8d2;
}

.card-metric {
  color: #7f93a9;
  font-size: 0.56rem;
}

.add-btn {
  padding: 0.18rem 0.46rem;
  border: 1px solid rgba(90, 213, 255, 0.28);
  border-radius: 999px;
  background: rgba(10, 132, 255, 0.12);
  color: #5ad5ff;
  cursor: pointer;
  font: inherit;
  font-size: 0.58rem;
  font-weight: 600;
  transition:
    background 0.18s ease,
    border-color 0.18s ease,
    transform 0.16s ease;
}

.add-btn:hover:not(:disabled) {
  background: rgba(10, 132, 255, 0.24);
  border-color: rgba(90, 213, 255, 0.5);
  transform: translateY(-1px);
}

.add-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.added-label {
  color: #9ff8cf;
  font-size: 0.58rem;
  font-weight: 600;
}

/* ── 工作流状态徽标（library 卡片自动运行反馈） ──────────────────────────── */
.job-status-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.22rem;
  padding: 0.12rem 0.4rem;
  border-radius: 999px;
  font-size: 0.54rem;
  font-weight: 600;
  border: 1px solid transparent;
}

.job-status-running {
  color: #5ad5ff;
  background: rgba(10, 132, 255, 0.12);
  border-color: rgba(90, 213, 255, 0.2);
}

.job-status-queued {
  color: #d7c1ff;
  background: rgba(187, 137, 255, 0.08);
  border-color: rgba(187, 137, 255, 0.14);
}

.job-status-succeeded {
  color: #9ff8cf;
  background: rgba(114, 255, 207, 0.1);
  border-color: rgba(114, 255, 207, 0.18);
}

.job-status-failed {
  color: #ff8080;
  background: rgba(255, 80, 80, 0.1);
  border-color: rgba(255, 80, 80, 0.18);
}

.job-status-cancelled {
  color: #8aa8bf;
  background: rgba(138, 168, 191, 0.1);
  border-color: rgba(138, 168, 191, 0.18);
}

.spin-dot {
  display: inline-block;
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  border: 1.5px solid rgba(90, 213, 255, 0.3);
  border-top-color: #5ad5ff;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* ── Active state ───────────────────────────────────────────────────────── */
.active-state {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  flex: 1;
  /* 列表内容超出时由 layer-list 滚动 */
  min-height: 0;
  overflow: hidden;
}

.no-layers {
  display: grid;
  gap: 0.42rem;
  padding: 1.4rem 0.8rem;
  text-align: center;
  color: #7f93a9;
  font-size: 0.62rem;
}

/* 图层列表：参考 ArcGIS Pro 紧凑设计
   - 不强制撑满侧边栏高度（无 flex:1），按内容高度排列
   - 列表项较多时仍可滚动 */
.layer-list {
  display: grid;
  gap: 0.16rem;
  list-style: none;
  padding: 0;
  margin: 0;
  /* 关键：内容多时自动滚动，内容少时按内容高度排列（不撑满） */
  overflow-y: auto;
  align-content: start;
  flex: 0 1 auto;
  min-height: 0;
  padding-right: 0.08rem;
}

/* ── Layer item ────────────────────────────────────────────────────────── */
.layer-item {
  display: grid;
  /* 始终展示三行：主行 + 图例 + 底行，统一间距 */
  gap: 0.18rem;
  padding: 0.3rem 0.42rem;
  border: 1px solid rgba(136, 192, 255, 0.28);
  border-left: 3px solid var(--accent, #67d4ff);
  border-radius: var(--sidebar-soft-radius);
  background: rgba(8, 18, 33, 0.86);
  color: #d8e4ef;
  font: inherit;
  font-size: 0.66rem;
  transition:
    border-color 0.2s ease,
    background-color 0.2s ease,
    box-shadow 0.2s ease,
    opacity 0.2s ease;
  user-select: none;
}

.layer-item:hover {
  border-color: rgba(90, 162, 255, 0.55);
  box-shadow: 0 4px 12px -8px rgba(90, 162, 255, 0.35);
}

.layer-item.active {
  background: rgba(20, 40, 72, 0.92);
  border-color: rgba(90, 162, 255, 0.65);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.03),
    0 12px 22px -18px rgba(90, 162, 255, 0.4);
}

.layer-item.hidden {
  opacity: 0.55;
}

.layer-item.drag-over {
  border-color: rgba(90, 213, 255, 0.6);
  background: rgba(10, 132, 255, 0.08);
  transition:
    border-color 0.08s ease,
    background-color 0.08s ease;
}

.layer-group-header {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  margin: 0.35rem 0 0.15rem;
  padding: 0.42rem 0.5rem;
  border: 1px solid rgba(90, 213, 255, 0.22);
  border-radius: var(--sidebar-soft-radius);
  background: linear-gradient(90deg, rgba(14, 40, 62, 0.95) 0%, rgba(10, 24, 40, 0.88) 100%);
  box-shadow: inset 3px 0 0 rgba(90, 213, 255, 0.65);
  cursor: grab;
  user-select: none;
}

.layer-group-header.computing {
  border-color: rgba(255, 196, 86, 0.35);
  box-shadow: inset 3px 0 0 rgba(255, 196, 86, 0.75);
}

.layer-group-header.drag-over {
  border-color: rgba(90, 213, 255, 0.7);
  background: rgba(10, 132, 255, 0.12);
}

.group-accent {
  width: 0.28rem;
  height: 1.1rem;
  border-radius: 999px;
  background: rgba(90, 213, 255, 0.85);
  flex-shrink: 0;
}

.group-title {
  font-size: 0.72rem;
  font-weight: 650;
  color: #e8f3fb;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.group-status-chip {
  font-size: 0.58rem;
  color: #9ec3d8;
  max-width: 9rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.group-progress-track {
  width: 2.4rem;
  height: 0.28rem;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
  flex-shrink: 0;
}

.group-progress-fill {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, #5ad5ff, #67ffb0);
}

.group-count {
  font-size: 0.58rem;
  color: #7f9bb0;
  flex-shrink: 0;
}

.layer-item.in-run-group {
  margin-left: 0.55rem;
  border-left-width: 2px;
  background: rgba(8, 18, 33, 0.78);
}

.layer-item.group-locked {
  opacity: 0.92;
}

/* ── Layer row top (主行紧凑布局) ──────────────────────────────────────── */
.layer-row-top {
  display: flex;
  align-items: center;
  gap: 0.24rem;
}

.drag-handle {
  color: #3d5060;
  font-size: 0.56rem;
  cursor: grab;
  flex-shrink: 0;
  transition: color 0.16s ease;
}

.drag-handle:hover {
  color: #8ea3b8;
}
.drag-handle:active {
  cursor: grabbing;
}

.vis-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 1.05rem;
  height: 1.05rem;
  border: none;
  border-radius: 0.36rem;
  background: transparent;
  color: #6e8ba0;
  cursor: pointer;
  font-size: 0.62rem;
  flex-shrink: 0;
  transition:
    color 0.16s ease,
    background 0.16s ease;
  padding: 0;
}

.vis-btn:hover {
  background: rgba(136, 192, 255, 0.1);
  color: #c8dff0;
}

.layer-color-dot {
  width: 0.36rem;
  height: 0.36rem;
  border-radius: 50%;
  flex-shrink: 0;
  box-shadow: 0 0 4px currentColor;
}

.layer-name {
  flex: 1;
  color: #f3fbff;
  font-size: 0.68rem;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.layer-chip {
  padding: 0.06rem 0.24rem;
  border-radius: 999px;
  color: #d9effd;
  font-size: 0.48rem;
  flex-shrink: 0;
}

.del-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 1.05rem;
  height: 1.05rem;
  border: none;
  border-radius: 0.36rem;
  background: transparent;
  color: #4a5560;
  cursor: pointer;
  font-size: 0.56rem;
  flex-shrink: 0;
  transition:
    color 0.16s ease,
    background 0.16s ease;
  padding: 0;
}

.del-btn:hover {
  background: rgba(255, 100, 100, 0.12);
  color: #ff8080;
}

/* ── Layer legend (颜色图例 - 参考 ArcGIS TOC) ─────────────────────────── */
.layer-legend {
  display: grid;
  gap: 0.1rem;
  padding: 0 0.12rem;
}

.legend-ramp {
  width: 100%;
  height: 0.46rem;
  border-radius: 0.18rem;
  border: 1px solid rgba(136, 192, 255, 0.1);
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.16);
}

.legend-labels {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.2rem;
}

.legend-min,
.legend-max {
  color: #7d93a8;
  font-size: 0.48rem;
  font-variant-numeric: tabular-nums;
  font-family: ui-monospace, 'SF Mono', monospace;
}

.legend-unit {
  color: #5e7488;
  font-size: 0.46rem;
  letter-spacing: 0.02em;
}

/* ── Layer row bottom (底行状态信息) ────────────────────────────────────── */
.layer-row-bottom {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  flex-wrap: wrap;
  padding-top: 0.16rem;
  border-top: 1px solid rgba(136, 192, 255, 0.06);
}

.availability-chip {
  padding: 0.06rem 0.26rem;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.12);
  background: rgba(148, 163, 184, 0.08);
  font-size: 0.5rem;
}

.availability-ready {
  color: #9ff8cf;
  border-color: rgba(114, 255, 207, 0.2);
  background: rgba(114, 255, 207, 0.1);
}
.availability-partial {
  color: #ffd38a;
  border-color: rgba(255, 196, 120, 0.18);
  background: rgba(255, 196, 120, 0.08);
}
.availability-empty {
  color: #cbb8ff;
  border-color: rgba(187, 137, 255, 0.18);
  background: rgba(187, 137, 255, 0.08);
}

.order-hint {
  color: #5a7080;
  font-size: 0.5rem;
  margin-left: auto;
}

.admin-tip-inline {
  color: #7fbbdd;
  font-size: 0.5rem;
}

/* ── Job badge ─────────────────────────────────────────────────────────── */
.job-status-badge {
  padding: 0.06rem 0.26rem;
  border-radius: 999px;
  font-size: 0.5rem;
  font-weight: 600;
}

.job-running {
  color: #5ad5ff;
  background: rgba(10, 132, 255, 0.12);
  border: 1px solid rgba(90, 213, 255, 0.2);
}

.job-succeeded {
  color: #9ff8cf;
  background: rgba(114, 255, 207, 0.1);
  border: 1px solid rgba(114, 255, 207, 0.18);
}

.job-failed {
  color: #ff8080;
  background: rgba(255, 80, 80, 0.1);
  border: 1px solid rgba(255, 80, 80, 0.18);
}

.job-queued,
.job-cancelled {
  color: #d7c1ff;
  background: rgba(187, 137, 255, 0.08);
  border: 1px solid rgba(187, 137, 255, 0.14);
}

.job-retry_pending {
  color: #ffd38a;
  background: rgba(255, 211, 138, 0.1);
  border: 1px solid rgba(255, 196, 120, 0.18);
}

.job-report-hint {
  border: none;
  background: transparent;
  color: #5ad5ff;
  font-size: 0.5rem;
  cursor: pointer;
  text-decoration: underline;
  text-decoration-style: dotted;
  padding: 0;
  white-space: nowrap;
}

/* ── Footer ─────────────────────────────────────────────────────────────── */
.panel-footnote {
  margin: 0;
  padding: 0.12rem;
  color: #7f95aa;
  line-height: 1.35;
  font-size: 0.64rem;
}

/* ── 右键上下文菜单 ──────────────────────────────────────────────────────── */
.ctx-menu {
  position: fixed;
  z-index: 9999;
  min-width: 8rem;
  padding: 0.2rem;
  border: 1px solid rgba(90, 162, 255, 0.24);
  border-radius: 0.5rem;
  background: rgba(10, 20, 36, 0.96);
  backdrop-filter: blur(12px);
  box-shadow:
    0 12px 32px -12px rgba(0, 0, 0, 0.6),
    0 0 0 1px rgba(136, 192, 255, 0.04);
  font-size: 0.6rem;
  animation: ctx-fade-in 0.12s ease;
}

@keyframes ctx-fade-in {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.ctx-item {
  display: flex;
  align-items: center;
  gap: 0.36rem;
  width: 100%;
  padding: 0.3rem 0.4rem;
  border: none;
  border-radius: 0.36rem;
  background: transparent;
  color: #b8ccdf;
  cursor: pointer;
  font: inherit;
  font-size: 0.6rem;
  text-align: left;
  transition:
    background 0.12s ease,
    color 0.12s ease;
}

.ctx-item:hover {
  background: rgba(90, 162, 255, 0.14);
  color: #e8f4ff;
}

.ctx-item:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  pointer-events: none;
}

.ctx-item.ctx-danger:hover {
  background: rgba(255, 80, 80, 0.14);
  color: #ff9a9a;
}

.ctx-sep {
  height: 1px;
  margin: 0.18rem 0.28rem;
  background: rgba(136, 172, 204, 0.14);
}

.ctx-icon {
  font-size: 0.66rem;
  width: 1rem;
  text-align: center;
}

.subcategory-pills-bar {
  display: flex;
  gap: 0.35rem;
  margin: 0.3rem 0.5rem 0.5rem 0.5rem;
}

.sub-pill {
  border: 1px solid rgba(136, 192, 255, 0.16);
  border-radius: 999px;
  padding: 0.18rem 0.5rem;
  background: rgba(15, 23, 42, 0.4);
  color: #94a3b8;
  font-size: 0.7rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.sub-pill:hover {
  border-color: rgba(136, 192, 255, 0.35);
  color: #e2e8f0;
}

.sub-pill.active {
  border-color: #ff6f91;
  background: rgba(255, 111, 145, 0.16);
  color: #ff6f91;
  font-weight: 500;
}

.empty-subcategory-hint {
  padding: 0.75rem 0.5rem;
  font-size: 0.75rem;
  color: #94a3b8;
  text-align: center;
  background: rgba(15, 23, 42, 0.25);
  border-radius: 6px;
  margin: 0.35rem 0.5rem;
  border: 1px dashed rgba(148, 163, 184, 0.2);
}

/* 侧栏细体纵向滚动条 */
.library-scroll::-webkit-scrollbar,
.active-layers-scroll::-webkit-scrollbar,
.layer-sidebar-container::-webkit-scrollbar {
  width: 4px;
  height: 4px;
}
.library-scroll::-webkit-scrollbar-thumb,
.active-layers-scroll::-webkit-scrollbar-thumb,
.layer-sidebar-container::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.16);
  border-radius: 4px;
}
.library-scroll::-webkit-scrollbar-thumb:hover,
.active-layers-scroll::-webkit-scrollbar-thumb:hover,
.layer-sidebar-container::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.32);
}
</style>
