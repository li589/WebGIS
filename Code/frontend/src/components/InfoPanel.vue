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

import type { ActiveLayerDisplay, LayerHotspot } from '../stores/layers/types'
import type { WeatherPointResponse } from '../services/runtime-api'
import type { OverlayTimeState } from './map/overlay-image-module'
import { useLayersStore } from '../stores/layers'
import { useUiStore } from '../stores/ui'
import { ANALYSIS_COPY } from '../ui-copy'
import { buildResultDisplayModel } from './info-panel/result-adapter'
import type { AnalysisTabId } from './info-panel/analysis-tab-focus'

// ── Composables ───────────────────────────────────────────────────────────
import { useLayerSymbology } from './info-panel/useLayerSymbology'
import { useWeatherPointData } from './info-panel/useWeatherPointData'
import { useOverlayData } from './info-panel/useOverlayData'
import { useWorkflowState } from './info-panel/useWorkflowState'
import { useImportExport } from './info-panel/useImportExport'
import { usePanelScroll } from './info-panel/usePanelScroll'

// ── 子组件 ─────────────────────────────────────────────────────────────────
import InfoPanelTopBar from './info-panel/InfoPanelTopBar.vue'
import InfoPanelMetaTab from './info-panel/InfoPanelMetaTab.vue'
import InfoPanelToolsTab from './info-panel/InfoPanelToolsTab.vue'
import InfoPanelVisualTab from './info-panel/InfoPanelVisualTab.vue'
import InfoPanelStyleTab from './info-panel/InfoPanelStyleTab.vue'

const layersStore = useLayersStore()
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
  layersStore.isWeatherEngineLayer(displayLayer.value.catalogId),
)

const activeTab = ref<AnalysisTabId>('visual')
function setActiveTab(tab: AnalysisTabId | string) {
  activeTab.value = tab as AnalysisTabId
}

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

const wf = useWorkflowState(
  displayLayer,
  jobLayer,
  isRealtimeWeatherLayer,
  symbology.tileStats,
  isSubmittingRef,
  symbology.windStyleChipLabel,
  symbology.canToggleParticleFlow,
  visibleHotspotsRef,
  weatherPoint.hasPointWeatherSection,
  overlay.showMultiOverlayBar,
  overlay.showSelectedOverlayTimeSeries,
  overlay.showDemoOverlayTimeSeries,
  pointWeatherRef,
  resultModel,
)

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
      <InfoPanelTopBar
        :active-tab="activeTab"
        :stage-label="stageLabel"
        @update:active-tab="setActiveTab"
      />

      <div ref="analysisScrollEl" class="panel-scroll">
        <!-- 顶摘要行 -->
        <div ref="topSummaryEl" class="panel-topline">
          <div v-if="workflowError" class="workflow-error">
            <span class="error-icon">⚠️</span>
            <span class="error-message">{{ workflowError }}</span>
          </div>

          <div v-if="isRealtimeWeatherLayer" class="analysis-context-card">
            <p class="analysis-context-line">
              {{ displayLayer.name }}
              <span v-if="wf.weatherTopLines.value[0]"> · {{ wf.weatherTopLines.value[0] }}</span>
            </p>
          </div>

          <div v-else-if="!wf.canRunWorkflow.value" class="analysis-context-card">
            <p class="analysis-context-line">{{ displayLayer.name }} · {{ wf.staticTopHint.value }}</p>
          </div>

          <template v-else>
            <div v-if="wf.runBlockedReason.value" class="run-block-hint">
              {{ wf.runBlockedReason.value }}
            </div>
            <div v-if="wf.workflowMeta.value.engineLabel" class="workflow-meta-row">
              <span class="wf-engine-icon" aria-hidden="true">{{ wf.workflowMeta.value.engineIcon }}</span>
              <span class="wf-engine-label">{{ wf.workflowMeta.value.engineLabel }}</span>
              <span v-if="wf.workflowMeta.value.name" class="wf-name">{{ wf.workflowMeta.value.name }}</span>
            </div>
          </template>

          <div v-if="wf.showWorkflowStageRow.value" class="workflow-stage-row">
            <span class="stage-pill" :class="wf.workflowStage.value">{{ wf.workflowStage.value }}</span>
            <span class="stage-copy">{{ wf.workflowStageCopy.value }}</span>
          </div>

          <div
            v-if="wf.canRunWorkflow.value && (wf.isWorkflowRunning.value || wf.workflowStage.value === 'succeeded')"
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
              :can-run-workflow="wf.canRunWorkflow.value"
              :interaction-mode="uiStore.interactionMode"
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
