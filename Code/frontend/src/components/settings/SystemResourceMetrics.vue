<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { fetchRuntimeResources } from '../../services/settings-api'
import type { ResourceUsageResponse } from '../../types/api-reexports'

interface FrontendMetrics {
  /** JS 堆占用 MB */
  jsHeapMb: number | null
  /** JS 堆上限 MB */
  jsHeapLimitMb: number | null
  /** 设备总内存 GB（navigator.deviceMemory，Chromium） */
  deviceMemoryGb: number | null
  /** 逻辑核数 */
  cores: number | null
  /** GPU 型号（WebGL renderer，尽力获取） */
  gpu: string | null
  /** 主线程 60s 窗口内 longtask 次数（近似忙碌度） */
  longTasks: number
}

const frontend = ref<FrontendMetrics>({
  jsHeapMb: null,
  jsHeapLimitMb: null,
  deviceMemoryGb: null,
  cores: null,
  gpu: null,
  longTasks: 0,
})
const backend = ref<ResourceUsageResponse | null>(null)
const backendError = ref<string | null>(null)
const loading = ref(false)

let timer: ReturnType<typeof setInterval> | null = null
let longTaskObserver: PerformanceObserver | null = null

// ── 前端指标采集（全部低开销，仅挂载时一次采样） ─────────────────────────
function collectFrontendMetrics(): FrontendMetrics {
  const m = frontend.value
  // JS 堆（仅 Chromium 暴露 performance.memory）
  const perfMem = (
    performance as Performance & { memory?: { usedJSHeapSize: number; jsHeapSizeLimit: number } }
  ).memory
  if (perfMem) {
    m.jsHeapMb = Math.round(perfMem.usedJSHeapSize / 1024 / 1024)
    m.jsHeapLimitMb = Math.round(perfMem.jsHeapSizeLimit / 1024 / 1024)
  }
  // 设备内存 / 核数（navigator 扩展属性，非标准）
  const nav = navigator as Navigator & { deviceMemory?: number }
  m.deviceMemoryGb = nav.deviceMemory ?? null
  m.cores = navigator.hardwareConcurrency ?? null
  // GPU 型号（WebGL2 → WebGL 回退，一次性查询后缓存）
  if (m.gpu === null) {
    try {
      const canvas = document.createElement('canvas')
      const gl = (canvas.getContext('webgl2') || canvas.getContext('webgl')) as
        WebGLRenderingContext | WebGL2RenderingContext | null
      if (gl) {
        const ext = gl.getExtension('WEBGL_debug_renderer_info')
        m.gpu =
          ext && gl.getParameter ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) ?? '') : ''
        m.gpu = m.gpu.replace(/^ANGLE \(/i, '').slice(0, 60) || null
      }
    } catch {
      m.gpu = null
    }
  }
  return { ...m }
}

// ── 后端指标采集 ─────────────────────────────────────────────────────────
async function refreshBackend() {
  loading.value = true
  backendError.value = null
  try {
    backend.value = await fetchRuntimeResources()
  } catch (err) {
    backendError.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

function isPageVisible(): boolean {
  return typeof document !== 'undefined' && document.visibilityState === 'visible'
}

onMounted(() => {
  collectFrontendMetrics()
  // 主线程 longtask 观察（近似 CPU 忙碌度，低开销被动监听）
  if (typeof PerformanceObserver !== 'undefined') {
    try {
      longTaskObserver = new PerformanceObserver((list) => {
        frontend.value.longTasks += list.getEntries().length
      })
      longTaskObserver.observe({ entryTypes: ['longtask'] })
    } catch {
      longTaskObserver = null
    }
  }
  void refreshBackend()
  timer = setInterval(() => {
    if (!isPageVisible()) return // 页面隐藏时跳过，节省资源
    collectFrontendMetrics()
    void refreshBackend()
  }, 60_000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  longTaskObserver?.disconnect()
})

// ── 格式化工具 ───────────────────────────────────────────────────────────
function formatMb(mb: number | null | undefined): string {
  if (mb == null || Number.isNaN(mb)) return '—'
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`
}

function percentOf(used: number | null | undefined, total: number | null | undefined): number {
  if (used == null || total == null || total <= 0) return 0
  return Math.min(100, Math.round((used / total) * 100))
}
</script>

<template>
  <div class="resource-grid">
    <!-- ── 前端页面占用 ─────────────────────────────────────────────── -->
    <div class="resource-card">
      <div class="card-head">
        <h4 class="card-title">前端页面占用</h4>
        <span class="card-meta">浏览器 · 每 60s 刷新</span>
      </div>
      <ul class="metric-list">
        <li class="metric-row">
          <span class="metric-label">JS 堆内存</span>
          <div class="metric-main">
            <div class="bar">
              <div
                class="bar-fill"
                :style="{ width: `${percentOf(frontend.jsHeapMb, frontend.jsHeapLimitMb)}%` }"
              />
            </div>
            <span class="metric-value">
              {{ formatMb(frontend.jsHeapMb)
              }}<template v-if="frontend.jsHeapLimitMb">
                / {{ formatMb(frontend.jsHeapLimitMb) }}</template
              >
            </span>
          </div>
        </li>
        <li class="metric-row">
          <span class="metric-label">设备内存</span>
          <div class="metric-main">
            <span class="metric-value">
              {{ frontend.deviceMemoryGb ? `${frontend.deviceMemoryGb} GB` : '—' }}
            </span>
          </div>
        </li>
        <li class="metric-row">
          <span class="metric-label">逻辑核心</span>
          <div class="metric-main">
            <span class="metric-value">{{ frontend.cores ?? '—' }}</span>
          </div>
        </li>
        <li class="metric-row">
          <span class="metric-label">主线程忙碌</span>
          <div class="metric-main">
            <span class="metric-value">{{ frontend.longTasks }} 次长任务</span>
          </div>
        </li>
        <li class="metric-row">
          <span class="metric-label">GPU</span>
          <div class="metric-main">
            <span class="metric-value gpu-name" :title="frontend.gpu ?? ''">{{
              frontend.gpu || '不可用'
            }}</span>
          </div>
        </li>
      </ul>
    </div>

    <!-- ── 后端占用 ─────────────────────────────────────────────────── -->
    <div class="resource-card">
      <div class="card-head">
        <h4 class="card-title">后端占用</h4>
        <span class="card-meta">服务器 · {{ backend?.worker_count ?? '—' }} worker 在线</span>
      </div>
      <p v-if="backendError" class="error">{{ backendError }}</p>
      <template v-if="backend?.system">
        <ul class="metric-list">
          <li class="metric-row">
            <span class="metric-label">系统 CPU</span>
            <div class="metric-main">
              <div class="bar">
                <div class="bar-fill" :style="{ width: `${backend.system.cpu_percent ?? 0}%` }" />
              </div>
              <span class="metric-value">{{ backend.system.cpu_percent ?? '—' }}%</span>
            </div>
          </li>
          <li class="metric-row">
            <span class="metric-label">系统内存</span>
            <div class="metric-main">
              <div class="bar">
                <div
                  class="bar-fill"
                  :style="{ width: `${backend.system.memory_percent ?? 0}%` }"
                />
              </div>
              <span class="metric-value">
                {{ formatMb(backend.system.memory_used_mb) }}
                <template v-if="backend.system.memory_total_mb">
                  / {{ formatMb(backend.system.memory_total_mb) }}</template
                >
                <template v-if="backend.system.memory_percent != null">
                  （{{ Math.round(backend.system.memory_percent) }}%）</template
                >
              </span>
            </div>
          </li>
          <li class="metric-row">
            <span class="metric-label">数据盘</span>
            <div class="metric-main">
              <div class="bar">
                <div class="bar-fill" :style="{ width: `${backend.system.disk_percent ?? 0}%` }" />
              </div>
              <span class="metric-value">
                {{ formatMb(backend.system.disk_used_mb) }}
                <template v-if="backend.system.disk_total_mb">
                  / {{ formatMb(backend.system.disk_total_mb) }}</template
                >
                <template v-if="backend.system.disk_percent != null">
                  （{{ Math.round(backend.system.disk_percent) }}%）</template
                >
              </span>
            </div>
          </li>
        </ul>
      </template>
      <template v-else-if="!backendError">
        <p class="empty">{{ loading ? '加载中…' : '暂无数据' }}</p>
      </template>
      <template v-if="backend?.processes?.length">
        <p class="processes-title">后端进程（{{ backend.processes.length }}）</p>
        <ul class="process-list">
          <li v-for="p in backend.processes" :key="p.pid" class="process-row">
            <span class="process-name" :title="p.name">{{ p.name }}</span>
            <span class="process-pid">#{{ p.pid }}</span>
            <span class="process-cpu">CPU {{ p.cpu_percent ?? '—' }}%</span>
            <span class="process-mem">RAM {{ formatMb(p.memory_rss_mb) }}</span>
          </li>
        </ul>
      </template>
    </div>
  </div>
</template>

<style scoped>
.resource-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 0.75rem;
}

.resource-card {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  padding: 0.75rem 0.85rem;
  border-radius: 0.55rem;
  border: 1px solid rgba(136, 192, 255, 0.12);
  background: rgba(4, 12, 23, 0.45);
}

.card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5rem;
}

.card-title {
  margin: 0;
  font-size: var(--font-size-caption);
  color: var(--text-primary);
}

.card-meta {
  font-size: var(--font-size-caption);
  color: var(--text-faint);
}

.metric-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.metric-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
}

.metric-label {
  flex: 0 0 4.6rem;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}

.metric-main {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
}

.bar {
  flex: 1;
  height: 0.4rem;
  border-radius: 999px;
  background: rgba(136, 192, 255, 0.14);
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, rgba(90, 213, 255, 0.7), rgba(90, 213, 255, 1));
  transition: width 0.4s ease;
}

.metric-value {
  flex: 0 0 auto;
  font-size: var(--font-size-caption);
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.gpu-name {
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 11rem;
}

.processes-title {
  margin: 0.2rem 0 0;
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}

.process-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  max-height: 9rem;
  overflow-y: auto;
}

.process-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}

.process-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #c9dbea;
}

.process-pid {
  color: var(--text-faint);
  font-variant-numeric: tabular-nums;
}

.process-cpu,
.process-mem {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.error {
  margin: 0;
  color: #ffb4a8;
  font-size: var(--font-size-caption);
}

.empty {
  margin: 0;
  color: var(--text-faint);
  font-size: var(--font-size-caption);
}
</style>
