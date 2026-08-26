/**
 * Globe 3D 场景参数解析（纯函数，可单测）。
 *
 * 目标：按「底图亮度 + 用户光影档位」解析 MapLibre light/sky 参数。
 * 核心问题：亮色底图（街道/矢量/地形）在太阳直射下会过曝发白；
 * 影像/暗色底图则更需要高对比来体现球面立体感。
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

function clamp(v: number, min: number, max: number): number {
  return v < min ? min : v > max ? max : v
}

/**
 * 解析光照参数。
 * - 亮色底图：直射强度 ×0.5 + 太阳高度上限 36°（柔和长影）+ light color 偏冷白
 *   （亮度乘到瓦片上时整体压暗约 15%，避免白底+直射=全白的过曝）
 * - 影像/地形：×0.78 + 50° + 近白偏暖
 * - 暗色底图：×1.0 + 64° + 暖白（保留立体光影冲击）
 * - soft 档再 ×0.72 整体压低；off 返回 null（不设置自定义光照）
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

  const brightnessScale =
    brightness === 'light' ? 0.5 : brightness === 'dark' ? 1.0 : 0.78
  const modeScale = mode === 'soft' ? 0.72 : 1.0
  // 直射强度：正午 0.95、夜间 0.4 的基准随底图/档位缩放（亮色底图上限更严）
  const intensity = clamp((0.4 + daylight * 0.55) * brightnessScale * modeScale, 0.18, 1.0)

  // 太阳高度：亮色底图更低更斜（柔和长影），暗色底图更高（强立体感）
  const elevationBase = brightness === 'light' ? 10 : brightness === 'dark' ? 20 : 16
  const elevationRange = brightness === 'light' ? 26 : brightness === 'dark' ? 44 : 34
  const elevation = elevationBase + daylight * elevationRange

  // 光照色温 = MapLibre light color，会直接乘到瓦片像素上。
  // 亮色底图用「偏冷白」rgb(215, 226, 232)（RGB 整体低于暗色底图）：
  // 乘以亮瓦片后整体压暗 ~15% 抑制伽马过曝，同时保持色温变化（夜间冷蓝、晨昏暖橙）。
  // 暗色底图保留近白偏暖以维持立体感。
  const lightBase = brightness === 'light'
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
 * 白天亮色底图用更柔和的雾蓝（避免亮面反射发白），暗色底图用饱和天蓝。
 * 夜间统一深空蓝黑，制造「球外深空」氛围。
 */
export function resolveGlobeSky(
  hour: number,
  brightness: BasemapBrightness,
): GlobeSkyParams {
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
