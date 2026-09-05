<script setup lang="ts">
/**
 * GlobeSolarSystemBackdrop — 3D「太阳系」深空背景。
 * 相机联动星空 + 时间轴联动太阳盘；不拦截指针；晨昏线仍由 night-mask 负责。
 */
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { paintSolarSystemBackdrop, type SolarSystemCamera } from './globe-solar-system'
import { resolveReducedMotionPreference } from '../../services/motion-preference'

const props = defineProps<{
  active: boolean
  hour: number
  currentDate?: string | Date | null
  camera: SolarSystemCamera
}>()

const canvasRef = ref<HTMLCanvasElement | null>(null)
let rafId: number | null = null
let startMs = performance.now()
let lastPaintMs = 0

function parseDate(raw: string | Date | null | undefined): Date {
  if (raw instanceof Date) return raw
  if (typeof raw === 'string' && raw.trim()) {
    const d = new Date(raw)
    if (!Number.isNaN(d.getTime())) return d
  }
  return new Date()
}

function paint(nowMs: number) {
  const canvas = canvasRef.value
  if (!canvas || !props.active) return
  const parent = canvas.parentElement
  const cssW = parent?.clientWidth || window.innerWidth
  const cssH = parent?.clientHeight || window.innerHeight
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  const w = Math.max(1, Math.floor(cssW * dpr))
  const h = Math.max(1, Math.floor(cssH * dpr))
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w
    canvas.height = h
  }
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  paintSolarSystemBackdrop(ctx, {
    width: w,
    height: h,
    camera: props.camera,
    hour: props.hour,
    date: parseDate(props.currentDate),
    reducedMotion: resolveReducedMotionPreference(),
    timeSec: (nowMs - startMs) / 1000,
    seed: 42,
  })
}

function frame(nowMs: number) {
  rafId = null
  if (!props.active) return
  const reduced = resolveReducedMotionPreference()
  // 日冕微动约 12fps；减少动效时只在属性变化时画
  if (!reduced && nowMs - lastPaintMs >= 80) {
    lastPaintMs = nowMs
    paint(nowMs)
  }
  if (!reduced) {
    rafId = requestAnimationFrame(frame)
  }
}

function startLoop() {
  stopLoop()
  if (!props.active) return
  paint(performance.now())
  if (!resolveReducedMotionPreference()) {
    rafId = requestAnimationFrame(frame)
  }
}

function stopLoop() {
  if (rafId != null) {
    cancelAnimationFrame(rafId)
    rafId = null
  }
}

watch(
  () =>
    [
      props.active,
      props.hour,
      props.currentDate,
      props.camera.lng,
      props.camera.lat,
      props.camera.bearing,
      props.camera.pitch,
      props.camera.zoom,
    ] as const,
  () => {
    if (props.active) {
      paint(performance.now())
      if (rafId == null && !resolveReducedMotionPreference()) {
        rafId = requestAnimationFrame(frame)
      }
    } else {
      stopLoop()
    }
  },
)

function handleResize() {
  paint(performance.now())
}

function handleVisibilityChange() {
  if (typeof document === 'undefined') return
  if (document.visibilityState === 'visible') {
    if (props.active) {
      startMs = performance.now()
      startLoop()
    }
  } else {
    stopLoop()
  }
}

onMounted(() => {
  if (props.active) startLoop()
  window.addEventListener('resize', handleResize)
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onUnmounted(() => {
  stopLoop()
  window.removeEventListener('resize', handleResize)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
</script>

<template>
  <canvas
    ref="canvasRef"
    class="globe-solar-system"
    :class="{ 'globe-solar-system--visible': active }"
    aria-hidden="true"
  ></canvas>
</template>

<style scoped>
.globe-solar-system {
  position: absolute;
  inset: 0;
  z-index: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.6s var(--ease-standard);
}

.globe-solar-system--visible {
  opacity: 1;
}
</style>
