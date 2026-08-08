<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { resolveApiUrl } from '../services/_http'

const offline = ref(false)
const checking = ref(false)
let timer: ReturnType<typeof setInterval> | null = null

async function probeHealth(): Promise<boolean> {
  checking.value = true
  try {
    const resp = await fetch(resolveApiUrl('/health'), {
      method: 'GET',
      credentials: 'include',
      cache: 'no-store',
    })
    const ok = resp.ok
    offline.value = !ok
    return ok
  } catch {
    offline.value = true
    return false
  } finally {
    checking.value = false
  }
}

onMounted(() => {
  void probeHealth()
  timer = setInterval(() => {
    void probeHealth()
  }, 30_000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
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
  z-index: 12000;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  padding: 0.45rem 1rem;
  background: rgba(120, 24, 24, 0.92);
  border-bottom: 1px solid rgba(255, 140, 100, 0.35);
  color: #ffd8cc;
  font-size: 0.82rem;
}

button {
  border: 1px solid rgba(255, 200, 176, 0.4);
  border-radius: 0.4rem;
  padding: 0.2rem 0.55rem;
  background: rgba(255, 255, 255, 0.08);
  color: inherit;
  cursor: pointer;
  font: inherit;
}

button:disabled {
  opacity: 0.6;
  cursor: wait;
}
</style>
