<script setup lang="ts">
/**
 * 多图层时间序列对比图：基于 ECharts 的多序列折线图。
 *
 * 支持在同一图表中展示多个图层的时序数据，各图层以不同颜色区分，
 * 共享时间轴，支持图例切换、tooltip 联动与 dataZoom 缩放。
 */
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'

use([
  CanvasRenderer,
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
])

export interface MultiLayerSeriesPoint {
  /** 时间标签（如 "08:00" 或 "20240101 → 20240108"） */
  time: string
  /** 数值，null 表示缺失 */
  value: number | null
}

export interface MultiLayerSeries {
  /** 图层标识 */
  id: string
  /** 显示名称 */
  name: string
  /** 主题色 */
  color?: string
  /** 数据点 */
  data: MultiLayerSeriesPoint[]
  /** 单位 */
  unit?: string
}

const props = defineProps<{
  series: MultiLayerSeries[]
  title?: string
  /** 图表高度（px），默认 260 */
  height?: number
  /** 是否以柱状图显示（默认折线） */
  asBar?: boolean
}>()

/** 合并所有序列的时间标签作为共享 X 轴 */
const xCategories = computed(() => {
  const timeSet = new Set<string>()
  for (const s of props.series) {
    for (const p of s.data) {
      if (p.time) timeSet.add(p.time)
    }
  }
  return Array.from(timeSet)
})

const showLegend = computed(() => props.series.length > 1)
const showDataZoom = computed(() => xCategories.value.length > 30)

const echartsOption = computed(() => {
  const categories = xCategories.value
  const isBar = props.asBar ?? false

  const seriesData = props.series.map((s) => {
    const valueMap = new Map<string, number | null>()
    for (const p of s.data) {
      valueMap.set(p.time, p.value)
    }
    return {
      name: s.name,
      type: isBar ? 'bar' : 'line',
      data: categories.map((cat) => valueMap.get(cat) ?? null),
      smooth: !isBar,
      showSymbol: categories.length <= 48,
      areaStyle: isBar ? undefined : { opacity: 0.06 },
      itemStyle: s.color ? { color: s.color } : undefined,
      lineStyle: s.color ? { color: s.color } : undefined,
      connectNulls: true,
    }
  })

  return {
    title: props.title
      ? {
          text: props.title,
          left: 0,
          textStyle: { fontSize: 13, fontWeight: 600 },
        }
      : undefined,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
    },
    legend: showLegend.value
      ? {
          top: props.title ? 28 : 0,
          type: 'scroll',
          textStyle: { fontSize: 11 },
        }
      : undefined,
    grid: {
      left: 52,
      right: 16,
      top: props.title ? (showLegend.value ? 56 : 36) : showLegend.value ? 28 : 12,
      bottom: showDataZoom.value ? 48 : 28,
    },
    dataZoom: showDataZoom.value
      ? [
          { type: 'inside', start: 0, end: 100 },
          { type: 'slider', height: 16, bottom: 8 },
        ]
      : undefined,
    xAxis: {
      type: 'category',
      data: categories,
      axisLabel: {
        hideOverlap: true,
        fontSize: 10,
        rotate: categories.length > 12 ? 30 : 0,
      },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { fontSize: 10 },
    },
    series: seriesData,
  }
})
</script>

<template>
  <div class="multi-layer-chart-card">
    <VChart
      class="multi-layer-echart"
      :option="echartsOption"
      autoresize
      :style="{ height: (height ?? 260) + 'px' }"
    />
  </div>
</template>

<style scoped>
.multi-layer-chart-card {
  background: var(--surface-1);
  backdrop-filter: blur(8px);
  border: 1px solid var(--surface-hover);
  border-radius: 10px;
  padding: 0.6rem;
  margin-top: 0.6rem;
}

.multi-layer-echart {
  width: 100%;
}
</style>
