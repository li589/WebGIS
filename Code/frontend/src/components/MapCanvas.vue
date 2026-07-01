<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { DemoHotspot, DemoLayer } from '../app/demo-data'
import type { BasemapMode } from '../stores/ui'
import type { StyleSpecification } from 'maplibre-gl'

const props = defineProps<{
  basemapMode: BasemapMode
  activeLayer: DemoLayer
  currentHour: number
  hourLabel: string
}>()
const emit = defineEmits<{
  visibleHotspotsChange: [hotspots: DemoHotspot[]]
}>()

const mapContainer = ref<HTMLElement | null>(null)
const hotspotPins = ref<
  Array<{
    id: string
    name: string
    value: string
    left: string
    top: string
  }>
>([])
const mapReady = ref(false)
const mapVisible = ref(false)
const skeletonVisible = ref(true)
const isMapInteracting = ref(false)
const isBasemapTransitioning = ref(false)
const loadingLabel = ref('正在加载地图...')
const timeProgressPercent = computed(() => `${(props.currentHour / 23) * 100}%`)
const timeGlowOpacity = computed(() => {
  const normalized = props.currentHour / 23
  const peak = 1 - Math.abs(normalized - 0.55) / 0.55
  return (0.08 + Math.max(0, peak) * 0.18).toFixed(3)
})
const horizonPosition = computed(() => `${12 + (props.currentHour / 23) * 76}%`)
const stageBandOpacity = computed(() => {
  const normalized = props.currentHour / 23
  const peak = 1 - Math.abs(normalized - 0.58) / 0.58
  return (0.06 + Math.max(0, peak) * 0.16).toFixed(3)
})
const stageGlowSpread = computed(() => {
  if (props.currentHour < 6) return '16rem'
  if (props.currentHour < 11) return '20rem'
  if (props.currentHour < 17) return '24rem'
  if (props.currentHour < 20) return '21rem'
  return '17rem'
})
const hotspotScale = computed(() => {
  if (props.currentHour < 6) return '0.88'
  if (props.currentHour < 11) return '0.96'
  if (props.currentHour < 17) return '1.08'
  if (props.currentHour < 20) return '0.98'
  return '0.9'
})
const hotspotHaloSize = computed(() => {
  if (props.currentHour < 6) return '8px'
  if (props.currentHour < 11) return '10px'
  if (props.currentHour < 17) return '12px'
  if (props.currentHour < 20) return '10px'
  return '8px'
})
const hotspotLabelOpacity = computed(() => {
  if (props.currentHour < 6) return '0.82'
  if (props.currentHour < 11) return '0.9'
  if (props.currentHour < 17) return '1'
  if (props.currentHour < 20) return '0.92'
  return '0.84'
})

type MapInstance = import('maplibre-gl').Map
type GeoJsonSourceSpecification = import('maplibre-gl').GeoJSONSourceSpecification
type RasterSourceSpecification = import('maplibre-gl').RasterSourceSpecification
type GuangdongBoundaryData = typeof import('../app/guangdong-boundaries')

let boundaryModule: GuangdongBoundaryData | null = null
let boundaryModulePromise: Promise<GuangdongBoundaryData> | null = null
let map: MapInstance | null = null
let animationFrameId: number | null = null
let basemapTransitionTimer: number | null = null

const modeDescription = computed(() => (!mapReady.value ? '正在加载地图...' : '2D 地图已就绪。'))
const isOsmFocused = computed(() => props.basemapMode === 'osm')

function createBaseStyle(): StyleSpecification {
  return {
    version: 8,
    sources: {},
    layers: [
      {
        id: 'background',
        type: 'background',
        paint: {
          'background-color': '#07111e',
        },
      },
    ],
  }
}

function waitForFirstPaint() {
  return new Promise<void>((resolve) => {
    requestAnimationFrame(() => resolve())
  })
}

function ensureOsmRasterLayer() {
  if (!map) {
    return
  }

  if (!map.getSource('osm')) {
    map.addSource('osm', {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution: '&copy; OpenStreetMap contributors',
    } as RasterSourceSpecification)
  }

  if (!map.getLayer('osm-raster')) {
    const beforeLayerId = map.getLayer('admin-fill') ? 'admin-fill' : undefined
    map.addLayer(
      {
        id: 'osm-raster',
        type: 'raster',
        source: 'osm',
        layout: {
          visibility: 'none',
        },
        paint: {
          'raster-opacity': 0.82,
          'raster-saturation': -0.18,
          'raster-contrast': 0.18,
        },
      },
      beforeLayerId,
    )
  }
}

async function ensureBoundaryModule() {
  if (!boundaryModule) {
    if (!boundaryModulePromise) {
      loadingLabel.value = '正在载入行政区边界...'
      boundaryModulePromise = import('../app/guangdong-boundaries')
    }

    boundaryModule = await boundaryModulePromise
  }

  return boundaryModule
}

async function ensureBoundaryLayers() {
  if (!map) {
    return
  }

  const loadedBoundaryModule = boundaryModule ?? (await ensureBoundaryModule())

  if (!map.getSource('admin-boundaries')) {
    map.addSource('admin-boundaries', {
      type: 'geojson',
      data: loadedBoundaryModule.guangdongCityBoundaries,
    } as GeoJsonSourceSpecification)
  }

  if (!map.getSource('admin-centers')) {
    map.addSource('admin-centers', {
      type: 'geojson',
      data: loadedBoundaryModule.guangdongCityCenters,
    } as GeoJsonSourceSpecification)
  }

  if (!map.getLayer('admin-fill')) {
    map.addLayer({
      id: 'admin-fill',
      type: 'fill',
      source: 'admin-boundaries',
      paint: {
        'fill-color': '#0c2238',
        'fill-opacity': 0.32,
      },
    })
  }

  if (!map.getLayer('admin-line')) {
    map.addLayer({
      id: 'admin-line',
      type: 'line',
      source: 'admin-boundaries',
      paint: {
        'line-color': '#4c88ba',
        'line-width': 1,
        'line-opacity': 0.82,
      },
    })
  }

  if (!map.getLayer('admin-center-points')) {
    map.addLayer({
      id: 'admin-center-points',
      type: 'circle',
      source: 'admin-centers',
      paint: {
        'circle-radius': 2.2,
        'circle-color': '#d8efff',
        'circle-opacity': 0.72,
        'circle-stroke-width': 1,
        'circle-stroke-color': '#0a233a',
      },
    })
  }
}

async function applyBasemapMode(mode: BasemapMode) {
  if (!map) {
    return
  }

  const showOsm = mode === 'osm' || mode === 'hybrid'
  const showAdmin = mode === 'admin' || mode === 'hybrid'

  if (showOsm) {
    ensureOsmRasterLayer()
  }

  if (showAdmin) {
    await ensureBoundaryLayers()
  }

  if (map.getLayer('osm-raster')) {
    map.setLayoutProperty('osm-raster', 'visibility', showOsm ? 'visible' : 'none')
    map.setPaintProperty('osm-raster', 'raster-opacity', mode === 'hybrid' ? 0.4 : 0.88)
    map.setPaintProperty('osm-raster', 'raster-saturation', mode === 'osm' ? -0.04 : -0.14)
    map.setPaintProperty('osm-raster', 'raster-contrast', mode === 'osm' ? 0.1 : 0.16)
  }

  if (map.getLayer('admin-fill')) {
    map.setLayoutProperty('admin-fill', 'visibility', showAdmin ? 'visible' : 'none')
    map.setPaintProperty('admin-fill', 'fill-opacity', mode === 'hybrid' ? 0.1 : 0.2)
  }

  if (map.getLayer('admin-line')) {
    map.setLayoutProperty('admin-line', 'visibility', showAdmin ? 'visible' : 'none')
    map.setPaintProperty('admin-line', 'line-opacity', mode === 'hybrid' ? 0.92 : 0.78)
  }

  if (map.getLayer('admin-center-points')) {
    map.setLayoutProperty('admin-center-points', 'visibility', showAdmin ? 'visible' : 'none')
  }
}

function triggerBasemapTransition() {
  if (typeof window === 'undefined') {
    return
  }

  isBasemapTransitioning.value = true

  if (basemapTransitionTimer !== null) {
    window.clearTimeout(basemapTransitionTimer)
  }

  basemapTransitionTimer = window.setTimeout(() => {
    isBasemapTransitioning.value = false
    basemapTransitionTimer = null
  }, 260)
}

function scheduleHotspotSync() {
  if (!map) {
    return
  }

  if (animationFrameId !== null) {
    cancelAnimationFrame(animationFrameId)
  }

  animationFrameId = requestAnimationFrame(() => {
    const currentMap = map
    if (!currentMap) {
      return
    }

    const zoom = currentMap.getZoom()
    const visibleHotspots =
      zoom < 5.4
        ? props.activeLayer.hotspots.slice(0, 1)
        : zoom < 6.2
          ? props.activeLayer.hotspots.slice(0, 2)
          : zoom < 7
            ? props.activeLayer.hotspots.slice(0, 3)
            : props.activeLayer.hotspots

    emit('visibleHotspotsChange', visibleHotspots)
    hotspotPins.value = visibleHotspots.map((hotspot) => {
      const point = currentMap.project([hotspot.lng, hotspot.lat])

      return {
        id: hotspot.id,
        name: hotspot.name,
        value: hotspot.value,
        left: `${point.x}px`,
        top: `${point.y}px`,
      }
    })

    animationFrameId = null
  })
}

function focusActiveLayer() {
  if (!map || props.activeLayer.hotspots.length === 0) {
    return
  }

  const firstHotspot = props.activeLayer.hotspots[0]
  map.easeTo({
    center: [firstHotspot.lng, firstHotspot.lat],
    zoom: 6.4,
    duration: 650,
    essential: true,
  })
}

onMounted(async () => {
  if (!mapContainer.value) {
    return
  }

  loadingLabel.value = '正在准备地图...'
  await waitForFirstPaint()
  loadingLabel.value = '正在加载地图引擎...'
  const { default: maplibregl } = await import('maplibre-gl')

  map = new maplibregl.Map({
    container: mapContainer.value,
    style: createBaseStyle(),
    center: [113.2644, 23.1291],
    zoom: 4.8,
    pitch: 0,
    bearing: 0,
    attributionControl: false,
    renderWorldCopies: false,
    cancelPendingTileRequestsWhileZooming: false,
    refreshExpiredTiles: false,
  })

  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right')
  map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left')
  map.on('load', async () => {
    await applyBasemapMode(props.basemapMode)
    focusActiveLayer()
    scheduleHotspotSync()
    mapReady.value = true
    requestAnimationFrame(() => {
      mapVisible.value = true
      window.setTimeout(() => {
        skeletonVisible.value = false
      }, 260)
    })
  })
  map.on('movestart', () => {
    isMapInteracting.value = true
  })
  map.on('zoomstart', () => {
    isMapInteracting.value = true
  })
  map.on('moveend', scheduleHotspotSync)
  map.on('zoomend', scheduleHotspotSync)
  map.on('moveend', () => {
    isMapInteracting.value = false
  })
  map.on('zoomend', () => {
    isMapInteracting.value = false
  })
  map.on('resize', scheduleHotspotSync)
})

watch(
  () => props.basemapMode,
  (mode) => {
    if (mapReady.value) {
      triggerBasemapTransition()
    }
    void applyBasemapMode(mode)
  },
)

watch(
  () => props.activeLayer,
  () => {
    emit('visibleHotspotsChange', props.activeLayer.hotspots.slice(0, 3))
    focusActiveLayer()
    scheduleHotspotSync()
  },
)

onBeforeUnmount(() => {
  if (animationFrameId !== null) {
    cancelAnimationFrame(animationFrameId)
  }
  if (basemapTransitionTimer !== null && typeof window !== 'undefined') {
    window.clearTimeout(basemapTransitionTimer)
  }
  map?.remove()
  map = null
})
</script>

<template>
  <section
    class="map-stage"
    :class="[
      { 'map-stage-osm': isOsmFocused },
      { 'map-stage-moving': isMapInteracting },
      { 'map-stage-basemap-transitioning': isBasemapTransitioning },
      `map-stage-${props.activeLayer.availabilityState}`,
    ]"
    :style="{
      '--accent-color': props.activeLayer.accentColor,
      '--accent-glow': props.activeLayer.accentGlow,
      '--chip-tone': props.activeLayer.chipTone,
      '--time-progress': timeProgressPercent,
      '--time-glow-opacity': timeGlowOpacity,
      '--horizon-position': horizonPosition,
      '--stage-band-opacity': stageBandOpacity,
      '--stage-glow-spread': stageGlowSpread,
      '--hotspot-scale': hotspotScale,
      '--hotspot-halo-size': hotspotHaloSize,
      '--hotspot-label-opacity': hotspotLabelOpacity,
    }"
  >
    <div ref="mapContainer" class="map-host" :class="{ visible: mapVisible }"></div>
    <div class="map-skeleton" :class="{ hidden: !skeletonVisible }" aria-hidden="true">
      <div class="skeleton-sweep"></div>
      <div class="skeleton-node skeleton-node-a"></div>
      <div class="skeleton-node skeleton-node-b"></div>
      <div class="skeleton-strip skeleton-strip-a"></div>
      <div class="skeleton-strip skeleton-strip-b"></div>
    </div>
    <div class="map-fog"></div>
    <div class="basemap-transition-mask"></div>
    <div class="time-sheen"></div>
    <div class="time-band"></div>
    <div class="weather-overlay"></div>
    <div class="grid-overlay"></div>
    <div v-if="!mapReady" class="map-loading">
      <span class="loading-dot"></span>
      <span>{{ loadingLabel }}</span>
    </div>

    <div class="map-overlay">
      <span class="chip">
        {{
          props.basemapMode === 'admin'
            ? '行政区'
            : props.basemapMode === 'osm'
              ? 'OSM'
              : '混合底图'
        }}
      </span>
      <span class="chip">{{ props.hourLabel }}</span>
      <span class="chip secondary">{{ props.activeLayer.name }}</span>
      <span class="chip" :class="`chip-${props.activeLayer.availabilityState}`">
        {{ props.activeLayer.availabilityLabel }}
      </span>
    </div>

    <div class="map-note">
      <h2>{{ props.activeLayer.name }}</h2>
      <p>{{ props.activeLayer.trendLabel }}</p>
      <span class="map-note-meta">{{ props.activeLayer.observationTimeLabel }} · {{ props.activeLayer.availabilityLabel }}</span>
      <div class="time-indicator" aria-hidden="true">
        <div class="time-indicator-fill"></div>
      </div>
    </div>

    <div class="metric-card" :class="`metric-card-${props.activeLayer.availabilityState}`">
      <strong>{{ props.activeLayer.metricLabel }}</strong>
      <span class="metric-value">{{ props.activeLayer.metricValue }}</span>
      <span>{{ props.activeLayer.availabilityDescription }}</span>
      <span>缺失：{{ props.activeLayer.missingFieldsLabel }}</span>
      <span>{{ modeDescription }}</span>
    </div>

    <div v-if="hotspotPins.length === 0" class="map-empty-hint">
      <strong>{{ props.activeLayer.availabilityLabel }}</strong>
      <span>{{ props.activeLayer.availabilityDescription }}</span>
    </div>

    <div class="hotspot-layer" :class="`hotspot-layer-${props.activeLayer.availabilityState}`" aria-hidden="true">
      <div
        v-for="pin in hotspotPins"
        :key="pin.id"
        class="hotspot-pin"
        :style="{ left: pin.left, top: pin.top }"
      >
        <div class="hotspot-core"></div>
        <div class="hotspot-label">
          <strong>{{ pin.name }}</strong>
          <span>{{ pin.value }}</span>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.map-stage {
  position: relative;
  min-height: calc(100vh - 1.5rem);
  overflow: hidden;
  border-radius: 1.4rem;
  border: 1px solid rgba(136, 192, 255, 0.16);
  background:
    radial-gradient(circle at top, rgba(66, 130, 255, 0.14), transparent 28rem),
    linear-gradient(180deg, rgba(6, 14, 26, 0.98), rgba(10, 19, 35, 0.94));
}

.map-host,
.map-fog,
.weather-overlay,
.grid-overlay,
.hotspot-layer {
  position: absolute;
  inset: 0;
}

.map-host {
  z-index: 0;
  opacity: 0.01;
  transition: opacity 0.45s ease;
}

.map-host.visible {
  opacity: 1;
}

.map-skeleton {
  position: absolute;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  background:
    radial-gradient(circle at 28% 36%, rgba(87, 166, 255, 0.18), transparent 16rem),
    linear-gradient(180deg, rgba(7, 16, 29, 0.98), rgba(10, 19, 35, 0.95));
  opacity: 1;
  transition: opacity 0.35s ease;
}

.map-skeleton.hidden {
  opacity: 0;
  pointer-events: none;
}

.skeleton-sweep,
.skeleton-node,
.skeleton-strip {
  position: absolute;
}

.skeleton-sweep {
  inset: 0;
  background: linear-gradient(110deg, transparent 26%, rgba(255, 255, 255, 0.08) 50%, transparent 74%);
  transform: translateX(-100%);
  animation: sweep 2.4s linear infinite;
}

.skeleton-node {
  width: 0.9rem;
  height: 0.9rem;
  border-radius: 999px;
  background: rgba(138, 198, 255, 0.34);
  box-shadow: 0 0 0 10px rgba(82, 134, 255, 0.08);
}

.skeleton-node-a {
  top: 34%;
  left: 28%;
}

.skeleton-node-b {
  top: 56%;
  left: 64%;
}

.skeleton-strip {
  height: 0.7rem;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
}

.skeleton-strip-a {
  left: 1rem;
  bottom: 5rem;
  width: 10rem;
}

.skeleton-strip-b {
  right: 1rem;
  bottom: 4.9rem;
  width: 7.6rem;
}

.map-fog {
  z-index: 1;
  pointer-events: none;
  background:
    radial-gradient(circle at 20% 18%, rgba(3, 12, 24, 0.06), transparent 18rem),
    linear-gradient(180deg, rgba(4, 11, 20, 0.01), rgba(4, 11, 20, 0.24));
}

.basemap-transition-mask {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
  opacity: 0;
  background:
    radial-gradient(circle at 50% 48%, rgba(125, 192, 255, 0.08), transparent 18rem),
    linear-gradient(180deg, rgba(4, 11, 20, 0.08), rgba(4, 11, 20, 0.14));
  transition: opacity 0.22s ease;
}

.time-sheen {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
  background:
    radial-gradient(
      circle at var(--horizon-position) 18%,
      rgba(255, 196, 120, var(--time-glow-opacity)),
      transparent 20rem
    ),
    linear-gradient(
      180deg,
      rgba(255, 181, 107, calc(var(--time-glow-opacity) * 0.35)) 0%,
      transparent 38%
    );
  transition: background 0.35s ease;
}

.time-band {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
  background:
    radial-gradient(
      circle at var(--horizon-position) 72%,
      color-mix(in srgb, var(--accent-color) 18%, rgba(255, 210, 150, var(--stage-band-opacity))),
      transparent var(--stage-glow-spread)
    ),
    linear-gradient(
      180deg,
      transparent 58%,
      rgba(255, 255, 255, calc(var(--stage-band-opacity) * 0.16)) 100%
    );
  opacity: 0.92;
  transition: background 0.35s ease, opacity 0.35s ease;
}

.weather-overlay {
  z-index: 1;
  pointer-events: none;
  opacity: 0.24;
  background:
    radial-gradient(circle at 18% 30%, color-mix(in srgb, var(--accent-color) 18%, transparent), transparent 18rem),
    radial-gradient(circle at 78% 24%, rgba(82, 134, 255, 0.12), transparent 20rem),
    radial-gradient(circle at 52% 72%, rgba(255, 255, 255, 0.06), transparent 16rem);
  filter: blur(8px);
  transform: translateZ(0);
}

.grid-overlay {
  z-index: 1;
  pointer-events: none;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.035) 1px, transparent 1px);
  background-size: 72px 72px;
  mask-image: linear-gradient(180deg, transparent, rgba(0, 0, 0, 0.6) 18%, rgba(0, 0, 0, 0.92));
}

.map-stage-osm .map-fog {
  background: linear-gradient(180deg, rgba(4, 11, 20, 0.02), rgba(4, 11, 20, 0.14));
}

.map-stage-osm .time-sheen {
  opacity: 0.7;
}

.map-stage-osm .weather-overlay {
  opacity: 0.12;
  filter: none;
}

.map-stage-osm .time-band {
  opacity: 0.62;
}

.map-stage-osm .grid-overlay {
  opacity: 0.42;
}

.map-stage-moving .weather-overlay,
.map-stage-moving .time-sheen,
.map-stage-moving .time-band,
.map-stage-moving .grid-overlay {
  opacity: 0.08;
  filter: none;
}

.map-stage-moving .hotspot-layer {
  opacity: 0.4;
}

.map-stage-basemap-transitioning .basemap-transition-mask {
  opacity: 1;
}

.map-stage-basemap-transitioning .map-host {
  filter: saturate(0.92) brightness(0.92);
}

.map-stage-ready .weather-overlay {
  opacity: 0.28;
}

.map-stage-ready .time-sheen {
  opacity: 1;
}

.map-stage-ready .time-band {
  opacity: 1;
}

.map-stage-partial .weather-overlay {
  opacity: 0.16;
  filter: blur(6px);
}

.map-stage-partial .grid-overlay {
  opacity: 0.32;
}

.map-stage-empty .map-fog {
  background:
    radial-gradient(circle at 20% 18%, rgba(3, 12, 24, 0.12), transparent 18rem),
    linear-gradient(180deg, rgba(4, 11, 20, 0.08), rgba(4, 11, 20, 0.34));
}

.map-stage-empty .time-sheen {
  opacity: 0.38;
}

.map-stage-empty .time-band {
  opacity: 0.46;
}

.map-stage-empty .weather-overlay {
  opacity: 0.08;
  filter: none;
}

.map-stage-empty .grid-overlay {
  opacity: 0.2;
}

.map-overlay {
  position: absolute;
  z-index: 2;
  top: 5.2rem;
  left: 1rem;
  display: flex;
  gap: 0.38rem;
  flex-wrap: wrap;
}

.chip {
  padding: 0.24rem 0.48rem;
  border-radius: 999px;
  background: rgba(8, 18, 33, 0.52);
  border: 1px solid rgba(136, 192, 255, 0.12);
  color: #eff7ff;
  font-size: 0.64rem;
}

.chip.secondary {
  color: #eaf7ff;
  border-color: color-mix(in srgb, var(--accent-color) 36%, rgba(136, 192, 255, 0.16));
  background: color-mix(in srgb, var(--chip-tone) 100%, rgba(8, 18, 33, 0.78));
}

.chip-ready {
  color: #9ff8cf;
  border-color: rgba(114, 255, 207, 0.2);
  background: rgba(114, 255, 207, 0.08);
}

.chip-partial {
  color: #ffd38a;
  border-color: rgba(255, 196, 120, 0.18);
  background: rgba(255, 196, 120, 0.08);
}

.chip-empty {
  color: #d7c1ff;
  border-color: rgba(187, 137, 255, 0.18);
  background: rgba(187, 137, 255, 0.08);
}

.map-note {
  position: absolute;
  z-index: 2;
  left: 1rem;
  bottom: 5.1rem;
  max-width: 12rem;
  display: grid;
  gap: 0.22rem;
  padding: 0.48rem 0.56rem;
  border-radius: 0.82rem;
  background: rgba(8, 18, 33, 0.46);
  border: 1px solid color-mix(in srgb, var(--accent-color) 14%, rgba(136, 192, 255, 0.12));
  backdrop-filter: blur(14px);
}

.map-note h2 {
  margin: 0;
  font-size: 0.76rem;
  color: #f3fbff;
}

.map-note p {
  margin: 0;
  color: #96a8bb;
  font-size: 0.64rem;
  line-height: 1.32;
}

.map-note-meta {
  color: #bfd3e6;
  font-size: 0.58rem;
  letter-spacing: 0.02em;
}

.time-indicator {
  position: relative;
  height: 0.24rem;
  margin-top: 0.16rem;
  border-radius: 999px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.08);
}

.time-indicator-fill {
  width: var(--time-progress);
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, color-mix(in srgb, var(--accent-color) 40%, rgba(255, 255, 255, 0.1)), var(--accent-color));
}

.metric-card {
  position: absolute;
  z-index: 2;
  display: grid;
  gap: 0.18rem;
  right: 1rem;
  bottom: 5rem;
  max-width: 8.4rem;
  padding: 0.44rem 0.54rem;
  border-radius: 0.82rem;
  background: rgba(8, 18, 33, 0.48);
  border: 1px solid rgba(136, 192, 255, 0.12);
  backdrop-filter: blur(14px);
  color: #dbe7f2;
}

.metric-card strong {
  font-size: 0.64rem;
}

.metric-card span {
  color: #90a2b5;
  line-height: 1.3;
  font-size: 0.6rem;
}

.metric-card-ready {
  border-color: rgba(114, 255, 207, 0.18);
}

.metric-card-partial {
  border-color: rgba(255, 196, 120, 0.16);
}

.metric-card-empty {
  border-color: rgba(187, 137, 255, 0.16);
  background: rgba(8, 18, 33, 0.58);
}

.map-empty-hint {
  position: absolute;
  z-index: 2;
  right: 1rem;
  bottom: 3.7rem;
  display: grid;
  gap: 0.18rem;
  max-width: 12rem;
  padding: 0.52rem 0.62rem;
  border-radius: 0.9rem;
  background: rgba(8, 18, 33, 0.66);
  border: 1px solid rgba(148, 163, 184, 0.12);
}

.map-empty-hint strong {
  color: #eef7ff;
  font-size: 0.68rem;
}

.map-empty-hint span {
  color: #98abbe;
  font-size: 0.6rem;
  line-height: 1.34;
}

.metric-value {
  color: #f5fbff;
  font-size: 0.92rem;
  font-weight: 700;
}

.hotspot-layer {
  z-index: 2;
  pointer-events: none;
}

.hotspot-layer-ready .hotspot-pin {
  opacity: 1;
}

.hotspot-layer-partial .hotspot-pin {
  opacity: 0.76;
}

.hotspot-layer-empty .hotspot-pin {
  opacity: 0.38;
}

.hotspot-pin {
  position: absolute;
  transform: translate(-50%, -50%);
}

.hotspot-core {
  width: 0.74rem;
  height: 0.74rem;
  border-radius: 999px;
  background: var(--accent-color);
  transform: scale(var(--hotspot-scale));
  box-shadow:
    0 0 0 0 rgba(255, 255, 255, 0.08),
    0 0 0 var(--hotspot-halo-size) color-mix(in srgb, var(--accent-glow) 70%, transparent);
  transition: transform 0.28s ease, box-shadow 0.28s ease;
}

.hotspot-label {
  margin-top: 0.4rem;
  padding: 0.32rem 0.42rem;
  border-radius: 0.8rem;
  background: rgba(4, 12, 23, 0.66);
  border: 1px solid rgba(136, 192, 255, 0.14);
  color: #e8f3fc;
  white-space: nowrap;
  box-shadow: 0 10px 18px rgba(1, 8, 16, 0.18);
  opacity: var(--hotspot-label-opacity);
  transition: opacity 0.28s ease, transform 0.28s ease;
}

.map-loading {
  position: absolute;
  inset: auto auto 1rem 1rem;
  z-index: 2;
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.5rem 0.72rem;
  border-radius: 999px;
  background: rgba(8, 18, 33, 0.84);
  border: 1px solid rgba(136, 192, 255, 0.16);
  color: #dfeefd;
  font-size: 0.74rem;
  backdrop-filter: blur(14px);
}

.loading-dot {
  width: 0.48rem;
  height: 0.48rem;
  border-radius: 999px;
  background: var(--accent-color);
  box-shadow: 0 0 0 6px color-mix(in srgb, var(--accent-glow) 42%, transparent);
}

.hotspot-label strong,
.hotspot-label span {
  display: block;
}

.hotspot-label strong {
  font-size: 0.64rem;
}

.hotspot-label span {
  margin-top: 0.15rem;
  color: #99afc3;
  font-size: 0.6rem;
}

:deep(.maplibregl-ctrl-top-right) {
  top: 7rem;
  right: 0.8rem;
}

:deep(.maplibregl-ctrl-group) {
  border-radius: 0.8rem;
  overflow: hidden;
  box-shadow: 0 12px 32px rgba(3, 10, 20, 0.35);
}

:deep(.maplibregl-ctrl-attrib) {
  background: rgba(255, 255, 255, 0.8);
}

@keyframes sweep {
  to {
    transform: translateX(100%);
  }
}

@media (max-width: 820px) {
  .map-stage {
    min-height: calc(100vh - 1rem);
  }

  .map-overlay {
    top: 7.15rem;
    left: 0.75rem;
    right: 0.75rem;
  }

  .map-note {
    left: 0.75rem;
    right: 0.75rem;
    bottom: 8.3rem;
    max-width: none;
  }

  .metric-card {
    right: 0.75rem;
    left: 0.75rem;
    bottom: 5.2rem;
    max-width: none;
  }

  :deep(.maplibregl-ctrl-top-right) {
    top: 11rem;
  }
}
</style>
