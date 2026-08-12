/** * InfoPanel Visual Tab：图表 / 点查 / 叠加时序 / 热点 / 结果 / 空态。 * * 从 InfoPanel.vue
模板抽取（原 1708-1834、2247-2336 行）。纯展示组件， * 全部状态经 props 传入，交互经 emit
上抛父组件。 */
<script setup lang="ts">
import type { ActiveLayerDisplay, LayerHotspot } from '../../stores/layers/types'
import type { WeatherPointResponse } from '../../services/runtime-api'
import { ANALYSIS_COPY, INSPECT_COPY } from '../../ui-copy'
import AppButton from '../ui/AppButton.vue'
import PointTimeSeriesChart from './PointTimeSeriesChart.vue'
import MultiOverlayBarChart from './MultiOverlayBarChart.vue'
import AnalysisResultCharts from './AnalysisResultCharts.vue'

defineProps<{
  displayLayer: ActiveLayerDisplay
  isRealtimeWeatherLayer: boolean
  hasAnalysisCharts: boolean
  analysisCharts: any[]
  analysisTables: any[]
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
  pointWeatherHourlyChartRows: { time: string; metric: string; active: boolean }[]
  pointWeatherMetricLabel: string
  showMultiOverlayBar: boolean
  multiOverlayBarItems: any[]
  showSelectedOverlayTimeSeries: boolean
  showDemoOverlayTimeSeries: boolean
  selectedOverlayTimeSeriesRows: {
    time: string
    metric: string
    numericValue?: number
    active: boolean
  }[]
  overlayStyleMeta: any
  visibleHotspots: LayerHotspot[]
  selectedHotspot: LayerHotspot | null
  resultModel: any
  hasVisualTabContent: boolean
  sparseVisualHint: string
  canRunWorkflow: boolean
  interactionMode: string
}>()

const emit = defineEmits<{
  selectHotspot: [hotspotId: string]
  setActiveTab: [tab: string]
  enterSelectMode: []
  queryOverlaySeries: [payload: { lng: number; lat: number }]
}>()

function enterInspectTools() {
  emit('setActiveTab', 'tools')
  emit('enterSelectMode')
}

function queryDefaultOverlaySeries() {
  emit('queryOverlaySeries', { lng: 11.25, lat: 19.7623 })
}
</script>

<template>
  <!-- ── visual Tab：工作流图表结果 ─────────────────────────────── -->
  <section v-if="hasAnalysisCharts" v-show="true" id="workflow-charts" class="analysis-section">
    <AnalysisResultCharts :charts="analysisCharts" :tables="analysisTables" />
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

      <PointTimeSeriesChart
        v-if="pointWeatherHourlyChartRows.length"
        :hourly-rows="pointWeatherHourlyChartRows"
        :title="pointWeatherMetricLabel + ' 时序趋势'"
      />
    </template>
  </section>

  <section
    v-if="showMultiOverlayBar"
    v-show="true"
    id="overlay-compare"
    class="analysis-section analysis-section--overlays"
  >
    <div class="section-kicker">叠加对比</div>
    <h3>可见叠加层点值</h3>
    <p>当前选点处可见各叠加层的采样对比（含当前选中层与非天气层）。</p>
    <MultiOverlayBarChart :items="multiOverlayBarItems" />
  </section>

  <section
    v-if="
      showSelectedOverlayTimeSeries || showDemoOverlayTimeSeries || displayLayer.isImportedRaster
    "
    v-show="true"
    id="overlay-point-series"
    class="analysis-section analysis-section--overlays"
  >
    <div class="section-kicker">点时间序列</div>
    <h3>
      {{ displayLayer.name }} ·
      {{ showDemoOverlayTimeSeries ? '默认有效点时序' : '选点时序' }}
    </h3>
    <p>
      {{
        showDemoOverlayTimeSeries
          ? '展示当前图层一个稳定有效观测点在全部 8 天块上的数值变化；点击地图可切换为自定义选点。'
          : '同一选点在全部可用 8 天时间块上的数值变化；高亮当前时间轴块。'
      }}
    </p>
    <AppButton
      v-if="!selectedOverlayTimeSeriesRows.length"
      size="xs"
      variant="secondary"
      @click="queryDefaultOverlaySeries"
    >
      加载当前图层 8 天块时序
    </AppButton>
    <PointTimeSeriesChart
      v-if="selectedOverlayTimeSeriesRows.length"
      :hourly-rows="selectedOverlayTimeSeriesRows"
      :title="displayLayer.name + ' 8 天块时序'"
      :unit="overlayStyleMeta?.unit || ''"
    />
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
