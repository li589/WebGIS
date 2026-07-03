<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'

import { resolveDemoLayer } from '../app/demo-adapter'
import { demoLayerCatalog, type DemoHotspot, type DemoLayer } from '../app/demo-data'
import FloatingPanelFrame from '../components/FloatingPanelFrame.vue'
import InfoPanel from '../components/InfoPanel.vue'
import LayerSidebar from '../components/LayerSidebar.vue'
import MapCanvas from '../components/MapCanvas.vue'
import ModeToolbar from '../components/ModeToolbar.vue'
import ScreenshotExport from '../components/ScreenshotExport.vue'
import TimelineScrubber from '../components/TimelineScrubber.vue'
import type { TileSourceId } from '../stores/ui'
import { useUiStore } from '../stores/ui'
import { useLayersStore } from '../stores/layers'

const uiStore = useUiStore()
const layersStore = useLayersStore()

const { tileSourceId, currentHour, hourLabel } = storeToRefs(uiStore)
const { selectedLayerDisplay, activeLayerCount, workflowError, isSubmitting } = storeToRefs(layersStore)

const activeLayer = computed(() => selectedLayerDisplay.value ?? buildFallbackActiveLayer(currentHour.value))
const activeLayerId = ref('wind')

const viewLabel = computed(() => '2D 主视图')
const stageLabel = computed(() => '2D-first Demo')
const supportedLayerCount = computed(() => demoLayerCatalog.length)
const visibleHotspots = ref<DemoHotspot[]>([])
const mapCanvasRef = ref<InstanceType<typeof MapCanvas> | null>(null)
const screenshotOpen = ref(false)

watch(currentHour, (hour) => {
  layersStore.setCurrentHour(hour)
}, { immediate: true })

const timelineSegments = computed(() => {
  void currentHour.value
  return Array.from({ length: 8 }, (_, index) => {
    const hour = index * 3
    const snapshot: DemoLayer = resolveDemoLayer(activeLayerId.value, hour)
    return {
      hour,
      label: `${String(hour).padStart(2, '0')}:00`,
      state: snapshot.availabilityState,
      availabilityLabel: snapshot.availabilityLabel,
    }
  })
})

function handleTileSourceChange(sourceId: TileSourceId) {
  uiStore.setTileSource(sourceId)
}

function handleLayerSelect(layerId: string) {
  layersStore.selectLayer(layerId)
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

function handleOpenScreenshot() {
  screenshotOpen.value = true
}

function handleCloseScreenshot() {
  screenshotOpen.value = false
}

async function handleRunWorkflow(catalogId: string) {
  try {
    await layersStore.runWorkflowForCatalog(catalogId)
  } catch (error) {
    console.error('[DashboardView] workflow submit failed', error)
  }
}

function buildFallbackActiveLayer(hour: number): ActiveLayerDisplay {
  const demo = resolveDemoLayer('wind', hour)
  return {
    instanceId: '',
    catalogId: 'wind',
    name: demo.name,
    category: demo.category,
    summary: demo.summary,
    metricLabel: demo.metricLabel,
    metricValue: demo.metricValue,
    trendLabel: demo.trendLabel,
    statusLabel: demo.statusLabel,
    updateLabel: demo.updateLabel,
    sourceLabel: demo.sourceLabel,
    confidenceLabel: demo.confidenceLabel,
    accentColor: demo.accentColor,
    accentGlow: demo.accentGlow,
    chipTone: demo.chipTone,
    availabilityState: demo.availabilityState,
    availabilityLabel: demo.availabilityLabel,
    availabilityDescription: demo.availabilityDescription,
    observationTimeLabel: demo.observationTimeLabel,
    missingFieldsLabel: demo.missingFieldsLabel,
    hotspots: demo.hotspots,
    isAdminBoundary: false,
    visible: true,
    opacity: 1,
    order: 0,
    dataState: 'demo',
  }
}
</script>

<template>
  <main class="dashboard">
    <section class="map-shell">
      <MapCanvas
        ref="mapCanvasRef"
        :tile-source-id="tileSourceId"
        :current-hour="currentHour"
        :hour-label="hourLabel"
        @visible-hotspots-change="handleVisibleHotspotsChange"
      />

      <div class="overlay overlay-top">
        <ModeToolbar
          :tile-source-id="tileSourceId"
          :active-layer="activeLayer"
          :hour-label="hourLabel"
          :supported-layer-count="supportedLayerCount"
          :active-layer-count="activeLayerCount"
          @change-tile-source="handleTileSourceChange"
          @open-screenshot="handleOpenScreenshot"
        />
      </div>

      <div class="overlay overlay-left">
        <FloatingPanelFrame
          panel-label="图层"
          panel-key="layers"
          :max-offset-x="100"
          :max-offset-y="110"
          :default-width="290"
          :min-width="240"
          :max-width="400"
        >
          <LayerSidebar
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
          :default-width="300"
        >
          <InfoPanel
            :view-label="viewLabel"
            :active-layer="activeLayer"
            :hour-label="hourLabel"
            :stage-label="stageLabel"
            :visible-hotspots="visibleHotspots"
            :selected-layer="selectedLayerDisplay"
            :is-submitting="isSubmitting"
            :workflow-error="workflowError"
            @run-workflow="handleRunWorkflow"
          />
        </FloatingPanelFrame>
      </div>

      <div class="overlay overlay-bottom">
        <FloatingPanelFrame
          panel-label="时间轴"
          panel-key="timeline"
          :max-offset-x="80"
          :max-offset-y="40"
          :resizable="false"
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

    <ScreenshotExport
      v-if="screenshotOpen"
      :map-stage-el="mapCanvasRef?.getMapStageElement() ?? null"
      :active-layer-name="activeLayer.name"
      :hour-label="hourLabel"
      @close="handleCloseScreenshot"
    />
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
  z-index: 24;
  pointer-events: none;
}

.overlay :deep(*) {
  pointer-events: auto;
}

.overlay-top {
  top: 0.8rem;
  left: 0.8rem;
  right: 0.8rem;
  z-index: 20;
}

.overlay-left {
  top: 9.5rem;
  left: 0.8rem;
  width: min(18rem, calc(100vw - 1.6rem));
}

.overlay-right {
  top: 6.2rem;
  right: 0.8rem;
  width: min(13.2rem, calc(100vw - 1.6rem));
}

.overlay-bottom {
  left: 50%;
  bottom: 0.8rem;
  width: min(42rem, calc(100vw - 1.6rem));
  transform: translateX(-50%);
  height: min-content;
}

@media (max-width: 1100px) {
  .overlay-left,
  .overlay-right {
    top: auto;
    bottom: 7.4rem;
    width: min(14.1rem, calc(100vw - 1.5rem));
  }

  .overlay-left {
    left: 0.75rem;
    width: min(16rem, calc(100vw - 1.5rem));
  }

  .overlay-right {
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
