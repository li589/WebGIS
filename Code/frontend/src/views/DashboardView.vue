<script setup lang="ts">
/**
 * DashboardView — 仪表盘主视图（编排壳）。
 *
 * 职责：初始化 store / 组装 composables / 声明少量内联 handler / 渲染模板。
 * 时间轴同步、天气覆盖、地图点查、工作流编辑器运行等逻辑均委托给 composables。
 *
 * 拆分历史：原 1659 行 → CSS 提取(-196) → composable 提取(-1050)
 */
import { computed, defineAsyncComponent, onBeforeUnmount, ref, toRef } from 'vue'
import { Globe } from '../components/ui/icons'
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
import {
  is3DViewExperimentalEnabled,
  subscribe3DViewExperimental,
} from '../services/settings-local'
import type { OverlayTimeState } from '../components/map/overlay-image-module'
import { useUiStore } from '../stores/ui'
import { useUiLoadingStore } from '../stores/ui-loading'
import { useLayerWorkspace, useLayerLifecycle, useWorkflowRun } from '../stores/layers/selectors'
import { syncWorkspaceOnBoot, teardownWorkspaceSync } from '../stores/layers/workspace-sync'
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
import { useOnlineTemporalIntegration } from './dashboard/useOnlineTemporalIntegration'

// ── Store 设置 ────────────────────────────────────────────────────────────
const uiStore = useUiStore()
const workspace = useLayerWorkspace()
const workflowRun = useWorkflowRun()
const lifecycle = useLayerLifecycle()
const logStore = useLogStore()
const uiLoading = useUiLoadingStore()
const weatherTileManager = useWeatherTileManager()
const weatherSyncStatus = useWeatherSyncStatusStore()
const weatherEngine = useWeatherEngineStore()
const workflowOutputStore = useWorkflowOutputLayersStore()

uiLoading.showImmediate('初始化地图数据...')
void workspace.ensureRuntimeLayerCatalog().finally(() => uiLoading.hideImmediate())
// 先完成跨设备工作区同步（远端较新时接管 localStorage），再从快照恢复图层。
// 全程开启水合保护：防止 MapCanvas 草稿恢复的早期落盘在矢量图层恢复前
// 重写快照，把未恢复的导入图层永久抹掉（见 workspace-hydrate 注释）。
void (async () => {
  workflowRun.setWorkspaceHydrationGuard(true)
  try {
    await syncWorkspaceOnBoot()
    await workflowRun.restoreActiveWorkflows()
  } finally {
    workflowRun.setWorkspaceHydrationGuard(false)
  }
})()

// Dashboard 卸载时清理所有 429 重试定时器，防止已取消的工作流被重新提交
onBeforeUnmount(() => {
  workflowRun.cleanupAllRetryTimers()
  teardownWorkspaceSync()
  _unsubscribe3DView?.()
  _unsubscribe3DView = null
})

const tileSourceId = toRef(uiStore, 'tileSourceId')
const currentHour = toRef(uiStore, 'currentHour')
const currentDate = toRef(uiStore, 'currentDate')
const hourLabel = toRef(uiStore, 'hourLabel')
const isPlaying = toRef(uiStore, 'isPlaying')
const playIntervalMs = toRef(uiStore, 'playIntervalMs')
const unifiedTimeLock = toRef(uiStore, 'unifiedTimeLock')
const { selectedLayerDisplay, isSubmitting, selectedInstanceId } = workspace
const {
  workflowError,
  workflowProgressTimeSeek,
  pointWeather,
  pointWeatherLoading,
  pointWeatherError,
} = workflowRun
const weatherStatusVersion = toRef(weatherTileManager, 'statusVersion')
const weatherActivityVersion = toRef(weatherTileManager, 'activityVersion')

const activeLayer = computed(() => selectedLayerDisplay.value ?? buildFallbackActiveLayerDisplay())
const has3dCompatibleLayer = computed(() => Boolean(activeLayer.value.instanceId))

const stageLabel = computed(() => {
  const layer = activeLayer.value
  const hasRealSelection = Boolean(layer.instanceId)
  const isWeather = hasRealSelection && workspace.isWeatherEngineLayer(layer.catalogId)
  const canRun =
    hasRealSelection &&
    !layer.isAdminBoundary &&
    !layer.isImported &&
    !layer.isImportedRaster &&
    !isWeather &&
    workspace.supportsAnalysisWorkflow(layer.catalogId)
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
  timelineSegments,
} = useTimelineSync(
  uiStore,
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

// ── 图层平台子系统：选中图层生命周期（时间轴徽标数据源） ──
const selectedLayerLifecycle = computed(() => {
  const catalogId = selectedCatalogId.value
  if (!catalogId) return null
  return lifecycle.getLifecycle(catalogId)
})

// ── 实验性 3D 视图（外观设置勾选）──
// 勾选后 3D 模式复用现有 MapCanvas 并切 globe 投影；未勾选时保持「尚未实现」遮罩。
const enable3DView = ref(is3DViewExperimentalEnabled())
let _unsubscribe3DView: (() => void) | null = null
{
  _unsubscribe3DView = subscribe3DViewExperimental(() => {
    enable3DView.value = is3DViewExperimentalEnabled()
  })
}
/** 3D 模式下是否直接显示真实地图（globe 投影） */
const showGlobeMap = computed(
  () => uiStore.viewMode === '2d' || (uiStore.viewMode === '3d' && enable3DView.value),
)
const globeProjectionOn = computed(() => uiStore.viewMode === '3d' && enable3DView.value)

// ── Online Temporal Integration ──
// 在线时间获取编排器：当用户选中 fetchable 段时自动触发工作流获取数据
const onlineTemporal = useOnlineTemporalIntegration({
  workspace,
  workflowRun,
  selectedCatalogId,
  currentDate,
  currentHour,
  activeLayerGranularity,
  timelineSegments,
  isPlaying,
  logOperation: (tag, message) => logStore.logOperation(tag, message),
})

const {
  selectedMapPoint,
  selectedHotspot,
  visibleHotspots,
  overlayPointValues,
  selectedOverlayTimeSeries,
  allOverlayTimeSeries,
  handleMapPointSelect,
  clearMapPointInspect,
  handleHotspotSelect,
  handleHotspotSelectFromPanel,
  handleVisibleHotspotsChange,
  handleOverlayTimeUpdate,
  fetchSelectedOverlaySeries,
} = useMapInspect(
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
  logStore,
  workflowOutputStore,
  workflowEditorOpen,
  workflowStatusOpen,
  workflowEditorRef,
)

// ── 异步组件 ──────────────────────────────────────────────────────────────
// chunk 加载失败（弱网/刷新竞态）时 loader promise reject，组件永不挂载，
// usePanelManager 的 showImmediate 将无人配对 hideImmediate → 顶栏光带
// 永久加载（2026-08-25 反馈）。此处统一兜底关 loading 后再抛出。
function withLoadingGuard<T>(loader: () => Promise<T>) {
  return async (): Promise<T> => {
    try {
      return await loader()
    } catch (err) {
      try {
        uiLoading.hideImmediate()
      } catch {
        /* store 未就绪时忽略 */
      }
      throw err
    }
  }
}
const ScreenshotExport = defineAsyncComponent(
  withLoadingGuard(() => import('../components/ScreenshotExport.vue')),
)
const SettingsPanel = defineAsyncComponent(
  withLoadingGuard(() => import('../components/settings/SettingsPanel.vue')),
)
const WorkflowEditorPanel = defineAsyncComponent(
  withLoadingGuard(() => import('../components/workflow/WorkflowEditorPanel.vue')),
)

// ── 面板尺寸 ──────────────────────────────────────────────────────────────
// 2026-08-25 用户反馈：图层/分析面板纵向拉伸要能拉到主界面最底——
// maxHeight 随视口高度动态计算（overlay 顶部 9.5rem=152px + 12px 底部
// 呼吸余量）；小屏（结果 < 540）保持原 540 下限，行为不回退。
function computeSidePanelMaxHeight(): number {
  if (typeof window === 'undefined') return 540
  return Math.max(540, window.innerHeight - 152 - 12)
}
const sidePanelMaxHeight = ref(computeSidePanelMaxHeight())
function handleSidePanelResize(): void {
  sidePanelMaxHeight.value = computeSidePanelMaxHeight()
}
if (typeof window !== 'undefined') {
  window.addEventListener('resize', handleSidePanelResize)
}
onBeforeUnmount(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('resize', handleSidePanelResize)
  }
})
const sidePanelDimensions = computed(() => ({
  defaultHeight: 372,
  minHeight: 236,
  maxHeight: sidePanelMaxHeight.value,
  minWidth: 280,
  maxWidth: 420,
}))
const layerPanelDimensions = computed(() => ({ ...sidePanelDimensions.value, defaultWidth: 292 }))
const analysisPanelDimensions = computed(() => ({
  ...sidePanelDimensions.value,
  defaultWidth: 304,
}))

// ── 内联 handler ──────────────────────────────────────────────────────────
function handleTileSourceChange(sourceId: TileSourceId) {
  uiStore.setTileSource(sourceId)
  logStore.logOperation('tile-source-change', `切换底图源: ${sourceId}`)
}
function handleLayerSelect(layerId: string) {
  if (selectedInstanceId.value !== layerId) workspace.selectLayer(layerId)
  logStore.logOperation('layer-select', `选中图层: ${layerId}`)
}
function handleZoomToLayer(instanceId: string) {
  if (mapCanvasRef.value?.fitToLayerExtent?.(instanceId))
    logStore.logOperation('layer-zoom', `缩放到图层: ${instanceId}`)
}
function handleToggleLayerVisibility(instanceId: string) {
  workspace.toggleLayerVisibility(instanceId)
}
function handleSetLayerOpacity(payload: { instanceId: string; opacity: number }) {
  workspace.setLayerOpacity(payload.instanceId, payload.opacity)
}

/** 用户点击时间轴上的 fetchable 段时，手动触发在线获取 */
function handleFetchSegment(_segment: { index: number; label: string; state: string }) {
  const catalogId = selectedCatalogId.value
  if (!catalogId) return
  const timeKey = onlineTemporal.orchestrator.currentTimeKey.value
  if (!timeKey) return
  void onlineTemporal.orchestrator.triggerOnlineFetch(catalogId, timeKey)
  logStore.logOperation('online-temporal', `手动触发获取 ${catalogId} @ ${timeKey}`)
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
        v-if="showGlobeMap"
        ref="mapCanvasRef"
        :tile-source-id="tileSourceId"
        :current-hour="currentHour"
        :current-date="currentDate"
        :inspect-point="selectedMapPoint"
        :globe-projection="globeProjectionOn"
        @visible-hotspots-change="handleVisibleHotspotsChange"
        @hotspot-select="handleHotspotSelect"
        @map-point-select="handleMapPointSelect"
        @overlay-time-update="handleOverlayTimeUpdate"
      />

      <div v-else class="view-placeholder-3d" :class="{ 'view-placeholder-3d--layer-ready': has3dCompatibleLayer }">
        <div class="placeholder-3d-stars" aria-hidden="true">
          <i v-for="n in 10" :key="n" :style="{ '--star-index': n }"></i>
        </div>
        <div class="placeholder-3d-orbit orbit--one" aria-hidden="true"></div>
        <div class="placeholder-3d-orbit orbit--two" aria-hidden="true"></div>
        <div class="placeholder-3d-planet" aria-hidden="true">
          <div class="planet-grid"></div>
          <div class="planet-glow"></div>
        </div>
        <div class="placeholder-3d-inner">
          <div class="placeholder-3d-icon"><Globe :size="30" aria-hidden="true" /></div>
          <h2 class="placeholder-3d-title">3D 地球视图</h2>
          <p class="placeholder-3d-desc">该功能尚未实现</p>
          <p v-if="has3dCompatibleLayer" class="placeholder-3d-layer-note">
            已保留当前图层状态，3D 渲染器上线后将继续使用「{{ activeLayer.name }}」
          </p>
          <p class="placeholder-3d-hint">点击顶栏「2D」按钮可返回平面地图</p>
          <p class="placeholder-3d-hint">
            可在 设置 → 外观 → 地图显示 勾选「启用3D视图（实验测试）」提前体验地球投影
          </p>
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
          :hour-label="hourLabel"
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
            :all-overlay-time-series="allOverlayTimeSeries"
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
          :default-height="235"
          :min-width="460"
          :min-height="210"
          :max-width="980"
          :max-height="330"
        >
          <TimelineScrubber
            :current-hour="currentHour"
            :current-date="currentDate"
            :hour-label="hourLabel"
            :accent-color="hasTimelineLayer ? activeLayer.accentColor : 'var(--text-secondary)'"
            :availability-label="timelineAvailabilityLabel"
            :observation-time-label="timelineObservationLabel"
            :timeline-segments="timelineSegments"
            :coverage-source-label="coverageSourceLabel"
            :unified-time-lock="unifiedTimeLock"
            :is-playing="isPlaying"
            :play-interval-ms="playIntervalMs"
            :granularity="hasTimelineLayer ? activeLayerGranularity : 'hour'"
            :active-layer-name="timelineLayerName"
            :online-fetch-in-progress="
              onlineTemporal.orchestrator.currentFetchStatus.value?.status === 'in-flight' ||
              onlineTemporal.orchestrator.currentFetchStatus.value?.status === 'submitting'
            "
            :lifecycle-state="selectedLayerLifecycle?.lifecycleState ?? 'unknown'"
            :lifecycle-message="selectedLayerLifecycle?.message ?? null"
            @step="handleTimelineStep"
            @change-hour="handleTimelineChange"
            @change-date="handleTimelineDateChange"
            @toggle-play="handleTimelineTogglePlay"
            @change-play-interval="handleTimelinePlayInterval"
            @toggle-unified-time="handleTimelineToggleUnified"
            @toggle-layer-lock="handleToggleLayerLock"
            @fetch-segment="handleFetchSegment"
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
