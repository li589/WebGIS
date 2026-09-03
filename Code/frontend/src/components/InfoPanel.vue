<script setup lang="ts">
/**
 * InfoPanel — 分析面板主组件（编排壳）。
 *
 * 职责：调用 composables 获取状态，将各 Tab 内容委托给子组件渲染。
 * 自身仅保留：空态、顶部 Tab 栏、顶摘要行（工作流错误/阶段/进度）。
 *
 * 拆分历史：原 4281 行 → CSS 提取(-1862) → composable 提取(-1170) → 子组件提取(-1050)
 */
import { computed, ref } from 'vue'

import { AlertTriangle } from './ui/icons'
import type { ActiveLayerDisplay, LayerHotspot } from '../stores/layers/types'
import type { WeatherPointResponse } from '../services/runtime-api'
import type { OverlayTimeState } from './map/overlay-image-module'
import { useLayerWorkspace } from '../stores/layers/selectors'
import { useUiStore } from '../stores/ui'
import { TILE_SOURCE_MAP } from '../services/api-config'
import { ANALYSIS_COPY } from '../ui-copy'
import { buildResultDisplayModel } from './info-panel/result-adapter'
import type { AnalysisTabId } from './info-panel/analysis-tab-focus'

// ── Composables ───────────────────────────────────────────────────────────
import { useLayerSymbology } from './info-panel/useLayerSymbology'
import { useWeatherPointData } from './info-panel/useWeatherPointData'
import { useOverlayData } from './info-panel/useOverlayData'
import { useUnifiedChartData } from './info-panel/useUnifiedChartData'
import { useWorkflowState } from './info-panel/useWorkflowState'
import { useImportExport } from './info-panel/useImportExport'
import { usePanelScroll } from './info-panel/usePanelScroll'

// ── 子组件 ─────────────────────────────────────────────────────────────────
import InfoPanelTopBar from './info-panel/InfoPanelTopBar.vue'
import InfoPanelMetaTab from './info-panel/InfoPanelMetaTab.vue'
import InfoPanelToolsTab from './info-panel/InfoPanelToolsTab.vue'
import InfoPanelVisualTab from './info-panel/InfoPanelVisualTab.vue'
import InfoPanelStyleTab from './info-panel/InfoPanelStyleTab.vue'

const workspace = useLayerWorkspace()
const uiStore = useUiStore()

// ── Props / Emits ─────────────────────────────────────────────────────────

const props = defineProps<{
  activeLayer: ActiveLayerDisplay
  stageLabel: string
  visibleHotspots: LayerHotspot[]
  selectedLayer?: ActiveLayerDisplay | null
  selectedHotspot?: LayerHotspot | null
  selectedMapPoint?: { lng: number; lat: number } | null
  inspectHour?: number
  isSubmitting?: boolean
  workflowError?: string | null
  pointWeather?: WeatherPointResponse | null
  pointWeatherLoading?: boolean
  pointWeatherError?: string | null
  overlayTimeStates?: OverlayTimeState[]
  overlayPointValues?: import('../services/runtime-api').OverlayPointValue[]
  selectedOverlayTimeSeries?: import('../services/runtime-api').OverlayPointValue[]
  allOverlayTimeSeries?: Record<string, import('../services/runtime-api').OverlayPointValue[]>
}>()

const emit = defineEmits<{
  toggleLayerVisibility: [instanceId: string]
  setLayerOpacity: [payload: { instanceId: string; opacity: number }]
  selectHotspot: [hotspotId: string]
  clearMapPoint: []
  enterSelectMode: []
  queryOverlaySeries: [payload: { lng: number; lat: number }]
}>()

// ── 基础计算属性 ──────────────────────────────────────────────────────────

const displayLayer = computed(() => props.selectedLayer ?? props.activeLayer)
const jobLayer = computed(() => displayLayer.value?.jobLayer)
const resultModel = computed(() => buildResultDisplayModel(jobLayer.value?.resultView ?? null))
const isRealtimeWeatherLayer = computed(() =>
  workspace.isWeatherEngineLayer(displayLayer.value.catalogId),
)

const activeTab = ref<AnalysisTabId>('visual')
function setActiveTab(tab: AnalysisTabId | string) {
  activeTab.value = tab as AnalysisTabId
}

/** 选点基础信息：无任何数据图层取值时，图表 tab 至少反馈坐标与底图 */
const pointInspectInfo = computed(() => {
  const point = props.selectedMapPoint
  if (!point) return null
  const basemapLabel = TILE_SOURCE_MAP.get(uiStore.tileSourceId)?.label ?? '空白底图'
  return {
    lng: point.lng.toFixed(5),
    lat: point.lat.toFixed(5),
    basemapLabel,
  }
})

// ── 从 props 派生 ComputedRef 供 composables 使用 ────────────────────────

const overlayTimeStatesRef = computed(() => props.overlayTimeStates ?? [])
const pointWeatherRef = computed(() => props.pointWeather ?? null)
const pointWeatherLoadingRef = computed(() => !!props.pointWeatherLoading)
const pointWeatherErrorRef = computed(() => props.pointWeatherError ?? null)
const selectedMapPointRef = computed(() => props.selectedMapPoint ?? null)
const inspectHourRef = computed(() => props.inspectHour ?? 0)
const isSubmittingRef = computed(() => !!props.isSubmitting)
const visibleHotspotsRef = computed(() => props.visibleHotspots ?? [])
const selectedHotspotRef = computed(() => props.selectedHotspot ?? null)
const overlayPointValuesRef = computed(() => props.overlayPointValues ?? [])
const selectedOverlayTimeSeriesRef = computed(() => props.selectedOverlayTimeSeries ?? [])
const allOverlayTimeSeriesRef = computed(() => props.allOverlayTimeSeries ?? {})

// ── Composable 调用（按依赖顺序） ────────────────────────────────────────

const symbology = useLayerSymbology(
  displayLayer,
  isRealtimeWeatherLayer,
  overlayTimeStatesRef,
  pointWeatherRef,
)

const weatherPoint = useWeatherPointData(
  displayLayer,
  isRealtimeWeatherLayer,
  symbology.weatherRenderHint,
  pointWeatherRef,
  pointWeatherLoadingRef,
  pointWeatherErrorRef,
  selectedMapPointRef,
  inspectHourRef,
)

const overlay = useOverlayData(
  displayLayer,
  overlayTimeStatesRef,
  overlayPointValuesRef,
  selectedOverlayTimeSeriesRef,
  selectedMapPointRef,
  symbology.overlayStyleMeta,
)

const unified = useUnifiedChartData(
  pointWeatherRef,
  overlayPointValuesRef,
  allOverlayTimeSeriesRef,
  overlayTimeStatesRef,
  selectedMapPointRef,
  inspectHourRef,
)

const wf = useWorkflowState({
  displayLayer,
  jobLayer,
  isRealtimeWeatherLayer,
  tileStats: symbology.tileStats,
  isSubmitting: isSubmittingRef,
  windStyleChipLabel: symbology.windStyleChipLabel,
  canToggleParticleFlow: symbology.canToggleParticleFlow,
  visibleHotspots: visibleHotspotsRef,
  hasPointWeatherSection: weatherPoint.hasPointWeatherSection,
  showMultiOverlayBar: overlay.showMultiOverlayBar,
  showSelectedOverlayTimeSeries: overlay.showSelectedOverlayTimeSeries,
  showDemoOverlayTimeSeries: overlay.showDemoOverlayTimeSeries,
  hasUnifiedData: unified.hasUnifiedData,
  resultModel,
})

const impExp = useImportExport(displayLayer)

usePanelScroll(
  displayLayer,
  activeTab,
  symbology.hasLayerStyleSection,
  isRealtimeWeatherLayer,
  visibleHotspotsRef,
  selectedHotspotRef,
  pointWeatherLoadingRef,
  pointWeatherRef,
  pointWeatherErrorRef,
  selectedMapPointRef,
)

// ── 事件桥接 ────────────────────────────────────────────────────────────

function handleToggleLayerVisibility(instanceId: string) {
  emit('toggleLayerVisibility', instanceId)
}
function handleSetLayerOpacity(payload: { instanceId: string; opacity: number }) {
  emit('setLayerOpacity', payload)
}
function enterInspectTools() {
  setActiveTab('tools')
  emit('enterSelectMode')
}
function queryDefaultOverlaySeries() {
  emit('queryOverlaySeries', { lng: 11.25, lat: 19.7623 })
}
</script>

<template>
  <aside class="panel" :style="{ '--accent-color': displayLayer.accentColor }">
    <!-- 无选中：整页空态 -->
    <div v-if="!wf.hasRealSelection.value" ref="analysisScrollEl" class="analysis-idle">
      <div class="analysis-idle-orb" aria-hidden="true"></div>
      <p class="analysis-idle-kicker">{{ ANALYSIS_COPY.panelTitle }}</p>
      <h2 class="analysis-idle-title">{{ ANALYSIS_COPY.emptyTitle }}</h2>
      <p class="analysis-idle-lead">{{ ANALYSIS_COPY.emptyLeadShort }}</p>
      <ul class="analysis-idle-steps">
        <li>{{ ANALYSIS_COPY.emptyStepAdd }}</li>
        <li>{{ ANALYSIS_COPY.emptyStepInspect }}</li>
        <li>{{ ANALYSIS_COPY.emptyStepStyle }}</li>
      </ul>
    </div>

    <template v-else>
      <InfoPanelTopBar :active-tab="activeTab" @update:active-tab="setActiveTab" />

      <div ref="analysisScrollEl" class="panel-scroll">
        <!-- 顶摘要行 -->
        <div ref="topSummaryEl" class="panel-topline">
          <div v-if="workflowError" class="workflow-error">
            <span class="error-icon"><AlertTriangle :size="14" aria-hidden="true" /></span>
            <span class="error-message">{{ workflowError }}</span>
          </div>

          <!-- 2026-08-25 用户反馈：原 TopBar 右上角「图层名 · 阶段标签」
               指示移到这里（右对齐）；同时删除原顶摘要行的图层信息行
               （天气摘要「瓦片按视口自动加载…」/静态提示行/工作流引擎
               「⚡Python 处理器 xxx」）——图层名与摘要重复且属噪音。 -->
          <div class="panel-stage-row panel-stage-row--topline">
            <span
              class="readiness readiness--inline"
              :title="`${displayLayer.name} · ${stageLabel}`"
            >
              {{ displayLayer.name }} · {{ stageLabel }}
            </span>
            <button
              v-if="wf.onlinePlanPending.value"
              type="button"
              class="plan-pending-chip"
              :title="wf.onlinePlanPendingTitle"
              @click="wf.openOnlinePlanSession()"
            >
              {{ wf.onlinePlanPendingLabel }}
            </button>
          </div>

          <template v-if="wf.canRunWorkflow.value">
            <div v-if="wf.runBlockedReason.value" class="run-block-hint">
              {{ wf.runBlockedReason.value }}
            </div>
            <div
              v-if="wf.workflowVariants.value"
              class="variant-switch-row"
              role="radiogroup"
              aria-label="数据来源"
            >
              <span class="variant-label">数据来源</span>
              <div class="variant-segmented">
                <button
                  v-for="opt in wf.workflowVariants.value.options"
                  :key="opt.key"
                  type="button"
                  class="variant-seg-btn"
                  :class="{ active: opt.key === wf.workflowVariants.value.selectedKey }"
                  role="radio"
                  :aria-checked="opt.key === wf.workflowVariants.value.selectedKey"
                  :title="
                    opt.key === 'auto'
                      ? '按源路由策略：本地有数走本地，否则走在线'
                      : `切换为${opt.label}并重新运行`
                  "
                  @click="wf.switchWorkflowVariant(opt.key)"
                >
                  {{ opt.label }}
                </button>
              </div>
            </div>
          </template>

          <div v-if="wf.showWorkflowStageRow.value" class="workflow-stage-row">
            <span class="stage-pill" :class="wf.workflowStage.value">{{
              wf.workflowStage.value
            }}</span>
            <span class="stage-copy">{{ wf.workflowStageCopy.value }}</span>
          </div>

          <div
            v-if="
              wf.canRunWorkflow.value &&
              (wf.isWorkflowRunning.value || wf.workflowStage.value === 'succeeded')
            "
            class="wf-progress-bar"
          >
            <div
              class="wf-progress-fill"
              :class="wf.workflowStage.value"
              :style="{ width: wf.workflowProgress.value + '%' }"
            ></div>
          </div>

          <div v-if="wf.canRunWorkflow.value && wf.latestEventMessage.value" class="wf-event-msg">
            <span class="wf-event-dot" :class="wf.workflowStage.value"></span>
            <span class="wf-event-text">{{ wf.latestEventMessage.value }}</span>
          </div>
        </div>

        <!-- Tab 内容流 -->
        <div class="analysis-stream">
          <!-- meta Tab -->
          <div v-show="activeTab === 'meta'">
            <InfoPanelMetaTab
              :display-layer="displayLayer"
              :is-realtime-weather-layer="isRealtimeWeatherLayer"
              :job-layer="jobLayer"
              :result-model="resultModel"
              :analysis-summary="wf.analysisSummary.value"
              :show-compact-hero="wf.showCompactHero.value"
              :workflow-stage="wf.workflowStage.value"
              :workflow-stage-copy="wf.workflowStageCopy.value"
              :workflow-meta="wf.workflowMeta.value"
              :workflow-progress="wf.workflowProgress.value"
              :latest-event-message="wf.latestEventMessage.value"
              :can-run-workflow="wf.canRunWorkflow.value"
              :is-workflow-running="wf.isWorkflowRunning.value"
              :run-blocked-reason="wf.runBlockedReason.value"
              :show-workflow-stage-row="wf.showWorkflowStageRow.value"
              :weather-top-lines="wf.weatherTopLines.value"
              :static-top-hint="wf.staticTopHint.value"
              :job-event-notes="wf.jobEventNotes.value"
              :job-report-summary="wf.jobReportSummary.value"
              :has-layer-style-section="symbology.hasLayerStyleSection.value"
              :workflow-error="workflowError ?? null"
              :interaction-mode="uiStore.interactionMode"
              :import-action-hint="impExp.importActionHint.value"
              @set-active-tab="setActiveTab"
              @enter-select-mode="emit('enterSelectMode')"
              @export-geo-json="impExp.exportImportedGeoJson()"
              @export-csv="impExp.exportImportedCsv()"
              @export-shp="impExp.exportImportedShp()"
              @open-export-panel="impExp.openExportPanelForDisplay()"
              @export-raster="impExp.exportImportedRaster($event as 'png' | 'tif' | 'nc' | 'mat')"
            />
          </div>

          <!-- tools Tab -->
          <div v-show="activeTab === 'tools'">
            <InfoPanelToolsTab
              :display-layer="displayLayer"
              :selected-map-point="selectedMapPoint ?? null"
              :point-weather="pointWeather"
              :point-weather-primary-value="weatherPoint.pointWeatherPrimaryValue.value"
              :point-weather-numeric-value="weatherPoint.pointWeatherNumericValue.value"
              :interaction-mode="uiStore.interactionMode"
              :is-realtime-weather-layer="isRealtimeWeatherLayer"
              @enter-select-mode="emit('enterSelectMode')"
              @clear-map-point="emit('clearMapPoint')"
            />
          </div>

          <!-- visual Tab -->
          <div v-show="activeTab === 'visual'">
            <InfoPanelVisualTab
              :display-layer="displayLayer"
              :is-realtime-weather-layer="isRealtimeWeatherLayer"
              :has-analysis-charts="wf.hasAnalysisCharts.value"
              :analysis-charts="wf.analysisCharts.value"
              :analysis-tables="wf.analysisTables.value"
              :has-point-weather-section="weatherPoint.hasPointWeatherSection.value"
              :point-weather="pointWeather ?? null"
              :point-weather-loading="!!pointWeatherLoading"
              :point-weather-error="pointWeatherError ?? null"
              :selected-map-point="selectedMapPoint ?? null"
              :point-inspect-status-label="weatherPoint.pointInspectStatusLabel.value"
              :point-weather-primary-label="weatherPoint.pointWeatherPrimaryLabel.value"
              :point-weather-primary-value="weatherPoint.pointWeatherPrimaryValue.value"
              :point-weather-rows="weatherPoint.pointWeatherRows.value"
              :point-weather-hourly-rows="weatherPoint.pointWeatherHourlyRows.value"
              :point-weather-hourly-chart-rows="weatherPoint.pointWeatherHourlyChartRows.value"
              :point-weather-metric-label="weatherPoint.pointWeatherMetric.value.label"
              :show-multi-overlay-bar="overlay.showMultiOverlayBar.value"
              :multi-overlay-bar-items="overlay.multiOverlayBarItems.value"
              :show-selected-overlay-time-series="overlay.showSelectedOverlayTimeSeries.value"
              :show-demo-overlay-time-series="overlay.showDemoOverlayTimeSeries.value"
              :selected-overlay-time-series-rows="overlay.selectedOverlayTimeSeriesRows.value"
              :overlay-style-meta="symbology.overlayStyleMeta.value"
              :visible-hotspots="visibleHotspots"
              :selected-hotspot="selectedHotspot ?? null"
              :result-model="resultModel"
              :has-visual-tab-content="wf.hasVisualTabContent.value"
              :sparse-visual-hint="wf.sparseVisualHint.value"
              :visual-product-summary="wf.visualProductSummary.value"
              :point-inspect-info="pointInspectInfo"
              :can-run-workflow="wf.canRunWorkflow.value"
              :interaction-mode="uiStore.interactionMode"
              :has-unified-data="unified.hasUnifiedData.value"
              :has-point-comparison="unified.hasPointComparison.value"
              :has-multi-layer-time-series="unified.hasMultiLayerTimeSeries.value"
              :unified-bar-items="unified.unifiedBarItems.value"
              :unified-point-values="unified.unifiedPointValues.value"
              :all-time-series="unified.allTimeSeries.value"
              :time-series-by-category="unified.timeSeriesByCategory.value"
              :point-values-by-category="unified.pointValuesByCategory.value"
              @select-hotspot="emit('selectHotspot', $event)"
              @set-active-tab="setActiveTab"
              @enter-select-mode="enterInspectTools"
              @query-overlay-series="queryDefaultOverlaySeries"
            />
          </div>

          <!-- style Tab -->
          <div v-show="activeTab === 'style'">
            <InfoPanelStyleTab
              :display-layer="displayLayer"
              :is-realtime-weather-layer="isRealtimeWeatherLayer"
              :overlay-time-states="overlayTimeStates ?? []"
              :point-weather="pointWeather ?? null"
              @toggle-layer-visibility="handleToggleLayerVisibility"
              @set-layer-opacity="handleSetLayerOpacity"
            />
          </div>
        </div>
      </div>
    </template>
  </aside>
</template>

<style scoped src="./info-panel/InfoPanel.styles.css"></style>
