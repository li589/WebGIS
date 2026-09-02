<script setup lang="ts">
/**
 * CesiumGlobeHost — 实验性 Cesium 地球宿主。
 * 底图 / overlay-tiles / 光影；与 MapCanvas 互斥；视口桥接。
 */
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'

import type { TileSourceId } from '../../../services/api-config'
import {
  getGlobeDaylightMode,
  subscribeGlobeScene,
  type GlobeDaylightMode,
} from '../../../services/settings-local'
import { useLayerWorkspace } from '../../../stores/layers/selectors'
import { collectCesiumOverlayTileSpecs } from './cesium/overlay-tiles-adapter'
import { createCesiumViewer, type CesiumViewerHandle } from './cesium/create-viewer'
import {
  consumeGlobeViewSnapshot,
  setGlobeViewSnapshot,
} from './view-bridge'
import type { LngLatBoundsTuple } from './layer-extent'

const props = defineProps<{
  tileSourceId: TileSourceId
  hour: number
  currentDate?: string | Date | null
  /** 时间轴 time key（overlay query） */
  timeKey?: string | null
}>()

const workspace = useLayerWorkspace()
const rootRef = ref<HTMLElement | null>(null)
const containerRef = ref<HTMLElement | null>(null)
const error = ref<string | null>(null)
const loading = ref(true)
const handle = shallowRef<CesiumViewerHandle | null>(null)
const daylightMode = ref<GlobeDaylightMode>(getGlobeDaylightMode())
const overlayCount = ref(0)

let resizeObserver: ResizeObserver | null = null
let cancelled = false
let unsubScene: (() => void) | null = null

function parseDate(raw: string | Date | null | undefined): Date | null {
  if (raw instanceof Date) return Number.isNaN(raw.getTime()) ? null : raw
  if (typeof raw === 'string' && raw.trim()) {
    const d = new Date(raw)
    if (!Number.isNaN(d.getTime())) return d
  }
  return null
}

const overlaySpecs = computed(() =>
  collectCesiumOverlayTileSpecs(workspace.activeLayersDisplay.value, {
    isWeatherEngineLayer: (id) => workspace.isWeatherEngineLayer(id),
    timeKey: props.timeKey ?? null,
  }),
)

const bannerText = computed(() => {
  if (overlayCount.value > 0) {
    return 'Cesium 实验：底图 + 瓦片叠加已启用；风场粒子等尚未接入'
  }
  return 'Cesium 实验模式：底图已接应用瓦片源；天气 GeoJSON / 风场尚未接入'
})

function syncOverlays() {
  const specs = overlaySpecs.value
  handle.value?.syncOverlayImagery(specs)
  overlayCount.value = specs.length
}

onMounted(async () => {
  cancelled = false
  const el = containerRef.value
  if (!el) return
  unsubScene = subscribeGlobeScene(() => {
    daylightMode.value = getGlobeDaylightMode()
  })
  const initial = consumeGlobeViewSnapshot()
  try {
    const host = await createCesiumViewer(el, {
      tileSourceId: props.tileSourceId,
      daylightMode: daylightMode.value,
      hour: props.hour,
      date: parseDate(props.currentDate),
      initialView: initial
        ? { lng: initial.lng, lat: initial.lat, heightMeters: initial.heightMeters }
        : null,
    })
    if (cancelled) {
      host.destroy()
      return
    }
    handle.value = host
    syncOverlays()
    // 容器可能在首帧仍为 0×0（绝对定位叠层），强制一次 resize 以免黑屏
    host.resize()
    resizeObserver = new ResizeObserver(() => {
      host.resize()
    })
    resizeObserver.observe(el)
  } catch (err) {
    if (!cancelled) {
      error.value = err instanceof Error ? err.message : 'Cesium 初始化失败'
    }
  } finally {
    if (!cancelled) loading.value = false
  }
})

onUnmounted(() => {
  cancelled = true
  const view = handle.value?.captureView()
  if (view) {
    setGlobeViewSnapshot({
      lng: view.lng,
      lat: view.lat,
      heightMeters: view.heightMeters,
    })
  }
  unsubScene?.()
  unsubScene = null
  resizeObserver?.disconnect()
  resizeObserver = null
  handle.value?.destroy()
  handle.value = null
})

watch(
  () => props.tileSourceId,
  (id) => {
    handle.value?.setBasemap(id)
    syncOverlays()
  },
)

watch(
  [daylightMode, () => props.hour, () => props.currentDate],
  ([mode, hour, date]) => {
    handle.value?.setDaylight(mode, hour, parseDate(date))
  },
)

watch(overlaySpecs, () => {
  syncOverlays()
})

defineExpose({
  flyTo(lng: number, lat: number, heightMeters?: number) {
    handle.value?.flyTo(lng, lat, heightMeters)
  },
  flyToBounds(bounds: LngLatBoundsTuple) {
    handle.value?.flyToBounds(bounds)
  },
  getCanvas(): HTMLCanvasElement | null {
    const viewer = handle.value?.getViewer()
    return (viewer?.scene?.canvas as HTMLCanvasElement | undefined) ?? null
  },
  getHostElement(): HTMLElement | null {
    return rootRef.value
  },
  captureView() {
    return handle.value?.captureView() ?? null
  },
})
</script>

<template>
  <div ref="rootRef" class="cesium-globe-host">
    <div ref="containerRef" class="cesium-globe-host__viewport" />
    <div v-if="loading" class="cesium-globe-host__banner">正在加载 Cesium…</div>
    <div v-else-if="error" class="cesium-globe-host__banner cesium-globe-host__banner--error">
      {{ error }}
    </div>
    <div v-else class="cesium-globe-host__banner">{{ bannerText }}</div>
  </div>
</template>

<style scoped>
.cesium-globe-host {
  position: absolute;
  inset: 0;
  z-index: 0;
  background: #02040a;
}

.cesium-globe-host__viewport {
  position: absolute;
  inset: 0;
}

.cesium-globe-host__banner {
  position: absolute;
  left: 50%;
  bottom: 5.5rem;
  transform: translateX(-50%);
  z-index: 2;
  max-width: min(32rem, calc(100% - 2rem));
  padding: 0.4rem 0.75rem;
  border-radius: 8px;
  border: 1px solid color-mix(in srgb, var(--border-subtle, #445) 80%, transparent);
  background: color-mix(in srgb, var(--surface-1, #12161e) 88%, transparent);
  color: var(--text-secondary, #b8c0cc);
  font-size: var(--font-size-caption, 0.75rem);
  line-height: 1.4;
  text-align: center;
  pointer-events: none;
}

.cesium-globe-host__banner--error {
  color: var(--danger, #e07070);
  border-color: color-mix(in srgb, var(--danger, #c44) 45%, transparent);
}
</style>
