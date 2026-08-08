<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { fetchRuntimeStatus } from '../../services/settings-api'
import type { BackendServiceStatus, RuntimeStatusResponse } from '../../types/api-reexports'
import type { components } from '../../types/api-contracts'

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

onMounted(() => {
  void refresh()
  timer = setInterval(() => {
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
    <p class="section-hint">后端运行时服务健康与活跃工作流概况（每 60 秒自动刷新）。</p>

    <p v-if="error" class="error">{{ error }}</p>

    <div v-if="status" class="status-summary">
      <div class="summary-chip" :class="healthClass(status.overall_health)">
        <span class="health-symbol" :title="HEALTH_TITLE[status.overall_health]">{{
          HEALTH_SYMBOL[status.overall_health]
        }}</span>
        <span class="health-label">总体</span>
      </div>
      <div class="summary-meta">
        <span>环境：{{ status.environment }}</span>
        <span>活跃运行：{{ status.active_run_count }}</span>
        <span>更新：{{ formatTime(status.updated_at) }}</span>
      </div>
    </div>

    <ul v-if="status?.services?.length" class="service-list">
      <li v-for="svc in status.services as BackendServiceStatus[]" :key="svc.service_name">
        <div class="service-row">
          <span class="service-name">{{ svc.service_name }}</span>
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
  font-size: 0.68rem;
  color: #8aa8bf;
}

.refresh-btn {
  border: 1px solid rgba(90, 213, 255, 0.25);
  border-radius: 0.45rem;
  padding: 0.3rem 0.6rem;
  background: rgba(10, 132, 255, 0.12);
  color: #5ad5ff;
  cursor: pointer;
  font: inherit;
  font-size: 0.62rem;
}

.error {
  margin: 0;
  color: #ffb4a8;
  font-size: 0.65rem;
}

.status-summary {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  padding: 0.65rem 0.75rem;
  border-radius: 0.55rem;
  border: 1px solid rgba(136, 192, 255, 0.12);
  background: rgba(4, 12, 23, 0.45);
}

.summary-chip {
  display: inline-flex;
  align-self: flex-start;
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
  font-size: 0.62rem;
  font-weight: 600;
  gap: 0.35rem;
  align-items: center;
}

.summary-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem;
  color: #9fb6cc;
  font-size: 0.6rem;
}

.service-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}

.service-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.service-name {
  font-size: 0.72rem;
  color: #d8e6f5;
  font-weight: 600;
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
  font-size: 0.72rem;
  line-height: 1;
}

.health-symbol {
  font-size: 0.72rem;
  line-height: 1;
}

.health-label {
  font-size: 0.62rem;
}

.health-ok {
  background: rgba(114, 255, 207, 0.12);
  color: #9ff8cf;
  border-color: rgba(114, 255, 207, 0.2);
}

.health-busy {
  background: rgba(255, 211, 138, 0.12);
  color: #ffd38a;
  border-color: rgba(255, 196, 120, 0.2);
}

.health-degraded {
  background: rgba(255, 180, 80, 0.12);
  color: #ffc878;
  border-color: rgba(255, 160, 60, 0.2);
}

.health-offline {
  background: rgba(255, 120, 100, 0.12);
  color: #ffb4a8;
  border-color: rgba(255, 100, 80, 0.25);
}

.service-message {
  margin: 0.25rem 0 0;
  font-size: 0.62rem;
  color: #9fb6cc;
}

.service-time {
  margin: 0.15rem 0 0;
  font-size: 0.56rem;
  color: #6e8ba0;
}
</style>
