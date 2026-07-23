<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { storeToRefs } from 'pinia'

import { useLayersStore } from '../stores/layers'
import { useUiStore } from '../stores/ui'
import { useLogStore } from '../stores/log'
import type { RuntimeLayerLibraryItem } from '../stores/layers/types'
import {
  WEATHER_PALETTE_OPTIONS,
  buildWeatherLegendGradient,
  isMapLinkedPalette,
  resolveCanonicalPaletteId,
  resolveStyleRenderHint,
  resolveSymbologyColors,
} from './map/layer-symbology'
import { useOverlaySymbologyStore } from '../stores/overlay-symbology'
import { useWeatherSourcePrefsStore } from '../stores/weather-source-prefs'
import {
  DEFAULT_WEATHER_MODEL as DEFAULT_TILE_MODEL,
  isWeatherLayerUnsupportedByModel,
} from '../stores/weather-tile-manager'
import { getWeatherProvidersForLayer, type WeatherProviderForLayer } from '../services/runtime-api'

const emit = defineEmits<{
  selectLayer: [instanceId: string]
}>()

const layersStore = useLayersStore()
const uiStore = useUiStore()
const logStore = useLogStore()
const overlaySymbologyStore = useOverlaySymbologyStore()
const weatherSourcePrefs = useWeatherSourcePrefsStore()

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
const dragOverInstanceId = ref<string | null>(null)

// ── Filter library items by search ────────────────────────────────────────────

const filteredLibrary = computed(() => {
  if (!searchQuery.value.trim()) return layerLibrary.value
  const q = searchQuery.value.toLowerCase()
  return layerLibrary.value.filter(
    (item) =>
      item.name.toLowerCase().includes(q) ||
      item.category.toLowerCase().includes(q) ||
      item.sourceLabel.toLowerCase().includes(q) ||
      item.description.toLowerCase().includes(q),
  )
})

const filteredLibraryByCategory = computed(() => {
  const map = new Map(
    layerCategories.map((c) => [c.id, { category: c, items: [] as RuntimeLayerLibraryItem[] }]),
  )
  for (const item of filteredLibrary.value) {
    if (map.has(item.category)) {
      map.get(item.category)!.items.push(item)
    }
  }
  return Array.from(map.values()).filter((g) => g.items.length > 0)
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
  if (isWeatherLayerUnsupportedByModel(catalogId, DEFAULT_TILE_MODEL)) {
    return `当前模型（${DEFAULT_TILE_MODEL}）不提供该图层变量，请切换其他气象模型。`
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
}

function openActive() {
  // 显式切到已添加列表；即使当前已是 active 也再写一次，避免偶发状态不同步
  layersStore.setSidebarView('active')
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

/** 批量移除所有图层（保留行政区边界） */
function removeAllLayers() {
  layersStore.removeAllLayers(true)
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

function openJobReport(instanceId: string) {
  selectItem(instanceId)
  uiStore.requestAnalysisFocus(['report-section', 'result-section', 'scheduler-status'])
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

function onDragStart(instanceId: string) {
  draggedInstanceId.value = instanceId
}

function onDragOver(instanceId: string, event: DragEvent) {
  event.preventDefault()
  dragOverInstanceId.value = instanceId
}

function onDrop(targetInstanceId: string) {
  if (!draggedInstanceId.value || draggedInstanceId.value === targetInstanceId) return
  const sorted = activeLayersDisplay.value
  const fromIndex = sorted.findIndex((d) => d.instanceId === draggedInstanceId.value)
  const toIndex = sorted.findIndex((d) => d.instanceId === targetInstanceId)
  if (fromIndex === -1) {
    draggedInstanceId.value = null
    dragOverInstanceId.value = null
    return
  }
  if (toIndex !== -1) {
    layersStore.reorderLayers(fromIndex, toIndex)
  }
  draggedInstanceId.value = null
  dragOverInstanceId.value = null
}

function onDragEnd() {
  draggedInstanceId.value = null
  dragOverInstanceId.value = null
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
    sources.find((s) => s.id === id)?.name ?? (sources.length === 0 ? '暂无可用数据源' : '未选择')
  )
}

function getCatalogSourceSummary(catalogId: string): string {
  const sources = getCatalogSources(catalogId)
  if (!sources.length) return '暂无可用数据源'
  return sources.map((source) => source.name).join(' / ')
}

// ── 符号系统 (Symbology) ─────────────────────────────────────────────────────

// ── 右键菜单与符号系统浮窗 ───────────────────────────────────────────────────

interface ContextMenuState {
  instanceId: string
  x: number
  y: number
}

const contextMenu = ref<ContextMenuState | null>(null)
const symbologyPanel = ref<ContextMenuState | null>(null)

const contextMenuLayer = computed(() => {
  if (!contextMenu.value) return null
  return (
    activeLayersDisplay.value.find((l) => l.instanceId === contextMenu.value!.instanceId) ?? null
  )
})

/** 右键图层条目时弹出上下文菜单 */
function onLayerContextMenu(instanceId: string, event: MouseEvent) {
  event.preventDefault()
  // 边界检测：防止菜单超出视口
  const MENU_W = 180
  const MENU_H = 220
  const vw = window.innerWidth
  const vh = window.innerHeight
  const x = Math.min(event.clientX, vw - MENU_W - 8)
  const y = Math.min(event.clientY, vh - MENU_H - 8)
  contextMenu.value = { instanceId, x: Math.max(8, x), y: Math.max(8, y) }
}

function closeContextMenu() {
  contextMenu.value = null
}

/** 从右键菜单打开"符号系统"浮窗 */
function openSymbologyFromMenu() {
  if (!contextMenu.value) return
  // 边界检测：防止浮窗超出视口
  const POPOVER_W = 220
  const POPOVER_H = 240
  const vw = window.innerWidth
  const vh = window.innerHeight
  const x = Math.min(contextMenu.value.x, vw - POPOVER_W - 8)
  const y = Math.min(contextMenu.value.y, vh - POPOVER_H - 8)
  symbologyPanel.value = {
    instanceId: contextMenu.value.instanceId,
    x: Math.max(8, x),
    y: Math.max(8, y),
  }
  // 异步获取 overlay 元数据
  const layer = activeLayersDisplay.value.find(
    (l) => l.instanceId === contextMenu.value!.instanceId,
  )
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

/** 右键菜单：查看详情（选中图层） */
function viewDetailFromMenu() {
  if (!contextMenu.value) return
  selectItem(contextMenu.value.instanceId)
  closeContextMenu()
}

/** 右键菜单：移除图层 */
function removeLayerFromMenu() {
  if (!contextMenu.value) return
  removeItem(contextMenu.value.instanceId, new MouseEvent('click'))
  closeContextMenu()
}

function exportImportedGeoJsonFromMenu() {
  if (!contextMenu.value) return
  const layer = contextMenuLayer.value
  const geojson = layersStore.getImportedVectorGeojson(contextMenu.value.instanceId)
  if (!layer || !geojson) {
    logStore.logOperation('export-fail', '当前图层不是可导出的导入矢量')
    closeContextMenu()
    return
  }
  void import('../stores/layers/imported-vector').then(({ exportFeatureCollectionAsGeoJson }) => {
    exportFeatureCollectionAsGeoJson(geojson, layer.name)
    logStore.logOperation(
      'export-geojson',
      `导出 GeoJSON「${layer.name}」`,
      `要素数: ${geojson.features.length}`,
    )
  })
  closeContextMenu()
}

function exportImportedCsvFromMenu() {
  if (!contextMenu.value) return
  const layer = contextMenuLayer.value
  const geojson = layersStore.getImportedVectorGeojson(contextMenu.value.instanceId)
  if (!layer || !geojson) {
    logStore.logOperation('export-fail', '当前图层不是可导出的导入矢量')
    closeContextMenu()
    return
  }
  void import('../stores/layers/imported-vector').then(({ exportFeatureCollectionAsCsv }) => {
    exportFeatureCollectionAsCsv(geojson, layer.name)
    logStore.logOperation(
      'export-csv',
      `导出 CSV「${layer.name}」`,
      `要素数: ${geojson.features.length}`,
    )
  })
  closeContextMenu()
}

function closeSymbologyPanel() {
  symbologyPanel.value = null
}

/** 点击页面空白处关闭浮窗 */
function onGlobalClick(event: MouseEvent) {
  const target = event.target as HTMLElement
  if (contextMenu.value && !target.closest('.ctx-menu')) {
    closeContextMenu()
  }
  if (symbologyPanel.value && !target.closest('.sym-popover') && !target.closest('.ctx-menu')) {
    closeSymbologyPanel()
  }
}

/** ESC 关闭浮窗 */
function onGlobalKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    closeSymbologyPanel()
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

function getSymbologyVmin(layer: ActiveLayerDisplayLike): string {
  if (layer.renderHint?.legend_ticks?.length) {
    const first = layer.renderHint.legend_ticks[0]
    return typeof first === 'number' ? String(first) : '—'
  }
  void overlaySymbologyStore.version
  const meta = overlaySymbologyStore.getMeta(layer.catalogId)
  if (meta?.vmin != null) return String(meta.vmin)
  return '—'
}

function getSymbologyVmax(layer: ActiveLayerDisplayLike): string {
  if (layer.renderHint?.legend_ticks?.length) {
    const last = layer.renderHint.legend_ticks[layer.renderHint.legend_ticks.length - 1]
    return typeof last === 'number' ? String(last) : '—'
  }
  void overlaySymbologyStore.version
  const meta = overlaySymbologyStore.getMeta(layer.catalogId)
  if (meta?.vmax != null) return String(meta.vmax)
  return '—'
}

function getSymbologyUnit(layer: ActiveLayerDisplayLike): string {
  if (layer.renderHint?.unit_label) return layer.renderHint.unit_label
  void overlaySymbologyStore.version
  const meta = overlaySymbologyStore.getMeta(layer.catalogId)
  if (meta?.unit) return meta.unit
  return ''
}

function getSymbologyMetric(layer: ActiveLayerDisplayLike): string {
  return layer.metricLabel || '—'
}

function handleSymbologyOpacity(instanceId: string, event: Event) {
  const target = event.target as HTMLInputElement
  layersStore.setLayerOpacity(instanceId, Number(target.value) / 100)
}

function canEditSymbologyPalette(layer: ActiveLayerDisplayLike): boolean {
  return isMapLinkedPalette({
    hasRenderHint: Boolean(layer.renderHint),
    isImportedRaster: layer.isImportedRaster,
  })
}

function handleSymbologyPalette(instanceId: string, paletteId: string) {
  const layer = activeLayersDisplay.value.find((l) => l.instanceId === instanceId)
  if (!layer || !canEditSymbologyPalette(layer)) return
  const defaultPalette = layer.renderHint?.palette ?? ''
  const target = paletteId === defaultPalette ? null : paletteId
  layersStore.setLayerPaletteOverride(instanceId, target)
}

function getColorRampStyle(layer: ActiveLayerDisplayLike): Record<string, string> {
  void overlaySymbologyStore.version
  // 与 InfoPanel 同源：resolveStyleRenderHint + buildWeatherLegendGradient
  const hint = resolveStyleRenderHint({
    paletteOverride: layer.paletteOverride,
    renderHint: layer.renderHint ?? null,
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

function currentSymbologyPaletteId(layer: ActiveLayerDisplayLike): string {
  void overlaySymbologyStore.version
  return resolveCanonicalPaletteId(
    layer.paletteOverride ??
      layer.renderHint?.palette ??
      overlaySymbologyStore.getMeta(layer.catalogId)?.palette ??
      '',
  )
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

/** 符号系统浮窗当前关联的图层 */
const symbologyPanelLayer = computed(() => {
  if (!symbologyPanel.value) return null
  return (
    activeLayersDisplay.value.find((l) => l.instanceId === symbologyPanel.value!.instanceId) ?? null
  )
})
</script>

<template>
  <aside class="panel">
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
          <span v-if="activeLayerCount > 0" class="badge">{{ activeLayerCount }}</span>
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
      <p class="empty-title">图层为空</p>
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
                  <span class="card-chip" :style="{ background: item.chipTone }">{{
                    getCategoryName(item.category)
                  }}</span>
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
                        <option value="auto">自动（优先本地 Open-Meteo）</option>
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
                    <span>暂无可用数据源</span>
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
        <p>暂无已添加图层。</p>
        <button class="empty-cta small" @click="openLibrary">去添加</button>
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
          <button
            class="batch-btn batch-btn-danger"
            title="移除所有图层（边界除外）"
            @click="removeAllLayers"
          >
            <span aria-hidden="true">✕</span> 全部移除
          </button>
        </div>

        <!-- 图层列表：参考 ArcGIS Pro 紧凑设计，按内容高度排列，不强制撑满 -->
        <ul class="layer-list" role="listbox" aria-label="已添加图层">
          <li
            v-for="(layer, index) in activeLayersDisplay"
            :key="layer.instanceId"
            class="layer-item"
            :class="{
              active: layer.instanceId === selectedInstanceId,
              hidden: !layer.visible,
              'drag-over': layer.instanceId === dragOverInstanceId,
            }"
            :style="{
              '--accent': layer.accentColor,
              '--glow': layer.accentGlow,
            }"
            draggable="true"
            role="option"
            :aria-selected="layer.instanceId === selectedInstanceId"
            @click="selectItem(layer.instanceId)"
            @contextmenu="onLayerContextMenu(layer.instanceId, $event)"
            @dragstart="onDragStart(layer.instanceId)"
            @dragover="onDragOver(layer.instanceId, $event)"
            @drop="onDrop(layer.instanceId)"
            @dragend="onDragEnd"
          >
            <!-- 主行：紧凑单行布局 -->
            <div class="layer-row-top">
              <span class="drag-handle" title="拖动排序">☰</span>
              <button
                class="vis-btn"
                :title="layer.visible ? '隐藏图层' : '显示图层'"
                @click="toggleVisibility(layer.instanceId, $event)"
              >
                <span aria-hidden="true">{{ layer.visible ? '◉' : '◯' }}</span>
              </button>
              <span
                class="layer-color-dot"
                :style="{ background: layer.accentColor }"
                aria-hidden="true"
              ></span>
              <strong class="layer-name">{{ layer.name }}</strong>
              <span class="layer-chip" :style="{ background: layer.chipTone }">{{
                getCategoryName(layer.category)
              }}</span>
              <button
                class="del-btn"
                title="移除图层"
                @click="removeItem(layer.instanceId, $event)"
              >
                <span aria-hidden="true">✕</span>
              </button>
            </div>

            <!-- 颜色图例（参考 ArcGIS TOC：仅支持显示的图层展示色带） -->
            <div v-if="hasColorSymbology(layer)" class="layer-legend">
              <div class="legend-ramp" :style="getColorRampStyle(layer)"></div>
              <div class="legend-labels">
                <span class="legend-min">{{ getSymbologyVmin(layer) }}</span>
                <span class="legend-unit">{{ getSymbologyUnit(layer) }}</span>
                <span class="legend-max">{{ getSymbologyVmax(layer) }}</span>
              </div>
            </div>

            <!-- 底行：状态信息（样板可运行、顺序、作业状态） -->
            <div class="layer-row-bottom">
              <span class="availability-chip" :class="availabilityClass(layer.availabilityState)">
                {{ layer.availabilityLabel }}
              </span>
              <span v-if="layer.isAdminBoundary" class="admin-tip-inline">边界 · 静态矢量</span>
              <span v-else-if="layer.isImported" class="admin-tip-inline"
                >导入 · {{ layer.importedGeometryType }} ·
                {{ layer.importedFeatureCount }} 要素</span
              >
              <span v-else-if="layer.isImportedRaster" class="admin-tip-inline"
                >导入 · 栅格 · TIF</span
              >
              <template v-if="layer.jobLayer">
                <span class="job-status-badge" :class="`job-${layer.jobLayer.status}`">
                  {{
                    layer.jobLayer.status === 'running'
                      ? `运行中 ${layer.jobLayer.progress}%`
                      : layer.jobLayer.status === 'queued'
                        ? '排队中'
                        : layer.jobLayer.status === 'retry_pending'
                          ? '等待重试'
                          : layer.jobLayer.status === 'succeeded'
                            ? '已完成'
                            : layer.jobLayer.status === 'failed'
                              ? '失败'
                              : layer.jobLayer.status === 'cancelled'
                                ? '已取消'
                                : layer.jobLayer.status
                  }}
                </span>
                <button
                  v-if="layer.jobLayer.reportSummary"
                  class="job-report-hint"
                  type="button"
                  @click.stop="openJobReport(layer.instanceId)"
                >
                  查看报告
                </button>
              </template>
              <span class="order-hint"
                >顺序 {{ index + 1 }} / {{ activeLayersDisplay.length }}</span
              >
            </div>
          </li>
        </ul>
      </template>
    </div>

    <!-- ── Footer ──────────────────────────────────────────────────────────── -->
    <p class="panel-footnote">
      <template v-if="sidebarView === 'active'">拖动排序 · 右键符号系统 / 导出</template>
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
        <button
          v-if="contextMenuLayer && !contextMenuLayer.isAdminBoundary"
          class="ctx-item"
          type="button"
          @click="openSymbologyFromMenu"
        >
          <span class="ctx-icon" aria-hidden="true">🎨</span>
          <span>{{ hasColorSymbology(contextMenuLayer) ? '符号系统' : '透明度' }}</span>
        </button>
        <button class="ctx-item" type="button" @click="viewDetailFromMenu">
          <span class="ctx-icon" aria-hidden="true">ℹ</span>
          <span>查看详情</span>
        </button>
        <template v-if="contextMenuLayer?.isImported">
          <div class="ctx-sep" role="separator"></div>
          <button class="ctx-item" type="button" @click="exportImportedGeoJsonFromMenu">
            <span class="ctx-icon" aria-hidden="true">⇩</span>
            <span>导出 GeoJSON</span>
          </button>
          <button class="ctx-item" type="button" @click="exportImportedCsvFromMenu">
            <span class="ctx-icon" aria-hidden="true">⇩</span>
            <span>导出 CSV</span>
          </button>
        </template>
        <div class="ctx-sep" role="separator"></div>
        <button class="ctx-item ctx-danger" type="button" @click="removeLayerFromMenu">
          <span class="ctx-icon" aria-hidden="true">✕</span>
          <span>移除图层</span>
        </button>
      </div>

      <!-- ── 符号系统浮窗（Teleport 到 body） ─────────────────────────────── -->
      <div
        v-if="symbologyPanel && symbologyPanelLayer"
        class="sym-popover"
        :style="{
          left: symbologyPanel.x + 'px',
          top: symbologyPanel.y + 'px',
          '--accent': symbologyPanelLayer.accentColor,
        }"
        @click.stop
      >
        <div class="sym-popover-header">
          <span class="sym-popover-title">{{
            hasColorSymbology(symbologyPanelLayer) ? '符号系统' : '透明度'
          }}</span>
          <button class="sym-popover-close" type="button" @click="closeSymbologyPanel">✕</button>
        </div>
        <div class="sym-popover-body">
          <!-- 图层名 -->
          <div class="sym-layer-name">{{ symbologyPanelLayer.name }}</div>

          <template v-if="hasColorSymbology(symbologyPanelLayer)">
            <!-- 字段/指标 -->
            <div class="sym-field-row">
              <span class="sym-field-label">字段</span>
              <span class="sym-field-value">{{ getSymbologyMetric(symbologyPanelLayer) }}</span>
            </div>

            <!-- 色带条 -->
            <div class="sym-color-ramp" :style="getColorRampStyle(symbologyPanelLayer)"></div>

            <!-- 值域范围 -->
            <div class="sym-range-row">
              <span class="sym-range-min">{{ getSymbologyVmin(symbologyPanelLayer) }}</span>
              <span class="sym-range-unit">{{ getSymbologyUnit(symbologyPanelLayer) }}</span>
              <span class="sym-range-max">{{ getSymbologyVmax(symbologyPanelLayer) }}</span>
            </div>

            <!-- 配色方案：仅地图会跟随 palette 的图层可改；预渲染 overlay 只读 -->
            <div
              v-if="
                symbologyPanelLayer.renderHint ||
                overlaySymbologyStore.getMeta(symbologyPanelLayer.catalogId)?.palette
              "
              class="sym-palette-row"
            >
              <span class="sym-field-label">配色</span>
              <select
                class="sym-palette-select"
                :value="currentSymbologyPaletteId(symbologyPanelLayer)"
                :disabled="!canEditSymbologyPalette(symbologyPanelLayer)"
                :title="
                  canEditSymbologyPalette(symbologyPanelLayer)
                    ? '切换地图配色'
                    : '预渲染栅格图例，改配色不会重涂 PNG'
                "
                @change="
                  handleSymbologyPalette(
                    symbologyPanelLayer.instanceId,
                    ($event.target as HTMLSelectElement).value,
                  )
                "
              >
                <option v-for="opt in WEATHER_PALETTE_OPTIONS" :key="opt.id" :value="opt.id">
                  {{ opt.label }}
                </option>
              </select>
            </div>
            <p
              v-if="
                !canEditSymbologyPalette(symbologyPanelLayer) &&
                (symbologyPanelLayer.renderHint ||
                  overlaySymbologyStore.getMeta(symbologyPanelLayer.catalogId)?.palette)
              "
              class="sym-palette-hint"
            >
              预渲染图例，不支持前端改色
            </p>
          </template>

          <!-- 透明度（与"分析"面板同步） -->
          <div class="sym-opacity-row">
            <span>透明度</span>
            <input
              class="sym-opacity-slider"
              type="range"
              min="0"
              max="100"
              :value="Math.round(symbologyPanelLayer.opacity * 100)"
              @input="handleSymbologyOpacity(symbologyPanelLayer.instanceId, $event)"
            />
            <strong>{{ Math.round(symbologyPanelLayer.opacity * 100) }}%</strong>
          </div>
        </div>
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
  /* 不要 sticky 实色底：会盖住面板顶部圆角，看起来像直角 */
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
  min-width: 1.65rem;
  padding: 0.18rem 0.34rem;
  border-radius: 999px;
  background: rgba(103, 212, 255, 0.14);
  color: #8fe7ff;
  text-align: center;
  font-size: 0.58rem;
  flex: 0 0 auto;
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
  border: 1px solid color-mix(in srgb, var(--cat-color, #88d8ff) 35%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--cat-color, #88d8ff) 10%, transparent);
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
  background: color-mix(in srgb, var(--cat-color, #88d8ff) 22%, transparent);
  border-color: color-mix(in srgb, var(--cat-color, #88d8ff) 55%, transparent);
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
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: var(--sidebar-soft-radius);
  background: rgba(8, 18, 33, 0.5);
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
  border-color: rgba(90, 162, 255, 0.4);
  box-shadow: 0 4px 10px -8px rgba(90, 106, 128, 0.3);
}

.layer-item.active {
  background: rgba(90, 162, 255, 0.12);
  border-color: rgba(90, 162, 255, 0.5);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.02),
    0 12px 22px -20px rgba(90, 106, 128, 0.3);
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

/* ── 符号系统浮窗 (Symbology Popover) ────────────────────────────────────── */
.sym-popover {
  position: fixed;
  z-index: 9999;
  min-width: 12rem;
  max-width: 16rem;
  border: 1px solid rgba(90, 162, 255, 0.28);
  border-radius: 0.6rem;
  background: rgba(8, 18, 33, 0.97);
  backdrop-filter: blur(14px);
  box-shadow:
    0 16px 40px -16px rgba(0, 0, 0, 0.7),
    0 0 0 1px rgba(136, 192, 255, 0.04);
  overflow: hidden;
  animation: sym-pop-in 0.16s ease;
}

@keyframes sym-pop-in {
  from {
    opacity: 0;
    transform: scale(0.96) translateY(-6px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

.sym-popover-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.36rem 0.5rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.1);
  background: rgba(90, 162, 255, 0.06);
}

.sym-popover-title {
  color: #e8f4ff;
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.sym-popover-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 1.1rem;
  height: 1.1rem;
  border: none;
  border-radius: 0.32rem;
  background: transparent;
  color: #6e8ba0;
  cursor: pointer;
  font-size: 0.56rem;
  transition:
    background 0.12s ease,
    color 0.12s ease;
}

.sym-popover-close:hover {
  background: rgba(255, 100, 100, 0.14);
  color: #ff9a9a;
}

.sym-popover-body {
  display: grid;
  gap: 0.26rem;
  padding: 0.4rem 0.5rem;
}

.sym-layer-name {
  color: #f3fbff;
  font-size: 0.62rem;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 字段行 */
.sym-field-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.3rem;
}

.sym-field-label {
  color: #6e8ba0;
  font-size: 0.54rem;
  letter-spacing: 0.02em;
}

.sym-field-value {
  color: #d4e4f4;
  font-size: 0.58rem;
  font-weight: 600;
  text-align: right;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}

/* 色带条 */
.sym-color-ramp {
  width: 100%;
  height: 0.72rem;
  border-radius: 0.28rem;
  border: 1px solid rgba(136, 192, 255, 0.12);
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.18);
}

/* 值域范围 */
.sym-range-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.2rem;
}

.sym-range-min,
.sym-range-max {
  color: #9fb6cc;
  font-size: 0.52rem;
  font-variant-numeric: tabular-nums;
  font-family: ui-monospace, 'SF Mono', monospace;
}

.sym-range-unit {
  color: #6e8ba0;
  font-size: 0.5rem;
  letter-spacing: 0.02em;
}

/* 配色下拉（与分析框 palette 同源） */
.sym-palette-row {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.3rem;
  align-items: center;
  margin-top: 0.12rem;
  color: #9eb3c8;
  font-size: 0.54rem;
}

.sym-palette-select {
  width: 100%;
  border: 1px solid rgba(136, 192, 255, 0.2);
  border-radius: 0.36rem;
  background: rgba(8, 18, 33, 0.85);
  color: #d8e6f5;
  font: inherit;
  font-size: 0.54rem;
  padding: 0.22rem 0.35rem;
}

.sym-palette-select:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.sym-palette-hint {
  margin: 0.2rem 0 0;
  color: #7f93a9;
  font-size: 0.48rem;
  line-height: 1.35;
}

/* 透明度滑块（与"分析"面板同步） */
.sym-opacity-row {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 0.3rem;
  align-items: center;
  margin-top: 0.12rem;
  padding-top: 0.18rem;
  border-top: 1px solid rgba(136, 192, 255, 0.06);
  color: #9eb3c8;
  font-size: 0.54rem;
}

.sym-opacity-slider {
  width: 100%;
  -webkit-appearance: none;
  appearance: none;
  height: 1.2rem;
  background: transparent;
  outline: none;
  cursor: pointer;
}

.sym-opacity-slider::-webkit-slider-runnable-track {
  height: 4px;
  border-radius: 999px;
  background: rgba(136, 192, 255, 0.18);
}

.sym-opacity-slider::-moz-range-track {
  height: 4px;
  border-radius: 999px;
  background: rgba(136, 192, 255, 0.18);
}

.sym-opacity-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 0.82rem;
  height: 0.82rem;
  margin-top: -0.36rem;
  border-radius: 50%;
  background: var(--accent, #5ad5ff);
  box-shadow: 0 0 6px var(--accent, #5ad5ff);
  cursor: pointer;
  transition: transform 0.14s ease;
}

.sym-opacity-slider::-webkit-slider-thumb:hover {
  transform: scale(1.15);
}

.sym-opacity-slider::-moz-range-thumb {
  width: 0.82rem;
  height: 0.82rem;
  border: none;
  border-radius: 50%;
  background: var(--accent, #5ad5ff);
  box-shadow: 0 0 6px var(--accent, #5ad5ff);
  cursor: pointer;
}

.sym-opacity-row strong {
  color: #eff8ff;
  font-size: 0.54rem;
  font-variant-numeric: tabular-nums;
  min-width: 2rem;
  text-align: right;
}
</style>
