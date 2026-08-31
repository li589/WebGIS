<script setup lang="ts">
/**
 * 自动统计卡片 — 面要素绘制后实时统计。
 *
 * 几何统计（前端即算，球面测地线近似）：测地线面积、周长
 * 栅格统计（对可见栅格图层调 /analysis/zonal-stats/sync）：
 * 均值、最大值、最小值、像元数、标准差
 */
import { computed, ref, watch } from 'vue'
import { AlertCircle, RefreshCw } from '../ui/icons'
import { useDrawStore } from '../../stores/draw-store'
import { useLayerWorkspace } from '../../stores/layers/selectors'
import { useUiStore } from '../../stores/ui'
import { resolveApiUrl } from '../../services/_http'
import { applyApiFetchDefaults } from '../../services/http-credentials'
import { formatArea, formatLength, geodesicAreaM2, geodesicPerimeterM } from '../map/geometry-stats'

interface ZonalStatItem {
  layer_id: string
  layer_name: string
  mean: number | null
  max: number | null
  min: number | null
  sum: number | null
  count: number
  std: number | null
  unit: string | null
}

interface ZonalStatsResponse {
  results: ZonalStatItem[]
}

const drawStore = useDrawStore()
const uiStore = useUiStore()
const { activeLayers } = useLayerWorkspace()

const loading = ref(false)
const error = ref<string | null>(null)
const stats = ref<ZonalStatItem[]>([])
// 竞态防护：仅采纳最新一次请求的结果，避免慢响应覆盖新结果
let statsSeq = 0

const visible = computed(() => {
  return (
    uiStore.interactionMode === 'draw' &&
    drawStore.features.some((f) => f.geometry.type === 'Polygon')
  )
})

const lastPolygonFeature = computed(() => {
  const polys = [...drawStore.features].reverse().find((f) => f.geometry.type === 'Polygon')
  return polys ?? null
})

// 几何统计：测地线面积与周长（纯前端计算，不依赖栅格）
const geomAreaM2 = computed(() =>
  lastPolygonFeature.value ? geodesicAreaM2(lastPolygonFeature.value.geometry) : 0,
)
const geomPerimeterM = computed(() =>
  lastPolygonFeature.value ? geodesicPerimeterM(lastPolygonFeature.value.geometry) : 0,
)

const overlayLayers = computed(() => {
  return activeLayers.value.filter(
    (l) => l.visible && (l.importedRaster || l.dataState === 'catalog'),
  )
})

async function fetchStats() {
  const feature = lastPolygonFeature.value
  if (!feature) {
    stats.value = []
    return
  }
  const seq = ++statsSeq

  const overlayLayerIds = overlayLayers.value.map(
    (l) => l.importedRaster?.overlayLayerId ?? l.catalogId,
  )
  if (overlayLayerIds.length === 0) {
    // 无栅格不算错误：几何统计仍在展示，仅提示栅格部分不可用
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
          geojson: {
            type: 'Feature',
            geometry: feature.geometry,
            properties: {},
          },
          overlay_layer_ids: overlayLayerIds,
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

// 当最后一个面要素几何变化时自动触发统计（覆盖删除/替换/新增）
watch(
  () => {
    const f = lastPolygonFeature.value
    return f ? JSON.stringify(f.geometry) : null
  },
  () => {
    if (visible.value) {
      fetchStats()
    }
  },
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
  <Transition name="zonal-stats">
    <div v-if="visible" class="zonal-stats-card">
      <div class="zonal-stats-header">
        <h4 class="zonal-stats-title">自动统计</h4>
        <button
          class="zonal-stats-refresh"
          :disabled="loading"
          title="刷新统计"
          @click="fetchStats"
        >
          <RefreshCw :size="12" :class="{ spinning: loading }" />
        </button>
      </div>

      <!-- 几何统计（测地线，球面近似） -->
      <div class="geom-stats">
        <div class="geom-stat">
          <span class="geom-label">测地线面积</span>
          <strong class="geom-value">{{ formatArea(geomAreaM2) }}</strong>
        </div>
        <div class="geom-stat">
          <span class="geom-label">周长</span>
          <strong class="geom-value">{{ formatLength(geomPerimeterM) }}</strong>
        </div>
      </div>

      <div v-if="loading" class="zonal-stats-loading">
        <span class="loading-dot"></span>
        <span>正在统计可见栅格…</span>
      </div>

      <div v-else-if="error" class="zonal-stats-error">
        <AlertCircle :size="14" />
        <span>{{ error }}</span>
        <button class="zonal-stats-retry" @click="fetchStats">重试</button>
      </div>

      <div v-else-if="stats.length === 0" class="zonal-stats-empty">
        导入栅格图层后可自动统计选区像元数与最大/最小值
      </div>

      <div v-else class="zonal-stats-table-wrap">
        <table class="zonal-stats-table">
          <thead>
            <tr>
              <th>图层</th>
              <th>均值</th>
              <th>最大值</th>
              <th>最小值</th>
              <th>像元数</th>
              <th>标准差</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in stats" :key="item.layer_id">
              <td class="stat-name" :title="item.layer_name">
                {{ item.layer_name }}
                <span v-if="item.unit" class="stat-unit">({{ item.unit }})</span>
              </td>
              <td class="stat-value">{{ formatValue(item.mean) }}</td>
              <td class="stat-value">{{ formatValue(item.max) }}</td>
              <td class="stat-value">{{ formatValue(item.min) }}</td>
              <td class="stat-value stat-count">{{ item.count.toLocaleString() }}</td>
              <td class="stat-value">{{ formatValue(item.std) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.zonal-stats-card {
  position: absolute;
  right: 1rem;
  top: 5rem;
  z-index: 18;
  background: var(--surface-2);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
  padding: 10px 12px;
  min-width: 340px;
  max-width: 420px;
  max-height: 360px;
  overflow-y: auto;
}

.zonal-stats-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

/* 几何统计行：测地线面积 / 周长 */
.geom-stats {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}

.geom-stat {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px 8px;
  background: var(--surface-1);
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

.zonal-stats-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.zonal-stats-refresh {
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

.zonal-stats-refresh:hover {
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

.zonal-stats-loading,
.zonal-stats-empty {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 12px 0;
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

.zonal-stats-error {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 0;
  font-size: 12px;
  color: var(--danger);
}

.zonal-stats-retry {
  margin-left: auto;
  padding: 2px 8px;
  border: 1px solid var(--border-default);
  border-radius: 4px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
}

.zonal-stats-table-wrap {
  overflow-x: auto;
}

.zonal-stats-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}

.zonal-stats-table th,
.zonal-stats-table td {
  padding: 4px 6px;
  text-align: right;
  white-space: nowrap;
}

.zonal-stats-table th {
  color: var(--text-secondary);
  font-weight: 500;
  border-bottom: 1px solid var(--border-default);
  position: sticky;
  top: 0;
  background: var(--surface-2);
}

.zonal-stats-table th:first-child,
.zonal-stats-table td:first-child {
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

.stat-count {
  color: var(--text-secondary);
}

/* Transition */
.zonal-stats-enter-active,
.zonal-stats-leave-active {
  transition:
    opacity 0.2s ease,
    transform 0.2s ease;
}

.zonal-stats-enter-from,
.zonal-stats-leave-to {
  opacity: 0;
  transform: translateX(8px);
}
</style>
