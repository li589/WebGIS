<script setup lang="ts">
/**
 * 多图层点值柱状对比图：基于 ECharts 的横向柱状图。
 *
 * 支持悬停 tooltip 显示图层名称、数值与单位，
 * 各图层以独立颜色区分，支持负值方向显示。
 */
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { useEchartsThemeName } from './echarts-theme'
import { resolveCanvasColor } from '../workflow/canvas-theme'

use([CanvasRenderer, BarChart, GridComponent, TooltipComponent])

export interface OverlayBarItem {
  layerId: string
  name: string
  category?: string
  valueText: string
  numericValue: number | null
  unit?: string
  accentColor?: string
}

const props = defineProps<{
  items: OverlayBarItem[]
  title?: string
  /** 图表高度（px），默认按条目数自适应 */
  height?: number
}>()

const echartsTheme = useEchartsThemeName()

const defaultBarColor = () => resolveCanvasColor('--accent', '#5ad5ff')

const chartHeight = computed(() => {
  if (props.height) return props.height
  return Math.max(120, props.items.length * 36 + 50)
})

const echartsOption = computed(() => {
  const items = props.items
  const hasNegative = items.some((i) => i.numericValue !== null && i.numericValue < 0)

  return {
    title: props.title
      ? {
          text: props.title,
          left: 0,
          textStyle: { fontSize: 13, fontWeight: 600 },
        }
      : undefined,
    tooltip: {
      trigger: 'item',
      formatter: (params: { dataIndex: number }) => {
        const item = items[params.dataIndex]
        if (!item) return ''
        const unit = item.unit ? ` ${item.unit}` : ''
        return `<strong>${item.name}</strong><br/>数值: ${item.valueText}<br/>单位: ${unit || '—'}`
      },
    },
    grid: {
      left: 110,
      right: 40,
      top: props.title ? 36 : 12,
      bottom: 16,
    },
    xAxis: {
      type: 'value',
      min: hasNegative ? 'dataMin' : 0,
      axisLabel: { fontSize: 10 },
      splitLine: { lineStyle: { type: 'dashed' as const } },
    },
    yAxis: {
      type: 'category',
      data: items.map((i) => i.name),
      axisLabel: {
        fontSize: 11,
        width: 100,
        overflow: 'truncate' as const,
      },
    },
    series: [
      {
        type: 'bar',
        data: items.map((i) => ({
          value: i.numericValue ?? 0,
          itemStyle: {
            color: i.accentColor || defaultBarColor(),
            borderRadius: [0, 3, 3, 0],
          },
        })),
        barWidth: '60%',
        label: {
          show: true,
          position: 'right' as const,
          fontSize: 10,
          formatter: (params: { dataIndex: number }) => {
            const item = items[params.dataIndex]
            return item?.valueText ?? ''
          },
        },
      },
    ],
  }
})
</script>

<template>
  <div class="multi-overlay-chart-card">
    <div class="chart-head">
      <span class="chart-title">{{ title || '多层共显提取对比' }}</span>
      <span class="chart-badge">{{ items.length }} 个共显层</span>
    </div>
    <VChart
      :key="echartsTheme"
      class="multi-overlay-echart"
      :theme="echartsTheme"
      :option="echartsOption"
      autoresize
      :style="{ height: chartHeight + 'px' }"
    />
  </div>
</template>

<style scoped>
.multi-overlay-chart-card {
  background: var(--surface-1);
  backdrop-filter: blur(8px);
  border: 1px solid var(--surface-hover);
  border-radius: 10px;
  padding: 0.6rem;
  margin-top: 0.6rem;
}

.chart-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.4rem;
}

.chart-title {
  font-size: var(--font-size-caption);
  font-weight: 600;
  color: var(--text-strong);
}

.chart-badge {
  font-size: var(--font-size-caption);
  background: var(--accent-surface);
  color: var(--accent);
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
  border: 1px solid var(--accent-border);
}

.multi-overlay-echart {
  width: 100%;
}
</style>
