<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { ActiveLayerDisplay } from '../stores/layers/types'
import type { DemoHotspot } from '../app/demo-data'
import type { WeatherPointResponse } from '../services/runtime-api'
import { buildWeatherLegendStops, isRealtimeWeatherLayerId } from './map/weather-render'
import { buildResultDisplayModel } from './info-panel/result-adapter'

const props = defineProps<{
  viewLabel: string
  activeLayer: ActiveLayerDisplay
  hourLabel: string
  stageLabel: string
  visibleHotspots: DemoHotspot[]
  selectedLayer?: ActiveLayerDisplay | null
  selectedHotspot?: DemoHotspot | null
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
const isRealtimeWeatherLayer = computed(() => isRealtimeWeatherLayerId(displayLayer.value.catalogId))
const weatherRenderHint = computed(
  () => jobLayer.value?.mapLayerPayload?.renderHint ?? props.pointWeather?.render_hint ?? null,
)
const weatherLegendStops = computed(() => (weatherRenderHint.value ? buildWeatherLegendStops(weatherRenderHint.value) : []))
const hasWeatherLayerAsset = computed(() => !!jobLayer.value?.mapLayerPayload?.layerAssets?.geojsonUrl)
const hasPointWeatherSection = computed(
  () =>
    props.pointWeatherLoading ||
    !!props.pointWeatherError ||
    !!props.pointWeather ||
    isRealtimeWeatherLayer.value,
)
const pointWeatherPrimaryLabel = computed(() => {
  if (displayLayer.value.catalogId === 'wind-field') return '实时风速'
  if (displayLayer.value.catalogId === 'precipitation') return '实时降水'
  return '实时气温'
})
const pointWeatherPrimaryValue = computed(() => {
  const weather = props.pointWeather
  if (!weather) return '--'
  if (displayLayer.value.catalogId === 'wind-field') {
    return formatMetric(weather.current.wind_speed_10m, 'm/s')
  }
  if (displayLayer.value.catalogId === 'precipitation') {
    return formatMetric(weather.current.precipitation, 'mm')
  }
  return formatMetric(weather.current.temperature_2m, 'C')
})
const pointWeatherRows = computed(() => {
  const weather = props.pointWeather
  if (!weather) return []
  return [
    { label: 'Point', value: weather.place_name ?? `${weather.latitude.toFixed(3)}, ${weather.longitude.toFixed(3)}` },
    { label: 'Model', value: weather.model },
    {
      label: displayLayer.value.catalogId === 'wind-field' ? 'Wind' : displayLayer.value.catalogId === 'precipitation' ? 'Precipitation' : 'Temperature',
      value:
        displayLayer.value.catalogId === 'wind-field'
          ? formatMetric(weather.current.wind_speed_10m, 'm/s')
          : displayLayer.value.catalogId === 'precipitation'
            ? formatMetric(weather.current.precipitation, 'mm')
            : formatMetric(weather.current.temperature_2m, 'C'),
    },
    { label: 'Observed', value: weather.observation_time ? formatTime(weather.observation_time) : '--' },
  ]
})
const pointWeatherHourlyRows = computed(() => {
  const weather = props.pointWeather
  if (!weather) return []
  return weather.hourly.slice(0, 4).map((entry) => {
    let metric = '--'
    if (displayLayer.value.catalogId === 'wind-field') {
      metric = formatMetric(entry.wind_speed_10m, 'm/s')
    } else if (displayLayer.value.catalogId === 'precipitation') {
      metric = formatMetric(entry.precipitation, 'mm')
    } else {
      metric = formatMetric(entry.temperature_2m, 'C')
    }
    return {
      time: formatHour(entry.time),
      metric,
    }
  })
})
const canRunWorkflow = computed(() => !displayLayer.value?.isAdminBoundary)
const isWorkflowRunning = computed(() => jobLayer.value?.status === 'running' || jobLayer.value?.status === 'queued')
const workflowStage = computed(() => {
  if (props.isSubmitting) return 'submitting'
  if (jobLayer.value?.status === 'queued') return 'queued'
  if (jobLayer.value?.status === 'running') return 'running'
  if (jobLayer.value?.status === 'succeeded') return 'succeeded'
  if (jobLayer.value?.status === 'failed') return 'failed'
  return 'idle'
})
const buttonDisabled = computed(() => isWorkflowRunning.value || props.isSubmitting)
const buttonLabel = computed(() => {
  if (props.isSubmitting) return '提交中...'
  if (isWorkflowRunning.value) return '任务进行中'
  return '运行工作流'
})

const analysisScrollEl = ref<HTMLElement | null>(null)
const topSummaryEl = ref<HTMLElement | null>(null)

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
  window.setTimeout(() => {
    const el = analysisScrollEl.value?.querySelector(selector) as HTMLElement | null
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, 0)
}

function scrollToTopSummary() {
  window.setTimeout(() => {
    topSummaryEl.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, 0)
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
          @click="handleRunWorkflow"
        >
          {{ buttonLabel }}
        </button>
        <span v-else class="run-workflow-hint">该图层仅用于边界展示，不支持任务运行</span>
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

        <div v-if="weatherRenderHint" class="weather-style-panel">
          <div class="weather-style-head">
            <strong>图层样式</strong>
            <span class="analysis-chip">{{ weatherRenderHint.paint_mode }}</span>
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
          </div>

          <div class="weather-legend-row">
            <span class="weather-legend-label">图例</span>
            <span class="weather-legend-meta">
              {{ weatherRenderHint.primary_metric }} · {{ weatherRenderHint.unit_label }}
            </span>
          </div>
          <div class="weather-legend-strip">
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
            <span>默认不透明度 {{ Math.round(weatherRenderHint.opacity * 100) }}%</span>
          </div>

          <ul v-if="weatherRenderHint.notes.length" class="weather-note-list">
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
      <summary>接入占位</summary>
      <p>协议模式：{{ displayLayer.dataState === 'real' ? '真实数据' : '演示数据' }}</p>
      <p>状态说明：{{ displayLayer.availabilityDescription }}</p>
      <p>缺失字段：{{ displayLayer.missingFieldsLabel }}</p>
    </details>
  </aside>
</template>

<style scoped>
.panel { display: grid; gap: 0.52rem; padding: 0.56rem 0.48rem 0.5rem; border-radius: 0.88rem; border: 1px solid rgba(148, 163, 184, 0.15); background: linear-gradient(180deg, rgba(13, 21, 36, 0.72), rgba(8, 15, 28, 0.6)); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03), 0 12px 26px rgba(1, 8, 16, 0.14); min-height: 100%; overflow: visible; contain: layout style; }
.panel-topline { display: grid; gap: 0.38rem; padding: 0.12rem 0.06rem 0.02rem; }
.panel-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.44rem; }
.readiness { padding: 0.16rem 0.36rem; border-radius: 999px; background: rgba(90, 162, 255, 0.16); color: #cfeaff; font-size: 0.58rem; }
.action-row { display: flex; justify-content: flex-start; }
.workflow-error { display: flex; align-items: center; gap: 0.4rem; padding: 0.34rem 0.48rem; border-radius: 0.62rem; background: rgba(255, 80, 80, 0.12); border: 1px solid rgba(255, 80, 80, 0.22); color: #ff9999; font-size: 0.58rem; }
.error-icon { font-size: 0.72rem; }
.run-workflow-btn { border: 1px solid rgba(103, 212, 255, 0.24); border-radius: 999px; background: rgba(29, 78, 216, 0.18); color: #d8f3ff; font-size: 0.62rem; padding: 0.34rem 0.7rem; cursor: pointer; }
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
.analysis-stream { display: grid; gap: 0.34rem; overflow: visible; scrollbar-width: thin; scrollbar-color: rgba(136,192,255,.22) rgba(255,255,255,.05); }
.analysis-stream::-webkit-scrollbar { width: 4px; }
.analysis-stream::-webkit-scrollbar-thumb { background: rgba(136,192,255,.22); border-radius: 999px; }
.analysis-stream::-webkit-scrollbar-track { background: rgba(255,255,255,.05); }
.analysis-section, .job-report-card { background: rgba(8, 18, 33, 0.56); border: 1px solid rgba(136, 192, 255, 0.1); border-radius: 0.82rem; padding: 0.46rem 0.5rem; }
.analysis-section--overview { background: linear-gradient(180deg, rgba(12, 25, 43, 0.82), rgba(8, 18, 33, 0.62)); border-color: rgba(103, 212, 255, 0.16); }
.analysis-section--layer { border-color: rgba(136, 192, 255, 0.14); }
.analysis-section--weather { border-color: rgba(103, 212, 255, 0.18); background: linear-gradient(180deg, rgba(8, 23, 42, 0.78), rgba(8, 18, 33, 0.62)); }
.analysis-section--hotspots { border-color: rgba(114, 255, 207, 0.14); }
.analysis-section--result { border-color: rgba(126, 168, 255, 0.16); }
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
.weather-opacity-row { display: grid; grid-template-columns: auto 1fr auto; gap: 0.3rem; align-items: center; color: #9eb3c8; font-size: 0.56rem; }
.weather-opacity-slider { width: 100%; }
.weather-legend-row { display: flex; justify-content: space-between; gap: 0.4rem; color: #9eb3c8; font-size: 0.54rem; }
.weather-legend-label { color: #dbeeff; }
.weather-legend-meta { color: #7f93a9; }
.weather-legend-strip { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.18rem 0.3rem; }
.weather-legend-stop { display: flex; align-items: center; gap: 0.24rem; color: #c8dff0; font-size: 0.54rem; }
.weather-legend-swatch { width: 0.72rem; height: 0.72rem; border-radius: 0.22rem; border: 1px solid rgba(255, 255, 255, 0.08); flex-shrink: 0; }
.weather-style-meta { display: flex; justify-content: space-between; gap: 0.4rem; color: #7f93a9; font-size: 0.52rem; }
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
.job-steps { display: flex; flex-direction: column; gap: 0.18rem; }
.job-step { padding: 0.18rem 0.34rem; border-radius: 0.52rem; background: rgba(148, 163, 184, 0.08); color: #7f93a9; font-size: 0.56rem; }
.job-step.active { background: rgba(90, 213, 255, 0.12); color: #bcefff; }
.job-metrics { display: grid; gap: 0.28rem; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.job-metric-item { display: grid; gap: 0.06rem; padding: 0.28rem 0.34rem; border-radius: 0.56rem; background: rgba(148, 163, 184, 0.08); }
.jm-label { color: #7f93a9; font-size: 0.54rem; }
.jm-value { color: #edf6ff; font-size: 0.62rem; margin: 0; }
.hero-metric, .insight-card, .learning-note, .protocol-details { border-radius: 0.82rem; background: rgba(8, 18, 33, 0.56); border: 1px solid rgba(136, 192, 255, 0.1); padding: 0.5rem 0.56rem; }
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
</style>
