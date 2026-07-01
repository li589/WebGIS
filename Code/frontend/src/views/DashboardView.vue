<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'

import { resolveDemoLayer, resolveDemoLayers } from '../app/demo-adapter'
import { demoLayerCatalog, type DemoHotspot, type DemoLayer } from '../app/demo-data'
import FloatingPanelFrame from '../components/FloatingPanelFrame.vue'
import InfoPanel from '../components/InfoPanel.vue'
import LayerSidebar from '../components/LayerSidebar.vue'
import MapCanvas from '../components/MapCanvas.vue'
import ModeToolbar from '../components/ModeToolbar.vue'
import TimelineScrubber from '../components/TimelineScrubber.vue'
import type { BasemapMode } from '../stores/ui'
import { useUiStore } from '../stores/ui'

const uiStore = useUiStore()
const { basemapMode, activeLayer, activeLayerId, currentHour, hourLabel } = storeToRefs(uiStore)

const viewLabel = computed(() => '2D 主视图')
const stageLabel = computed(() => '2D-first Demo')
const supportedLayerCount = computed(() => demoLayerCatalog.length)
const demoLayers = computed(() => resolveDemoLayers(currentHour.value))
const visibleHotspots = ref<DemoHotspot[]>(activeLayer.value.hotspots.slice(0, 3))
const timelineSegments = computed(() =>
  Array.from({ length: 8 }, (_, index) => {
    const hour = index * 3
    const snapshot: DemoLayer = resolveDemoLayer(activeLayerId.value, hour)
    return {
      hour,
      label: `${String(hour).padStart(2, '0')}:00`,
      state: snapshot.availabilityState,
      availabilityLabel: snapshot.availabilityLabel,
    }
  }),
)

function handleBasemapChange(mode: BasemapMode) {
  uiStore.setBasemap(mode)
}

function handleLayerSelect(layerId: string) {
  uiStore.setLayer(layerId)
}

function handleTimelineStep(delta: number) {
  uiStore.stepHour(delta)
}

function handleTimelineChange(hour: number) {
  uiStore.setHour(hour)
}

function handleVisibleHotspotsChange(hotspots: DemoHotspot[]) {
  visibleHotspots.value = hotspots
}

watch(
  activeLayer,
  (layer) => {
    visibleHotspots.value = layer.hotspots.slice(0, 3)
  },
  { immediate: true },
)
</script>

<template>
  <main class="dashboard">
    <section class="map-shell">
      <MapCanvas
        :basemap-mode="basemapMode"
        :active-layer="activeLayer"
        :current-hour="currentHour"
        :hour-label="hourLabel"
        @visible-hotspots-change="handleVisibleHotspotsChange"
      />

      <div class="overlay overlay-top">
        <ModeToolbar
          :basemap-mode="basemapMode"
          :active-layer="activeLayer"
          :hour-label="hourLabel"
          :supported-layer-count="supportedLayerCount"
          @change-basemap="handleBasemapChange"
        />
      </div>

      <div class="overlay overlay-left">
        <FloatingPanelFrame
          panel-label="图层"
          panel-key="layers"
          :max-offset-x="100"
          :max-offset-y="110"
        >
          <LayerSidebar
            :layers="demoLayers"
            :active-layer-id="activeLayerId"
            :current-hour-label="hourLabel"
            @select-layer="handleLayerSelect"
          />
        </FloatingPanelFrame>
      </div>

      <div class="overlay overlay-right">
        <FloatingPanelFrame
          panel-label="分析"
          panel-key="analysis"
          :max-offset-x="100"
          :max-offset-y="110"
        >
          <InfoPanel
            :view-label="viewLabel"
            :active-layer="activeLayer"
            :hour-label="hourLabel"
            :stage-label="stageLabel"
            :visible-hotspots="visibleHotspots"
          />
        </FloatingPanelFrame>
      </div>

      <div class="overlay overlay-bottom">
        <FloatingPanelFrame
          panel-label="时间轴"
          panel-key="timeline"
          :max-offset-x="80"
          :max-offset-y="40"
        >
          <TimelineScrubber
            :current-hour="currentHour"
            :hour-label="hourLabel"
            :accent-color="activeLayer.accentColor"
            :availability-label="activeLayer.availabilityLabel"
            :observation-time-label="activeLayer.observationTimeLabel"
            :timeline-segments="timelineSegments"
            @step="handleTimelineStep"
            @change-hour="handleTimelineChange"
          />
        </FloatingPanelFrame>
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
  isolation: isolate;
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
  top: 0.8rem;
  left: 0.8rem;
  right: 0.8rem;
}

.overlay-left {
  top: 5.8rem;
  left: 0.8rem;
  width: min(15.4rem, calc(100vw - 1.6rem));
}

.overlay-right {
  top: 5.8rem;
  right: 0.8rem;
  width: min(14.4rem, calc(100vw - 1.6rem));
}

.overlay-bottom {
  left: 50%;
  bottom: 0.8rem;
  width: min(42rem, calc(100vw - 1.6rem));
  transform: translateX(-50%);
}

@media (max-width: 1100px) {
  .overlay-left,
  .overlay-right {
    top: auto;
    width: min(14.1rem, calc(100vw - 1.5rem));
  }

  .overlay-left {
    bottom: 7.4rem;
    left: 0.75rem;
  }

  .overlay-right {
    bottom: 7.4rem;
    right: 0.75rem;
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
