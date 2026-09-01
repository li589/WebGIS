<script setup lang="ts">
/**
 * 自动统计卡片（分析面板 · 图表 Tab 顶部）— 导入/绘制矢量图层的自动统计。
 *
 * 几何统计（前端即算，球面测地线近似）：测地线面积、周长/线总长
 * 栅格统计（对全部可见栅格图层调 /analysis/zonal-stats/sync）：
 * 像元数、最大值、最小值、均值
 */
import { computed, ref, watch } from 'vue'
import { AlertCircle, RefreshCw } from '../ui/icons'
import { useLayerWorkspace } from '../../stores/layers/selectors'
import type { ActiveLayerDisplay } from '../../stores/layers/types'
import { resolveApiUrl } from '../../services/_http'
import { applyApiFetchDefaults } from '../../services/http-credentials'
import { formatArea, formatLength, summarizeFeatureCollection } from '../map/geometry-stats'
import {
  activeLayerHasReadableRaster,
  resolveRasterOverlayIdFromActiveLayer,
} from './tools/tool-layer-capabilities'

interface ZonalStatItem {
  layer_id: string
  layer_name: string
  mean: number | null
  max: number | null
  min: number | null
  count: number
  unit: string | null
}

interface ZonalStatsResponse {
  results: ZonalStatItem[]
}

const props = defineProps<{ displayLayer: ActiveLayerDisplay }>()

const { activeLayers } = useLayerWorkspace()

const payload = computed(() => {
  const layer = activeLayers.value.find((l) => l.instanceId === props.displayLayer.instanceId)
  return layer?.importedVector ?? null
})

const summary = computed(() => {
  const p = payload.value
  if (!p?.geojson?.features?.length) return null
  const s = summarizeFeatureCollection(p.geojson)
  return s.polygonCount > 0 || s.lineCount > 0 ? s : null
})

/** 可见栅格图层 id 列表（与 tool-layer-capabilities 口径一致） */
const overlayLayerIds = computed(() =>
  activeLayers.value
    .filter((l) => l.visible && activeLayerHasReadableRaster(l))
    .map((l) => resolveRasterOverlayIdFromActiveLayer(l))
    .filter((id): id is string => Boolean(id)),
)

const loading = ref(false)
const error = ref<string | null>(null)
const stats = ref<ZonalStatItem[]>([])
// 竞态防护：仅采纳最新一次请求的结果
let statsSeq = 0

async function fetchStats() {
  const p = payload.value
  if (!p?.geojson || summary.value?.polygonCount === 0) {
    stats.value = []
    return
  }
  const seq = ++statsSeq
  const ids = overlayLayerIds.value
  if (ids.length === 0) {
    if (seq === statsSeq) {
      stats.value = []
      error.value = null
    }
    return
  }
  loading.value = true
  error.value = null
  try {
    const resp = await fetch(
      resolveApiUrl('/analysis/zonal-stats/sync'),
      applyApiFetchDefaults({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          geojson: p.geojson,
          overlay_layer_ids: ids,
        }),
      }),
    )
    if (!resp.ok) {
      const text = await resp.text()
      throw new Error(text || `HTTP ${resp.status}`)
    }
    const data = (await resp.json()) as ZonalStatsResponse
    if (seq === statsSeq) stats.value = data.results ?? []
  } catch (err) {
    if (seq === statsSeq) {
      error.value = `统计失败: ${err instanceof Error ? err.message : String(err)}`
      stats.value = []
    }
  } finally {
    if (seq === statsSeq) loading.value = false
  }
}

// 图层数据（revision）或可见栅格集合变化时自动统计
watch(
  [() => payload.value?.revision ?? 0, () => overlayLayerIds.value.join(',')],
  () => {
    fetchStats()
  },
  { immediate: true },
)

function formatValue(val: number | null): string {
  if (val === null || val === undefined) return '—'
  if (Math.abs(val) < 0.01) return val.toExponential(2)
  if (Math.abs(val) < 1) return val.toFixed(4)
  if (Math.abs(val) < 1000) return val.toFixed(2)
  return val.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}
</script>

<template>
  <section v-if="summary" class="auto-stats">
    <div class="auto-stats-head">
      <div>
        <div class="section-kicker">自动统计</div>
        <h3 class="auto-stats-title">
          矢量几何 + 可见栅格
          <span class="auto-stats-meta">
            {{ summary.polygonCount }} 面 · {{ summary.lineCount }} 线
          </span>
        </h3>
      </div>
      <button class="auto-stats-refresh" :disabled="loading" title="刷新统计" @click="fetchStats">
        <RefreshCw :size="12" :class="{ spinning: loading }" />
      </button>
    </div>

    <div class="geom-stats">
      <div v-if="summary.polygonCount > 0" class="geom-stat">
        <span class="geom-label">测地线面积</span>
        <strong class="geom-value">{{ formatArea(summary.areaM2) }}</strong>
      </div>
      <div class="geom-stat">
        <span class="geom-label">{{ summary.polygonCount > 0 ? '周长' : '线总长' }}</span>
        <strong class="geom-value">{{ formatLength(summary.perimeterM) }}</strong>
      </div>
    </div>

    <div v-if="loading" class="auto-stats-loading">
      <span class="loading-dot"></span>
      <span>正在统计可见栅格…</span>
    </div>

    <div v-else-if="error" class="auto-stats-error">
      <AlertCircle :size="14" />
      <span>{{ error }}</span>
      <button class="auto-stats-retry" @click="fetchStats">重试</button>
    </div>

    <div v-else-if="stats.length === 0" class="auto-stats-empty">
      导入栅格图层后可自动统计选区像元数与最大/最小值
    </div>

    <div v-else class="auto-stats-table-wrap">
      <table class="auto-stats-table">
        <thead>
          <tr>
            <th>图层</th>
            <th>像元数</th>
            <th>最大值</th>
            <th>最小值</th>
            <th>均值</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in stats" :key="item.layer_id">
            <td class="stat-name" :title="item.layer_name">
              {{ item.layer_name }}
              <span v-if="item.unit" class="stat-unit">({{ item.unit }})</span>
            </td>
            <td class="stat-value">{{ item.count.toLocaleString() }}</td>
            <td class="stat-value">{{ formatValue(item.max) }}</td>
            <td class="stat-value">{{ formatValue(item.min) }}</td>
            <td class="stat-value">{{ formatValue(item.mean) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.auto-stats {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
  background: var(--surface-1);
  border: 1px solid var(--border-default);
  border-radius: 10px;
}

.auto-stats-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.section-kicker {
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--accent);
  margin-bottom: 2px;
}

.auto-stats-title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.auto-stats-meta {
  margin-left: 6px;
  font-size: 10px;
  font-weight: 400;
  color: var(--text-secondary);
}

.auto-stats-refresh {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}

.auto-stats-refresh:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.geom-stats {
  display: flex;
  gap: 8px;
}

.geom-stat {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px 8px;
  background: var(--surface-2);
  border: 1px solid var(--border-default);
  border-radius: 6px;
}

.geom-label {
  font-size: 10px;
  color: var(--text-secondary);
}

.geom-value {
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  color: var(--text-primary);
}

.auto-stats-loading,
.auto-stats-empty {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 0;
  font-size: 12px;
  color: var(--text-secondary);
}

.loading-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent);
  animation: pulse 1.2s ease-in-out infinite;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 0.3;
  }
  50% {
    opacity: 1;
  }
}

.auto-stats-error {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 0;
  font-size: 12px;
  color: var(--danger);
}

.auto-stats-retry {
  margin-left: auto;
  padding: 2px 8px;
  border: 1px solid var(--border-default);
  border-radius: 4px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
}

.auto-stats-table-wrap {
  overflow-x: auto;
}

.auto-stats-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}

.auto-stats-table th,
.auto-stats-table td {
  padding: 4px 6px;
  text-align: right;
  white-space: nowrap;
}

.auto-stats-table th {
  color: var(--text-secondary);
  font-weight: 500;
  border-bottom: 1px solid var(--border-default);
}

.auto-stats-table th:first-child,
.auto-stats-table td:first-child {
  text-align: left;
}

.stat-name {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--text-primary);
}

.stat-unit {
  color: var(--text-secondary);
  font-size: 10px;
}

.stat-value {
  font-variant-numeric: tabular-nums;
  color: var(--text-primary);
}
</style>
