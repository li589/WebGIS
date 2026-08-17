<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { resolveApiUrl } from '../services/_http'

const PROBE_INTERVAL_MS = 30_000
const PROBE_TIMEOUT_MS = 8_000
// 连续失败达到该次数才判定断联：后端高负载时单次探测超时/慢响应不应立即报断联
const OFFLINE_FAILURE_THRESHOLD = 3

const offline = ref(false)
const checking = ref(false)
let timer: ReturnType<typeof setInterval> | null = null
let consecutiveFailures = 0
let inFlight = false

async function probeHealth(): Promise<boolean> {
  if (inFlight) return !offline.value
  inFlight = true
  checking.value = true
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS)
  try {
    const resp = await fetch(resolveApiUrl('/health'), {
      method: 'GET',
      credentials: 'include',
      cache: 'no-store',
      signal: controller.signal,
    })
    if (resp.ok) {
      consecutiveFailures = 0
      offline.value = false
      return true
    }
    throw new Error(`health probe returned ${resp.status}`)
  } catch {
    consecutiveFailures += 1
    if (consecutiveFailures >= OFFLINE_FAILURE_THRESHOLD) offline.value = true
    return false
  } finally {
    clearTimeout(timeout)
    checking.value = false
    inFlight = false
  }
}

function startPolling(): void {
  stopPolling()
  void probeHealth()
  timer = setInterval(() => {
    if (!document.hidden) void probeHealth()
  }, PROBE_INTERVAL_MS)
}

function stopPolling(): void {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

function handleVisibilityChange(): void {
  if (document.hidden) {
    stopPolling()
  } else {
    startPolling()
  }
}

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibilityChange)
  startPolling()
})

onBeforeUnmount(() => {
  stopPolling()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
</script>

<template>
  <div v-if="offline" class="connectivity-banner" role="alert">
    <span>后端服务不可用，部分功能可能无法使用。</span>
    <button type="button" :disabled="checking" @click="probeHealth">
      {{ checking ? '检测中…' : '重试' }}
    </button>
  </div>
</template>

<style scoped>
.connectivity-banner {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: var(--z-debug);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  padding: 0.45rem 1rem;
  background: rgba(120, 24, 24, 0.92);
  border-bottom: 1px solid var(--danger-border);
  color: var(--danger);
  font-size: 0.82rem;
}

button {
  border: 1px solid rgba(255, 200, 176, 0.4);
  border-radius: 0.4rem;
  padding: 0.2rem 0.55rem;
  background: var(--surface-hover);
  color: inherit;
  cursor: pointer;
  font: inherit;
}

button:disabled {
  opacity: 0.6;
  cursor: wait;
}
</style>
