<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'

import InfoPanel from '../components/InfoPanel.vue'
import LayerSidebar from '../components/LayerSidebar.vue'
import MapCanvas from '../components/MapCanvas.vue'
import ModeToolbar from '../components/ModeToolbar.vue'
import TimelineScrubber from '../components/TimelineScrubber.vue'
import type { MapMode } from '../stores/ui'
import { useUiStore } from '../stores/ui'

const datasets = ['风场', '降水', '温度', '遥感反演', '课题组模型输出']

const uiStore = useUiStore()
const { mapMode, activeDataset, hourLabel } = storeToRefs(uiStore)

const currentModeLabel = computed(() => (mapMode.value === '2d' ? '2D 平面地图模式' : '3D 地球模式'))

function handleModeChange(mode: MapMode) {
  uiStore.setMode(mode)
}

function handleDatasetSelect(dataset: string) {
  uiStore.setDataset(dataset)
}

function handleTimelineStep(delta: number) {
  uiStore.stepHour(delta)
}
</script>

<template>
  <main class="dashboard">
    <section class="map-shell">
      <MapCanvas
        :current-mode="mapMode"
        :active-dataset="activeDataset"
        :hour-label="hourLabel"
      />

      <div class="overlay overlay-top">
        <ModeToolbar :current-mode="mapMode" @change-mode="handleModeChange" />
      </div>

      <div class="overlay overlay-left">
        <LayerSidebar
          :datasets="datasets"
          :active-dataset="activeDataset"
          @select-dataset="handleDatasetSelect"
        />
      </div>

      <div class="overlay overlay-right">
        <InfoPanel
          :current-mode-label="currentModeLabel"
          :active-dataset="activeDataset"
          :hour-label="hourLabel"
        />
      </div>

      <div class="overlay overlay-bottom">
        <TimelineScrubber :hour-label="hourLabel" @step="handleTimelineStep" />
      </div>
    </section>
  </main>
</template>

<style scoped>
.dashboard {
  min-height: calc(100vh - 1.5rem);
}

.map-shell {
  position: relative;
  min-height: calc(100vh - 1.5rem);
  border-radius: 1.4rem;
  overflow: hidden;
}

.overlay {
  position: absolute;
  z-index: 10;
  pointer-events: none;
}

.overlay :deep(*) {
  pointer-events: auto;
}

.overlay-top {
  top: 1rem;
  left: 1rem;
  right: 1rem;
}

.overlay-left {
  top: 8.25rem;
  left: 1rem;
  width: min(22rem, calc(100vw - 2rem));
}

.overlay-right {
  top: 8.25rem;
  right: 1rem;
  width: min(21rem, calc(100vw - 2rem));
}

.overlay-bottom {
  left: 50%;
  bottom: 1rem;
  width: min(40rem, calc(100vw - 2rem));
  transform: translateX(-50%);
}

@media (max-width: 1100px) {
  .overlay-left,
  .overlay-right {
    top: auto;
    width: min(20rem, calc(100vw - 2rem));
  }

  .overlay-left {
    bottom: 8.75rem;
    left: 1rem;
  }

  .overlay-right {
    bottom: 8.75rem;
    right: 1rem;
  }
}

@media (max-width: 820px) {
  .dashboard,
  .map-shell {
    min-height: calc(100vh - 1rem);
  }

  .overlay-top {
    top: 0.75rem;
    left: 0.75rem;
    right: 0.75rem;
  }

  .overlay-left,
  .overlay-right {
    position: static;
    width: auto;
  }

  .overlay-left {
    margin: 8rem 0.75rem 0;
  }

  .overlay-right {
    margin: 0.75rem 0.75rem 0;
  }

  .overlay-bottom {
    left: 0.75rem;
    right: 0.75rem;
    bottom: 0.75rem;
    width: auto;
    transform: none;
  }
}
</style>
