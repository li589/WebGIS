<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import maplibregl, { type StyleSpecification } from 'maplibre-gl'

import type { MapMode } from '../stores/ui'

const props = defineProps<{
  currentMode: MapMode
  activeDataset: string
  hourLabel: string
}>()

const mapContainer = ref<HTMLElement | null>(null)

let map: maplibregl.Map | null = null

const modeDescription = computed(() =>
  props.currentMode === '2d'
    ? '当前已接入 OSM 底图，后续可叠加风场、降水和实时计算结果。'
    : '当前仍显示 OSM 底图，3D 地球模式后续会切换到 Cesium。'
)

function createOsmStyle(): StyleSpecification {
  return {
    version: 8,
    sources: {
      osm: {
        type: 'raster',
        tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
        tileSize: 256,
        attribution: '&copy; OpenStreetMap Contributors',
      },
    },
    layers: [
      {
        id: 'osm',
        type: 'raster',
        source: 'osm',
      },
    ],
  }
}

function updateMapView(mode: MapMode) {
  if (!map) {
    return
  }

  if (mode === '2d') {
    map.easeTo({
      pitch: 0,
      bearing: 0,
      duration: 600,
    })
    return
  }

  map.easeTo({
    pitch: 55,
    bearing: 20,
    duration: 800,
  })
}

onMounted(() => {
  if (!mapContainer.value) {
    return
  }

  map = new maplibregl.Map({
    container: mapContainer.value,
    style: createOsmStyle(),
    center: [113.2644, 23.1291],
    zoom: 4.8,
    pitch: props.currentMode === '2d' ? 0 : 55,
    bearing: props.currentMode === '2d' ? 0 : 20,
    attributionControl: {},
  })

  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right')
  map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left')
})

watch(
  () => props.currentMode,
  (mode) => {
    updateMapView(mode)
  },
)

onBeforeUnmount(() => {
  map?.remove()
  map = null
})
</script>

<template>
  <section class="map-stage">
    <div ref="mapContainer" class="map-host"></div>
    <div class="map-fog"></div>

    <div class="map-overlay">
      <span class="chip">{{ props.currentMode === '2d' ? 'OSM 2D 底图' : '3D 过渡视图' }}</span>
      <span class="chip secondary">当前图层：{{ props.activeDataset }}</span>
      <span class="chip">{{ props.hourLabel }}</span>
    </div>

    <div class="map-note">
      <h2>{{ props.currentMode === '2d' ? '已接入 OpenStreetMap' : '3D 模式仍在开发中' }}</h2>
      <p>{{ modeDescription }}</p>
    </div>

    <div class="status-card">
      <strong>实时计算预留区</strong>
      <span>下一步可以把课题组算法结果作为栅格、等值面或点图层叠加到这个 OSM 底图上。</span>
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
  background: linear-gradient(180deg, rgba(6, 14, 26, 0.96), rgba(10, 19, 35, 0.92));
}

.map-host,
.map-fog {
  position: absolute;
  inset: 0;
}

.map-host {
  z-index: 0;
}

.map-fog {
  z-index: 1;
  pointer-events: none;
  background:
    radial-gradient(circle at 20% 18%, rgba(3, 12, 24, 0.08), transparent 18rem),
    linear-gradient(180deg, rgba(4, 11, 20, 0.08), rgba(4, 11, 20, 0.32));
}

.map-overlay {
  position: absolute;
  z-index: 2;
  top: 6.8rem;
  left: 1rem;
  display: flex;
  gap: 0.55rem;
  flex-wrap: wrap;
}

.chip {
  padding: 0.38rem 0.72rem;
  border-radius: 999px;
  background: rgba(8, 18, 33, 0.84);
  border: 1px solid rgba(136, 192, 255, 0.16);
  color: #eff7ff;
  font-size: 0.82rem;
}

.chip.secondary {
  color: #91f6df;
}

.map-note {
  position: absolute;
  z-index: 2;
  left: 1rem;
  bottom: 6.8rem;
  max-width: 24rem;
  display: grid;
  gap: 0.35rem;
  padding: 0.95rem 1rem;
  border-radius: 1rem;
  background: rgba(8, 18, 33, 0.72);
  border: 1px solid rgba(136, 192, 255, 0.14);
  backdrop-filter: blur(12px);
}

.map-note h2 {
  margin: 0;
  font-size: 1.05rem;
  color: #f3fbff;
}

.map-note p {
  margin: 0;
  color: #96a8bb;
  font-size: 0.88rem;
  line-height: 1.5;
}

.status-card {
  position: absolute;
  z-index: 2;
  right: 1rem;
  bottom: 6.75rem;
  max-width: 16rem;
  display: grid;
  gap: 0.35rem;
  padding: 0.85rem 0.95rem;
  border-radius: 1rem;
  background: rgba(8, 18, 33, 0.72);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(136, 192, 255, 0.15);
  color: #dbe7f2;
}

.status-card strong {
  font-size: 0.92rem;
}

.status-card span {
  color: #90a2b5;
  line-height: 1.5;
  font-size: 0.84rem;
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

@media (max-width: 820px) {
  .map-stage {
    min-height: calc(100vh - 1rem);
  }

  .map-overlay {
    top: 7.6rem;
    left: 0.75rem;
    right: 0.75rem;
  }

  .map-note {
    left: 0.75rem;
    right: 0.75rem;
    bottom: 9.5rem;
    max-width: none;
  }

  .status-card {
    right: 0.75rem;
    left: 0.75rem;
    bottom: 5.8rem;
    max-width: none;
  }

  :deep(.maplibregl-ctrl-top-right) {
    top: 11rem;
  }
}
</style>
