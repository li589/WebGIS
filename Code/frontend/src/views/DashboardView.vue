<script setup lang="ts">
import { computed, defineAsyncComponent, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'

import { resolveDemoLayer } from '../app/demo-adapter'
import { demoLayerCatalog, type DemoHotspot, type DemoLayer } from '../app/demo-data'
import ControlPanel from '../components/ControlPanel.vue'
import InfoPanel from '../components/InfoPanel.vue'
import LayerSidebar from '../components/LayerSidebar.vue'
import MapCanvas from '../components/MapCanvas.vue'
import ModeToolbar from '../components/ModeToolbar.vue'
import TimelinePanel from '../components/TimelinePanel.vue'
import TimelineScrubber from '../components/TimelineScrubber.vue'
import { getWeatherPoint, type WeatherPointResponse } from '../services/runtime-api'
import type { ActiveLayerDisplay } from '../stores/layers/types'
import type { TileSourceId } from '../stores/ui'
import { useUiStore } from '../stores/ui'
import { useLayersStore } from '../stores/layers'

const uiStore = useUiStore()
const layersStore = useLayersStore()

const { tileSourceId, currentHour, hourLabel } = storeToRefs(uiStore)
const { selectedLayerDisplay, activeLayerCount, workflowError, isSubmitting } = storeToRefs(layersStore)

const activeLayer = computed(() => {
  if (selectedLayerDisplay.value) return selectedLayerDisplay.value
  return buildFallbackActiveLayer(currentHour.value)
})

const viewLabel = computed(() => '2D 主视图')
const stageLabel = computed(() => '2D-first Demo')
const supportedLayerCount = computed(() => demoLayerCatalog.length)
const visibleHotspots = ref<DemoHotspot[]>([])
const selectedHotspot = ref<DemoHotspot | null>(null)
const selectedMapPoint = ref<{ lng: number; lat: number } | null>(null)
const pointWeather = ref<WeatherPointResponse | null>(null)
const pointWeatherLoading = ref(false)
const pointWeatherError = ref<string | null>(null)
let pointWeatherRequestToken = 0
const dashboardRef = ref<HTMLElement | null>(null)
const mapShellRef = ref<HTMLElement | null>(null)
const mapCanvasRef = ref<InstanceType<typeof MapCanvas> | null>(null)
const screenshotOpen = ref(false)
const ScreenshotExport = defineAsyncComponent(() => import('../components/ScreenshotExport.vue'))

watch(currentHour, (hour) => {
  layersStore.setCurrentHour(hour)
}, { immediate: true })

const timelineSegments = computed(() => {
  void currentHour.value
  return Array.from({ length: 8 }, (_, index) => {
    const hour = index * 3
    let state: DemoLayer['availabilityState'] = 'empty'
    let availabilityLabel = '空状态'
    
    if (activeLayer.value.catalogId) {
      const snapshot: DemoLayer = resolveDemoLayer(activeLayer.value.catalogId, hour)
      state = snapshot.availabilityState
      availabilityLabel = snapshot.availabilityLabel
    }
    
    return {
      hour,
      label: `${String(hour).padStart(2, '0')}:00`,
      state,
      availabilityLabel,
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
  if (selectedHotspot.value && !hotspots.some((hotspot) => hotspot.id === selectedHotspot.value?.id)) {
    selectedHotspot.value = null
  }
}

function handleHotspotSelect(hotspot: DemoHotspot | null) {
  selectedHotspot.value = hotspot
}

function clearPointWeather() {
  pointWeather.value = null
  pointWeatherError.value = null
  pointWeatherLoading.value = false
}

function isRealtimeWeatherLayer(catalogId?: string) {
  return catalogId === 'wind-field' || catalogId === 'temperature' || catalogId === 'precipitation'
}

async function fetchPointWeather(lng: number, lat: number) {
  if (!isRealtimeWeatherLayer(activeLayer.value.catalogId)) {
    clearPointWeather()
    return
  }
  const token = ++pointWeatherRequestToken
  pointWeatherLoading.value = true
  pointWeatherError.value = null
  try {
    const weather = await getWeatherPoint({
      layer_id: activeLayer.value.catalogId,
      latitude: lat,
      longitude: lng,
      forecast_hours: 6,
      place_name: `${lat.toFixed(3)}, ${lng.toFixed(3)}`,
    })
    if (token !== pointWeatherRequestToken) return
    pointWeather.value = weather
  } catch (error) {
    if (token !== pointWeatherRequestToken) return
    pointWeather.value = null
    pointWeatherError.value = error instanceof Error ? error.message : 'Failed to load point weather'
  } finally {
    if (token === pointWeatherRequestToken) {
      pointWeatherLoading.value = false
    }
  }
}

function handleMapPointSelect(point: { lng: number; lat: number }) {
  selectedMapPoint.value = point
  void fetchPointWeather(point.lng, point.lat)
}

function handleToggleLayerVisibility(instanceId: string) {
  layersStore.toggleLayerVisibility(instanceId)
}

function handleSetLayerOpacity(payload: { instanceId: string; opacity: number }) {
  layersStore.setLayerOpacity(payload.instanceId, payload.opacity)
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

watch(
  () => activeLayer.value.catalogId,
  (catalogId) => {
    if (!isRealtimeWeatherLayer(catalogId)) {
      clearPointWeather()
      return
    }
    if (selectedMapPoint.value) {
      void fetchPointWeather(selectedMapPoint.value.lng, selectedMapPoint.value.lat)
    }
  },
)

function buildFallbackActiveLayer(hour: number): ActiveLayerDisplay {
  void hour
  return {
    instanceId: '',
    catalogId: '',
    name: '无图层',
    category: '',
    summary: '请在左侧面板选择图层进行展示。',
    metricLabel: '—',
    metricValue: '—',
    trendLabel: '—',
    statusLabel: '—',
    updateLabel: '—',
    sourceLabel: '—',
    confidenceLabel: '—',
    accentColor: '#5a6a80',
    accentGlow: 'rgba(90, 106, 128, 0.3)',
    chipTone: 'rgba(90, 106, 128, 0.16)',
    availabilityState: 'empty',
    availabilityLabel: '空状态',
    availabilityDescription: '从左侧图层面板添加数据图层。',
    observationTimeLabel: '—',
    missingFieldsLabel: '—',
    hotspots: [],
    isAdminBoundary: false,
    visible: true,
    opacity: 1,
    order: 0,
    dataState: 'demo',
  }
}
</script>

<template>
  <main ref="dashboardRef" class="dashboard">
    <section ref="mapShellRef" class="map-shell">
      <MapCanvas
        ref="mapCanvasRef"
        :tile-source-id="tileSourceId"
        :current-hour="currentHour"
        :hour-label="hourLabel"
        @visible-hotspots-change="handleVisibleHotspotsChange"
        @hotspot-select="handleHotspotSelect"
        @map-point-select="handleMapPointSelect"
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
        <ControlPanel
          panel-label="图层"
          panel-key="layers"
          handle-position="bottom-right"
          :max-offset-x="100"
          :max-offset-y="110"
          :default-width="290"
          :default-height="360"
          :min-width="240"
          :min-height="220"
          :max-width="400"
          :max-height="520"
        >
          <LayerSidebar @select-layer="handleLayerSelect" />
        </ControlPanel>
      </div>

      <div class="overlay overlay-right">
        <ControlPanel
          panel-label="分析"
          panel-key="analysis"
          handle-position="bottom-left"
          :max-offset-x="80"
          :max-offset-y="110"
          :default-width="300"
          :default-height="360"
          :min-width="280"
          :min-height="220"
          :max-width="420"
          :max-height="520"
        >
          <InfoPanel
            :view-label="viewLabel"
            :active-layer="activeLayer"
            :hour-label="hourLabel"
            :stage-label="stageLabel"
            :visible-hotspots="visibleHotspots"
            :selected-layer="selectedLayerDisplay"
            :selected-hotspot="selectedHotspot"
            :is-submitting="isSubmitting"
            :workflow-error="workflowError"
            :point-weather="pointWeather"
            :point-weather-loading="pointWeatherLoading"
            :point-weather-error="pointWeatherError"
            @run-workflow="handleRunWorkflow"
            @toggle-layer-visibility="handleToggleLayerVisibility"
            @set-layer-opacity="handleSetLayerOpacity"
          />
        </ControlPanel>
      </div>

      <div class="overlay overlay-bottom">
        <TimelinePanel
          panel-label="时间轴"
          panel-key="timeline"
          :max-offset-x="140"
          :max-offset-y="70"
          :default-width="720"
          :default-height="207"
          :min-width="460"
          :min-height="175"
          :max-width="980"
          :max-height="248"
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
        </TimelinePanel>
      </div>
    </section>

    <ScreenshotExport
      v-if="screenshotOpen"
      :dashboard-el="dashboardRef"
      :map-shell-el="mapShellRef"
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
  top: 9.5rem;
  right: 0.8rem;
  width: min(21rem, calc(100vw - 1.6rem));
  display: flex;
  justify-content: flex-end;
}

.overlay-bottom {
  left: 50%;
  bottom: 0.72rem;
  width: min(45rem, calc(100vw - 1.6rem));
  transform: translateX(-50%);
  height: min-content;
}

@media (max-width: 1100px) {
  .overlay-left,
  .overlay-right {
    top: auto;
    bottom: 7rem;
    width: min(14rem, calc(100vw - 1.5rem));
  }

  .overlay-left {
    left: 0.75rem;
    width: min(15.5rem, calc(100vw - 1.5rem));
  }

  .overlay-right {
    right: 0.75rem;
    width: min(21rem, calc(100vw - 1.5rem));
    display: flex;
    justify-content: flex-end;
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
  .overlay-right,
  .overlay-bottom {
    position: static;
    width: auto;
    transform: none;
  }

  .overlay-left {
    margin: 7.2rem 0.75rem 0;
  }

  .overlay-right {
    margin: 0.75rem 0.75rem 0;
    width: auto;
  }

  .overlay-bottom {
    margin: 0.75rem 0.75rem 0;
  }
}
</style>
