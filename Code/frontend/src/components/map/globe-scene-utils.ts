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
 * 太阳下点经度（本地时间模型）。
 * hour 是**本地时间轴小时**（如中国 UTC+8 的 12:00 = UTC 04:00），
 * 必须先换算 UTC 再按下点公式：utcHour = hour - tzOffset，
 * subsolarLon = (12 - utcHour) × 15°。
 * 北京时间正午（hour=12, tz=+8）：太阳下点 120°E（杭州附近）✓
 * tzOffsetHours 缺省取运行环境本地时区（浏览器/Node）。
 */
export function subsolarLongitude(hour: number, tzOffsetHours?: number): number {
  const tz = tzOffsetHours ?? -new Date().getTimezoneOffset() / 60
  const utcHour = (((hour - tz) % 24) + 24) % 24
  return ((12 - utcHour) * 15 + 540) % 360 - 180
}

/**
 * 太阳赤纬（度），Cooper 近似：δ = 23.45° × sin(360° × (284 + n) / 365)。
 * n = 年内第几天。精度约 ±1°，对晨昏线视觉完全足够。
 * date 缺省时取当前日期。
 */
export function subsolarDeclination(date?: Date): number {
  const d = date ?? new Date()
  const start = Date.UTC(d.getUTCFullYear(), 0, 0)
  const dayOfYear = Math.floor((d.getTime() - start) / 86400000)
  return 23.45 * Math.sin(((360 * (284 + dayOfYear)) / 365) * (Math.PI / 180))
}

export interface NightHemisphereGeoJSON {
  type: 'FeatureCollection'
  features: Array<{
    type: 'Feature'
    properties: { hemisphere: 'night'; tier: number }
    geometry: {
      type: 'Polygon'
      coordinates: number[][][]
    }
  }>
}

/**
 * 晨昏线纬度边界（真实球面几何，不是经度矩形）：
 * 点 (φ, λ) 位于晨昏线上 ⟺ 太阳高度角 h = 0：
 *   cosφ·cosδ·cos(λ-λs) + sinφ·sinδ = 0
 * 解出边界纬度（δ≠0 时）：
 *   φc(λ) = atan(-cosδ·cos(λ-λs) / sinδ)
 * δ>0（北夏）：夜侧 = φ < φc(λ)（南极极夜、北极极昼自然出现）
 * δ<0（北冬）：夜侧 = φ > φc(λ)
 * δ=0（二分日）：退化为经度跨度 180° 的矩形带（φc 恒 0）
 */
function terminatorLatitude(lonDeg: number, subsolarLon: number, declDeg: number): number {
  if (Math.abs(declDeg) < 0.5) return 0
  const declRad = (declDeg * Math.PI) / 180
  const hourRad = ((lonDeg - subsolarLon) * Math.PI) / 180
  const ratio = (-Math.cos(declRad) * Math.cos(hourRad)) / Math.sin(declRad)
  return (Math.atan(ratio) * 180) / Math.PI
}

/**
 * 生成夜半球经纬度多边形（真实太空观感的"自然"晨昏样式）：
 *
 * - **弯曲晨昏线**：按太阳赤纬精确求解晨昏线纬度边界 φc(λ)，
 *   极昼/极夜随日期自然出现（NASA Blue Marble 式球面形态）
 * - **夜侧均匀暗化**：全夜核区（距晨昏线 >18°）统一高不透明度，
 *   明暗分界清晰可辨（修正"看不出哪边暗哪边亮"）
 * - **窄过渡带**：晨昏线附近 18° 内 12 档渐隐（每档 1.5°），
 *   互不重叠（MapLibre fill stencil 去重使嵌套叠加无效），
 *   无彩色条带——太空摄影中晨昏线就是平滑的明暗渐变
 * - antimeridian 拆分：多边形沿 ±180° 切割成合法 ring
 */
export function buildNightHemisphereGeoJSON(
  hour: number,
  date?: Date,
  tzOffsetHours?: number,
): NightHemisphereGeoJSON {
  const subsolarLon = subsolarLongitude(hour, tzOffsetHours)
  const decl = subsolarDeclination(date)
  const nightCenter = subsolarLon + 180
  const southNight = decl >= 0 // δ≥0：夜侧偏南；δ<0：夜侧偏北

  const TRANSITION_BANDS = 36 // 过渡带档数（18° / 0.5°，平滑无条纹）
  const BAND_STEP = 0.5
  const LON_STEP = 3 // 晨昏线经度采样步长
  const features: NightHemisphereGeoJSON['features'] = []

  /** 归一化经度到 [-180, 180) */
  const normLon = (lon: number) => ((lon + 540) % 360) - 180

  /**
   * 按"夜侧纬度偏移"构造一个带多边形：
   * bandOffset = 距晨昏线的偏移（度，向夜侧），带下沿 = 上沿 - BAND_STEP。
   * 沿 λ ∈ [nightCenter-90, nightCenter+90] 采样 φc(λ)，
   * 多边形 = [上沿曲线(λ 递增)] + [下沿曲线(λ 递减)] 闭合。
   * 极点侧开放到 ±90°（isCore=true 的全夜核）。
   */
  const pushBand = (bandOffset: number, tier: number, isCore: boolean) => {
    const lonStart = nightCenter - 90
    const lonEnd = nightCenter + 90
    const upPts: number[][] = [] // 上沿（晨昏线侧）
    const dnPts: number[][] = [] // 下沿（夜心侧）
    for (let lon = lonStart; lon <= lonEnd + 1e-9; lon += LON_STEP) {
      const phiC = terminatorLatitude(lon, subsolarLon, decl)
      // δ>0：夜侧在南（φ 更小）；δ<0：夜侧在北（φ 更大）
      // 双向 clamp：极昼区（up 越过极点）形成零宽退化段，不产生越界纬度
      const up = southNight
        ? Math.max(Math.min(phiC - bandOffset, 90), -90)
        : Math.min(Math.max(phiC + bandOffset, -90), 90)
      const dn = isCore
        ? southNight ? -90 : 90
        : southNight
          ? Math.max(phiC - (bandOffset + BAND_STEP), -90)
          : Math.min(phiC + (bandOffset + BAND_STEP), 90)
      // 该经度段无夜侧（极昼）则跳过；下沿被 clamp 到极点时整段恒夜仍生成
      const hasNight = southNight ? up > dn : up < dn
      if (!hasNight && !isCore) continue
      upPts.push([lon, up])
      dnPts.push([lon, dn])
    }
    if (upPts.length < 3) return

    // 按 antimeridian 切分：点列经度连续（未归一化），在跨 ±180 处插值切段
    const rings: number[][][] = []
    let upCur: number[][] = []
    let dnCur: number[][] = []
    const flush = (boundaryLon: number | null) => {
      if (upCur.length >= 3) {
        const ring = [...upCur]
        for (let i = dnCur.length - 1; i >= 0; i--) ring.push(dnCur[i])
        ring.push([...upCur[0]])
        rings.push(ring)
      }
      upCur = []
      dnCur = []
      void boundaryLon
    }
    for (let i = 0; i < upPts.length; i++) {
      const [lon, up] = upPts[i]
      const dn = dnPts[i][1]
      const norm = normLon(lon)
      if (i > 0) {
        const prevNorm = normLon(upPts[i - 1][0])
        // 经度跳变（跨 antimeridian）：在边界处插值闭合当前段
        if (Math.abs(norm - prevNorm) > 180) {
          const prevLon = upPts[i - 1][0]
          const prevUp = upPts[i - 1][1]
          const prevDn = dnPts[i - 1][1]
          // 采样经度递增：跳变时 norm<0（从 +178 跳到 -178），
          // 前段在 +180 闭合、新段从 -180 起（norm>0 的递减情形反之）
          const boundary = norm > 0 ? 180 : -180
          const prevBoundary = norm > 0 ? -180 : 180
          // 当前段在 prevBoundary 闭合（纬度线性插值到边界）
          const frac = (prevBoundary - prevLon) / (lon - prevLon)
          const upB = prevUp + (up - prevUp) * frac
          const dnB = prevDn + (dn - prevDn) * frac
          upCur.push([prevBoundary, upB])
          dnCur.push([prevBoundary, dnB])
          flush(prevBoundary)
          // 新段从 boundary 起
          upCur.push([boundary, upB])
          dnCur.push([boundary, dnB])
        }
      }
      upCur.push([norm, up])
      dnCur.push([norm, dn])
    }
    flush(null)

    for (const ring of rings) {
      features.push({
        type: 'Feature',
        properties: { hemisphere: 'night', tier },
        geometry: { type: 'Polygon', coordinates: [ring] },
      })
    }
  }

  // 过渡带：tier 0（贴晨昏线，最淡）→ tier 11（最靠近全夜核）
  // opacity 在 fill layer 按 tier 数据驱动插值（tier 越大越暗）
  for (let t = 0; t < TRANSITION_BANDS; t++) {
    pushBand(t * BAND_STEP, t, false)
  }
  // 全夜核区（距晨昏线 ≥18° 直到夜心）：tier = TRANSITION_BANDS，opacity 最高
  pushBand(TRANSITION_BANDS * BAND_STEP, TRANSITION_BANDS, true)

  return { type: 'FeatureCollection', features }
}

function clamp(v: number, min: number, max: number): number {
  return v < min ? min : v > max ? max : v
}

/**
 * 解析光照参数（当前仅测试使用；globe 模式已停用 setLight——
 * raster 瓦片不吃 light，昼夜由夜半球遮罩负责）。
 * - 亮色底图：直射强度 ×0.5 + 太阳高度上限 36°（柔和长影）+ light color 偏冷白
 * - 影像/地形：×0.78 + 50° + 近白偏暖
 * - 暗色底图：×1.0 + 64° + 暖白（保留立体光影冲击）
 * - off 返回 null（不设置自定义光照）
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
  // 直射强度：正午 0.95、夜间 0.4 的基准随底图缩放（亮色底图上限更严）
  const intensity = clamp((0.4 + daylight * 0.55) * brightnessScale, 0.18, 1.0)

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
