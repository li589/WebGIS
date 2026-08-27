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
    properties: { hemisphere: 'night-core' | 'terminator' }
    geometry:
      | { type: 'Polygon'; coordinates: number[][][] }
      | { type: 'LineString'; coordinates: number[][] }
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
 * 生成夜半球经纬度几何（真实太空观感的"自然"晨昏样式）：
 *
 * - **弯曲晨昏线**：按太阳赤纬精确求解晨昏线纬度边界 φc(λ)，
 *   极昼/极夜随日期自然出现（NASA Blue Marble 式球面形态）
 * - **夜侧均匀暗化**：单一 night-core 多边形（h<0 全暗区，硬边），
 *   明暗分界清晰可辨
 * - **line-blur 羽化过渡**：晨昏线 terminator 用 MapLibre 原生
 *   line-blur 宽线渲染（向两侧像素级羽化扩散），彻底取代多档
 *   条纹方案（档边界在渲染下可见、用户反馈"好多线"）
 * - antimeridian 拆分：多边形/线都沿 ±180° 切割成合法几何
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

  const LON_STEP = 1 // 晨昏线经度采样步长（1°：消除折点，高 zoom 下曲线平滑圆润）
  const features: NightHemisphereGeoJSON['features'] = []

  /** 归一化经度到 [-180, 180) */
  const normLon = (lon: number) => ((lon + 540) % 360) - 180

  /**
   * 构造夜核多边形（全暗区）。
   *
   * **完整晨昏圈构造**（非二分日）：夜半球边界 = 完整晨昏线大圆
   * （360° 一圈：夜侧北弧 + 昼侧南弧在赤道交点 λs±90 处连续衔接），
   * 极点侧用极线闭合（极夜覆盖全经度，不只是夜侧经度）。
   * ——旧的"仅夜侧经度弧段 + 赤道交点垂直边"构造会在 λs±90 处
   * 产生经向直边折点（用户反馈：大西洋/美洲海域各一个明显折点，
   * 晨昏线圈像被截成两段弧），且漏掉昼侧经度的南/北半球夜区。
   *
   * **曲线起点对齐 antimeridian**（λ=180+360k）：ring 的起终点闭合边
   * （下极点/上极点的垂直边）全部落在日期变更线上（与拆分接缝重合，
   * fill-outline-color 覆盖后不可见）——若起终点在赤道交点，闭合边会
   * 从赤道交点垂到极点形成可见细线（用户反馈：放远时毛刺 +
   * 南半球视角偶见"赤道交点连到南极"的细线）。
   *
   * 二分日（|δ|<0.5°）：夜侧 = 全纬度经度带（φc 恒 0 退化）。
   */
  const pushNightCore = () => {
    const equinox = Math.abs(decl) < 0.5
    const poleLat = southNight ? -90 : 90

    if (!equinox) {
      // 完整晨昏圈：起点对齐 antimeridian（≥ nightCenter-90 的最小 180+360k）
      const startLon =
        180 + 360 * Math.ceil((nightCenter - 90 - 180) / 360)
      const curve: number[][] = []
      for (let lon = startLon; lon <= startLon + 360 + 1e-9; lon += LON_STEP) {
        curve.push([lon, terminatorLatitude(lon, subsolarLon, decl)])
      }
      if (curve.length < 4) return
      // antimeridian 拆分（段内曲线 + 极点侧极线闭合，闭合边均在 antimeridian）
      const rings = splitClosedRingAtAntimeridian(curve, poleLat)
      for (const ring of rings) {
        features.push({
          type: 'Feature',
          properties: { hemisphere: 'night-core' },
          geometry: { type: 'Polygon', coordinates: [ring] },
        })
      }
      return
    }

    // 二分日：夜侧经度带全纬度（矩形带）
    const lonStart = nightCenter - 90
    const lonEnd = nightCenter + 90
    const upPts: number[][] = [] // 上沿（晨昏线）
    const dnPts: number[][] = [] // 下沿（极点侧）
    for (let lon = lonStart; lon <= lonEnd + 1e-9; lon += LON_STEP) {
      upPts.push([lon, 90])
      dnPts.push([lon, -90])
    }
    if (upPts.length < 3) return
    const rings = splitClosedRingAtAntimeridian(
      [...upPts, ...dnPts.slice().reverse()],
      0,
    )
    for (const ring of rings) {
      features.push({
        type: 'Feature',
        properties: { hemisphere: 'night-core' },
        geometry: { type: 'Polygon', coordinates: [ring] },
      })
    }
  }

  /**
   * 把闭合 ring 点列（经度连续未归一化，可能跨任意 antimeridian）
   * 拆为 [-180,180] 内的合法 ring 列表。
   * 每段闭合：段尾下到极点（poleLat）→ 沿极线横到段首经度 → 上到段首点。
   * poleLat 传 0 时极点闭合退化为直连（二分日上下沿已含极线）。
   */
  const splitClosedRingAtAntimeridian = (pts: number[][], poleLat: number): number[][][] => {
    const rings: number[][][] = []
    let cur: number[][] = []
    const flushSeg = () => {
      if (cur.length >= 3) {
        const ring = [...cur]
        if (poleLat === 0) {
          ring.push([...cur[0]])
        } else {
          ring.push([cur[cur.length - 1][0], poleLat])
          ring.push([cur[0][0], poleLat])
          ring.push([...cur[0]])
        }
        rings.push(ring)
      }
      cur = []
    }
    for (let i = 0; i < pts.length; i++) {
      const [lon, lat] = pts[i]
      const norm = normLon(lon)
      if (i > 0 && Math.abs(norm - normLon(pts[i - 1][0])) > 180) {
        // 经度跳变（跨 antimeridian）：在边界处插值闭合当前段。
        // ⚠️ 闭合点必须在**绝对经度空间**计算：normLon(180+360k) 会映射到
        // -180（而非 +180），直接用归一化边界算 frac 会外插出越界纬度。
        const [prevLon, prevLat] = pts[i - 1]
        const prevNorm = normLon(prevLon)
        const k = Math.floor((Math.min(prevLon, lon) + 180) / 360)
        const lambdaB = 180 + 360 * k // 区间内的 antimeridian 绝对经度
        const frac = (lambdaB - prevLon) / (lon - prevLon)
        const latB = prevLat + (lat - prevLat) * frac
        // 显示经度：跳变两侧一正一负——前段闭合取 prevNorm 侧、新段起点取 norm 侧
        cur.push([prevNorm > 0 ? 180 : -180, latB])
        flushSeg()
        cur.push([norm > 0 ? 180 : -180, latB])
      }
      cur.push([norm, lat])
    }
    flushSeg()
    return rings
  }

  /**
   * 构造晨昏线 linestring（line-blur 羽化的载体）：
   * - δ≥0.5°：完整晨昏圈曲线（360° 连续大圆），antimeridian 断开
   * - δ<0.5°（二分日）：退化为两条经线线段（λn±90，φ 从 -90 到 90）
   */
  const pushTerminatorLines = () => {
    const lines: number[][][] = []
    if (Math.abs(decl) < 0.5) {
      // 二分日：晨昏线 = 两条经线（夜心 ±90°）
      const lonW = normLon(nightCenter - 90)
      const lonE = normLon(nightCenter + 90)
      lines.push([[lonW, -90], [lonW, 90]])
      lines.push([[lonE, -90], [lonE, 90]])
    } else {
      // 完整晨昏圈：起点对齐 antimeridian（与夜核一致——断口在日期变更线，
      // 与拆分接缝/闭合边重合，视觉上不显眼）
      const startLon =
        180 + 360 * Math.ceil((nightCenter - 90 - 180) / 360)
      let cur: number[][] = []
      const flush = () => {
        if (cur.length >= 2) lines.push(cur)
        cur = []
      }
      let prevNorm: number | null = null
      for (let lon = startLon; lon <= startLon + 360 + 1e-9; lon += LON_STEP) {
        const phiC = terminatorLatitude(lon, subsolarLon, decl)
        const norm = normLon(lon)
        if (prevNorm !== null && Math.abs(norm - prevNorm) > 180) {
          flush()
        }
        cur.push([norm, phiC])
        prevNorm = norm
      }
      flush()
    }
    for (const line of lines) {
      features.push({
        type: 'Feature',
        properties: { hemisphere: 'terminator' },
        geometry: { type: 'LineString', coordinates: line },
      })
    }
  }

  pushNightCore()
  pushTerminatorLines()
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
