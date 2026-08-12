<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { fetchRuntimeStatus } from '../../services/settings-api'
import type { BackendServiceStatus, RuntimeStatusResponse } from '../../types/api-reexports'
import type { components } from '../../types/api-contracts'
import SystemResourceMetrics from './SystemResourceMetrics.vue'

type ServiceHealth = components['schemas']['ServiceHealth']

defineEmits<{ close: [] }>()

const loading = ref(false)
const error = ref<string | null>(null)
const status = ref<RuntimeStatusResponse | null>(null)
let timer: ReturnType<typeof setInterval> | null = null

const HEALTH_SYMBOL: Record<ServiceHealth, string> = {
  ok: '●',
  busy: '◐',
  degraded: '▲',
  offline: '✕',
}

const HEALTH_TITLE: Record<ServiceHealth, string> = {
  ok: '正常',
  busy: '繁忙',
  degraded: '降级',
  offline: '离线',
}

const HEALTH_ORDER: Record<ServiceHealth, number> = {
  ok: 0,
  busy: 1,
  degraded: 2,
  offline: 3,
}

const orderedServices = computed<BackendServiceStatus[]>(() => {
  const svcs = (status.value?.services ?? []) as BackendServiceStatus[]
  return [...svcs].sort(
    (a, b) =>
      HEALTH_ORDER[a.health] - HEALTH_ORDER[b.health] ||
      a.service_name.localeCompare(b.service_name),
  )
})

const serviceCount = computed(() => {
  const svcs = status.value?.services ?? []
  const byHealth: Record<string, number> = { ok: 0, busy: 0, degraded: 0, offline: 0 }
  for (const s of svcs as BackendServiceStatus[]) byHealth[s.health] = (byHealth[s.health] ?? 0) + 1
  return byHealth
})

function isPageVisible(): boolean {
  return typeof document !== 'undefined' && document.visibilityState === 'visible'
}

async function refresh() {
  loading.value = true
  error.value = null
  try {
    status.value = await fetchRuntimeStatus()
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

function healthClass(health: ServiceHealth): string {
  return `health-${health}`
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

/** 服务行展开查看详情（details 内容较长，默认折叠避免视觉噪音） */
const expanded = ref<Set<string>>(new Set())

function toggleExpand(serviceName: string) {
  const next = new Set(expanded.value)
  if (next.has(serviceName)) next.delete(serviceName)
  else next.add(serviceName)
  expanded.value = next
}

function detailEntries(svc: BackendServiceStatus): Array<[string, unknown]> {
  return Object.entries(svc.details ?? {}).filter(([, v]) => v !== null && v !== undefined)
}

function formatDetailValue(value: unknown): string {
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

onMounted(() => {
  void refresh()
  timer = setInterval(() => {
    if (!isPageVisible()) return
    void refresh()
  }, 60_000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <section class="settings-section">
    <div class="section-head">
      <h3 class="section-title">系统状态</h3>
      <button type="button" class="refresh-btn" :disabled="loading" @click="refresh">
        {{ loading ? '刷新中…' : '刷新' }}
      </button>
    </div>
    <p class="section-hint">
      后端服务健康、资源占用与活跃工作流概况（每 60 秒自动刷新；页面隐藏时暂停）。
    </p>

    <p v-if="error" class="error">{{ error }}</p>

    <!-- ── 总体健康 + 资源占用 ─────────────────────────────────────── -->
    <div v-if="status" class="overview-card">
      <div class="overview-row">
        <div class="summary-chip" :class="healthClass(status.overall_health)">
          <span class="health-symbol" :title="HEALTH_TITLE[status.overall_health]">{{
            HEALTH_SYMBOL[status.overall_health]
          }}</span>
          <span class="health-label">总体 {{ HEALTH_TITLE[status.overall_health] }}</span>
        </div>
        <div class="summary-meta">
          <span>环境：{{ status.environment }}</span>
          <span>活跃运行：{{ status.active_run_count }}</span>
          <span>服务：{{ status.services?.length ?? 0 }}</span>
          <span>更新：{{ formatTime(status.updated_at) }}</span>
        </div>
      </div>
      <div
        v-if="serviceCount.ok || serviceCount.busy || serviceCount.degraded || serviceCount.offline"
        class="health-strip"
      >
        <span
          v-for="h in ['ok', 'busy', 'degraded', 'offline'] as ServiceHealth[]"
          v-show="serviceCount[h] > 0"
          :key="h"
          class="strip-chip"
          :class="healthClass(h)"
        >
          {{ HEALTH_SYMBOL[h] }} {{ HEALTH_TITLE[h] }} ×{{ serviceCount[h] }}
        </span>
      </div>
    </div>

    <SystemResourceMetrics v-if="status" />

    <!-- ── 后端服务列表 ────────────────────────────────────────────── -->
    <ul v-if="orderedServices.length" class="service-list">
      <li v-for="svc in orderedServices" :key="svc.service_name" class="service-item">
        <div
          class="service-row"
          @click="detailEntries(svc).length && toggleExpand(svc.service_name)"
        >
          <span class="service-name">
            {{ svc.service_name }}
            <span
              v-if="detailEntries(svc).length"
              class="expand-hint"
              :class="{ expanded: expanded.has(svc.service_name) }"
              >▸</span
            >
          </span>
          <span
            class="health-badge"
            :class="healthClass(svc.health)"
            :title="HEALTH_TITLE[svc.health]"
          >
            {{ HEALTH_SYMBOL[svc.health] }}
          </span>
        </div>
        <p class="service-message">{{ svc.message }}</p>
        <p class="service-time">更新：{{ formatTime(svc.updated_at) }}</p>
        <ul v-if="expanded.has(svc.service_name)" class="detail-list">
          <li v-for="[k, v] in detailEntries(svc)" :key="k" class="detail-row">
            <span class="detail-key">{{ k }}</span>
            <code class="detail-value">{{ formatDetailValue(v) }}</code>
          </li>
        </ul>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.settings-section {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.section-title {
  margin: 0;
  font-size: 0.9rem;
  color: #e8f3fc;
}

.section-hint {
  margin: 0;
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}

.refresh-btn {
  border: 1px solid rgba(90, 213, 255, 0.25);
  border-radius: 0.45rem;
  padding: 0.3rem 0.6rem;
  background: rgba(10, 132, 255, 0.12);
  color: var(--accent);
  cursor: pointer;
  font: inherit;
  font-size: var(--font-size-caption);
}

.refresh-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error {
  margin: 0;
  color: #ffb4a8;
  font-size: var(--font-size-caption);
}

/* ── 总体健康 ────────────────────────────────────────────────────── */
.overview-card {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.65rem 0.75rem;
  border-radius: 0.55rem;
  border: 1px solid rgba(136, 192, 255, 0.12);
  background: rgba(4, 12, 23, 0.45);
}

.overview-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.summary-chip {
  display: inline-flex;
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
  font-size: var(--font-size-caption);
  font-weight: 600;
  gap: 0.35rem;
  align-items: center;
}

.summary-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem;
  color: var(--text-secondary);
  font-size: var(--font-size-caption);
}

.health-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.strip-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.12rem 0.45rem;
  border-radius: 999px;
  font-size: var(--font-size-caption);
  border: 1px solid transparent;
}

/* ── 服务列表 ────────────────────────────────────────────────────── */
.service-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}

.service-item {
  padding: 0.6rem 0.75rem;
  border-radius: 0.55rem;
  border: 1px solid rgba(136, 192, 255, 0.1);
  background: rgba(4, 12, 23, 0.3);
}

.service-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  cursor: pointer;
  user-select: none;
}

.service-name {
  font-size: var(--font-size-caption);
  color: var(--text-primary);
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
}

.expand-hint {
  display: inline-block;
  font-size: var(--font-size-caption);
  color: var(--text-faint);
  transition: transform 0.15s ease;
}

.expand-hint.expanded {
  transform: rotate(90deg);
}

.health-badge,
.summary-chip {
  border: 1px solid transparent;
}

.health-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 1.35rem;
  padding: 0.15rem 0.35rem;
  border-radius: 999px;
  font-size: var(--font-size-caption);
  line-height: 1;
}

.health-symbol {
  font-size: var(--font-size-caption);
  line-height: 1;
}

.health-label {
  font-size: var(--font-size-caption);
}

.health-ok {
  background: rgba(114, 255, 207, 0.12);
  color: var(--success);
  border-color: rgba(114, 255, 207, 0.2);
}

.health-busy {
  background: rgba(255, 211, 138, 0.12);
  color: #ffd38a;
  border-color: rgba(255, 196, 120, 0.2);
}

.health-degraded {
  background: rgba(255, 180, 80, 0.12);
  color: var(--accent-warm);
  border-color: rgba(255, 160, 60, 0.2);
}

.health-offline {
  background: rgba(255, 120, 100, 0.12);
  color: #ffb4a8;
  border-color: rgba(255, 100, 80, 0.25);
}

.service-message {
  margin: 0.25rem 0 0;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}

.service-time {
  margin: 0.15rem 0 0;
  font-size: var(--font-size-caption);
  color: var(--text-faint);
}

/* ── 详情（点击展开） ────────────────────────────────────────────── */
.detail-list {
  list-style: none;
  margin: 0.45rem 0 0;
  padding: 0.45rem 0.55rem 0.1rem;
  border-top: 1px dashed rgba(136, 192, 255, 0.12);
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.detail-row {
  display: flex;
  gap: 0.5rem;
  font-size: var(--font-size-caption);
}

.detail-key {
  flex: 0 0 8.5rem;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-value {
  flex: 1;
  color: #c9dbea;
  word-break: break-all;
  font-family: 'Cascadia Code', Consolas, monospace;
}
</style>
