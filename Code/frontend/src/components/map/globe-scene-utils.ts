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

/**
 * 时间轴小时对应的太阳下点经度（简化无日期模型，太阳赤纬取 0°）。
 * hour=12 时太阳位于 0° 经线；hour=0 时位于 180° 经线。
 * 该值只用于 raster 底图的昼夜遮罩，避免误把 MapLibre light 当成 raster 光照。
 */
export function subsolarLongitude(hour: number): number {
  const normalized = ((hour % 24) + 24) % 24
  return ((12 - normalized) * 15 + 540) % 360 - 180
}

export interface NightHemisphereGeoJSON {
  type: 'FeatureCollection'
  features: Array<{
    type: 'Feature'
    properties: { hemisphere: 'night' | 'twilight'; tier: number }
    geometry: {
      type: 'Polygon'
      coordinates: number[][][]
    }
  }>
}

/**
 * 生成夜半球经纬度多边形（按 180° 经线拆分，避免 GeoJSON 跨日期变更线）。
 * 太阳赤纬取 0° 时夜半球是经度跨度 180° 的半球，极点始终位于边界两侧。
 *
 * ⚠️ 实现约束（MapLibre fill 的 stencil 去重）：同一 fill layer 内
 * 重叠的多边形只会被绘制一次——**嵌套/叠加矩形做渐变的方案无效**
 * （曾导致"阴面完全看不见，只剩一条淡红带"）。
 * 因此这里生成 60 档**互不重叠**的相邻环带（夜心左右对称各一条），
 * 每档 opacity 由 fill layer 的数据驱动表达式按 tier 插值
 * （夜心 tier=0 最暗 → 晨昏线 tier=59 最淡），1.5° 档差视觉连续无缝。
 *
 * twilight：晨昏线两侧 ±11°/±5° 两层宽度的暖橙光带（日出日落辉光）。
 */
export function buildNightHemisphereGeoJSON(hour: number): NightHemisphereGeoJSON {
  const nightCenter = subsolarLongitude(hour) + 180
  const TIER_COUNT = 60
  const bandStep = 90 / TIER_COUNT // 每档 1.5°
  const makeRing = (west: number, east: number): number[][] => [
    [west, -90],
    [east, -90],
    [east, 90],
    [west, 90],
    [west, -90],
  ]
  /** 把 [west, east] 矩形（可跨任意多个 antimeridian）拆为 [-180,180] 内的合法 ring 列表 */
  const pushRect = (
    west: number,
    east: number,
    props: { hemisphere: 'night' | 'twilight'; tier: number },
    features: NightHemisphereGeoJSON['features'],
  ) => {
    if (east - west <= 0) return
    let w = west
    while (w < east) {
      // w 所在的 360° 周期（[-180,180] 显示区的平移副本）
      const k = Math.floor((w + 180) / 360)
      const right = k * 360 + 180
      const segEnd = Math.min(east, right)
      // 段 [w, segEnd] 平移回显示区 [-180, 180]
      const shift = -k * 360
      const dispW = w + shift
      const dispE = segEnd + shift
      if (dispE > dispW) {
        features.push({
          type: 'Feature',
          properties: { ...props },
          geometry: { type: 'Polygon', coordinates: [makeRing(dispW, dispE)] },
        })
      }
      w = segEnd
    }
  }

  const features: NightHemisphereGeoJSON['features'] = []
  const center = ((nightCenter + 540) % 360) - 180
  for (let t = 0; t < TIER_COUNT; t++) {
    const inner = t * bandStep
    const outer = (t + 1) * bandStep
    // 左右对称的两条相邻带（互不重叠）：tier 越大离夜心越远越淡
    pushRect(center + inner, center + outer, { hemisphere: 'night', tier: t }, features)
    pushRect(center - outer, center - inner, { hemisphere: 'night', tier: t }, features)
  }
  // 晨昏暖光带：晨昏线（center ±90°）两侧各两层宽度做柔边
  pushRect(center + 90 - 11, center + 90 + 11, { hemisphere: 'twilight', tier: 0 }, features)
  pushRect(center + 90 - 5, center + 90 + 5, { hemisphere: 'twilight', tier: 1 }, features)
  pushRect(center - 90 - 11, center - 90 + 11, { hemisphere: 'twilight', tier: 0 }, features)
  pushRect(center - 90 - 5, center - 90 + 5, { hemisphere: 'twilight', tier: 1 }, features)
  return { type: 'FeatureCollection', features }
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
 * - soft 档：强度 ×0.55 + 光色整体压暗 ~12% + 太阳高度角抬高（光线更平柔），
 *   三重叠加确保与标准档肉眼可辨；off 返回 null（不设置自定义光照）
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
  const isSoft = mode === 'soft'

  const brightnessScale =
    brightness === 'light' ? 0.5 : brightness === 'dark' ? 1.0 : 0.78
  const modeScale = isSoft ? 0.55 : 1.0
  // 直射强度：正午 0.95、夜间 0.4 的基准随底图/档位缩放（亮色底图上限更严）
  const intensity = clamp((0.4 + daylight * 0.55) * brightnessScale * modeScale, 0.18, 1.0)

  // 太阳高度：亮色底图更低更斜（柔和长影），暗色底图更高（强立体感）；
  // soft 档整体抬高 8°（光线更平、阴影更淡）
  const elevationBase = (brightness === 'light' ? 10 : brightness === 'dark' ? 20 : 16) + (isSoft ? 8 : 0)
  const elevationRange = brightness === 'light' ? 26 : brightness === 'dark' ? 44 : 34
  const elevation = elevationBase + daylight * elevationRange

  // 光照色温 = MapLibre light color，会直接乘到瓦片像素上。
  // 亮色底图用「偏冷白」rgb(215, 226, 232)（RGB 整体低于暗色底图）：
  // 乘以亮瓦片后整体压暗 ~15% 抑制伽马过曝，同时保持色温变化（夜间冷蓝、晨昏暖橙）。
  // 暗色底图保留近白偏暖以维持立体感。soft 档再整体压暗 12%（柔化高光）。
  const softDim = isSoft ? 0.88 : 1.0
  const lightBase = brightness === 'light'
    ? { warm: 213, green: 224, blue: 230 }
    : brightness === 'dark'
      ? { warm: 255, green: 246, blue: 232 }
      : { warm: 244, green: 240, blue: 232 }
  const warm = Math.round((lightBase.warm - twilight * (lightBase.warm === 255 ? 28 : 24)) * softDim)
  const green = Math.round((lightBase.green - twilight * 56) * softDim)
  const blue = Math.round((lightBase.blue - twilight * 40) * softDim)
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
