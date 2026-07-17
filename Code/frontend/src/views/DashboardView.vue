<script setup lang="ts">
import { computed, defineAsyncComponent, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'

import ControlPanel from '../components/ControlPanel.vue'
import InfoPanel from '../components/InfoPanel.vue'
import LayerSidebar from '../components/LayerSidebar.vue'
import MapCanvas from '../components/MapCanvas.vue'
import ModeToolbar from '../components/ModeToolbar.vue'
import LogPanel from '../components/toolbar/LogPanel.vue'
import TimelinePanel from '../components/TimelinePanel.vue'
import TimelineScrubber, { type TimelineWorkflowIndicator } from '../components/TimelineScrubber.vue'
import WorkflowStatusPanel from '../components/workflow/WorkflowStatusPanel.vue'
import type { TileSourceId } from '../services/api-config'
import type { ActiveLayerDisplay, LayerHotspot } from '../stores/layers/types'
import type { OverlayTimeState } from '../components/map/overlay-image-module'
import { getOverlayValue, type OverlayPointValue } from '../services/runtime-api'
import { useUiStore } from '../stores/ui'
import { useUiLoadingStore } from '../stores/ui-loading'
import { useLayersStore } from '../stores/layers'
import { useLogStore } from '../stores/log'

const uiStore = useUiStore()
const layersStore = useLayersStore()
const logStore = useLogStore()
const uiLoading = useUiLoadingStore()
const workflowOutputStore = useWorkflowOutputLayersStore()

// 首次打开网页：立即显示 loading，图层目录加载完成后强制关闭（配对 showImmediate）
uiLoading.showImmediate('初始化地图数据...')
void layersStore.ensureRuntimeLayerCatalog().finally(() => {
  uiLoading.hideImmediate()
})

const { tileSourceId, currentHour, currentDate, hourLabel, isPlaying } = storeToRefs(uiStore)
const { selectedLayerDisplay, activeLayerCount, workflowError, isSubmitting, pointWeather, pointWeatherLoading, pointWeatherError } = storeToRefs(layersStore)

const activeLayer = computed(() => {
  if (selectedLayerDisplay.value) return selectedLayerDisplay.value
  return buildFallbackActiveLayer()
})

const stageLabel = computed(() => (activeLayer.value.dataState === 'real' ? '运行时工作流' : '运行时目录'))
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
const workflowEditorOpen = ref(false)
const ScreenshotExport = defineAsyncComponent(() => import('../components/ScreenshotExport.vue'))
const SettingsPanel = defineAsyncComponent(() => import('../components/settings/SettingsPanel.vue'))
const WorkflowEditorPanel = defineAsyncComponent(() => import('../components/workflow/WorkflowEditorPanel.vue'))
import type { WorkflowRunTarget } from '../components/workflow/WorkflowRunDialog.vue'
import { useWorkflowOutputLayersStore } from '../stores/workflow-output-layers'

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

watch(currentHour, (hour) => {
  layersStore.setCurrentHour(hour)
}, { immediate: true })

const timelineSegments = computed(() => {
  const layer = activeLayer.value
  return Array.from({ length: 8 }, (_, index) => {
    const hour = index * 3
    let state: ActiveLayerDisplay['availabilityState'] = 'empty'
    let availabilityLabel = '空状态'

    if (layer.catalogId) {
      const nearestSlot = Math.round(currentHour.value / 3) * 3
      const distance = Math.abs(hour - nearestSlot)
      if (layer.runReadiness === 'blocked') {
        state = 'empty'
        availabilityLabel = '数据未就绪'
      } else if (layer.dataState === 'real') {
        state = distance <= 3
          ? layer.availabilityState
          : layer.availabilityState === 'ready'
            ? 'partial'
            : layer.availabilityState
        availabilityLabel = distance <= 3 ? layer.availabilityLabel : '可继续查询'
      } else if (layer.supportsTime) {
        state = distance <= 6 ? 'partial' : 'empty'
        availabilityLabel = distance <= 6 ? '待运行' : '可请求'
      } else {
        state = layer.availabilityState
        availabilityLabel = layer.availabilityLabel
      }
    }

    return {
      hour,
      label: `${String(hour).padStart(2, '0')}:00`,
      state,
      availabilityLabel,
    }
  })
})

const timelineWorkflowIndicators = computed<TimelineWorkflowIndicator[]>(() => {
  return layersStore.jobLayers.map((job) => {
    const libItem = job.catalogId
      ? layersStore.layerLibrary.find((l) => l.catalogId === job.catalogId)
      : undefined
    return {
      name: job.name || libItem?.name || job.jobId,
      status: job.status,
      progress: job.progress ?? 0,
      engine: libItem?.engine ?? undefined,
    }
  })
})

function handleTileSourceChange(sourceId: TileSourceId) {
  uiStore.setTileSource(sourceId)
  logStore.logOperation('tile-source-change', `切换底图源: ${sourceId}`)
}

function handleLayerSelect(layerId: string) {
  layersStore.selectLayer(layerId)
  logStore.logOperation('layer-select', `选中图层: ${layerId}`)
}

function handleTimelineStep(delta: number) {
  uiStore.stepHour(delta)
  logStore.logOperation('timeline-step', `时间轴${delta > 0 ? '前进' : '后退'} ${Math.abs(delta)} 小时`)
}

function handleTimelineChange(hour: number) {
  uiStore.setHour(hour)
  logStore.logOperation('timeline-change', `时间轴跳转到 ${String(hour).padStart(2, '0')}:00`)
}

function handleTimelineDateChange(date: Date) {
  uiStore.setDate(date)
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  logStore.logOperation('timeline-date-change', `日期切换到 ${y}-${m}-${d}`)
}

function handleTimelineTogglePlay() {
  uiStore.togglePlay()
  logStore.logOperation('timeline-play', isPlaying.value ? '时间轴播放' : '时间轴暂停')
}

function handleVisibleHotspotsChange(hotspots: LayerHotspot[]) {
  visibleHotspots.value = hotspots
  if (selectedHotspot.value && !hotspots.some((hotspot) => hotspot.id === selectedHotspot.value?.id)) {
    selectedHotspot.value = null
  }
}

function handleHotspotSelect(hotspot: LayerHotspot | null) {
  selectedHotspot.value = hotspot
}

function handleMapPointSelect(point: { lng: number; lat: number }) {
  selectedMapPoint.value = point
  logStore.logOperation('map-point-select', `查询点 (${point.lng.toFixed(4)}, ${point.lat.toFixed(4)})`)
  void layersStore.fetchPointWeather(point.lng, point.lat, activeLayer.value.catalogId)
  void fetchOverlayPointValues(point.lng, point.lat)
}

function handleOverlayTimeUpdate(states: OverlayTimeState[]) {
  overlayTimeStates.value = states
}

async function fetchOverlayPointValues(lng: number, lat: number) {
  const states = overlayTimeStates.value
  if (states.length === 0) {
    overlayPointValues.value = []
    return
  }
  const results = await Promise.allSettled(
    states.map((s) => getOverlayValue(s.layerId, lng, lat, s.currentTime ?? undefined)),
  )
  overlayPointValues.value = results
    .map((r) => (r.status === 'fulfilled' ? r.value : null))
    .filter((v): v is OverlayPointValue => v !== null)
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

function handleRunWorkflowFromEditor(workflowId: string, linkedLayerId: string | null, target: WorkflowRunTarget) {
  logStore.logWorkflow('workflow-editor-run', `从编辑器运行工作流: ${workflowId} (目标: ${target.mode})`)
  if (!linkedLayerId) {
    logStore.logWorkflow('workflow-editor-error', `工作流 ${workflowId} 未关联图层，无法运行`)
    return
  }
  // 关闭编辑器面板，切换到工作流状态面板查看执行进度
  workflowEditorOpen.value = false
  workflowStatusOpen.value = true

  if (target.mode === 'default') {
    // 默认图层：直接使用源 layer_id 运行
    void handleRunWorkflow(linkedLayerId)
  } else {
    // 新建图层：在前端注册表创建产出条目，再用本地 catalogId 运行
    // runWorkflowForCatalog 会自动将本地 catalogId 解析回源 layer_id 提交后端
    const engine = layersStore.layerLibrary.find((l) => l.catalogId === linkedLayerId)?.engine ?? 'general'
    const entry = workflowOutputStore.createOutputLayer({
      name: target.name ?? `产出 ${workflowId}`,
      group: target.group ?? '默认分组',
      sourceWorkflowId: workflowId,
      sourceLayerId: linkedLayerId,
      engine,
    })
    logStore.logWorkflow('workflow-output-create', `创建产出图层「${entry.name}」→ 分组「${entry.group}」`)
    void handleRunWorkflow(entry.localId)
  }
}

async function handleRunWorkflow(catalogId: string) {
  logStore.logWorkflow('workflow-submit', `提交工作流: ${catalogId}`)
  try {
    await layersStore.runWorkflowForCatalog(catalogId)
    logStore.logWorkflow('workflow-accepted', `工作流已受理: ${catalogId}`)
  } catch (error) {
    logStore.logWorkflow('workflow-error', `工作流提交失败: ${catalogId} — ${(error as Error)?.message ?? error}`)
    console.error('[DashboardView] workflow submit failed', error)
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
      void layersStore.fetchPointWeather(selectedMapPoint.value.lng, selectedMapPoint.value.lat, catalogId)
    }
  },
)

function buildFallbackActiveLayer(): ActiveLayerDisplay {
  return {
    instanceId: '',
    catalogId: '',
    name: '无图层',
    category: '',
    summary: '请在左侧面板选择图层进行展示。',
    metricLabel: '—',
    metricValue: '—',
    trendLabel: '—',
    statusLabel: '—',
    updateLabel: '—',
    sourceLabel: '—',
    confidenceLabel: '—',
    accentColor: '#5a6a80',
    accentGlow: 'rgba(90, 106, 128, 0.3)',
    chipTone: 'rgba(90, 106, 128, 0.16)',
    availabilityState: 'empty',
    availabilityLabel: '空状态',
    availabilityDescription: '从左侧图层面板添加数据图层。',
    observationTimeLabel: '—',
    missingFieldsLabel: '—',
    hotspots: [],
    isAdminBoundary: false,
    isImported: false,
    isImportedRaster: false,
    visible: true,
    opacity: 1,
    order: 0,
    dataState: 'catalog',
  }
}
</script>

<template>
  <main ref="dashboardRef" class="dashboard">
    <section ref="mapShellRef" class="map-shell">
      <MapCanvas
        ref="mapCanvasRef"
        :tile-source-id="tileSourceId"
        :current-hour="currentHour"
        :hour-label="hourLabel"
        @visible-hotspots-change="handleVisibleHotspotsChange"
        @hotspot-select="handleHotspotSelect"
        @map-point-select="handleMapPointSelect"
        @overlay-time-update="handleOverlayTimeUpdate"
      />

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
            :is-playing="isPlaying"
            :workflow-indicators="timelineWorkflowIndicators"
            @step="handleTimelineStep"
            @change-hour="handleTimelineChange"
            @change-date="handleTimelineDateChange"
            @toggle-play="handleTimelineTogglePlay"
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

    <WorkflowStatusPanel
      v-if="workflowStatusOpen"
      @close="handleCloseWorkflowStatus"
    />

    <LogPanel
      v-if="logOpen"
      @close="logOpen = false"
    />

    <SettingsPanel
      v-if="settingsOpen"
      @close="handleCloseSettings"
    />

    <WorkflowEditorPanel
      v-if="workflowEditorOpen"
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
