/**
 * Globe 3D 场景参数解析（纯函数，可单测）。
 *
 * 目标：按「底图亮度 + 用户光影档位」解析 MapLibre light/sky 参数。
 * 「自然」档昼夜分界见 globe-night-mask.ts（光栅遮罩，非本文件）。
 */
import type { BasemapStyle } from '../../services/api-config'
import type { GlobeDaylightMode } from '../../services/settings-local'

/** 底图亮度分类：light=亮色（易过曝）/ medium=影像地形 / dark=暗色 */
export type BasemapBrightness = 'light' | 'medium' | 'dark'

export type { GlobeDaylightMode }

/** 归一化小时 → 昼夜因子：正午 1，午夜 0（余弦，晨昏自然过渡） */
export function daylightFactor(hour: number): number {
  const normalized = ((hour % 24) + 24) % 24
  return Math.max(0, Math.cos(((normalized - 12) / 12) * Math.PI))
}

/** 按底图 style 判亮度档。street/vec 等亮色→light；卫星影像/地形→medium；dark→dark。 */
export function classifyBasemapBrightness(
  style: BasemapStyle | string | undefined,
): BasemapBrightness {
  if (style === 'dark') return 'dark'
  if (style === 'satellite' || style === 'terrain') return 'medium'
  return 'light'
}

export interface GlobeLightingParams {
  /** 漫反射强度（MapLibre light intensity，0..1） */
  intensity: number
  /** 光照色温（白天暖白、晨昏暖橙、夜间冷蓝；亮色底图更白） */
  color: string
  /** 太阳方位角（度）：正午位于视口南侧 */
  azimuth: number
  /** 太阳高度角（度）：越低阴影越长越柔和 */
  elevation: number
}

export interface GlobeSkyParams {
  skyColor: string
  horizonColor: string
  fogColor: string
  fogGroundBlend: number
  horizonFogBlend: number
  skyHorizonBlend: number
  atmosphereBlend: number
}

/**
 * 太阳下点经度（本地时间模型）。
 * hour 是**本地时间轴小时**（如中国 UTC+8 的 12:00 = UTC 04:00），
 * 必须先换算 UTC 再按下点公式：utcHour = hour - tzOffset，
 * subsolarLon = (12 - utcHour) × 15°。
 */
export function subsolarLongitude(hour: number, tzOffsetHours?: number): number {
  const tz = tzOffsetHours ?? -new Date().getTimezoneOffset() / 60
  const utcHour = (((hour - tz) % 24) + 24) % 24
  return (((12 - utcHour) * 15 + 540) % 360) - 180
}

/**
 * 太阳赤纬（度），Cooper 近似：δ = 23.45° × sin(360° × (284 + n) / 365)。
 */
export function subsolarDeclination(date?: Date): number {
  const d = date ?? new Date()
  const start = Date.UTC(d.getUTCFullYear(), 0, 0)
  const dayOfYear = Math.floor((d.getTime() - start) / 86400000)
  return 23.45 * Math.sin(((360 * (284 + dayOfYear)) / 365) * (Math.PI / 180))
}

function clamp(v: number, min: number, max: number): number {
  return v < min ? min : v > max ? max : v
}

/**
 * 解析光照参数（当前仅测试使用；globe 模式已停用 setLight）。
 */
export function resolveGlobeLighting(
  hour: number,
  brightness: BasemapBrightness,
  mode: GlobeDaylightMode,
): GlobeLightingParams | null {
  if (mode === 'off') return null
  const daylight = daylightFactor(hour)
  const twilight = 1 - daylight
  const azimuth = 180 - ((((hour % 24) + 24) % 24) - 12) * 15

  const brightnessScale = brightness === 'light' ? 0.5 : brightness === 'dark' ? 1.0 : 0.78
  const intensity = clamp((0.4 + daylight * 0.55) * brightnessScale, 0.18, 1.0)

  const elevationBase = brightness === 'light' ? 10 : brightness === 'dark' ? 20 : 16
  const elevationRange = brightness === 'light' ? 26 : brightness === 'dark' ? 44 : 34
  const elevation = elevationBase + daylight * elevationRange

  const lightBase =
    brightness === 'light'
      ? { warm: 213, green: 224, blue: 230 }
      : brightness === 'dark'
        ? { warm: 255, green: 246, blue: 232 }
        : { warm: 244, green: 240, blue: 232 }
  const warm = Math.round(lightBase.warm - twilight * (lightBase.warm === 255 ? 28 : 24))
  const green = Math.round(lightBase.green - twilight * 56)
  const blue = Math.round(lightBase.blue - twilight * 40)
  const color = `rgb(${warm}, ${green}, ${blue})`

  return { intensity, color, azimuth, elevation }
}

/**
 * 解析天空大气参数（MapLibre sky）。
 */
export function resolveGlobeSky(hour: number, brightness: BasemapBrightness): GlobeSkyParams {
  const daylight = daylightFactor(hour)
  const isDay = daylight > 0.45
  if (!isDay) {
    return {
      skyColor: '#0a2440',
      horizonColor: '#143c58',
      fogColor: '#0d2c46',
      fogGroundBlend: 0.3,
      horizonFogBlend: 0.9,
      skyHorizonBlend: 0.85,
      atmosphereBlend: 0.82,
    }
  }
  const lightish = brightness === 'light'
  return {
    skyColor: lightish ? '#9db6c6' : '#8cc9ee',
    horizonColor: lightish ? '#c9dde8' : '#d4ebf5',
    fogColor: lightish ? '#a9c3d2' : '#9bd4ed',
    fogGroundBlend: 0.32,
    horizonFogBlend: 0.92,
    skyHorizonBlend: 0.8,
    atmosphereBlend: lightish ? 0.66 : 0.78,
  }
}
