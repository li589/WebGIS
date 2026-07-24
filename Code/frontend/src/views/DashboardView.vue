<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useDataImportFlow } from '../composables/useDataImportFlow'

import ControlPanel from '../components/ControlPanel.vue'
import InfoPanel from '../components/InfoPanel.vue'
import LayerSidebar from '../components/LayerSidebar.vue'
import MapCanvas from '../components/MapCanvas.vue'
import ModeToolbar from '../components/ModeToolbar.vue'
import LogPanel from '../components/toolbar/LogPanel.vue'
import TimelinePanel from '../components/TimelinePanel.vue'
import TimelineScrubber from '../components/TimelineScrubber.vue'
import WorkflowStatusPanel from '../components/workflow/WorkflowStatusPanel.vue'
import type { TileSourceId } from '../services/api-config'
import type { LayerHotspot } from '../stores/layers/types'
import type { OverlayTimeState } from '../components/map/overlay-image-module'
import {
  getOverlayValue,
  type OverlayPointValue,
  getWeatherCoverage,
  type WeatherCoverage,
} from '../services/runtime-api'
import { useUiStore } from '../stores/ui'
import { useUiLoadingStore } from '../stores/ui-loading'
import { useLayersStore } from '../stores/layers'
import { useLogStore } from '../stores/log'
import { useWeatherTileManager } from '../stores/weather-tile-manager'
import { useWeatherSyncStatusStore } from '../stores/weather-sync-status'
import {
  buildClockDayTimelineSegments,
  dateHourToTileHour,
  findLatestValidCoverageInstant,
} from '../utils/weather-timeline'
import { buildFallbackActiveLayerDisplay } from '../components/map/map-stage-view-model'

const uiStore = useUiStore()
const layersStore = useLayersStore()
const logStore = useLogStore()
const uiLoading = useUiLoadingStore()
const weatherTileManager = useWeatherTileManager()
const weatherSyncStatus = useWeatherSyncStatusStore()
const workflowOutputStore = useWorkflowOutputLayersStore()

// 首次打开网页：全屏地球+卫星；目录就绪后关闭
uiLoading.showImmediate('初始化地图数据...')
void layersStore.ensureRuntimeLayerCatalog().finally(() => {
  uiLoading.hideImmediate()
})
// 恢复后端活跃工作流（跨会话 / 定时器触发 / 其他客户端提交）
void layersStore.restoreActiveWorkflows()

const { tileSourceId, currentHour, currentDate, hourLabel, isPlaying, unifiedTimeLock } =
  storeToRefs(uiStore)
const {
  selectedLayerDisplay,
  activeLayerCount,
  workflowError,
  isSubmitting,
  pointWeather,
  pointWeatherLoading,
  pointWeatherError,
} = storeToRefs(layersStore)
// 引用 tile_manager 的版本号，使 timelineSegments 在瓦片状态变化时重新计算
const { statusVersion: weatherStatusVersion, activityVersion: weatherActivityVersion } =
  storeToRefs(weatherTileManager)

const activeLayer = computed(() => {
  if (selectedLayerDisplay.value) return selectedLayerDisplay.value
  return buildFallbackActiveLayerDisplay()
})

const stageLabel = computed(() =>
  activeLayer.value.dataState === 'real' ? '运行时工作流' : '运行时目录',
)
const visibleHotspots = ref<LayerHotspot[]>([])
const selectedHotspot = ref<LayerHotspot | null>(null)
const selectedMapPoint = ref<{ lng: number; lat: number } | null>(null)
const overlayTimeStates = ref<OverlayTimeState[]>([])
const overlayPointValues = ref<OverlayPointValue[]>([])
const dashboardRef = ref<HTMLElement | null>(null)
const mapShellRef = ref<HTMLElement | null>(null)
const mapCanvasRef = ref<InstanceType<typeof MapCanvas> | null>(null)
const screenshotOpen = ref(false)
const workflowStatusOpen = ref(false)
const logOpen = ref(false)
const settingsOpen = ref(false)

// 本地 Open-Meteo 覆盖范围：按「日期+钟点」着色；瓦片 hour 由日期映射得出
const weatherCoverage = ref<WeatherCoverage | null>(null)
let coverageAbort: AbortController | null = null

async function refreshWeatherCoverage() {
  if (coverageAbort) coverageAbort.abort()
  const ac = new AbortController()
  coverageAbort = ac
  try {
    const cov = await getWeatherCoverage(undefined, ac.signal)
    if (!ac.signal.aborted) weatherCoverage.value = cov
  } catch (err) {
    if (!(err instanceof DOMException && err.name === 'AbortError')) {
      console.warn('[DashboardView] weather coverage probe failed', err)
      if (!ac.signal.aborted) weatherCoverage.value = null
    }
  } finally {
    if (coverageAbort === ac) coverageAbort = null
  }
}

onMounted(() => {
  void refreshWeatherCoverage()
  void weatherSyncStatus.refreshOverview()
  const intervalId = window.setInterval(() => {
    void refreshWeatherCoverage()
    void weatherSyncStatus.refreshOverview()
  }, 600_000)
  onBeforeUnmount(() => window.clearInterval(intervalId))
})

const coverageSourceLabel = computed(() => {
  const mode = unifiedTimeLock.value ? '统一时间' : '分图层'
  const layerName = activeLayer.value?.name
  const base = layerName ? `${mode} · ${layerName}` : mode
  if (weatherSyncStatus.syncInProgress) return `${base} · 同步中`
  if (!weatherCoverage.value && weatherSyncStatus.modelEmpty) return `${base} · 本地无数据`
  return base
})

/** 瓦片 API 用的预报偏移：由所选日期+钟点映射，不限制 UI 拖动 */
const tileForecastHour = computed(() =>
  dateHourToTileHour(weatherCoverage.value, currentDate.value, currentHour.value),
)

watch(
  tileForecastHour,
  (hour) => {
    layersStore.setCurrentHour(hour)
  },
  { immediate: true },
)

/** 当前选中图层 catalogId（用于记忆 / 可用性同步） */
const selectedCatalogId = computed(() => selectedLayerDisplay.value?.catalogId ?? null)

/** 新加天气图层：跳过切层记忆恢复（由 snap 对齐最新有效时次） */
const pendingSnapCatalogIds = new Set<string>()
const knownActiveInstanceIds = new Set<string>()
let layerTimeTrackingReady = false

function snapTimelineToLatestValid(reason: string) {
  const latest = findLatestValidCoverageInstant(weatherCoverage.value, new Date())
  if (!latest) return
  uiStore.applyDateHour(latest.date, latest.hour)
  if (selectedCatalogId.value) {
    uiStore.rememberLayerTime(selectedCatalogId.value)
  }
  logStore.logOperation('timeline-snap-latest', reason)
}

// 拖动/改日期时记住当前图层时刻（不含切层，避免把旧时刻写进新图层）
watch([currentHour, currentDate], () => {
  if (unifiedTimeLock.value) return
  uiStore.rememberLayerTime(selectedCatalogId.value)
})

// 仅「新加」天气图层：非统一模式对齐最新有效数据时次（须先于切层 watch 登记 pending）
watch(
  () => layersStore.activeLayers.map((l) => l.instanceId),
  (ids) => {
    if (!layerTimeTrackingReady) {
      for (const id of ids) knownActiveInstanceIds.add(id)
      layerTimeTrackingReady = true
      return
    }
    const added = ids.filter((id) => !knownActiveInstanceIds.has(id))
    for (const id of ids) knownActiveInstanceIds.add(id)
    for (const id of Array.from(knownActiveInstanceIds)) {
      if (!ids.includes(id)) knownActiveInstanceIds.delete(id)
    }
    if (unifiedTimeLock.value || added.length === 0) return
    for (const instanceId of added) {
      const layer = layersStore.activeLayers.find((l) => l.instanceId === instanceId)
      if (!layer) continue
      if (!layersStore.isWeatherEngineLayer(layer.catalogId)) continue
      pendingSnapCatalogIds.add(layer.catalogId)
      snapTimelineToLatestValid(`新加图层 ${layer.catalogId} → 最新有效时次`)
      break
    }
  },
  { immediate: true },
)

// 切层：非统一模式先记住上一层，再恢复目标层记忆；统一模式保持共享时刻
watch(selectedCatalogId, (catalogId, previous) => {
  if (!catalogId || catalogId === previous) return
  if (unifiedTimeLock.value) return
  if (previous) {
    uiStore.rememberLayerTime(previous)
  }
  if (pendingSnapCatalogIds.has(catalogId)) {
    pendingSnapCatalogIds.delete(catalogId)
    return
  }
  const restored = uiStore.restoreLayerTime(catalogId)
  if (restored) {
    logStore.logOperation('timeline-restore-layer', `恢复图层 ${catalogId} 记忆时刻`)
  }
})

const workflowEditorOpen = ref(false)
const workflowEditorRef = ref<{
  notifyRunOutcome?: (ok: boolean, message?: string) => void
} | null>(null)
const ScreenshotExport = defineAsyncComponent(() => import('../components/ScreenshotExport.vue'))
const SettingsPanel = defineAsyncComponent(() => import('../components/settings/SettingsPanel.vue'))
const WorkflowEditorPanel = defineAsyncComponent(
  () => import('../components/workflow/WorkflowEditorPanel.vue'),
)
import type { WorkflowRunTarget } from '../components/workflow/WorkflowRunDialog.vue'
import { useWorkflowOutputLayersStore } from '../stores/workflow-output-layers'

const { processFiles: processImportFiles, dropActive, importing: importBusy } = useDataImportFlow()

function isFileDrag(e: DragEvent): boolean {
  return Array.from(e.dataTransfer?.types ?? []).includes('Files')
}

function onMapShellDragEnter(e: DragEvent) {
  if (workflowEditorOpen.value || settingsOpen.value || importBusy.value) return
  if (!isFileDrag(e)) return
  e.preventDefault()
  dropActive.value = true
}

function onMapShellDragOver(e: DragEvent) {
  if (workflowEditorOpen.value || settingsOpen.value || importBusy.value) return
  if (!isFileDrag(e)) return
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
  dropActive.value = true
}

function onMapShellDragLeave(e: DragEvent) {
  const related = e.relatedTarget as Node | null
  if (related && mapShellRef.value?.contains(related)) return
  dropActive.value = false
}

async function onMapShellDrop(e: DragEvent) {
  dropActive.value = false
  if (workflowEditorOpen.value || settingsOpen.value || importBusy.value) return
  if (!isFileDrag(e)) return
  e.preventDefault()
  e.stopPropagation()
  await processImportFiles(e.dataTransfer?.files)
}

// 异步组件首次加载跟踪：仅首次打开时显示 loading（后续从缓存加载无需 loading）
const _loadedAsyncPanels = new Set<string>()

watch(settingsOpen, (open) => {
  if (open && !_loadedAsyncPanels.has('settings')) {
    _loadedAsyncPanels.add('settings')
    uiLoading.showImmediate('加载设置面板...')
  }
})

watch(workflowEditorOpen, (open) => {
  if (open && !_loadedAsyncPanels.has('workflow-editor')) {
    _loadedAsyncPanels.add('workflow-editor')
    uiLoading.showImmediate('加载工作流编辑器...')
  }
})

const sidePanelDimensions = Object.freeze({
  defaultHeight: 372,
  minHeight: 236,
  maxHeight: 540,
  minWidth: 280,
  maxWidth: 420,
})

const layerPanelDimensions = Object.freeze({
  ...sidePanelDimensions,
  defaultWidth: 292,
})

const analysisPanelDimensions = Object.freeze({
  ...sidePanelDimensions,
  defaultWidth: 304,
})

/**
 * 时间轴色段：按「当前所选日期」判断各钟点是否有覆盖。
 * 绿=有数据，黄=加载中，紫=无数据。
 */
const timelineSegments = computed(() => {
  void weatherStatusVersion.value
  void weatherActivityVersion.value
  void currentHour.value
  void currentDate.value
  void weatherCoverage.value

  const layer = activeLayer.value
  const catalogId = layer.catalogId
  const isWeatherLayer = catalogId ? layersStore.isWeatherEngineLayer(catalogId) : false
  const currentStatus =
    isWeatherLayer && catalogId ? weatherTileManager.getLayerStatus(catalogId) : null

  return buildClockDayTimelineSegments({
    selectedDate: currentDate.value,
    currentHour: currentHour.value,
    coverage: weatherCoverage.value,
    currentStatus,
    isWeatherLayer,
    runReadiness: layer.runReadiness,
  })
})

function handleTileSourceChange(sourceId: TileSourceId) {
  uiStore.setTileSource(sourceId)
  logStore.logOperation('tile-source-change', `切换底图源: ${sourceId}`)
}

function handleLayerSelect(layerId: string) {
  // LayerSidebar 已 select；此处只记日志，避免重复副作用
  if (layersStore.selectedInstanceId !== layerId) {
    layersStore.selectLayer(layerId)
  }
  logStore.logOperation('layer-select', `选中图层: ${layerId}`)
}

/** 点查优先当前选中天气层；否则取最顶层可见天气层 */
function resolveWeatherInspectCatalogId(): string | null {
  const selected = selectedLayerDisplay.value
  if (selected && layersStore.isWeatherEngineLayer(selected.catalogId) && selected.visible) {
    return selected.catalogId
  }
  const topVisible = [...layersStore.activeLayers]
    .filter((l) => l.visible && layersStore.isWeatherEngineLayer(l.catalogId))
    .sort((a, b) => b.order - a.order)[0]
  return topVisible?.catalogId ?? null
}

function requestPointWeather(lng: number, lat: number, catalogId: string) {
  void layersStore.fetchPointWeather(lng, lat, catalogId, {
    forecastHours: tileForecastHour.value + 1,
  })
}

function handleMapPointSelect(point: { lng: number; lat: number }) {
  selectedMapPoint.value = point
  logStore.logOperation(
    'map-point-select',
    `查询点 (${point.lng.toFixed(4)}, ${point.lat.toFixed(4)})`,
  )
  const catalogId = resolveWeatherInspectCatalogId()
  if (catalogId) {
    requestPointWeather(point.lng, point.lat, catalogId)
  } else {
    layersStore.clearPointWeather()
  }
  void fetchOverlayPointValues(point.lng, point.lat)
}

function clearMapPointInspect() {
  selectedMapPoint.value = null
  layersStore.clearPointWeather()
  overlayPointValues.value = []
  logStore.logOperation('map-point-clear', '清除地图选点')
}

function handleHotspotSelect(hotspot: LayerHotspot | null) {
  selectedHotspot.value = hotspot
}

function handleHotspotSelectFromPanel(hotspotId: string) {
  const hotspot = visibleHotspots.value.find((h) => h.id === hotspotId) ?? null
  selectedHotspot.value = hotspot
  mapCanvasRef.value?.selectHotspot?.(hotspotId)
}

let overlayPointFetchSeq = 0

async function fetchOverlayPointValues(lng: number, lat: number) {
  const states = overlayTimeStates.value
  if (states.length === 0) {
    overlayPointValues.value = []
    return
  }
  const seq = ++overlayPointFetchSeq
  const results = await Promise.allSettled(
    states.map((s) => getOverlayValue(s.layerId, lng, lat, s.currentTime ?? undefined)),
  )
  if (seq !== overlayPointFetchSeq) return
  overlayPointValues.value = results
    .map((r) => (r.status === 'fulfilled' ? r.value : null))
    .filter((v): v is OverlayPointValue => v !== null)
}

function handleTimelineStep(delta: number) {
  uiStore.stepHour(delta)
  if (!unifiedTimeLock.value) uiStore.rememberLayerTime(selectedCatalogId.value)
  logStore.logOperation(
    'timeline-step',
    `时间轴${delta > 0 ? '前进' : '后退'} ${Math.abs(delta)} 小时`,
  )
}

function handleTimelineChange(hour: number) {
  uiStore.setHour(hour)
  if (!unifiedTimeLock.value) uiStore.rememberLayerTime(selectedCatalogId.value)
  logStore.logOperation('timeline-change', `时间轴跳转到 ${hourLabel.value}`)
}

function handleTimelineDateChange(date: Date) {
  uiStore.setDate(date)
  if (!unifiedTimeLock.value) uiStore.rememberLayerTime(selectedCatalogId.value)
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  logStore.logOperation('timeline-date-change', `日期切换到 ${y}-${m}-${d}`)
}

function handleTimelineTogglePlay() {
  uiStore.togglePlay()
  logStore.logOperation('timeline-play', isPlaying.value ? '时间轴播放' : '时间轴暂停')
}

function handleTimelineToggleUnified() {
  uiStore.toggleUnifiedTimeLock()
  const on = unifiedTimeLock.value
  if (on && selectedCatalogId.value) {
    // 开启统一时间时，以当前选中层时刻作为共享基准并写入各天气层记忆
    uiStore.rememberLayerTime(selectedCatalogId.value)
  }
  logStore.logOperation('timeline-unified', on ? '开启统一时间' : '关闭统一时间（分图层记忆）')
}

function handleVisibleHotspotsChange(hotspots: LayerHotspot[]) {
  visibleHotspots.value = hotspots
  if (
    selectedHotspot.value &&
    !hotspots.some((hotspot) => hotspot.id === selectedHotspot.value?.id)
  ) {
    selectedHotspot.value = null
  }
}

function handleOverlayTimeUpdate(states: OverlayTimeState[]) {
  overlayTimeStates.value = states
}

function handleToggleLayerVisibility(instanceId: string) {
  layersStore.toggleLayerVisibility(instanceId)
}

function handleSetLayerOpacity(payload: { instanceId: string; opacity: number }) {
  layersStore.setLayerOpacity(payload.instanceId, payload.opacity)
}

function handleOpenScreenshot() {
  screenshotOpen.value = true
}

function handleCloseScreenshot() {
  screenshotOpen.value = false
}

function handleOpenSettings() {
  settingsOpen.value = true
}

function handleCloseSettings() {
  settingsOpen.value = false
}

function handleOpenWorkflowStatus() {
  workflowStatusOpen.value = true
}

function handleCloseWorkflowStatus() {
  workflowStatusOpen.value = false
}

function handleOpenWorkflowEditor() {
  workflowEditorOpen.value = true
}

function handleCloseWorkflowEditor() {
  workflowEditorOpen.value = false
}

async function handleRunWorkflowFromEditor(
  workflowId: string,
  linkedLayerId: string | null,
  target: WorkflowRunTarget,
  canvasGraph?: {
    nodes: import('../services/workflow-definition-api').WorkflowDefinitionNode[]
    links: import('../services/workflow-definition-api').WorkflowDefinitionLink[]
  } | null,
) {
  logStore.logWorkflow(
    'workflow-editor-run',
    `从编辑器运行工作流: ${workflowId} (目标: ${target.mode})`,
  )
  if (!linkedLayerId) {
    const msg = `工作流 ${workflowId} 未关联图层，无法运行`
    logStore.logWorkflow('workflow-editor-error', msg)
    workflowEditorRef.value?.notifyRunOutcome?.(false, msg)
    return
  }

  let catalogId = linkedLayerId
  if (target.mode === 'new') {
    const engine =
      layersStore.layerLibrary.find((l) => l.catalogId === linkedLayerId)?.engine ?? 'general'
    const entry = workflowOutputStore.createOutputLayer({
      name: target.name ?? `产出 ${workflowId}`,
      group: target.group ?? '默认分组',
      sourceWorkflowId: workflowId,
      sourceLayerId: linkedLayerId,
      engine,
    })
    logStore.logWorkflow(
      'workflow-output-create',
      `创建产出图层「${entry.name}」→ 分组「${entry.group}」`,
    )
    catalogId = entry.localId
  }

  try {
    let algorithmRequest: Record<string, unknown> | undefined
    let weatherRequest: Record<string, unknown> | undefined
    const nodes = canvasGraph?.nodes ?? []
    const links = canvasGraph?.links ?? []
    if (nodes.length > 0) {
      const { compileWorkflowGraph } = await import('../services/workflow-definition-api')
      const compiled = await compileWorkflowGraph({
        workflow_id: workflowId,
        name: workflowId,
        nodes,
        links,
      })
      const def = compiled.workflow_definition as Record<string, unknown>
      const engine =
        ((def.metadata as Record<string, unknown> | undefined)?.engine as string | undefined) ??
        'python_provider'
      if (engine === 'weather') {
        weatherRequest = {
          workflow_id: workflowId,
          layer_id: linkedLayerId,
          workflow: def,
          context: {
            latitude: layersStore.currentMapCenter.lat,
            longitude: layersStore.currentMapCenter.lng,
          },
          priority: 'viewport',
        }
      } else {
        algorithmRequest = {
          workflow_definition: def,
          workflow_entry_name: workflowId,
          datasource_selection: {},
          algorithm_params: {},
          output_spec: {},
          tags: { source: 'workflow_editor', workflow_id: workflowId },
        }
      }
      logStore.logWorkflow(
        'workflow-editor-compile',
        `画布已编译(${engine}): nodes=${(def.nodes as unknown[] | undefined)?.length ?? 0}`,
      )
    }
    await layersStore.runWorkflowForCatalog(catalogId, {
      algorithmRequest,
      weatherRequest,
      commandLabel: `运行画布工作流 ${workflowId}`,
    })
    workflowEditorRef.value?.notifyRunOutcome?.(true)
    // 成功后再切到状态面板，便于看进度与结果摘要
    workflowEditorOpen.value = false
    workflowStatusOpen.value = true
  } catch (error) {
    const msg = (error as Error)?.message ?? String(error)
    workflowEditorRef.value?.notifyRunOutcome?.(false, msg)
    // 天气瓦片刷新也打开状态面板看瓦片进度
    if (/天气引擎|瓦片/.test(msg)) {
      workflowStatusOpen.value = true
    }
  }
}

async function handleRunWorkflow(catalogId: string) {
  logStore.logWorkflow('workflow-submit', `提交工作流: ${catalogId}`)
  try {
    await layersStore.runWorkflowForCatalog(catalogId)
    logStore.logWorkflow('workflow-accepted', `工作流已受理: ${catalogId}`)
  } catch (error) {
    const msg = (error as Error)?.message ?? String(error)
    if (/天气引擎图层|瓦片按需加载/.test(msg)) {
      logStore.logWorkflow('workflow-weather-refresh', msg)
    } else {
      logStore.logWorkflow('workflow-error', `工作流提交失败: ${catalogId} — ${msg}`)
    }
    console.error('[DashboardView] workflow submit failed', error)
    throw error
  }
}

watch(
  () => activeLayer.value.catalogId,
  (catalogId) => {
    if (!layersStore.isWeatherEngineLayer(catalogId)) {
      layersStore.clearPointWeather()
      return
    }
    if (selectedMapPoint.value) {
      requestPointWeather(selectedMapPoint.value.lng, selectedMapPoint.value.lat, catalogId)
    }
  },
)

let pointHourRefetchTimer: number | null = null
watch(tileForecastHour, () => {
  const point = selectedMapPoint.value
  const catalogId = resolveWeatherInspectCatalogId()
  if (!point || !catalogId) return
  if (pointHourRefetchTimer !== null) window.clearTimeout(pointHourRefetchTimer)
  pointHourRefetchTimer = window.setTimeout(() => {
    pointHourRefetchTimer = null
    requestPointWeather(point.lng, point.lat, catalogId)
  }, 180)
})
</script>

<template>
  <main ref="dashboardRef" class="dashboard">
    <section
      ref="mapShellRef"
      class="map-shell"
      :class="{ 'drop-active': dropActive }"
      @dragenter="onMapShellDragEnter"
      @dragover="onMapShellDragOver"
      @dragleave="onMapShellDragLeave"
      @drop="onMapShellDrop"
    >
      <MapCanvas
        ref="mapCanvasRef"
        :tile-source-id="tileSourceId"
        :current-hour="currentHour"
        :hour-label="hourLabel"
        :inspect-point="selectedMapPoint"
        @visible-hotspots-change="handleVisibleHotspotsChange"
        @hotspot-select="handleHotspotSelect"
        @map-point-select="handleMapPointSelect"
        @overlay-time-update="handleOverlayTimeUpdate"
      />

      <div v-if="dropActive" class="import-drop-overlay" aria-hidden="true">
        <div class="import-drop-card">
          <span class="import-drop-title">释放以导入数据</span>
          <span class="import-drop-desc">SHP / GeoJSON / CSV / TIF</span>
        </div>
      </div>

      <div class="overlay overlay-top">
        <ModeToolbar
          :tile-source-id="tileSourceId"
          :active-layer="activeLayer"
          :hour-label="hourLabel"
          :active-layer-count="activeLayerCount"
          @change-tile-source="handleTileSourceChange"
          @open-screenshot="handleOpenScreenshot"
          @open-settings="handleOpenSettings"
          @open-workflow-status="handleOpenWorkflowStatus"
          @open-workflow-editor="handleOpenWorkflowEditor"
          @open-log="logOpen = true"
        />
      </div>

      <div class="overlay overlay-left">
        <ControlPanel
          panel-label="图层"
          panel-key="layers"
          handle-position="bottom-right"
          :max-offset-x="100"
          :max-offset-y="110"
          :default-width="layerPanelDimensions.defaultWidth"
          :default-height="layerPanelDimensions.defaultHeight"
          :min-width="layerPanelDimensions.minWidth"
          :min-height="layerPanelDimensions.minHeight"
          :max-width="layerPanelDimensions.maxWidth"
          :max-height="layerPanelDimensions.maxHeight"
        >
          <LayerSidebar @select-layer="handleLayerSelect" />
        </ControlPanel>
      </div>

      <div class="overlay overlay-right">
        <ControlPanel
          panel-label="分析"
          panel-key="analysis"
          handle-position="bottom-left"
          :max-offset-x="80"
          :max-offset-y="110"
          :default-width="analysisPanelDimensions.defaultWidth"
          :default-height="analysisPanelDimensions.defaultHeight"
          :min-width="analysisPanelDimensions.minWidth"
          :min-height="analysisPanelDimensions.minHeight"
          :max-width="analysisPanelDimensions.maxWidth"
          :max-height="analysisPanelDimensions.maxHeight"
        >
          <InfoPanel
            :active-layer="activeLayer"
            :stage-label="stageLabel"
            :visible-hotspots="visibleHotspots"
            :selected-layer="selectedLayerDisplay"
            :selected-hotspot="selectedHotspot"
            :selected-map-point="selectedMapPoint"
            :inspect-hour="tileForecastHour"
            :is-submitting="isSubmitting"
            :workflow-error="workflowError"
            :point-weather="pointWeather"
            :point-weather-loading="pointWeatherLoading"
            :point-weather-error="pointWeatherError"
            :overlay-time-states="overlayTimeStates"
            :overlay-point-values="overlayPointValues"
            @run-workflow="handleRunWorkflow"
            @toggle-layer-visibility="handleToggleLayerVisibility"
            @set-layer-opacity="handleSetLayerOpacity"
            @select-hotspot="handleHotspotSelectFromPanel"
            @clear-map-point="clearMapPointInspect"
            @enter-select-mode="uiStore.setInteractionMode('select')"
          />
        </ControlPanel>
      </div>

      <div class="overlay overlay-bottom">
        <TimelinePanel
          panel-label="时间轴"
          panel-key="timeline"
          :max-offset-x="140"
          :max-offset-y="70"
          :default-width="720"
          :default-height="180"
          :min-width="460"
          :min-height="175"
          :max-width="980"
          :max-height="220"
        >
          <TimelineScrubber
            :current-hour="currentHour"
            :current-date="currentDate"
            :hour-label="hourLabel"
            :accent-color="activeLayer.accentColor"
            :availability-label="activeLayer.availabilityLabel"
            :observation-time-label="activeLayer.observationTimeLabel"
            :timeline-segments="timelineSegments"
            :coverage-source-label="coverageSourceLabel"
            :unified-time-lock="unifiedTimeLock"
            :is-playing="isPlaying"
            @step="handleTimelineStep"
            @change-hour="handleTimelineChange"
            @change-date="handleTimelineDateChange"
            @toggle-play="handleTimelineTogglePlay"
            @toggle-unified-time="handleTimelineToggleUnified"
          />
        </TimelinePanel>
      </div>
    </section>

    <ScreenshotExport
      v-if="screenshotOpen"
      :dashboard-el="dashboardRef"
      :map-shell-el="mapShellRef"
      :map-stage-el="mapCanvasRef?.getMapStageElement() ?? null"
      :capture-map-canvas="mapCanvasRef?.captureMapCanvas ?? null"
      :active-layer-name="activeLayer.name"
      :hour-label="hourLabel"
      @close="handleCloseScreenshot"
    />

    <WorkflowStatusPanel v-if="workflowStatusOpen" @close="handleCloseWorkflowStatus" />

    <LogPanel v-if="logOpen" @close="logOpen = false" />

    <SettingsPanel v-if="settingsOpen" @close="handleCloseSettings" />

    <WorkflowEditorPanel
      v-if="workflowEditorOpen"
      ref="workflowEditorRef"
      @close="handleCloseWorkflowEditor"
      @run="handleRunWorkflowFromEditor"
    />
  </main>
</template>

<style scoped>
.dashboard {
  min-height: calc(100vh - 1.5rem);
}

.map-shell {
  position: relative;
  min-height: calc(100vh - 1.5rem);
  border-radius: 1.4rem;
  overflow: hidden;
  isolation: isolate;
}

.map-shell.drop-active {
  outline: 2px solid rgba(90, 213, 255, 0.55);
  outline-offset: -2px;
}

.import-drop-overlay {
  position: absolute;
  inset: 0;
  z-index: 40;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(4, 12, 22, 0.55);
  pointer-events: none;
}

.import-drop-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.35rem;
  padding: 1.1rem 1.6rem;
  border-radius: 0.75rem;
  border: 1px dashed rgba(90, 213, 255, 0.55);
  background: rgba(8, 20, 36, 0.9);
  color: #d5e8f8;
}

.import-drop-title {
  font-size: 0.92rem;
  font-weight: 600;
}

.import-drop-desc {
  font-size: 0.68rem;
  color: #8aa8bf;
}

.overlay {
  position: absolute;
  z-index: 24;
  pointer-events: none;
}

.overlay :deep(*) {
  pointer-events: auto;
}

.overlay-top {
  top: 0.8rem;
  left: 0.8rem;
  right: 0.8rem;
  z-index: 20;
}

.overlay-left {
  top: 9.5rem;
  left: 0.8rem;
  width: min(18rem, calc(100vw - 1.6rem));
}

.overlay-right {
  top: 9.5rem;
  right: 0.8rem;
  width: min(21rem, calc(100vw - 1.6rem));
  display: flex;
  justify-content: flex-end;
}

.overlay-bottom {
  left: 50%;
  bottom: 0.72rem;
  width: min(45rem, calc(100vw - 1.6rem));
  transform: translateX(-50%);
  height: min-content;
}

@media (max-width: 1100px) {
  .overlay-left,
  .overlay-right {
    top: auto;
    bottom: 7rem;
    width: min(14rem, calc(100vw - 1.5rem));
  }

  .overlay-left {
    left: 0.75rem;
    width: min(15.5rem, calc(100vw - 1.5rem));
  }

  .overlay-right {
    right: 0.75rem;
    width: min(21rem, calc(100vw - 1.5rem));
    display: flex;
    justify-content: flex-end;
  }
}

@media (max-width: 820px) {
  .dashboard,
  .map-shell {
    min-height: calc(100vh - 1rem);
  }

  .overlay-top {
    top: 0.75rem;
    left: 0.75rem;
    right: 0.75rem;
  }

  .overlay-left,
  .overlay-right,
  .overlay-bottom {
    position: static;
    width: auto;
    transform: none;
  }

  .overlay-left {
    margin: 7.2rem 0.75rem 0;
  }

  .overlay-right {
    margin: 0.75rem 0.75rem 0;
    width: auto;
  }

  .overlay-bottom {
    margin: 0.75rem 0.75rem 0;
  }
}
</style>
