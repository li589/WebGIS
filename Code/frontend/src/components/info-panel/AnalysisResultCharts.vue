<script setup lang="ts">
/**
 * Render workflow ResultKind.chart / table refs in the analysis panel.
 * Uses ECharts for interactive charts; tables are plain HTML.
 */
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, ScatterChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'

use([
  CanvasRenderer,
  BarChart,
  LineChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
])

export interface AnalysisChartSeries {
  name: string
  x: Array<string | number>
  y: Array<number | null>
}

export interface AnalysisChartModel {
  id: string
  title: string
  chartType: string
  xLabel: string
  yLabel: string
  unit: string
  series: AnalysisChartSeries[]
}

export interface AnalysisTableModel {
  id: string
  title: string
  columns: string[]
  rows: unknown[][]
}

const props = defineProps<{
  charts?: AnalysisChartModel[]
  tables?: AnalysisTableModel[]
}>()

const hasContent = computed(
  () => (props.charts?.length ?? 0) > 0 || (props.tables?.length ?? 0) > 0,
)

function toEchartsOption(chart: AnalysisChartModel) {
  const categories = chart.series[0]?.x.map((v) => String(v)) ?? ([] as string[])
  const isBar = chart.chartType === 'bar' || chart.chartType === 'histogram'
  const isScatter = chart.chartType === 'scatter'
  return {
    title: {
      text: chart.title,
      left: 0,
      textStyle: { fontSize: 13, fontWeight: 600 },
    },
    tooltip: { trigger: isScatter ? 'item' : 'axis' },
    legend: chart.series.length > 1 ? { top: 24 } : undefined,
    grid: { left: 48, right: 16, top: 56, bottom: 40 },
    dataZoom: chart.series[0] && chart.series[0].x.length > 40 ? [{ type: 'inside' }] : undefined,
    xAxis: isScatter
      ? { type: 'value', name: chart.xLabel || undefined }
      : {
          type: 'category',
          data: categories,
          name: chart.xLabel || undefined,
          axisLabel: { hideOverlap: true },
        },
    yAxis: {
      type: 'value',
      name: chart.yLabel || chart.unit || undefined,
      scale: true,
    },
    series: chart.series.map((s) => {
      if (isScatter) {
        return {
          name: s.name,
          type: 'scatter',
          data: s.x.map((x, i) => [Number(x), s.y[i] ?? null]),
          symbolSize: 8,
        }
      }
      return {
        name: s.name,
        type: isBar ? 'bar' : 'line',
        data: s.y,
        smooth: !isBar,
        showSymbol: s.y.length <= 48,
        areaStyle: isBar ? undefined : { opacity: 0.08 },
      }
    }),
  }
}

function cellText(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : value.toFixed(4)
  }
  return String(value)
}
</script>

<template>
  <div v-if="hasContent" class="analysis-result-charts">
    <div class="section-kicker">工作流图表</div>
    <article v-for="chart in charts" :key="chart.id" class="analysis-chart-card">
      <VChart class="analysis-echart" :option="toEchartsOption(chart)" autoresize />
    </article>
    <article v-for="table in tables" :key="table.id" class="analysis-table-card">
      <h4>{{ table.title }}</h4>
      <div class="analysis-table-scroll">
        <table>
          <thead>
            <tr>
              <th v-for="col in table.columns" :key="col">{{ col }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, ri) in table.rows.slice(0, 200)" :key="ri">
              <td v-for="(cell, ci) in row" :key="ci">{{ cellText(cell) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="table.rows.length > 200" class="analysis-table-more">
        显示前 200 / {{ table.rows.length }} 行
      </p>
    </article>
  </div>
</template>

<style scoped>
.analysis-result-charts {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 12px;
}
.section-kicker {
  font-size: 11px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  opacity: 0.65;
}
.analysis-chart-card,
.analysis-table-card {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  padding: 10px 12px;
}
.analysis-echart {
  width: 100%;
  height: 240px;
}
.analysis-table-card h4 {
  margin: 0 0 8px;
  font-size: 13px;
}
.analysis-table-scroll {
  overflow: auto;
  max-height: 220px;
}
.analysis-table-card table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.analysis-table-card th,
.analysis-table-card td {
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding: 4px 6px;
  text-align: left;
  white-space: nowrap;
}
.analysis-table-more {
  margin: 6px 0 0;
  font-size: 11px;
  opacity: 0.7;
}
</style>
