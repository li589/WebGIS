<script setup lang="ts">
import type { MapMode } from '../stores/ui'

defineProps<{
  currentMode: MapMode
}>()

const emit = defineEmits<{
  changeMode: [mode: MapMode]
}>()
</script>

<template>
  <header class="toolbar">
    <div>
      <p class="eyebrow">WebGIS Learning Demo</p>
      <h1>综合地理信息展示前端壳子</h1>
      <p class="subtitle">先把 2D/3D 模式、图层控制、时间轴和结果面板组织起来，再逐步接入真实地图与数据。</p>
    </div>

    <div class="mode-switch">
      <button
        class="mode-button"
        :class="{ active: currentMode === '2d' }"
        @click="emit('changeMode', '2d')"
      >
        2D 地图
      </button>
      <button
        class="mode-button"
        :class="{ active: currentMode === '3d' }"
        @click="emit('changeMode', '3d')"
      >
        3D 地球
      </button>
    </div>
  </header>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: flex-start;
  padding: 0.95rem 1rem;
  border: 1px solid rgba(136, 192, 255, 0.14);
  border-radius: 1rem;
  background: rgba(8, 18, 33, 0.72);
  backdrop-filter: blur(14px);
}

.eyebrow {
  margin: 0 0 0.35rem;
  color: #88c0ff;
  font-size: 0.72rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  font-size: clamp(1.2rem, 2vw, 1.65rem);
  color: #f5fbff;
}

.subtitle {
  max-width: 38rem;
  margin: 0.45rem 0 0;
  color: #93a4b8;
  line-height: 1.45;
  font-size: 0.9rem;
}

.mode-switch {
  display: inline-flex;
  gap: 0.5rem;
  padding: 0.3rem;
  border: 1px solid rgba(136, 192, 255, 0.18);
  border-radius: 999px;
  background: rgba(4, 12, 23, 0.82);
}

.mode-button {
  border: none;
  border-radius: 999px;
  padding: 0.58rem 0.9rem;
  background: transparent;
  color: #a9bdd0;
  cursor: pointer;
  font: inherit;
  font-size: 0.9rem;
  transition: background-color 0.2s ease, color 0.2s ease, transform 0.2s ease;
}

.mode-button:hover {
  color: #f5fbff;
  transform: translateY(-1px);
}

.mode-button.active {
  background: linear-gradient(135deg, #0a84ff, #3cb4ff);
  color: #081221;
  font-weight: 700;
}

@media (max-width: 900px) {
  .toolbar {
    flex-direction: column;
    padding: 0.85rem;
  }

  .subtitle {
    font-size: 0.84rem;
  }
}
</style>
