<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useLogStore } from '../stores/log'
import { BRAND } from '../ui-copy'

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
      <button type="button" class="home-btn" @click="goHome">返回首页</button>
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
  color: #d8e6f5;
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
  color: #5ad5ff;
  letter-spacing: 0.08em;
}

h1 {
  margin: 0.5rem 0 0.75rem;
  font-size: 1.35rem;
}

.hint {
  margin: 0;
  color: #9fb6cc;
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

.home-btn {
  border: 1px solid rgba(90, 213, 255, 0.35);
  border-radius: 0.55rem;
  padding: 0.55rem 1.1rem;
  background: rgba(10, 132, 255, 0.18);
  color: #5ad5ff;
  cursor: pointer;
  font: inherit;
  font-size: 0.9rem;
}

.home-btn:hover {
  background: rgba(10, 132, 255, 0.28);
}
</style>
