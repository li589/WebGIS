<script setup lang="ts">
/**
 * DashboardView — 仪表盘主视图（编排壳）。
 *
 * 职责：初始化 store / 组装 composables / 声明少量内联 handler / 渲染模板。
 * 时间轴同步、天气覆盖、地图点查、工作流编辑器运行等逻辑均委托给 composables。
 *
 * 拆分历史：原 1659 行 → CSS 提取(-196) → composable 提取(-1050)
 */
import { computed, defineAsyncComponent, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useDataImportFlow } from '../data-manager/core/workspace-store'

import PanelDock from '../components/ui/PanelDock.vue'
import InfoPanel from '../components/InfoPanel.vue'
import LayerSidebar from '../components/LayerSidebar.vue'
import MapCanvas from '../components/MapCanvas.vue'
import ModeToolbar from '../components/ModeToolbar.vue'
import LogPanel from '../components/toolbar/LogPanel.vue'
import TimelinePanel from '../components/TimelinePanel.vue'
import TimelineScrubber from '../components/TimelineScrubber.vue'
import WorkflowStatusPanel from '../components/workflow/WorkflowStatusPanel.vue'
import type { TileSourceId } from '../services/api-config'
import type { OverlayTimeState } from '../components/map/overlay-image-module'
import { useUiStore } from '../stores/ui'
import { useUiLoadingStore } from '../stores/ui-loading'
import { useLayersStore } from '../stores/layers'
import { useLogStore } from '../stores/log'
import { useWeatherTileManager } from '../stores/weather-tile-manager'
import { useWeatherSyncStatusStore } from '../stores/weather-sync-status'
import { useWeatherEngineStore } from '../stores/weather-engine'
import { useWorkflowOutputLayersStore } from '../stores/workflow-output-layers'
import { buildFallbackActiveLayerDisplay } from '../components/map/map-stage-view-model'
import {
  resolveAnalysisStageKind,
  resolveAnalysisStageLabel,
} from '../components/info-panel/analysis-panel-summary'

// ── Composables ──────────────────────────────────────────────────────────
import { usePanelManager } from './dashboard/usePanelManager'
import { useWeatherCoverage } from './dashboard/useWeatherCoverage'
import { useTimelineSync } from './dashboard/useTimelineSync'
import { useMapInspect } from './dashboard/useMapInspect'
import { useTimelineControls } from './dashboard/useTimelineControls'
import { useFileDrop } from './dashboard/useFileDrop'
import { useWorkflowEditorRun } from './dashboard/useWorkflowEditorRun'

// ── Store 设置 ────────────────────────────────────────────────────────────
const uiStore = useUiStore()
const layersStore = useLayersStore()
const logStore = useLogStore()
const uiLoading = useUiLoadingStore()
const weatherTileManager = useWeatherTileManager()
const weatherSyncStatus = useWeatherSyncStatusStore()
const weatherEngine = useWeatherEngineStore()
const workflowOutputStore = useWorkflowOutputLayersStore()

uiLoading.showImmediate('初始化地图数据...')
void layersStore.ensureRuntimeLayerCatalog().finally(() => uiLoading.hideImmediate())
void layersStore.restoreActiveWorkflows()

const {
  tileSourceId,
  currentHour,
  currentDate,
  hourLabel,
  isPlaying,
  playIntervalMs,
  unifiedTimeLock,
} = storeToRefs(uiStore)
const {
  selectedLayerDisplay,
  activeLayerCount,
  workflowError,
  workflowProgressTimeSeek,
  isSubmitting,
  pointWeather,
  pointWeatherLoading,
  pointWeatherError,
} = storeToRefs(layersStore)
const { statusVersion: weatherStatusVersion, activityVersion: weatherActivityVersion } =
  storeToRefs(weatherTileManager)

const activeLayer = computed(() => selectedLayerDisplay.value ?? buildFallbackActiveLayerDisplay())

const stageLabel = computed(() => {
  const layer = activeLayer.value
  const hasRealSelection = Boolean(layer.instanceId)
  const isWeather = hasRealSelection && layersStore.isWeatherEngineLayer(layer.catalogId)
  const canRun =
    hasRealSelection &&
    !layer.isAdminBoundary &&
    !layer.isImported &&
    !layer.isImportedRaster &&
    !isWeather &&
    layersStore.supportsAnalysisWorkflow(layer.catalogId)
  return resolveAnalysisStageLabel(
    resolveAnalysisStageKind({
      hasRealSelection,
      isWeather,
      isImported: !!layer.isImported,
      isImportedRaster: !!layer.isImportedRaster,
      isAdminBoundary: !!layer.isAdminBoundary,
      canRunWorkflow: canRun,
    }),
  )
})

// ── 共享 ref ──────────────────────────────────────────────────────────────
const overlayTimeStates = ref<OverlayTimeState[]>([])
const dashboardRef = ref<HTMLElement | null>(null)
const mapShellRef = ref<HTMLElement | null>(null)
const mapCanvasRef = ref<InstanceType<typeof MapCanvas> | null>(null)

// ── Composable 调用（解构为顶层变量，模板自动解包） ──────────────────────

const {
  screenshotOpen,
  workflowStatusOpen,
  logOpen,
  settingsOpen,
  workflowEditorOpen,
  workflowEditorRef,
  analysisPanelRef,
  handleOpenScreenshot,
  handleCloseScreenshot,
  handleOpenSettings,
  handleCloseSettings,
  handleOpenWorkflowStatus,
  handleCloseWorkflowStatus,
  handleOpenWorkflowEditor,
  handleCloseWorkflowEditor,
} = usePanelManager(uiLoading, mapCanvasRef)

const { weatherCoverage, coverageSourceLabel } = useWeatherCoverage(
  weatherEngine,
  weatherSyncStatus,
  layersStore,
  selectedLayerDisplay,
  unifiedTimeLock,
  activeLayer,
)

const {
  tileForecastHour,
  selectedCatalogId,
  hasTimelineLayer,
  timelineLayerName,
  timelineAvailabilityLabel,
  timelineObservationLabel,
  activeLayerGranularity,
  isLayerLocked,
  timelineSegments,
} = useTimelineSync(
  uiStore,
  layersStore,
  logStore,
  weatherTileManager,
  weatherCoverage,
  mapCanvasRef,
  selectedLayerDisplay,
  activeLayer,
  overlayTimeStates,
  currentHour,
  currentDate,
  unifiedTimeLock,
  isPlaying,
  weatherStatusVersion,
  weatherActivityVersion,
  workflowProgressTimeSeek,
  analysisPanelRef,
)

const {
  selectedMapPoint,
  selectedHotspot,
  visibleHotspots,
  overlayPointValues,
  selectedOverlayTimeSeries,
  handleMapPointSelect,
  clearMapPointInspect,
  handleHotspotSelect,
  handleHotspotSelectFromPanel,
  handleVisibleHotspotsChange,
  handleOverlayTimeUpdate,
  fetchSelectedOverlaySeries,
} = useMapInspect(
  layersStore,
  logStore,
  uiStore,
  selectedLayerDisplay,
  tileForecastHour,
  mapCanvasRef,
  overlayTimeStates,
  activeLayer,
)

const {
  handleTimelineStep,
  handleTimelineChange,
  handleTimelineDateChange,
  handleTimelineTogglePlay,
  handleTimelinePlayInterval,
  handleTimelineToggleUnified,
  handleToggleLayerLock,
} = useTimelineControls(
  uiStore,
  logStore,
  selectedCatalogId,
  activeLayer,
  hourLabel,
  unifiedTimeLock,
  isPlaying,
)

const dataImportFlow = useDataImportFlow()
const { dropActive, onMapShellDragEnter, onMapShellDragOver, onMapShellDragLeave, onMapShellDrop } =
  useFileDrop(dataImportFlow, workflowEditorOpen, settingsOpen, mapShellRef)

const { handleRunWorkflowFromEditor } = useWorkflowEditorRun(
  layersStore,
  logStore,
  workflowOutputStore,
  workflowEditorOpen,
  workflowStatusOpen,
  workflowEditorRef,
)

// ── 异步组件 ──────────────────────────────────────────────────────────────
const ScreenshotExport = defineAsyncComponent(() => import('../components/ScreenshotExport.vue'))
const SettingsPanel = defineAsyncComponent(() => import('../components/settings/SettingsPanel.vue'))
const WorkflowEditorPanel = defineAsyncComponent(
  () => import('../components/workflow/WorkflowEditorPanel.vue'),
)

// ── 面板尺寸 ──────────────────────────────────────────────────────────────
const sidePanelDimensions = Object.freeze({
  defaultHeight: 372,
  minHeight: 236,
  maxHeight: 540,
  minWidth: 280,
  maxWidth: 420,
})
const layerPanelDimensions = Object.freeze({ ...sidePanelDimensions, defaultWidth: 292 })
const analysisPanelDimensions = Object.freeze({ ...sidePanelDimensions, defaultWidth: 304 })

// ── 内联 handler ──────────────────────────────────────────────────────────
function handleTileSourceChange(sourceId: TileSourceId) {
  uiStore.setTileSource(sourceId)
  logStore.logOperation('tile-source-change', `切换底图源: ${sourceId}`)
}
function handleLayerSelect(layerId: string) {
  if (layersStore.selectedInstanceId !== layerId) layersStore.selectLayer(layerId)
  logStore.logOperation('layer-select', `选中图层: ${layerId}`)
}
function handleZoomToLayer(instanceId: string) {
  if (mapCanvasRef.value?.fitToLayerExtent?.(instanceId))
    logStore.logOperation('layer-zoom', `缩放到图层: ${instanceId}`)
}
function handleToggleLayerVisibility(instanceId: string) {
  layersStore.toggleLayerVisibility(instanceId)
}
function handleSetLayerOpacity(payload: { instanceId: string; opacity: number }) {
  layersStore.setLayerOpacity(payload.instanceId, payload.opacity)
}
</script>

<template>
  <main ref="dashboardRef" class="dashboard">
    <section
      ref="mapShellRef"
      class="map-shell"
      :class="{ 'drop-active': dropActive, 'map-shell--3d': uiStore.viewMode === '3d' }"
      @dragenter="onMapShellDragEnter"
      @dragover="onMapShellDragOver"
      @dragleave="onMapShellDragLeave"
      @drop="onMapShellDrop"
    >
      <MapCanvas
        v-if="uiStore.viewMode === '2d'"
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

      <div v-else class="view-placeholder-3d">
        <div class="placeholder-3d-inner">
          <div class="placeholder-3d-icon">🌐</div>
          <h2 class="placeholder-3d-title">3D 地球视图</h2>
          <p class="placeholder-3d-desc">该功能尚未实现</p>
          <p class="placeholder-3d-hint">点击顶栏「3D」按钮可返回 2D 平面地图</p>
        </div>
      </div>

      <div v-if="dropActive" class="import-drop-overlay" aria-hidden="true">
        <div class="import-drop-card">
          <span class="import-drop-title">释放以导入数据</span>
          <span class="import-drop-desc"
            >SHP(+旁路) / GeoJSON / CSV·Excel·TXT / TIF·NC·HDF·MAT</span
          >
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
        <PanelDock
          panel-label="图层"
          panel-key="layers"
          position="left"
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
          <LayerSidebar @select-layer="handleLayerSelect" @zoom-to-layer="handleZoomToLayer" />
        </PanelDock>
      </div>

      <div class="overlay overlay-right">
        <PanelDock
          ref="analysisPanelRef"
          panel-label="分析"
          panel-key="analysis"
          position="right"
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
            :selected-overlay-time-series="selectedOverlayTimeSeries"
            @toggle-layer-visibility="handleToggleLayerVisibility"
            @set-layer-opacity="handleSetLayerOpacity"
            @select-hotspot="handleHotspotSelectFromPanel"
            @clear-map-point="clearMapPointInspect"
            @enter-select-mode="uiStore.setInteractionMode('select')"
            @query-overlay-series="
              (p: { lng: number; lat: number }) => fetchSelectedOverlaySeries(p.lng, p.lat)
            "
          />
        </PanelDock>
      </div>

      <div class="overlay overlay-bottom">
        <TimelinePanel
          panel-label="时间轴"
          panel-key="timeline"
          :max-offset-x="140"
          :max-offset-y="70"
          :default-width="720"
          :default-height="205"
          :min-width="460"
          :min-height="195"
          :max-width="980"
          :max-height="260"
        >
          <TimelineScrubber
            :current-hour="currentHour"
            :current-date="currentDate"
            :hour-label="hourLabel"
            :accent-color="hasTimelineLayer ? activeLayer.accentColor : '#64748b'"
            :availability-label="timelineAvailabilityLabel"
            :observation-time-label="timelineObservationLabel"
            :timeline-segments="timelineSegments"
            :coverage-source-label="coverageSourceLabel"
            :unified-time-lock="unifiedTimeLock"
            :is-playing="isPlaying"
            :play-interval-ms="playIntervalMs"
            :granularity="hasTimelineLayer ? activeLayerGranularity : 'hour'"
            :active-layer-name="timelineLayerName"
            :is-layer-locked="isLayerLocked"
            @step="handleTimelineStep"
            @change-hour="handleTimelineChange"
            @change-date="handleTimelineDateChange"
            @toggle-play="handleTimelineTogglePlay"
            @change-play-interval="handleTimelinePlayInterval"
            @toggle-unified-time="handleTimelineToggleUnified"
            @toggle-layer-lock="handleToggleLayerLock"
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
      :set-wind-animation-paused="mapCanvasRef?.setWindAnimationPaused ?? null"
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

<style scoped src="./dashboard/DashboardView.styles.css"></style>
