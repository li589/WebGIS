/**
 * Globe「自然」档夜半球 — 等经纬光栅遮罩（v1：硬边暗/亮，无动画、无晨昏羽化）。
 *
 * 按太阳高度角 h 逐像素判定：h < 0 → 夜侧半透明暗色；h ≥ 0 → 透明。
 * 避免 GeoJSON fill 在 globe 上的极点洞、antimeridian 毛刺与 setData 切片错乱。
 */
import { subsolarDeclination, subsolarLongitude } from './globe-scene-utils'

/**
 * 夜侧遮罩 RGBA（与历史 night-core fill 色一致；alpha 140→175 增强"暗面"感——
 * 半透明罩子视觉 → 更像真实太空照片的地球暗面）
 */
export const NIGHT_MASK_RGBA = { r: 10, g: 22, b: 38, a: 175 } as const

/** 经纬度 → 单位球面坐标（与 GLSL lngLatToGlobeSphereNight 一致） */
export function lngLatToUnitSphere(lngDeg: number, latDeg: number): [number, number, number] {
  const lonRad = (lngDeg * Math.PI) / 180
  const latRad = (Math.max(-90, Math.min(90, latDeg)) * Math.PI) / 180
  const cosLat = Math.cos(latRad)
  const x = cosLat * Math.sin(lonRad)
  const y = Math.sin(latRad)
  const z = cosLat * Math.cos(lonRad)
  const len = Math.hypot(x, y, z) || 1
  return [x / len, y / len, z / len]
}

/** 默认 equirectangular 分辨率：1080×540 ≈ 0.33°/pixel（globe 贴球时减少 terminator 锯齿环） */
export const NIGHT_MASK_DEFAULT_WIDTH = 1080
export const NIGHT_MASK_DEFAULT_HEIGHT = 540

/** addSource 占位图（1×1 透明 PNG），避免 data URL 异步解码与 updateImage 叠影 */
export const NIGHT_MASK_PLACEHOLDER_URL =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAD0lEQVQ42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='

/**
 * 太阳高度角（度）。
 * h = arcsin(sin φ sin δ + cos φ cos δ cos(λ − λ☉))
 */
export function sunAltitudeDeg(
  lonDeg: number,
  latDeg: number,
  subsolarLonDeg: number,
  declDeg: number,
): number {
  const lat = (latDeg * Math.PI) / 180
  const decl = (declDeg * Math.PI) / 180
  const hourAngle = ((lonDeg - subsolarLonDeg) * Math.PI) / 180
  const sinH = Math.sin(lat) * Math.sin(decl) + Math.cos(lat) * Math.cos(decl) * Math.cos(hourAngle)
  return (Math.asin(Math.max(-1, Math.min(1, sinH))) * 180) / Math.PI
}

/** 纯函数：生成 RGBA 像素（可单测，不依赖 canvas） */
export function buildNightMaskPixels(
  width: number,
  height: number,
  hour: number,
  date?: Date,
  tzOffsetHours?: number,
): Uint8ClampedArray {
  const subsolarLon = subsolarLongitude(hour, tzOffsetHours)
  const decl = subsolarDeclination(date)
  const { r, g, b, a } = NIGHT_MASK_RGBA
  const data = new Uint8ClampedArray(width * height * 4)
  for (let y = 0; y < height; y++) {
    const lat = height <= 1 ? 0 : 90 - (y / (height - 1)) * 180
    for (let x = 0; x < width; x++) {
      const lon = width <= 1 ? 0 : -180 + (x / (width - 1)) * 360
      const h = sunAltitudeDeg(lon, lat, subsolarLon, decl)
      const i = (y * width + x) * 4
      if (h < 0) {
        data[i] = r
        data[i + 1] = g
        data[i + 2] = b
        data[i + 3] = a
      }
    }
  }
  return data
}

let sharedNightMaskCanvas: HTMLCanvasElement | null = null

/**
 * 绘制夜半球遮罩到可复用 canvas（MapLibre updateImage 同步路径）。
 * 复用同一块 canvas，避免拖动时间轴时频繁分配触发纹理叠影。
 */
export function paintNightHemisphereMaskCanvas(
  hour: number,
  date?: Date,
  tzOffsetHours?: number,
  width = NIGHT_MASK_DEFAULT_WIDTH,
  height = NIGHT_MASK_DEFAULT_HEIGHT,
): HTMLCanvasElement {
  if (typeof document === 'undefined') {
    throw new Error('canvas unavailable')
  }
  if (
    !sharedNightMaskCanvas ||
    sharedNightMaskCanvas.width !== width ||
    sharedNightMaskCanvas.height !== height
  ) {
    sharedNightMaskCanvas = document.createElement('canvas')
    sharedNightMaskCanvas.width = width
    sharedNightMaskCanvas.height = height
  }
  const ctx = sharedNightMaskCanvas.getContext('2d')
  if (!ctx) throw new Error('canvas 2d unavailable')
  const pixels = buildNightMaskPixels(width, height, hour, date, tzOffsetHours)
  const imageData = ctx.createImageData(width, height)
  imageData.data.set(pixels)
  ctx.putImageData(imageData, 0, 0)
  return sharedNightMaskCanvas
}

/** 浏览器端：生成 PNG data URL（测试/调试） */
export function buildNightHemisphereMaskDataUrl(
  hour: number,
  date?: Date,
  tzOffsetHours?: number,
  width = NIGHT_MASK_DEFAULT_WIDTH,
  height = NIGHT_MASK_DEFAULT_HEIGHT,
): string {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('canvas 2d unavailable')
  const pixels = buildNightMaskPixels(width, height, hour, date, tzOffsetHours)
  const imageData = ctx.createImageData(width, height)
  imageData.data.set(pixels)
  ctx.putImageData(imageData, 0, 0)
  return canvas.toDataURL('image/png')
}

/** @deprecated 使用 paintNightHemisphereMaskCanvas */
export function buildNightHemisphereMaskCanvas(
  hour: number,
  date?: Date,
  tzOffsetHours?: number,
  width = NIGHT_MASK_DEFAULT_WIDTH,
  height = NIGHT_MASK_DEFAULT_HEIGHT,
): HTMLCanvasElement {
  return paintNightHemisphereMaskCanvas(hour, date, tzOffsetHours, width, height)
}

/** 与时间轴 slider step=0.25 对齐，避免无意义的高频重算 */
export function quantizeNightMaskHour(hour: number): number {
  return Math.round(hour * 4) / 4
}

/** MapLibre image source 四角（全球 equirectangular） */
export const NIGHT_MASK_IMAGE_COORDINATES: [
  [number, number],
  [number, number],
  [number, number],
  [number, number],
] = [
  [-180, 90],
  [180, 90],
  [180, -90],
  [-180, -90],
]
