<script setup lang="ts">
import type { DemoLayer } from '../app/demo-data'
import type { BasemapMode } from '../stores/ui'

defineProps<{
  basemapMode: BasemapMode
  activeLayer: DemoLayer
  hourLabel: string
  supportedLayerCount: number
}>()

const emit = defineEmits<{
  changeBasemap: [mode: BasemapMode]
}>()
</script>

<template>
  <header class="toolbar">
    <div class="brand">
      <div class="brand-mark"></div>
      <div class="brand-copy">
        <p class="eyebrow">GeoFlow</p>
        <h1>综合地理态势</h1>
        <p class="subtitle">2D 演示台</p>
      </div>
    </div>

    <div class="toolbar-main">
      <div class="toolbar-strip">
        <div class="basemap-switch">
          <button
            class="basemap-button"
            :class="{ active: basemapMode === 'admin' }"
            @click="emit('changeBasemap', 'admin')"
          >
            行政区
          </button>
          <button
            class="basemap-button"
            :class="{ active: basemapMode === 'osm' }"
            @click="emit('changeBasemap', 'osm')"
          >
            OSM
          </button>
          <button
            class="basemap-button"
            :class="{ active: basemapMode === 'hybrid' }"
            @click="emit('changeBasemap', 'hybrid')"
          >
            混合
          </button>
        </div>

        <div class="quick-stats">
          <div class="stat-pill">
            <span class="label">时间</span>
            <strong>{{ hourLabel }}</strong>
          </div>
          <div class="stat-pill compact">
            <span class="label">状态</span>
            <strong>{{ activeLayer.availabilityLabel }}</strong>
          </div>
        </div>
      </div>

      <div class="toolbar-strip">
        <div class="status-chip">2D-first</div>
        <div class="status-chip">{{ activeLayer.name }}</div>
        <div class="status-chip" :class="`availability-${activeLayer.availabilityState}`">
          {{ activeLayer.availabilityLabel }}
        </div>
      </div>
    </div>
  </header>
</template>


<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  gap: 0.8rem;
  align-items: center;
  padding: 0.62rem 0.76rem;
  border: 1px solid rgba(145, 197, 255, 0.14);
  border-radius: 1rem;
  background:
    linear-gradient(180deg, rgba(8, 17, 31, 0.8), rgba(7, 15, 28, 0.72)),
    rgba(8, 18, 33, 0.72);
  backdrop-filter: blur(18px);
  box-shadow:
    0 18px 42px rgba(1, 8, 16, 0.32),
    inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

.brand {
  display: flex;
  align-items: center;
  gap: 0.58rem;
  min-width: 0;
}

.brand-mark {
  width: 1.9rem;
  height: 1.9rem;
  flex: none;
  border-radius: 0.72rem;
  background:
    radial-gradient(circle at 30% 30%, rgba(255, 255, 255, 0.32), transparent 42%),
    linear-gradient(135deg, #5ad5ff, #2f7eff 58%, #7d7dff);
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.06), 0 12px 30px rgba(47, 126, 255, 0.28);
}

.brand-copy {
  min-width: 0;
}

.toolbar-main {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.38rem;
}

.toolbar-strip {
  display: flex;
  align-items: center;
  gap: 0.42rem;
  flex-wrap: wrap;
}

.basemap-switch {
  display: inline-flex;
  gap: 0.22rem;
  padding: 0.18rem;
  border: 1px solid rgba(136, 192, 255, 0.14);
  border-radius: 999px;
  background: rgba(4, 12, 23, 0.82);
}

.eyebrow {
  margin: 0 0 0.18rem;
  color: #88dfff;
  font-size: 0.62rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  font-size: clamp(0.9rem, 1.5vw, 1.18rem);
  color: #f5fbff;
}

.subtitle {
  max-width: 22rem;
  margin: 0.18rem 0 0;
  color: #93a4b8;
  line-height: 1.35;
  font-size: 0.68rem;
}

.quick-stats {
  display: flex;
  gap: 0.28rem;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.stat-pill {
  display: grid;
  gap: 0.15rem;
  min-width: 4rem;
  padding: 0.24rem 0.44rem;
  border-radius: 0.68rem;
  background: rgba(4, 12, 23, 0.42);
  border: 1px solid rgba(136, 192, 255, 0.1);
}

.stat-pill.compact {
  min-width: 3rem;
}

.label {
  color: #7f96ab;
  font-size: 0.52rem;
}

.stat-pill strong {
  color: #eff8ff;
  font-size: 0.62rem;
  font-weight: 600;
}

.status-chip {
  display: inline-flex;
  align-items: center;
  max-width: 8rem;
  padding: 0.24rem 0.46rem;
  border-radius: 999px;
  background: rgba(4, 12, 23, 0.42);
  border: 1px solid rgba(136, 192, 255, 0.1);
  color: #d8e6f5;
  font-size: 0.6rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.availability-ready {
  color: #9ff8cf;
  border-color: rgba(114, 255, 207, 0.18);
  background: rgba(114, 255, 207, 0.1);
}

.availability-partial {
  color: #ffd38a;
  border-color: rgba(255, 196, 120, 0.18);
  background: rgba(255, 196, 120, 0.08);
}

.availability-empty {
  color: #d7c1ff;
  border-color: rgba(187, 137, 255, 0.2);
  background: rgba(187, 137, 255, 0.1);
}

.basemap-button {
  border: none;
  border-radius: 999px;
  padding: 0.28rem 0.52rem;
  background: transparent;
  color: #a9bdd0;
  cursor: pointer;
  font: inherit;
  font-size: 0.64rem;
  transition: background-color 0.2s ease, color 0.2s ease, transform 0.2s ease;
}

.basemap-button:hover {
  color: #f5fbff;
  transform: translateY(-1px);
}

.basemap-button.active {
  background: linear-gradient(135deg, #0a84ff, #3cb4ff);
  color: #081221;
  font-weight: 700;
}

@media (max-width: 900px) {
  .toolbar {
    flex-direction: column;
    align-items: stretch;
    padding: 0.72rem;
  }

  .toolbar-main {
    align-items: stretch;
  }

  .toolbar-strip,
  .quick-stats {
    justify-content: flex-start;
  }

  .basemap-switch {
    align-self: flex-start;
  }
}
</style>
