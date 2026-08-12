<script setup lang="ts">
import { computed, ref } from 'vue'

export interface HourlyDataPoint {
  time: string
  metric: string
  numericValue?: number
  precipValue?: number
  active?: boolean
}

const props = defineProps<{
  hourlyRows: HourlyDataPoint[]
  title?: string
  unit?: string
}>()

const hoverIndex = ref<number | null>(null)

const parsedPoints = computed(() => {
  return props.hourlyRows.map((item, idx) => {
    const num = item.numericValue ?? parseFloat(item.metric.replace(/[^0-9.-]+/g, '')) ?? 0
    return {
      index: idx,
      time: item.time,
      rawMetric: item.metric,
      val: isNaN(num) ? 0 : num,
      active: item.active ?? false,
    }
  })
})

const minVal = computed(() => {
  if (!parsedPoints.value.length) return 0
  const vals = parsedPoints.value.map((p) => p.val)
  return Math.min(...vals)
})

const maxVal = computed(() => {
  if (!parsedPoints.value.length) return 100
  const vals = parsedPoints.value.map((p) => p.val)
  const max = Math.max(...vals)
  return max === minVal.value ? max + 10 : max
})

const chartWidth = 320
const chartHeight = 120
const padding = 20

const pointsSvgCoords = computed(() => {
  if (!parsedPoints.value.length) return []
  const count = parsedPoints.value.length
  const stepX = (chartWidth - padding * 2) / Math.max(1, count - 1)
  const rangeY = Math.max(0.1, maxVal.value - minVal.value)

  return parsedPoints.value.map((p, idx) => {
    const x = padding + idx * stepX
    const normalizedY = (p.val - minVal.value) / rangeY
    const y = chartHeight - padding - normalizedY * (chartHeight - padding * 2)
    return { ...p, x, y }
  })
})

const linePathD = computed(() => {
  const coords = pointsSvgCoords.value
  if (!coords.length) return ''
  return coords.reduce((acc, p, idx) => {
    return idx === 0 ? `M ${p.x} ${p.y}` : `${acc} L ${p.x} ${p.y}`
  }, '')
})

const areaPathD = computed(() => {
  const coords = pointsSvgCoords.value
  if (!coords.length) return ''
  const first = coords[0]
  const last = coords[coords.length - 1]
  const baselineY = chartHeight - padding
  return `${linePathD.value} L ${last.x} ${baselineY} L ${first.x} ${baselineY} Z`
})

const activePoint = computed(() => {
  if (hoverIndex.value !== null && pointsSvgCoords.value[hoverIndex.value]) {
    return pointsSvgCoords.value[hoverIndex.value]
  }
  return pointsSvgCoords.value.find((p) => p.active) ?? pointsSvgCoords.value[0] ?? null
})
</script>

<template>
  <div class="time-series-chart-card">
    <div class="chart-header">
      <span class="chart-title">{{ title || '24小时演变趋势' }}</span>
      <span v-if="unit" class="chart-unit">单位：{{ unit }}</span>
    </div>

    <div class="chart-stage">
      <svg
        :viewBox="`0 0 ${chartWidth} ${chartHeight}`"
        class="chart-svg"
        @mouseleave="hoverIndex = null"
      >
        <defs>
          <linearGradient id="chartAreaGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#4fc3f7" stop-opacity="0.35" />
            <stop offset="100%" stop-color="#4fc3f7" stop-opacity="0.0" />
          </linearGradient>
        </defs>

        <!-- Grid Lines -->
        <line
          :x1="padding"
          :y1="padding"
          :x2="chartWidth - padding"
          :y2="padding"
          stroke="rgba(255, 255, 255, 0.08)"
          stroke-dasharray="3 3"
        />
        <line
          :x1="padding"
          :y1="chartHeight - padding"
          :x2="chartWidth - padding"
          :y2="chartHeight - padding"
          stroke="rgba(255, 255, 255, 0.15)"
        />

        <!-- Area Fill -->
        <path :d="areaPathD" fill="url(#chartAreaGradient)" />

        <!-- Line -->
        <path
          :d="linePathD"
          fill="none"
          stroke="#4fc3f7"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        />

        <!-- Points & Hover Triggers -->
        <circle
          v-for="p in pointsSvgCoords"
          :key="p.index"
          :cx="p.x"
          :cy="p.y"
          :r="hoverIndex === p.index || p.active ? 4.5 : 2.5"
          :fill="hoverIndex === p.index || p.active ? '#64ffda' : '#4fc3f7'"
          stroke="#0f172a"
          stroke-width="1.5"
          class="chart-point"
          @mouseenter="hoverIndex = p.index"
        />
      </svg>

      <!-- Active Tooltip Callout -->
      <div v-if="activePoint" class="chart-tooltip-badge">
        <span class="tooltip-time">{{ activePoint.time }}</span>
        <strong class="tooltip-val">{{ activePoint.rawMetric }}</strong>
      </div>
    </div>
  </div>
</template>

<style scoped>
.time-series-chart-card {
  background: rgba(15, 23, 42, 0.65);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  padding: 0.8rem;
  margin-top: 0.6rem;
}

.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.4rem;
}

.chart-title {
  font-size: var(--font-size-caption);
  font-weight: 600;
  color: rgba(255, 255, 255, 0.9);
}

.chart-unit {
  font-size: var(--font-size-caption);
  color: rgba(255, 255, 255, 0.45);
}

.chart-stage {
  position: relative;
  width: 100%;
}

.chart-svg {
  width: 100%;
  height: 110px;
  display: block;
  overflow: visible;
}

.chart-point {
  cursor: pointer;
  transition: all 0.2s ease;
}

.chart-tooltip-badge {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(30, 41, 59, 0.85);
  border: 1px solid rgba(79, 195, 247, 0.3);
  border-radius: 6px;
  padding: 0.25rem 0.6rem;
  margin-top: 0.4rem;
}

.tooltip-time {
  font-size: var(--font-size-caption);
  color: rgba(255, 255, 255, 0.65);
}

.tooltip-val {
  font-size: 0.82rem;
  color: #64ffda;
  font-weight: 700;
}
</style>
