<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useLogStore } from '../stores/log'
import { BRAND } from '../ui-copy'
import AppButton from '../components/ui/AppButton.vue'

const route = useRoute()
const router = useRouter()
const logStore = useLogStore()

const attemptedPath = computed(() => route.fullPath)

onMounted(() => {
  logStore.logOperation('route-not-found', `未找到页面：${attemptedPath.value}`)
})

function goHome() {
  router.replace('/')
}
</script>

<template>
  <div class="not-found-page">
    <div class="not-found-card">
      <p class="code">404</p>
      <h1>页面不存在</h1>
      <p class="hint">请求的地址在 {{ BRAND.shortName }} 中未找到。</p>
      <p class="path" aria-live="polite">{{ attemptedPath }}</p>
      <AppButton variant="primary" @click="goHome">返回首页</AppButton>
    </div>
  </div>
</template>

<style scoped>
.not-found-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 2rem;
  background:
    radial-gradient(ellipse at 50% 0%, rgba(10, 132, 255, 0.12), transparent 55%), #060d18;
  color: var(--text-primary);
}

.not-found-card {
  width: min(28rem, 100%);
  padding: 2rem 1.75rem;
  border-radius: 1rem;
  border: 1px solid rgba(136, 192, 255, 0.14);
  background: rgba(4, 12, 23, 0.82);
  text-align: center;
}

.code {
  margin: 0;
  font-size: 2.5rem;
  font-weight: 700;
  color: var(--accent);
  letter-spacing: 0.08em;
}

h1 {
  margin: 0.5rem 0 0.75rem;
  font-size: 1.35rem;
}

.hint {
  margin: 0;
  color: var(--text-secondary);
  font-size: 0.9rem;
}

.path {
  margin: 1rem 0 1.25rem;
  padding: 0.5rem 0.75rem;
  border-radius: 0.5rem;
  background: rgba(136, 192, 255, 0.06);
  color: #c8dff0;
  font-family: ui-monospace, monospace;
  font-size: 0.82rem;
  word-break: break-all;
}
</style>
