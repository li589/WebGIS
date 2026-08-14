/** * InfoPanel Visual Tab：图表 / 点查 / 叠加时序 / 热点 / 结果 / 空态。 * * 从 InfoPanel.vue
模板抽取（原 1708-1834、2247-2336 行）。纯展示组件， * 全部状态经 props 传入，交互经 emit
上抛父组件。 */
<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ActiveLayerDisplay, LayerHotspot } from '../../stores/layers/types'
import type { WeatherPointResponse } from '../../services/runtime-api'
import type { OverlaySymbologyMeta } from '../../types/overlay-symbology'
import type { AnalysisChartModel, AnalysisTableModel } from './AnalysisResultCharts.vue'
import type { OverlayBarItem } from './MultiOverlayBarChart.vue'
import type { MultiLayerSeries } from './MultiLayerTimeSeriesChart.vue'
import type { UnifiedPointValue, LayerDataCategory } from './useUnifiedChartData'
import { normalizeUnitKey, detectTimeAxisType, type TimeAxisType } from './useUnifiedChartData'
import type { ResultDisplayModel } from './result-adapter'
import { ANALYSIS_COPY, INSPECT_COPY } from '../../ui-copy'
import AppButton from '../ui/AppButton.vue'
import MultiOverlayBarChart from './MultiOverlayBarChart.vue'
import MultiLayerTimeSeriesChart from './MultiLayerTimeSeriesChart.vue'
import AnalysisResultCharts from './AnalysisResultCharts.vue'

const props = defineProps<{
  displayLayer: ActiveLayerDisplay
  isRealtimeWeatherLayer: boolean
  hasAnalysisCharts: boolean
  analysisCharts: AnalysisChartModel[]
  analysisTables: AnalysisTableModel[]
  hasPointWeatherSection: boolean
  pointWeather: WeatherPointResponse | null
  pointWeatherLoading: boolean
  pointWeatherError: string | null
  selectedMapPoint: { lng: number; lat: number } | null
  pointInspectStatusLabel: string
  pointWeatherPrimaryLabel: string
  pointWeatherPrimaryValue: string
  pointWeatherRows: { label: string; value: string }[]
  pointWeatherHourlyRows: { time: string; metric: string; active: boolean }[]
  pointWeatherHourlyChartRows: {
    time: string
    metric: string
    numericValue: number | null
    active: boolean
  }[]
  pointWeatherMetricLabel: string
  showMultiOverlayBar: boolean
  multiOverlayBarItems: OverlayBarItem[]
  showSelectedOverlayTimeSeries: boolean
  showDemoOverlayTimeSeries: boolean
  selectedOverlayTimeSeriesRows: {
    time: string
    metric: string
    numericValue?: number
    active: boolean
  }[]
  overlayStyleMeta: OverlaySymbologyMeta | null
  visibleHotspots: LayerHotspot[]
  selectedHotspot: LayerHotspot | null
  resultModel: ResultDisplayModel | null
  hasVisualTabContent: boolean
  sparseVisualHint: string
  canRunWorkflow: boolean
  interactionMode: string
  // ── 统一多图层分析数据 ──
  hasUnifiedData: boolean
  hasPointComparison: boolean
  hasMultiLayerTimeSeries: boolean
  unifiedBarItems: OverlayBarItem[]
  unifiedPointValues: UnifiedPointValue[]
  allTimeSeries: MultiLayerSeries[]
  timeSeriesByCategory: Record<LayerDataCategory, MultiLayerSeries[]>
  pointValuesByCategory: Record<LayerDataCategory, UnifiedPointValue[]>
}>()

const emit = defineEmits<{
  selectHotspot: [hotspotId: string]
  setActiveTab: [tab: string]
  enterSelectMode: []
  queryOverlaySeries: [payload: { lng: number; lat: number }]
}>()

/** 显示模式：combined（组合显示）| categorized（分类显示） */
const displayMode = ref<'combined' | 'categorized'>('combined')

/** 天气点查时序转换为 MultiLayerSeries 格式 */
const weatherChartSeries = computed<MultiLayerSeries[]>(() => {
  const rows = props.pointWeatherHourlyChartRows
  if (!rows.length) return []
  return [
    {
      id: 'weather-hourly',
      name: props.pointWeatherMetricLabel,
      data: rows.map((r) => ({ time: r.time, value: r.numericValue ?? null })),
    },
  ]
})

/** 天气时序图是否有数据 */
const hasWeatherChart = computed(() => weatherChartSeries.value.length > 0)

// ── D1: 量纲感知分组（本地计算，从 props 派生） ─────────────────────────────

/** 按量纲分组的时间序列 */
const localTimeSeriesByUnit = computed<Record<string, MultiLayerSeries[]>>(() => {
  const groups: Record<string, MultiLayerSeries[]> = {}
  for (const s of props.allTimeSeries) {
    const key = normalizeUnitKey(s.unit ?? '')
    if (!groups[key]) groups[key] = []
    groups[key].push(s)
  }
  return groups
})

/** 按量纲分组的点值（仅含有数值的条目） */
const localPointValuesByUnit = computed<Record<string, UnifiedPointValue[]>>(() => {
  const groups: Record<string, UnifiedPointValue[]> = {}
  for (const v of props.unifiedPointValues) {
    if (v.value === null) continue
    const key = normalizeUnitKey(v.unit)
    if (!groups[key]) groups[key] = []
    groups[key].push(v)
  }
  return groups
})

/** 量纲分组 key 列表 */
const localUnitGroupKeys = computed<string[]>(() => Object.keys(localPointValuesByUnit.value))

/** 是否存在多种量纲 */
const hasMultipleUnits = computed(() => localUnitGroupKeys.value.length > 1)

/** 将 UnifiedPointValue 转为 OverlayBarItem */
function toBarItem(v: UnifiedPointValue): OverlayBarItem {
  return {
    layerId: v.layerId,
    name: v.name,
    category: v.category,
    valueText: v.valueText,
    numericValue: v.value,
    unit: v.unit,
    accentColor: v.accentColor,
  }
}

// ── D2: 时间轴类型分离 ────────────────────────────────────────────────────────

const timeAxisTypeLabels: Record<TimeAxisType, string> = {
  hourly: '逐小时',
  block: '周期块',
  date: '逐日',
  unknown: '其他',
}

/** 对给定序列列表按时间轴类型分组 */
function groupByTimeAxis(
  series: MultiLayerSeries[],
): { type: TimeAxisType; label: string; series: MultiLayerSeries[] }[] {
  const groups: Record<TimeAxisType, MultiLayerSeries[]> = {
    hourly: [],
    block: [],
    date: [],
    unknown: [],
  }
  for (const s of series) {
    const t = detectTimeAxisType(s.data.map((p) => p.time))
    groups[t].push(s)
  }
  return (Object.keys(groups) as TimeAxisType[])
    .filter((t) => groups[t].length > 0)
    .map((t) => ({ type: t, label: timeAxisTypeLabels[t], series: groups[t] }))
}

function enterInspectTools() {
  emit('setActiveTab', 'tools')
  emit('enterSelectMode')
}
</script>

<template>
  <!-- ── visual Tab：工作流图表结果 ─────────────────────────────── -->
  <section v-if="hasAnalysisCharts" v-show="true" id="workflow-charts" class="analysis-section">
    <AnalysisResultCharts :charts="analysisCharts" :tables="analysisTables" />
  </section>

  <!-- ── visual Tab：统一多图层分析 ──────────────────────────────── -->
  <section
    v-if="hasUnifiedData"
    v-show="true"
    id="unified-layer-analysis"
    class="analysis-section analysis-section--unified"
  >
    <div class="section-kicker">图层数据分析</div>
    <div class="unified-section-head">
      <div>
        <h3>选点图层对比</h3>
        <p>当前选点处所有可见图层的数值对比与时序演变。</p>
      </div>
      <div class="display-mode-toggle">
        <button
          class="mode-btn"
          :class="{ active: displayMode === 'combined' }"
          @click="displayMode = 'combined'"
        >
          组合
        </button>
        <button
          class="mode-btn"
          :class="{ active: displayMode === 'categorized' }"
          @click="displayMode = 'categorized'"
        >
          分类
        </button>
      </div>
    </div>

    <!-- 组合模式：全部图层在同一图表 -->
    <template v-if="displayMode === 'combined'">
      <!-- 多量纲：按量纲分组显示 -->
      <template v-if="hasMultipleUnits">
        <div
          v-for="unitKey in localUnitGroupKeys"
          :key="unitKey"
          class="unified-subsection unified-subsection--unit"
        >
          <h4 class="subsection-title">
            {{ unitKey }}
            <span class="subsection-count">{{ localPointValuesByUnit[unitKey].length }} 层</span>
          </h4>
          <MultiOverlayBarChart
            :items="localPointValuesByUnit[unitKey].map(toBarItem)"
            :title="`${unitKey} · 点值对比`"
          />
          <template
            v-for="tg in groupByTimeAxis(localTimeSeriesByUnit[unitKey] ?? [])"
            :key="tg.type"
          >
            <MultiLayerTimeSeriesChart
              :series="tg.series"
              :title="`${unitKey} · 时序（${tg.label}）`"
              :height="220"
            />
          </template>
        </div>
      </template>

      <!-- 单量纲：合并显示，但按时间轴类型分离时序 -->
      <template v-else>
        <div v-if="hasPointComparison" class="unified-subsection">
          <h4 class="subsection-title">点值对比</h4>
          <MultiOverlayBarChart :items="unifiedBarItems" title="全部可见图层点值" />
        </div>
        <div v-if="hasMultiLayerTimeSeries" class="unified-subsection">
          <h4 class="subsection-title">时间序列对比</h4>
          <template v-for="tg in groupByTimeAxis(allTimeSeries)" :key="tg.type">
            <MultiLayerTimeSeriesChart
              :series="tg.series"
              :title="tg.series.length > 1 ? `时序（${tg.label}）` : undefined"
              :height="280"
            />
          </template>
        </div>
      </template>
    </template>

    <!-- 分类模式：按数据类型分组显示 -->
    <template v-else>
      <!-- 天气数据组 -->
      <div
        v-if="pointValuesByCategory.weather.length || timeSeriesByCategory.weather.length"
        class="unified-category-group"
      >
        <div class="category-header">
          <span class="category-badge category-badge--weather">天气数据</span>
          <span class="category-count">{{ pointValuesByCategory.weather.length }} 个图层</span>
        </div>
        <MultiOverlayBarChart
          v-if="pointValuesByCategory.weather.length"
          :items="pointValuesByCategory.weather.map(toBarItem)"
          title="天气图层点值"
        />
        <template
          v-for="tg in groupByTimeAxis(timeSeriesByCategory.weather)"
          :key="'weather-' + tg.type"
        >
          <MultiLayerTimeSeriesChart
            v-if="tg.series.length"
            :series="tg.series"
            :title="`天气图层时序（${tg.label}）`"
            :height="240"
          />
        </template>
      </div>

      <!-- 栅格数据组 -->
      <div
        v-if="pointValuesByCategory.raster.length || timeSeriesByCategory.raster.length"
        class="unified-category-group"
      >
        <div class="category-header">
          <span class="category-badge category-badge--raster">栅格数据</span>
          <span class="category-count">{{ pointValuesByCategory.raster.length }} 个图层</span>
        </div>
        <MultiOverlayBarChart
          v-if="pointValuesByCategory.raster.length"
          :items="pointValuesByCategory.raster.map(toBarItem)"
          title="栅格图层点值"
        />
        <template
          v-for="tg in groupByTimeAxis(timeSeriesByCategory.raster)"
          :key="'raster-' + tg.type"
        >
          <MultiLayerTimeSeriesChart
            v-if="tg.series.length"
            :series="tg.series"
            :title="`栅格图层时序（${tg.label}）`"
            :height="240"
          />
        </template>
      </div>

      <!-- 矢量数据组 -->
      <div
        v-if="pointValuesByCategory.vector.length || timeSeriesByCategory.vector.length"
        class="unified-category-group"
      >
        <div class="category-header">
          <span class="category-badge category-badge--vector">矢量数据</span>
          <span class="category-count">{{ pointValuesByCategory.vector.length }} 个图层</span>
        </div>
        <MultiOverlayBarChart
          v-if="pointValuesByCategory.vector.length"
          :items="pointValuesByCategory.vector.map(toBarItem)"
          title="矢量图层信息"
        />
      </div>
    </template>
  </section>

  <!-- ── visual Tab：点查图表 ──────────────────────────────────────── -->
  <section
    v-if="hasPointWeatherSection"
    v-show="true"
    id="point-weather"
    class="analysis-section analysis-section--weather"
  >
    <div class="section-kicker">{{ INSPECT_COPY.sectionKicker }}</div>
    <div class="weather-section-head">
      <div>
        <h3>{{ INSPECT_COPY.sectionTitle }}</h3>
        <p v-if="!pointWeather && !pointWeatherLoading">点选地图后显示数值与时序。</p>
        <p v-else>
          使用工具栏「选择」后点击地图；漫游模式下可
          <kbd>Shift</kbd>+点击临时查询。
        </p>
      </div>
      <span class="analysis-chip" :class="{ muted: !pointWeather }">
        {{ pointInspectStatusLabel }}
      </span>
    </div>

    <div v-if="!selectedMapPoint && !pointWeather && !pointWeatherLoading" class="weather-state">
      尚未选点 — 切到「分析工具」进入选择模式后点击地图。
    </div>
    <div v-if="pointWeatherLoading" class="weather-state weather-state-loading">正在获取点查…</div>
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
        <article
          v-for="row in pointWeatherHourlyRows"
          :key="row.time"
          class="weather-hourly-card"
          :class="{ active: row.active }"
        >
          <span>{{ row.time }}</span>
          <strong>{{ row.metric }}</strong>
        </article>
      </div>

      <MultiLayerTimeSeriesChart
        v-if="hasWeatherChart"
        :series="weatherChartSeries"
        :title="pointWeatherMetricLabel + ' 时序趋势'"
        :height="180"
      />
    </template>
  </section>

  <section
    v-if="visibleHotspots.length > 0"
    v-show="true"
    id="hotspot-section"
    class="analysis-section analysis-section--hotspots"
  >
    <div class="section-kicker">热点</div>
    <h3>点位列表</h3>
    <ul class="hotspot-list">
      <li
        v-for="hotspot in visibleHotspots"
        :id="`hotspot-${hotspot.id}`"
        :key="hotspot.id"
        :class="{ selected: selectedHotspot?.id === hotspot.id }"
        role="button"
        tabindex="0"
        @click="emit('selectHotspot', hotspot.id)"
        @keydown.enter.prevent="emit('selectHotspot', hotspot.id)"
      >
        <span>{{ hotspot.name }}</span>
        <strong>{{ hotspot.value }}</strong>
      </li>
    </ul>
  </section>

  <section
    v-if="resultModel"
    v-show="true"
    id="result-section"
    class="analysis-section analysis-section--result"
  >
    <div class="section-kicker">结果</div>
    <div class="report-section-head">
      <div>
        <h3>{{ resultModel.title }}</h3>
        <p v-if="resultModel.subtitle">{{ resultModel.subtitle }}</p>
      </div>
      <a
        v-if="resultModel.canShowResultLink && resultModel.resultUrl"
        class="job-result-link"
        :href="resultModel.resultUrl"
        target="_blank"
        rel="noreferrer"
      >
        打开结果
      </a>
    </div>
    <dl class="meta-list" style="margin-top: 0.35rem">
      <div v-if="resultModel.statusText">
        <dt>状态</dt>
        <dd>{{ resultModel.statusText }}</dd>
      </div>
      <div v-if="resultModel.progressText">
        <dt>进度</dt>
        <dd>{{ resultModel.progressText }}</dd>
      </div>
      <div v-if="resultModel.category">
        <dt>类别</dt>
        <dd>{{ resultModel.category }}</dd>
      </div>
    </dl>
    <div v-if="resultModel.metricRows.length" class="job-metrics">
      <div v-for="m in resultModel.metricRows" :key="m.label" class="job-metric-item">
        <span class="jm-label">{{ m.label }}</span>
        <strong class="jm-value">{{ m.value }}</strong>
      </div>
    </div>
  </section>

  <div
    v-show="true"
    v-if="!hasVisualTabContent"
    class="analysis-sparse-card analysis-sparse-card--visual"
  >
    <p class="analysis-sparse-title">{{ ANALYSIS_COPY.sparseVisualTitle }}</p>
    <p>{{ sparseVisualHint }}</p>
    <div v-if="isRealtimeWeatherLayer || canRunWorkflow" class="overview-quick-actions">
      <AppButton
        v-if="isRealtimeWeatherLayer && interactionMode !== 'select'"
        size="xs"
        variant="secondary"
        @click="enterInspectTools"
      >
        {{ ANALYSIS_COPY.toolsQuickInspect }}
      </AppButton>
      <AppButton size="xs" variant="secondary" @click="emit('setActiveTab', 'style')">
        符号样式
      </AppButton>
    </div>
  </div>
</template>

<style scoped src="./InfoPanel.styles.css"></style>
