<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import type { ActiveLayerDisplay, LayerHotspot } from '../stores/layers/types'
import type { WeatherPointResponse } from '../services/runtime-api'
import { useLayersStore } from '../stores/layers'
import { useUiStore } from '../stores/ui'
import IntegrationStatusPanel from './info-panel/IntegrationStatusPanel.vue'
import { buildWeatherLegendStops, isRealtimeWeatherLayerId } from './map/weather-render'
import { buildResultDisplayModel } from './info-panel/result-adapter'

const layersStore = useLayersStore()
const uiStore = useUiStore()

const props = defineProps<{
  activeLayer: ActiveLayerDisplay
  stageLabel: string
  visibleHotspots: LayerHotspot[]
  selectedLayer?: ActiveLayerDisplay | null
  selectedHotspot?: LayerHotspot | null
  isSubmitting?: boolean
  workflowError?: string | null
  pointWeather?: WeatherPointResponse | null
  pointWeatherLoading?: boolean
  pointWeatherError?: string | null
}>()

const emit = defineEmits<{
  runWorkflow: [catalogId: string]
  toggleLayerVisibility: [instanceId: string]
  setLayerOpacity: [payload: { instanceId: string; opacity: number }]
}>()

const displayLayer = computed(() => props.selectedLayer ?? props.activeLayer)
const jobLayer = computed(() => displayLayer.value?.jobLayer)
const resultModel = computed(() => buildResultDisplayModel(jobLayer.value?.resultView ?? null))
const analysisSummary = computed(() => displayLayer.value.summary || props.activeLayer.summary)
const jobReportSummary = computed(() => jobLayer.value?.resultView?.summary ?? jobLayer.value?.reportSummary ?? '')
const isRealtimeWeatherLayer = computed(() => isRealtimeWeatherLayerId(displayLayer.value.catalogId))
const weatherRenderHint = computed(
  () => jobLayer.value?.mapLayerPayload?.renderHint ?? props.pointWeather?.render_hint ?? null,
)
const weatherLegendStops = computed(() => (weatherRenderHint.value ? buildWeatherLegendStops(weatherRenderHint.value) : []))
const hasWeatherLayerAsset = computed(() => !!jobLayer.value?.mapLayerPayload?.layerAssets?.geojsonUrl)
const jobEventNotes = computed(() => jobLayer.value?.eventMessages ?? jobLayer.value?.diagnosticNotes ?? [])
const hasWeatherStyleSection = computed(
  () => !!weatherRenderHint.value || canToggleParticleFlow.value || isRealtimeWeatherLayer.value,
)
const particleFlowButtonDisabled = computed(() => !hasWeatherLayerAsset.value && !isParticleFlowEnabled.value)

// 粒子流切换：仅风场变体图层显示按钮，独占式启用
const canToggleParticleFlow = computed(() => layersStore.supportsParticleFlow(displayLayer.value.catalogId))
const isParticleFlowEnabled = computed(() => layersStore.particleFlowCatalogId === displayLayer.value.catalogId)
function handleToggleParticleFlow() {
  if (particleFlowButtonDisabled.value) return
  layersStore.toggleParticleFlow(displayLayer.value.catalogId)
}
const hasPointWeatherSection = computed(
  () =>
    props.pointWeatherLoading ||
    !!props.pointWeatherError ||
    !!props.pointWeather ||
    isRealtimeWeatherLayer.value,
)

const WEATHER_METRIC_LABELS: Record<string, string> = {
  wind_speed_10m: '实时风速',
  wind_speed_80m: '80m 风速',
  wind_speed_120m: '120m 风速',
  wind_speed_180m: '180m 风速',
  wind_speed_850hPa: '850hPa 风速',
  wind_speed_500hPa: '500hPa 风速',
  wind_speed_200hPa: '200hPa 风速',
  temperature_2m: '实时气温',
  temperature_80m: '80m 气温',
  temperature_120m: '120m 气温',
  temperature_180m: '180m 气温',
  temperature_850hPa: '850hPa 气温',
  temperature_500hPa: '500hPa 气温',
  temperature_200hPa: '200hPa 气温',
  precipitation: '实时降水',
  relative_humidity_2m: '实时湿度',
  pressure_msl: '实时气压',
  visibility: '实时能见度',
}

function asWeatherRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' ? value as Record<string, unknown> : null
}

function readWeatherMetricValue(source: unknown, metricKey: string | null | undefined): number | null {
  if (!metricKey) return null
  const record = asWeatherRecord(source)
  const value = record?.[metricKey]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function normalizeWeatherUnit(unit: string | null | undefined): string {
  if (unit === 'C') return '°C'
  return unit ?? ''
}

function inferFallbackMetric(catalogId: string): string {
  if (catalogId.startsWith('wind-field-80m')) return 'wind_speed_80m'
  if (catalogId.startsWith('wind-field-120m')) return 'wind_speed_120m'
  if (catalogId.startsWith('wind-field-180m')) return 'wind_speed_180m'
  if (catalogId.startsWith('wind-field-850hPa')) return 'wind_speed_850hPa'
  if (catalogId.startsWith('wind-field-500hPa')) return 'wind_speed_500hPa'
  if (catalogId.startsWith('wind-field-200hPa')) return 'wind_speed_200hPa'
  if (catalogId.startsWith('wind-field')) return 'wind_speed_10m'
  if (catalogId.startsWith('temperature-80m')) return 'temperature_80m'
  if (catalogId.startsWith('temperature-120m')) return 'temperature_120m'
  if (catalogId.startsWith('temperature-180m')) return 'temperature_180m'
  if (catalogId.startsWith('temperature')) return 'temperature_2m'
  if (catalogId === 'precipitation') return 'precipitation'
  if (catalogId === 'humidity') return 'relative_humidity_2m'
  if (catalogId === 'pressure') return 'pressure_msl'
  if (catalogId === 'visibility') return 'visibility'
  return 'temperature_2m'
}

const pointWeatherMetric = computed(() => {
  const metricKey =
    props.pointWeather?.render_hint?.primary_metric
    ?? weatherRenderHint.value?.primary_metric
    ?? inferFallbackMetric(displayLayer.value.catalogId)
  const unit =
    props.pointWeather?.render_hint?.unit_label
    ?? weatherRenderHint.value?.unit_label
    ?? ''
  return {
    key: metricKey,
    label: WEATHER_METRIC_LABELS[metricKey] ?? '实时指标',
    unit: normalizeWeatherUnit(unit),
  }
})

const pointWeatherPrimaryLabel = computed(() => pointWeatherMetric.value.label)

// ── 元数据详情 ──────────────────────────────────────────────────────────────
const layerMetadata = computed(() => {
  const dl = displayLayer.value
  const weather = props.pointWeather
  const meta: { label: string; value: string }[] = [
    { label: '数据源', value: dl.sourceLabel || '—' },
    { label: '更新频率', value: dl.updateLabel || '—' },
    { label: '观测时间', value: dl.observationTimeLabel || '—' },
    { label: '可用性', value: dl.availabilityLabel || '—' },
  ]
  if (weather) {
    meta.push({ label: '数据提供方', value: weather.provider || '—' })
    meta.push({ label: '气象模型', value: weather.model || '—' })
    meta.push({ label: '缓存状态', value: weather.cache_status || '—' })
  }
  if (dl.jobLayer) {
    meta.push({ label: '作业状态', value: dl.jobLayer.status || '—' })
    if (dl.jobLayer.diagnosticNotes?.length) {
      meta.push({ label: '诊断', value: dl.jobLayer.diagnosticNotes.slice(0, 2).join('；') })
    }
  }
  return meta
})

// ── 叠加图层列表 ────────────────────────────────────────────────────────────
const overlayLayers = computed(() => {
  return layersStore.activeLayersDisplay
    .filter((l) => l.instanceId !== displayLayer.value.instanceId && l.visible)
    .map((l) => ({
      name: l.name,
      category: l.category,
      availabilityState: l.availabilityState,
      accentColor: l.accentColor,
    }))
})

const hasOverlayLayers = computed(() => overlayLayers.value.length > 0)

// ── 历史趋势方向识别 ────────────────────────────────────────────────────────
const trendDirection = computed<'up' | 'down' | 'flat'>(() => {
  const text = displayLayer.value?.trendLabel ?? ''
  if (/上升|增长|偏高|高于|增|升|回暖/.test(text)) return 'up'
  if (/下降|降低|偏低|低于|减|降|转凉/.test(text)) return 'down'
  return 'flat'
})
const trendArrowSymbol = computed(() => {
  if (trendDirection.value === 'up') return '↗'
  if (trendDirection.value === 'down') return '↘'
  return '→'
})
const pointWeatherPrimaryValue = computed(() => {
  const weather = props.pointWeather
  if (!weather) return '--'
  return formatMetric(
    readWeatherMetricValue(weather.current, pointWeatherMetric.value.key),
    pointWeatherMetric.value.unit,
  )
})
const pointWeatherRows = computed(() => {
  const weather = props.pointWeather
  if (!weather) return []
  const primaryValue = formatMetric(
    readWeatherMetricValue(weather.current, pointWeatherMetric.value.key),
    pointWeatherMetric.value.unit,
  )
  return [
    { label: 'Point', value: weather.place_name ?? `${weather.latitude.toFixed(3)}, ${weather.longitude.toFixed(3)}` },
    { label: 'Model', value: weather.model },
    {
      label: pointWeatherMetric.value.label,
      value: primaryValue,
    },
    { label: 'Observed', value: weather.observation_time ? formatTime(weather.observation_time) : '--' },
  ]
})
const pointWeatherHourlyRows = computed(() => {
  const weather = props.pointWeather
  if (!weather) return []
  return weather.hourly.slice(0, 4).map((entry) => {
    const metricValue =
      typeof entry.primary_value === 'number'
        ? entry.primary_value
        : readWeatherMetricValue(entry, pointWeatherMetric.value.key)
    const metric = formatMetric(metricValue, pointWeatherMetric.value.unit)
    return {
      time: formatHour(entry.time),
      metric,
    }
  }).filter((entry) => entry.metric !== `-- ${pointWeatherMetric.value.unit}`.trim())
})
const canRunWorkflow = computed(() => !displayLayer.value?.isAdminBoundary)
const isWorkflowRunning = computed(() => jobLayer.value?.status === 'running' || jobLayer.value?.status === 'queued')
const runBlockedReason = computed(() => layersStore.getCatalogRunBlockReason(displayLayer.value.catalogId))
const workflowStage = computed(() => {
  if (props.isSubmitting) return 'submitting'
  if (jobLayer.value?.status === 'queued') return 'queued'
  if (jobLayer.value?.status === 'running') return 'running'
  if (jobLayer.value?.status === 'succeeded') return 'succeeded'
  if (jobLayer.value?.status === 'failed') return 'failed'
  return 'idle'
})
const buttonDisabled = computed(() => Boolean(runBlockedReason.value) || isWorkflowRunning.value || props.isSubmitting)
const buttonLabel = computed(() => {
  if (runBlockedReason.value) return '数据未就绪'
  if (props.isSubmitting) return '提交中...'
  if (isWorkflowRunning.value) return '任务进行中'
  return '运行工作流'
})

const analysisScrollEl = ref<HTMLElement | null>(null)
const topSummaryEl = ref<HTMLElement | null>(null)
// 待清理的 setTimeout 句柄（组件卸载时统一清理，避免回调在卸载后执行）
const pendingTimers: number[] = []

function formatMetric(value: number | null | undefined, unit: string) {
  if (typeof value !== 'number' || Number.isNaN(value)) return `-- ${unit}`.trim()
  return `${value.toFixed(1)} ${unit}`.trim()
}

function formatTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function formatHour(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${String(date.getHours()).padStart(2, '0')}:00`
}

function handleRunWorkflow() {
  if (!displayLayer.value || !canRunWorkflow.value || buttonDisabled.value) return
  emit('runWorkflow', displayLayer.value.catalogId)
}

function handleToggleLayerVisibility() {
  if (!displayLayer.value?.instanceId) return
  emit('toggleLayerVisibility', displayLayer.value.instanceId)
}

function handleLayerOpacityInput(event: Event) {
  if (!displayLayer.value?.instanceId) return
  const target = event.target as HTMLInputElement
  emit('setLayerOpacity', {
    instanceId: displayLayer.value.instanceId,
    opacity: Number(target.value) / 100,
  })
}

function scrollAnalysisIntoView(selector: string) {
  const t = window.setTimeout(() => {
    const el = analysisScrollEl.value?.querySelector(selector) as HTMLElement | null
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, 0)
  pendingTimers.push(t)
}

function scrollToTopSummary() {
  const t = window.setTimeout(() => {
    topSummaryEl.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, 0)
  pendingTimers.push(t)
}

async function focusRequestedAnalysisSection(ids: string[], token: number) {
  await nextTick()
  let attempt = 0

  const tryFocus = () => {
    const container = analysisScrollEl.value
    if (!container) return
    const target = ids
      .map((id) => container.querySelector<HTMLElement>(`#${id}`))
      .find((element) => element !== null)
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'start' })
      uiStore.clearAnalysisFocusRequest(token)
      return
    }
    if (attempt >= 3) {
      uiStore.clearAnalysisFocusRequest(token)
      return
    }
    attempt += 1
    const retryTimer = window.setTimeout(tryFocus, 90)
    pendingTimers.push(retryTimer)
  }

  tryFocus()
}

watch(
  () => displayLayer.value?.instanceId,
  (instanceId) => {
    scrollToTopSummary()
    if (!instanceId) return
    void scrollAnalysisIntoView(`#layer-${instanceId}`)
  },
  { immediate: true },
)

watch(
  () => props.selectedHotspot?.id,
  (hotspotId) => {
    scrollToTopSummary()
    if (hotspotId) {
      void scrollAnalysisIntoView(`#hotspot-${hotspotId}`)
      return
    }
    if (props.visibleHotspots.length > 0) {
      void scrollAnalysisIntoView('#hotspot-section')
    }
  },
)

watch(
  () => uiStore.analysisFocusRequest,
  (request) => {
    if (!request) return
    void focusRequestedAnalysisSection(request.ids, request.token)
  },
)

onBeforeUnmount(() => {
  pendingTimers.forEach((t) => window.clearTimeout(t))
  pendingTimers.length = 0
})
</script>

<template>
  <aside class="panel" ref="analysisScrollEl">
    <div class="panel-topline" ref="topSummaryEl">
      <div class="panel-header">
        <div>
          <h2>分析</h2>
          <p class="panel-subtitle">当前摘要</p>
        </div>
        <span class="readiness">{{ stageLabel }}</span>
      </div>

      <div v-if="workflowError" class="workflow-error">
        <span class="error-icon">⚠️</span>
        <span class="error-message">{{ workflowError }}</span>
      </div>

      <div class="action-row">
        <button
          v-if="canRunWorkflow"
          class="run-workflow-btn"
          :disabled="buttonDisabled"
          :title="runBlockedReason ?? ''"
          @click="handleRunWorkflow"
        >
          {{ buttonLabel }}
        </button>
        <span v-else class="run-workflow-hint">该图层仅用于边界展示，不支持任务运行</span>
      </div>
      <div v-if="runBlockedReason" class="run-block-hint">
        {{ runBlockedReason }}
      </div>

      <div class="workflow-stage-row">
        <span class="stage-pill" :class="workflowStage">{{ workflowStage }}</span>
        <span class="stage-copy">逐步进入可用状态</span>
      </div>

      <dl class="meta-list">
        <div>
          <dt>图层</dt>
          <dd>{{ displayLayer.name }}</dd>
        </div>
        <div>
          <dt>来源</dt>
          <dd>{{ displayLayer.sourceLabel }}</dd>
        </div>
      </dl>
    </div>

    <div class="analysis-stream">
      <section class="analysis-section analysis-section--overview" id="global-overview">
        <div class="section-kicker">总览</div>
        <h3>全图态势</h3>
        <p>{{ analysisSummary }}</p>
      </section>

      <section v-if="jobLayer" class="job-report-card job-report-card--summary" id="scheduler-status">
        <div class="job-report-header">
          <div>
            <div class="section-kicker">调度器</div>
            <span class="job-report-title">任务总览</span>
          </div>
          <span class="job-status-chip" :class="`job-${jobLayer.status}`">
            {{
              jobLayer.status === 'running'
                ? `运行中 ${jobLayer.progress}%`
                : jobLayer.status === 'succeeded'
                  ? '已完成'
                  : jobLayer.status === 'failed'
                    ? '失败'
                    : jobLayer.status
            }}
          </span>
        </div>

        <div class="job-progress-shell">
          <div v-if="jobLayer.status === 'running'" class="job-progress-row">
            <div class="job-progress-bar">
              <div class="job-progress-fill" :style="{ width: `${jobLayer.progress}%` }"></div>
            </div>
            <span class="job-progress-label">{{ jobLayer.progress }}%</span>
          </div>
          <p class="job-message">{{ jobLayer.message || '作业正在处理中...' }}</p>
          <ul v-if="jobEventNotes.length" class="job-diagnostic-list">
            <li v-for="note in jobEventNotes" :key="note" class="job-diagnostic-item">{{ note }}</li>
          </ul>
        </div>

        <div class="job-steps">
          <div class="job-step">1. 提交任务</div>
          <div class="job-step" :class="{ active: workflowStage === 'queued' || workflowStage === 'running' }">2. 等待运行结果</div>
          <div class="job-step" :class="{ active: !!resultModel }">3. 读取视图</div>
        </div>

        <div v-if="resultModel?.metricRows.length" class="job-metrics">
          <div v-for="m in resultModel.metricRows" :key="m.label" class="job-metric-item">
            <span class="jm-label">{{ m.label }}</span>
            <strong class="jm-value">{{ m.value }}</strong>
          </div>
        </div>
      </section>

      <section v-if="jobLayer && jobReportSummary" class="analysis-section analysis-section--report" id="report-section">
        <div class="section-kicker">报告</div>
        <div class="report-section-head">
          <div>
            <h3>工作流报告</h3>
            <p>这里展示该图层当前任务的摘要与结果说明。</p>
          </div>
          <a
            v-if="jobLayer.resultUrl"
            class="job-result-link"
            :href="jobLayer.resultUrl"
            target="_blank"
            rel="noreferrer"
          >
            打开结果
          </a>
        </div>
        <p class="job-report-copy">{{ jobReportSummary }}</p>
      </section>

      <section class="analysis-section analysis-section--layer" :id="`layer-${displayLayer.instanceId || 'default'}`">
        <div class="section-kicker">当前对象</div>
        <h3>选中图层</h3>
        <p>{{ displayLayer.name }} · {{ displayLayer.availabilityLabel }}</p>
      </section>

      <section v-if="hasPointWeatherSection" class="analysis-section analysis-section--weather" id="point-weather">
        <div class="section-kicker">点天气</div>
        <div class="weather-section-head">
          <div>
            <h3>地图点击查询</h3>
            <p>点击地图空白位置后，右侧展示该点位的实时天气与短时预报。</p>
          </div>
          <span class="analysis-chip" :class="{ muted: !pointWeather }">
            {{ pointWeather?.cache_status ?? '等待点击' }}
          </span>
        </div>

        <div v-if="pointWeatherLoading" class="weather-state weather-state-loading">
          正在获取点天气...
        </div>
        <div v-else-if="pointWeatherError" class="weather-state weather-state-error">
          {{ pointWeatherError }}
        </div>
        <template v-else-if="pointWeather">
          <div class="weather-primary-card">
            <span>{{ pointWeatherPrimaryLabel }}</span>
            <strong>{{ pointWeatherPrimaryValue }}</strong>
            <p>{{ pointWeather.summary }}</p>
          </div>

          <div class="weather-row-grid">
            <div v-for="row in pointWeatherRows" :key="row.label" class="weather-row-card">
              <span>{{ row.label }}</span>
              <strong>{{ row.value }}</strong>
            </div>
          </div>

          <div v-if="pointWeatherHourlyRows.length" class="weather-hourly-strip">
            <article v-for="row in pointWeatherHourlyRows" :key="row.time" class="weather-hourly-card">
              <span>{{ row.time }}</span>
              <strong>{{ row.metric }}</strong>
            </article>
          </div>
        </template>

        <div v-if="hasWeatherStyleSection" class="weather-style-panel">
          <div class="weather-style-head">
            <strong>图层样式</strong>
            <span class="analysis-chip">{{ weatherRenderHint?.paint_mode ?? (canToggleParticleFlow ? 'particle_flow' : '等待产物') }}</span>
          </div>

          <div v-if="displayLayer.instanceId" class="weather-layer-controls">
            <button class="weather-visibility-btn" @click="handleToggleLayerVisibility">
              {{ displayLayer.visible ? '隐藏天气图层' : '显示天气图层' }}
            </button>
            <div class="weather-opacity-row">
              <span>透明度</span>
              <input
                class="weather-opacity-slider"
                type="range"
                min="0"
                max="100"
                :value="Math.round(displayLayer.opacity * 100)"
                @input="handleLayerOpacityInput"
              />
              <strong>{{ Math.round(displayLayer.opacity * 100) }}%</strong>
            </div>
            <button
              v-if="canToggleParticleFlow"
              class="particle-flow-toggle-btn"
              :class="{ active: isParticleFlowEnabled }"
              :disabled="particleFlowButtonDisabled"
              :title="
                particleFlowButtonDisabled
                  ? '当前风场地图产物尚未就绪'
                  : isParticleFlowEnabled
                    ? '关闭粒子流动画，释放 Canvas 资源'
                    : '启用粒子流动画（独占式，同时只能一个图层启用）'
              "
              @click="handleToggleParticleFlow"
            >
              <span class="pf-icon" aria-hidden="true">≋</span>
              {{ isParticleFlowEnabled ? '关闭粒子流' : '启用粒子流' }}
            </button>
          </div>

          <div v-if="weatherRenderHint" class="weather-legend-row">
            <span class="weather-legend-label">图例</span>
            <span class="weather-legend-meta">
              {{ weatherRenderHint.primary_metric }} · {{ weatherRenderHint.unit_label }}
            </span>
          </div>
          <div v-if="weatherRenderHint" class="weather-legend-strip">
            <div
              v-for="stop in weatherLegendStops"
              :key="`${stop.value}`"
              class="weather-legend-stop"
            >
              <span class="weather-legend-swatch" :style="{ background: stop.color }"></span>
              <span>{{ stop.label }}</span>
            </div>
          </div>

          <div class="weather-style-meta">
            <span>{{ hasWeatherLayerAsset ? 'GeoJSON 已挂载' : '尚未生成地图产物' }}</span>
            <span>{{ weatherRenderHint ? `默认不透明度 ${Math.round(weatherRenderHint.opacity * 100)}%` : '等待运行结果' }}</span>
          </div>

          <ul v-if="weatherRenderHint?.notes.length" class="weather-note-list">
            <li v-for="note in weatherRenderHint.notes" :key="note">{{ note }}</li>
          </ul>
        </div>
      </section>

      <section v-if="visibleHotspots.length > 0" class="analysis-section analysis-section--hotspots" id="hotspot-section">
        <div class="section-kicker">热点</div>
        <h3>点位列表</h3>
        <ul class="hotspot-list">
          <li
            v-for="hotspot in visibleHotspots"
            :id="`hotspot-${hotspot.id}`"
            :key="hotspot.id"
            :class="{ selected: selectedHotspot?.id === hotspot.id }"
          >
            <span>{{ hotspot.name }}</span>
            <strong>{{ hotspot.value }}</strong>
          </li>
        </ul>
      </section>

      <section v-if="resultModel" class="analysis-section analysis-section--result" id="result-section">
        <div class="section-kicker">结果</div>
        <h3>结果视图</h3>
        <p>{{ resultModel.title }}</p>
      </section>
    </div>

    <section class="hero-metric" :style="{ '--accent-color': displayLayer.accentColor }">
      <span>{{ displayLayer.metricLabel }}</span>
      <strong>{{ displayLayer.metricValue }}</strong>
      <p>{{ displayLayer.trendLabel }}</p>
    </section>

    <div class="insight-grid">
      <article class="insight-card">
        <span>更新频率</span>
        <strong>{{ displayLayer.updateLabel }}</strong>
      </article>
      <article class="insight-card">
        <span>可用性</span>
        <strong>{{ displayLayer.availabilityLabel }}</strong>
      </article>
      <article class="insight-card">
        <span>可靠性</span>
        <strong>{{ displayLayer.confidenceLabel }}</strong>
      </article>
      <article class="insight-card">
        <span>观测时间</span>
        <strong>{{ displayLayer.observationTimeLabel }}</strong>
      </article>
    </div>

    <div class="learning-note">
      <h3>摘要</h3>
      <p>{{ displayLayer.summary }}</p>
    </div>

    <details class="protocol-details">
      <summary>接入状态</summary>
      <p>数据阶段：{{ displayLayer.dataState === 'real' ? '真实数据' : '目录态' }}</p>
      <p>状态标签：{{ displayLayer.statusLabel }}</p>
      <p>状态说明：{{ displayLayer.availabilityDescription }}</p>
      <p>缺失字段：{{ displayLayer.missingFieldsLabel }}</p>
    </details>

    <IntegrationStatusPanel />

    <!-- ── 元数据详情卡片 ─────────────────────────────────────────────────── -->
    <section v-if="layerMetadata.length" class="info-card meta-card">
      <div class="info-card-head">
        <span class="info-kicker">元数据</span>
        <span class="info-card-tag" :class="{ real: displayLayer.dataState === 'real' }">
          {{ displayLayer.dataState === 'real' ? '真实' : '目录' }}
        </span>
      </div>
      <dl class="meta-grid">
        <div v-for="row in layerMetadata" :key="row.label" class="meta-grid-row">
          <dt>{{ row.label }}</dt>
          <dd>{{ row.value }}</dd>
        </div>
      </dl>
    </section>

    <!-- ── 历史趋势对比 ───────────────────────────────────────────────────── -->
    <section v-if="displayLayer.trendLabel" class="info-card trend-card" :style="{ '--accent-color': displayLayer.accentColor }">
      <div class="info-card-head">
        <span class="info-kicker">历史对比</span>
        <span class="info-card-tag trend">{{ displayLayer.metricLabel }}</span>
      </div>
      <div class="trend-body">
        <div class="trend-current">
          <span class="trend-current-label">当前</span>
          <strong class="trend-current-value">{{ displayLayer.metricValue }}</strong>
        </div>
        <div class="trend-indicator">
          <span class="trend-arrow" :class="trendDirection">{{ trendArrowSymbol }}</span>
          <span class="trend-text">{{ displayLayer.trendLabel }}</span>
        </div>
      </div>
    </section>

    <!-- ── 叠加图层列表 ───────────────────────────────────────────────────── -->
    <section v-if="hasOverlayLayers" class="info-card overlay-card">
      <div class="info-card-head">
        <span class="info-kicker">叠加分析</span>
        <span class="info-card-tag">{{ overlayLayers.length }} 个共显</span>
      </div>
      <ul class="overlay-list">
        <li
          v-for="layer in overlayLayers"
          :key="layer.name"
          :style="{ '--layer-accent': layer.accentColor }"
        >
          <span class="overlay-dot" aria-hidden="true"></span>
          <div class="overlay-info">
            <strong class="overlay-name">{{ layer.name }}</strong>
            <span class="overlay-category">{{ layer.category }}</span>
          </div>
          <span class="overlay-state" :class="`state-${layer.availabilityState}`">{{ layer.availabilityState }}</span>
        </li>
      </ul>
    </section>
  </aside>
</template>

<style scoped>
.panel { --info-card-radius: 0.82rem; --info-card-padding-y: 0.46rem; --info-card-padding-x: 0.5rem; --info-soft-gap: 0.34rem; display: grid; gap: 0.52rem; width: 100%; max-width: 100%; padding: 0.56rem 0.48rem 0.5rem; border-radius: 0.88rem; border: 1px solid rgba(148, 163, 184, 0.15); background: linear-gradient(180deg, rgba(13, 21, 36, 0.72), rgba(8, 15, 28, 0.6)); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03), 0 12px 26px rgba(1, 8, 16, 0.14); min-height: 100%; overflow: hidden; contain: layout style; }
.panel,
.panel * { box-sizing: border-box; }
.panel > *,
.panel :is(.panel-topline,.panel-header,.workflow-error,.workflow-stage-row,.meta-list,.meta-list > div,.analysis-stream,.analysis-section,.job-report-card,.job-report-header,.job-progress-shell,.job-progress-row,.job-steps,.job-metrics,.job-metric-item,.weather-section-head,.weather-primary-card,.weather-row-grid,.weather-row-card,.weather-hourly-strip,.weather-hourly-card,.weather-style-panel,.weather-style-head,.weather-layer-controls,.weather-legend-row,.weather-legend-strip,.weather-style-meta,.hero-metric,.insight-grid,.insight-card,.learning-note,.protocol-details,.info-card,.info-card-head,.meta-grid,.meta-grid-row,.trend-body,.trend-current,.trend-indicator,.overlay-list li,.overlay-info,.hotspot-list li,.report-section-head) { min-width: 0; }
.panel :is(p,span,strong,dd,dt,a,button,.job-message,.job-diagnostic-item,.trend-text,.overlay-name,.run-block-hint,.error-message,.job-report-copy,.weather-legend-stop,.weather-style-meta span) { overflow-wrap: anywhere; }
.panel-topline { display: grid; gap: 0.38rem; padding: 0.12rem 0.06rem 0.02rem; min-width: 0; }
.panel-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.44rem; flex-wrap: wrap; min-width: 0; }
.panel-header > div:first-child { flex: 1 1 8rem; min-width: 0; }
.readiness { padding: 0.16rem 0.36rem; border-radius: 999px; background: rgba(90, 162, 255, 0.16); color: #cfeaff; font-size: 0.58rem; flex: 0 1 auto; min-width: 0; max-width: 100%; align-self: flex-start; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.action-row { display: flex; justify-content: flex-start; }
.workflow-error { display: flex; align-items: center; gap: 0.4rem; padding: 0.34rem 0.48rem; border-radius: 0.62rem; background: rgba(255, 80, 80, 0.12); border: 1px solid rgba(255, 80, 80, 0.22); color: #ff9999; font-size: 0.58rem; }
.error-icon { font-size: 0.72rem; }
.run-workflow-btn { border: 1px solid rgba(103, 212, 255, 0.24); border-radius: 999px; background: rgba(29, 78, 216, 0.18); color: #d8f3ff; font-size: 0.62rem; padding: 0.34rem 0.7rem; cursor: pointer; }
.run-workflow-btn:disabled { opacity: 0.58; cursor: not-allowed; }
.run-block-hint { color: #ffd38a; font-size: 0.56rem; line-height: 1.4; }
.workflow-stage-row { display: flex; align-items: center; gap: 0.4rem; }
.stage-pill { padding: 0.18rem 0.44rem; border-radius: 999px; font-size: 0.56rem; background: rgba(148, 163, 184, 0.12); color: #bfd3e6; }
.stage-pill.running, .stage-pill.queued { background: rgba(90, 213, 255, 0.14); color: #bcefff; }
.stage-pill.succeeded { background: rgba(114, 255, 207, 0.12); color: #9ff8cf; }
.stage-pill.failed { background: rgba(255, 80, 80, 0.12); color: #ff9999; }
.stage-pill.submitting { background: rgba(255, 196, 120, 0.12); color: #ffd38a; }
.stage-copy { color: #7f93a9; font-size: 0.58rem; }
.meta-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.28rem 0.56rem; }
.meta-list dt { color: #7f93a9; font-size: 0.56rem; }
.meta-list dd { margin: 0.06rem 0 0; color: #eaf3fb; font-size: 0.66rem; }
.analysis-stream { display: grid; gap: var(--info-soft-gap); overflow-x: hidden; overflow-y: visible; scrollbar-width: thin; scrollbar-color: rgba(136,192,255,.22) rgba(255,255,255,.05); }
.analysis-stream::-webkit-scrollbar { width: 4px; }
.analysis-stream::-webkit-scrollbar-thumb { background: rgba(136,192,255,.22); border-radius: 999px; }
.analysis-stream::-webkit-scrollbar-track { background: rgba(255,255,255,.05); }
.analysis-section, .job-report-card { background: rgba(8, 18, 33, 0.56); border: 1px solid rgba(136, 192, 255, 0.1); border-radius: var(--info-card-radius); padding: var(--info-card-padding-y) var(--info-card-padding-x); }
.analysis-section--overview { background: linear-gradient(180deg, rgba(12, 25, 43, 0.82), rgba(8, 18, 33, 0.62)); border-color: rgba(103, 212, 255, 0.16); }
.analysis-section--layer { border-color: rgba(136, 192, 255, 0.14); }
.analysis-section--weather { border-color: rgba(103, 212, 255, 0.18); background: linear-gradient(180deg, rgba(8, 23, 42, 0.78), rgba(8, 18, 33, 0.62)); }
.analysis-section--hotspots { border-color: rgba(114, 255, 207, 0.14); }
.analysis-section--report { border-color: rgba(126, 168, 255, 0.18); background: linear-gradient(180deg, rgba(10, 22, 39, 0.72), rgba(8, 18, 33, 0.56)); }
.analysis-section--result { border-color: rgba(126, 168, 255, 0.16); }
.report-section-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.5rem; }
.job-report-copy { margin-top: 0.32rem !important; color: #d7e6f5 !important; }
.analysis-section h3 { margin: 0.1rem 0 0.18rem; font-size: 0.68rem; color: #f0f7ff; }
.analysis-section p { margin: 0; color: #9eb3c8; font-size: 0.58rem; line-height: 1.45; }
.section-kicker { color: #7f93a9; font-size: 0.52rem; letter-spacing: 0.08em; text-transform: uppercase; }
.analysis-chip-row { display: flex; gap: 0.28rem; flex-wrap: wrap; margin-bottom: 0.2rem; }
.analysis-chip { padding: 0.14rem 0.36rem; border-radius: 999px; background: rgba(90, 162, 255, 0.14); color: #dff1ff; font-size: 0.55rem; }
.analysis-chip.muted { background: rgba(148, 163, 184, 0.12); color: #b6c9da; }
.weather-section-head { display: flex; justify-content: space-between; gap: 0.5rem; align-items: flex-start; }
.weather-primary-card { display: grid; gap: 0.14rem; margin-top: 0.34rem; padding: 0.4rem 0.44rem; border-radius: 0.7rem; background: rgba(90, 162, 255, 0.1); border: 1px solid rgba(90, 162, 255, 0.16); }
.weather-primary-card span { color: #9bc8e9; font-size: 0.54rem; }
.weather-primary-card strong { color: #f4fbff; font-size: 0.86rem; }
.weather-primary-card p { color: #c8dff0; }
.weather-row-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.26rem; margin-top: 0.34rem; }
.weather-row-card { display: grid; gap: 0.08rem; padding: 0.3rem 0.34rem; border-radius: 0.56rem; background: rgba(148, 163, 184, 0.08); border: 1px solid rgba(148, 163, 184, 0.08); }
.weather-row-card span { color: #7f93a9; font-size: 0.54rem; }
.weather-row-card strong { color: #edf6ff; font-size: 0.6rem; }
.weather-hourly-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.24rem; margin-top: 0.34rem; }
.weather-hourly-card { display: grid; gap: 0.08rem; padding: 0.28rem 0.24rem; border-radius: 0.56rem; background: rgba(8, 18, 33, 0.56); border: 1px solid rgba(136, 192, 255, 0.1); text-align: center; }
.weather-hourly-card span { color: #7f93a9; font-size: 0.52rem; }
.weather-hourly-card strong { color: #eaf3fb; font-size: 0.58rem; }
.weather-state { margin-top: 0.34rem; padding: 0.34rem 0.42rem; border-radius: 0.62rem; font-size: 0.58rem; }
.weather-state-loading { background: rgba(90, 162, 255, 0.1); color: #cfeaff; border: 1px solid rgba(90, 162, 255, 0.14); }
.weather-state-error { background: rgba(255, 80, 80, 0.1); color: #ffb3b3; border: 1px solid rgba(255, 80, 80, 0.16); }
.weather-style-panel { display: grid; gap: 0.28rem; margin-top: 0.36rem; padding-top: 0.34rem; border-top: 1px solid rgba(136, 192, 255, 0.08); }
.weather-style-head { display: flex; justify-content: space-between; gap: 0.4rem; align-items: center; color: #eaf3fb; font-size: 0.58rem; }
.weather-layer-controls { display: grid; gap: 0.24rem; }
.weather-visibility-btn { border: 1px solid rgba(103, 212, 255, 0.2); border-radius: 999px; background: rgba(29, 78, 216, 0.14); color: #d8f3ff; font-size: 0.58rem; padding: 0.28rem 0.62rem; cursor: pointer; justify-self: start; }
.particle-flow-toggle-btn {
  border: 1px solid rgba(103, 212, 255, 0.28);
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.5);
  color: #b8d4ff;
  font-size: 0.58rem;
  padding: 0.3rem 0.72rem;
  cursor: pointer;
  justify-self: start;
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  transition: all 0.18s ease;
}
.particle-flow-toggle-btn .pf-icon { font-size: 0.72rem; line-height: 1; }
.particle-flow-toggle-btn:hover {
  border-color: rgba(103, 212, 255, 0.5);
  background: rgba(29, 78, 216, 0.22);
  color: #e8f3ff;
}
.particle-flow-toggle-btn:disabled {
  opacity: 0.52;
  cursor: not-allowed;
  border-color: rgba(148, 163, 184, 0.18);
  background: rgba(15, 23, 42, 0.3);
  color: #8da1b7;
}
.particle-flow-toggle-btn.active {
  border-color: rgba(110, 200, 255, 0.7);
  background: linear-gradient(135deg, rgba(56, 189, 248, 0.32), rgba(99, 102, 241, 0.28));
  color: #f0f9ff;
  box-shadow: 0 0 12px rgba(110, 200, 255, 0.36), inset 0 0 8px rgba(110, 200, 255, 0.18);
}
.particle-flow-toggle-btn.active .pf-icon {
  animation: pf-pulse 1.4s ease-in-out infinite;
}
@keyframes pf-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.6; transform: scale(1.12); }
}
.weather-opacity-row { display: grid; grid-template-columns: auto 1fr auto; gap: 0.3rem; align-items: center; color: #9eb3c8; font-size: 0.56rem; }
.weather-opacity-slider { width: 100%; }
.weather-legend-row { display: flex; justify-content: space-between; gap: 0.4rem; color: #9eb3c8; font-size: 0.54rem; }
.weather-legend-label { color: #dbeeff; }
.weather-legend-meta { color: #7f93a9; }
.weather-legend-strip { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.18rem 0.3rem; }
.weather-legend-stop { display: flex; align-items: center; gap: 0.24rem; color: #c8dff0; font-size: 0.54rem; }
.weather-legend-swatch { width: 0.72rem; height: 0.72rem; border-radius: 0.22rem; border: 1px solid rgba(255, 255, 255, 0.08); flex-shrink: 0; }
.weather-style-meta { display: flex; justify-content: space-between; gap: 0.4rem; color: #7f93a9; font-size: 0.52rem; flex-wrap: wrap; }
.weather-note-list { display: grid; gap: 0.16rem; margin: 0; padding-left: 1rem; color: #9eb3c8; font-size: 0.54rem; }
.job-report-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.4rem; }
.job-report-title { color: #eaf3fb; font-size: 0.66rem; font-weight: 700; }
.job-status-chip { padding: 0.12rem 0.34rem; border-radius: 999px; font-size: 0.54rem; background: rgba(148, 163, 184, 0.12); color: #bfd3e6; }
.job-report-card--summary { background: linear-gradient(180deg, rgba(10, 22, 39, 0.72), rgba(8, 18, 33, 0.56)); }
.job-progress-shell { display: grid; gap: 0.24rem; }
.job-progress-row { display: flex; align-items: center; gap: 0.4rem; }
.job-progress-bar { flex: 1; height: 0.26rem; border-radius: 999px; background: rgba(148, 163, 184, 0.14); overflow: hidden; }
.job-progress-fill { height: 100%; background: linear-gradient(90deg, #5ad5ff, #7ea8ff); }
.job-progress-label { width: 2rem; text-align: right; color: #8ea3b8; font-size: 0.54rem; }
.job-message { margin: 0; color: #c8dff0; font-size: 0.58rem; line-height: 1.4; }
.job-diagnostic-list { display: grid; gap: 0.12rem; margin: 0; padding-left: 1rem; color: #ffcf99; font-size: 0.54rem; }
.job-diagnostic-item { line-height: 1.35; }
.job-steps { display: flex; flex-direction: column; gap: 0.18rem; }
.job-step { padding: 0.18rem 0.34rem; border-radius: 0.52rem; background: rgba(148, 163, 184, 0.08); color: #7f93a9; font-size: 0.56rem; }
.job-step.active { background: rgba(90, 213, 255, 0.12); color: #bcefff; }
.job-metrics { display: grid; gap: 0.28rem; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.job-metric-item { display: grid; gap: 0.06rem; padding: 0.28rem 0.34rem; border-radius: 0.56rem; background: rgba(148, 163, 184, 0.08); }
.jm-label { color: #7f93a9; font-size: 0.54rem; }
.jm-value { color: #edf6ff; font-size: 0.62rem; margin: 0; }
.hero-metric, .insight-card, .learning-note, .protocol-details { border-radius: var(--info-card-radius); background: rgba(8, 18, 33, 0.56); border: 1px solid rgba(136, 192, 255, 0.1); padding: 0.5rem 0.56rem; }
.hero-metric span, .insight-card span { color: #7f93a9; font-size: 0.56rem; }
.hero-metric strong { display: block; font-size: 0.96rem; color: #f4fbff; }
.hero-metric p { margin: 0.16rem 0 0; color: #8ea3b8; font-size: 0.56rem; }
.insight-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.34rem; }
.insight-card strong { display: block; color: #edf6ff; font-size: 0.64rem; margin-top: 0.12rem; }
.protocol-details summary { cursor: pointer; color: #cfeaff; font-size: 0.58rem; }
.protocol-details p { margin: 0.18rem 0 0; color: #9eb3c8; font-size: 0.56rem; }
.hotspot-list { display: grid; gap: 0.18rem; padding: 0; margin: 0; list-style: none; }
.hotspot-list li { display: flex; justify-content: space-between; gap: 0.4rem; color: #eaf3fb; font-size: 0.58rem; padding: 0.22rem 0.32rem; border-radius: 0.52rem; background: rgba(148, 163, 184, 0.05); border: 1px solid rgba(148, 163, 184, 0.08); }
.hotspot-list li.selected { background: rgba(90, 213, 255, 0.16); border-color: rgba(90, 213, 255, 0.28); box-shadow: 0 0 0 1px rgba(90, 213, 255, 0.08) inset; transform: translateX(2px); }
.hotspot-list li.selected span, .hotspot-list li.selected strong { color: #f4fbff; }
.job-result-link { color: #5ad5ff; font-size: 0.58rem; text-decoration: none; }

/* ── 增强信息展示：元数据 / 历史对比 / 叠加分析 ─────────────────────────── */
.info-card { display: grid; gap: 0.32rem; padding: var(--info-card-padding-y) var(--info-card-padding-x); border-radius: var(--info-card-radius); background: rgba(8, 18, 33, 0.56); border: 1px solid rgba(136, 192, 255, 0.1); }
.info-card-head { display: flex; justify-content: space-between; align-items: center; gap: 0.4rem; }
.info-kicker { color: #7f93a9; font-size: 0.52rem; letter-spacing: 0.08em; text-transform: uppercase; }
.info-card-tag { padding: 0.12rem 0.34rem; border-radius: 999px; background: rgba(148, 163, 184, 0.12); color: #bfd3e6; font-size: 0.52rem; }
.info-card-tag.real { background: rgba(114, 255, 207, 0.12); color: #9ff8cf; }
.info-card-tag.trend { background: rgba(126, 168, 255, 0.14); color: #c8d8ff; }

/* 元数据网格 */
.meta-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.22rem 0.5rem; margin: 0; }
.meta-grid-row { display: grid; gap: 0.04rem; }
.meta-grid dt { color: #7f93a9; font-size: 0.52rem; }
.meta-grid dd { margin: 0; color: #eaf3fb; font-size: 0.6rem; word-break: break-word; }

/* 历史趋势卡片 */
.trend-card { border-color: rgba(126, 168, 255, 0.18); background: linear-gradient(180deg, rgba(10, 20, 38, 0.72), rgba(8, 18, 33, 0.56)); }
.trend-body { display: flex; align-items: center; gap: 0.56rem; }
.trend-current { display: grid; gap: 0.04rem; min-width: 4.4rem; }
.trend-current-label { color: #7f93a9; font-size: 0.52rem; }
.trend-current-value { color: var(--accent-color, #f4fbff); font-size: 0.86rem; }
.trend-indicator { display: flex; align-items: center; gap: 0.3rem; flex: 1; padding: 0.2rem 0.34rem; border-radius: 0.56rem; background: rgba(148, 163, 184, 0.06); }
.trend-arrow { font-size: 0.78rem; line-height: 1; }
.trend-arrow.up { color: #ff8aa7; }
.trend-arrow.down { color: #5ad5ff; }
.trend-arrow.flat { color: #9eb3c8; }
.trend-text { color: #c8dff0; font-size: 0.56rem; line-height: 1.35; }

/* 叠加图层列表 */
.overlay-list { display: grid; gap: 0.18rem; padding: 0; margin: 0; list-style: none; }
.overlay-list li { display: flex; align-items: center; gap: 0.34rem; padding: 0.24rem 0.3rem; border-radius: 0.56rem; background: rgba(148, 163, 184, 0.05); border: 1px solid rgba(148, 163, 184, 0.08); }
.overlay-dot { width: 0.5rem; height: 0.5rem; border-radius: 999px; background: var(--layer-accent, #88d8ff); box-shadow: 0 0 6px var(--layer-accent, rgba(136, 216, 255, 0.6)); flex-shrink: 0; }
.overlay-info { display: grid; gap: 0.04rem; flex: 1; min-width: 0; }
.overlay-name { color: #eaf3fb; font-size: 0.6rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.overlay-category { color: #7f93a9; font-size: 0.52rem; }
.overlay-state { padding: 0.1rem 0.3rem; border-radius: 999px; font-size: 0.5rem; text-transform: uppercase; letter-spacing: 0.04em; }
.overlay-state.state-ready { background: rgba(114, 255, 207, 0.12); color: #9ff8cf; }
.overlay-state.state-partial { background: rgba(255, 196, 120, 0.12); color: #ffd38a; }
.overlay-state.state-empty { background: rgba(148, 163, 184, 0.12); color: #b6c9da; }
@media (max-width: 560px) {
  .meta-list,
  .weather-row-grid,
  .job-metrics,
  .meta-grid,
  .insight-grid,
  .weather-hourly-strip {
    grid-template-columns: minmax(0, 1fr);
  }

  .weather-section-head,
  .job-report-header,
  .report-section-head,
  .info-card-head,
  .trend-body {
    grid-template-columns: minmax(0, 1fr);
    display: grid;
  }
}
</style>
