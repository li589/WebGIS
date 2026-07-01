<script setup lang="ts">
import type { DemoLayer } from '../app/demo-data'

const props = defineProps<{
  layers: DemoLayer[]
  activeLayerId: string
  currentHourLabel: string
}>()

const emit = defineEmits<{
  selectLayer: [layerId: string]
}>()
</script>

<template>
  <aside class="panel">
    <div class="panel-topline">
      <div class="panel-header">
        <div>
          <h2>图层</h2>
          <p class="panel-subtitle">Demo 图层目录</p>
        </div>
        <span class="badge">{{ layers.length }}</span>
      </div>
      <div class="panel-tip-row">
        <span class="mode-chip">2D Demo</span>
        <span class="panel-tip">{{ currentHourLabel }}</span>
      </div>
    </div>

    <ul class="dataset-list">
      <li v-for="layer in layers" :key="layer.id">
        <button
          class="dataset-button"
          :class="{ active: layer.id === activeLayerId }"
          :style="{
            '--accent-color': layer.accentColor,
            '--accent-glow': layer.accentGlow,
            '--chip-tone': layer.chipTone,
          }"
          @click="emit('selectLayer', layer.id)"
        >
          <div class="dataset-title-row">
            <strong>{{ layer.name }}</strong>
            <span class="dataset-category">{{ layer.category }}</span>
          </div>
          <p v-if="layer.id === activeLayerId" class="dataset-summary">{{ layer.summary }}</p>
          <div class="dataset-meta">
            <span>{{ layer.metricValue }}</span>
            <span class="availability-chip" :class="`availability-${layer.availabilityState}`">
              {{ layer.availabilityLabel }}
            </span>
          </div>
        </button>
      </li>
    </ul>

    <p class="panel-footnote">拖动或折叠查看。</p>
  </aside>
</template>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
  gap: 0.56rem;
  padding: 0.58rem;
  border: 1px solid rgba(148, 163, 184, 0.15);
  border-radius: 0.88rem;
  background: linear-gradient(180deg, rgba(13, 21, 36, 0.42), rgba(8, 15, 28, 0.3));
  backdrop-filter: blur(18px);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.03),
    0 12px 26px rgba(1, 8, 16, 0.14);
  max-height: min(31rem, calc(100vh - 10rem));
  overflow: hidden;
}

.panel-topline {
  display: grid;
  gap: 0.46rem;
  padding: 0.12rem;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.55rem;
}

h2,
h3 {
  margin: 0;
  color: #eef6ff;
  font-size: 0.76rem;
}

.panel-subtitle {
  margin: 0.14rem 0 0;
  color: #7f93a9;
  font-size: 0.62rem;
}

.badge {
  min-width: 1.65rem;
  padding: 0.18rem 0.34rem;
  border-radius: 999px;
  background: rgba(103, 212, 255, 0.14);
  color: #8fe7ff;
  text-align: center;
  font-size: 0.58rem;
}

.panel-tip,
.panel-footnote {
  margin: 0;
  color: #8ea3b8;
  line-height: 1.35;
  font-size: 0.64rem;
}

.panel-tip-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.45rem;
}

.mode-chip {
  width: fit-content;
  padding: 0.18rem 0.38rem;
  border-radius: 999px;
  background: rgba(8, 18, 33, 0.44);
  border: 1px solid rgba(136, 192, 255, 0.12);
  color: #dbeeff;
  font-size: 0.58rem;
}

.dataset-list {
  display: grid;
  gap: 0.3rem;
  list-style: none;
  padding: 0;
  margin: 0;
  overflow: auto;
  padding: 0 0.08rem 0 0;
}

.dataset-button {
  width: 100%;
  text-align: left;
  display: grid;
  gap: 0.26rem;
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: 0.72rem;
  padding: 0.46rem 0.52rem;
  background:
    linear-gradient(180deg, rgba(8, 18, 33, 0.5), rgba(8, 18, 33, 0.38)),
    rgba(8, 18, 33, 0.4);
  color: #d8e4ef;
  cursor: pointer;
  font: inherit;
  font-size: 0.72rem;
  transition:
    border-color 0.2s ease,
    background-color 0.2s ease,
    transform 0.2s ease,
    box-shadow 0.2s ease;
}

.dataset-button:hover {
  border-color: color-mix(in srgb, var(--accent-color) 44%, rgba(136, 192, 255, 0.4));
  transform: translateY(-2px);
  box-shadow: 0 14px 24px -18px var(--accent-glow);
}

.dataset-button.active {
  background:
    linear-gradient(135deg, color-mix(in srgb, var(--accent-color) 14%, rgba(10, 22, 38, 0.92)), rgba(8, 18, 33, 0.6)),
    rgba(8, 18, 33, 0.7);
  border-color: color-mix(in srgb, var(--accent-color) 55%, rgba(96, 181, 255, 0.55));
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.02),
    0 22px 34px -26px var(--accent-glow);
}

.dataset-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.42rem;
}

.dataset-title-row strong {
  color: #f3fbff;
  font-size: 0.74rem;
}

.dataset-category {
  padding: 0.12rem 0.34rem;
  border-radius: 999px;
  background: var(--chip-tone);
  color: #d9effd;
  font-size: 0.54rem;
}

.dataset-summary {
  margin: 0;
  color: #90a4b9;
  line-height: 1.28;
  font-size: 0.62rem;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.dataset-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.4rem;
  color: #dfeeff;
  font-size: 0.6rem;
}

.availability-chip {
  padding: 0.08rem 0.28rem;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.12);
  background: rgba(148, 163, 184, 0.08);
}

.availability-ready {
  color: #9ff8cf;
  border-color: rgba(114, 255, 207, 0.2);
  background: rgba(114, 255, 207, 0.1);
}

.availability-partial {
  color: #ffd38a;
  border-color: rgba(255, 196, 120, 0.18);
  background: rgba(255, 196, 120, 0.08);
}

.availability-empty {
  color: #cbb8ff;
  border-color: rgba(187, 137, 255, 0.18);
  background: rgba(187, 137, 255, 0.08);
}

.panel-footnote {
  padding: 0.12rem;
  color: #7f95aa;
}

code {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}
</style>
