<script setup lang="ts">
import { onErrorCaptured, ref } from 'vue'

import { useLogStore } from '../stores/log'

const errorMessage = ref<string | null>(null)

onErrorCaptured((err, _instance, info) => {
  const msg = err instanceof Error ? err.message : String(err)
  errorMessage.value = msg
  useLogStore().logOperation('client-render-error', '页面渲染异常', `${msg}\n${info}`)
  return false
})

function reloadPage() {
  window.location.reload()
}
</script>

<template>
  <div v-if="errorMessage" class="error-boundary">
    <div class="error-card">
      <h2>页面出现问题</h2>
      <p>当前视图渲染失败，可尝试刷新页面。若持续出现，请导出系统日志并联系管理员。</p>
      <p class="detail">{{ errorMessage }}</p>
      <button type="button" class="reload-btn" @click="reloadPage">刷新页面</button>
    </div>
  </div>
  <slot v-else />
</template>

<style scoped>
.error-boundary {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 2rem;
  background: var(--surface-base);
  color: var(--text-primary);
}

.error-card {
  width: min(32rem, 100%);
  padding: 1.75rem;
  border-radius: 0.9rem;
  border: 1px solid var(--danger-border);
  background: var(--surface-sunken);
}

h2 {
  margin: 0 0 0.75rem;
  color: var(--danger);
}

p {
  margin: 0 0 0.75rem;
  color: var(--text-primary);
  font-size: 0.9rem;
}

.detail {
  font-family: var(--font-mono);
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
  word-break: break-word;
}

.reload-btn {
  margin-top: 0.5rem;
  border: 1px solid var(--danger-border);
  border-radius: 0.5rem;
  padding: 0.5rem 1rem;
  background: var(--danger-surface);
  color: var(--warning);
  cursor: pointer;
  font: inherit;
}
</style>
