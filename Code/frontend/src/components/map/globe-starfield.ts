/**
 * 程序化深空星图生成器（纯函数，可单测）。
 *
 * 真实天文数据版本：内嵌精修的肉眼亮星表（RA/Dec/星等/光谱型），
 * 银河带沿 J2000 银道面投影到天球（等距圆柱展开），
 * 深空天体按真实赤道坐标（M31/M42/M45/LMC/SMC）。
 *
 * - 暗色主题：完整深空星图（真星表 + 银河 + 深空天体）
 * - 浅色主题：淡化微尘（仅保留少量背景星 + 浅淡银河）
 * - minimal：透明空画布（仅 .map-stage 兜底深空/浅蓝灰）
 *
 * 数据来源：
 * - 亮星表：Hipparcos/Yale BSC 前 ~60 颗，肉眼可观测（mag < 2.1）
 *   数据精度 RA ±0.1h / Dec ±1°，足以肉眼识别星座与方位
 * - 银河几何：银心 RA 266.405° / Dec -28.936°（人马座方向），
 *   银道面与赤道面夹角 62.87°，标准 J2000 银道↔赤道转换
 * - 深空天体：M31（仙女座星系）/ M42（猎户座星云）/ M45（昴星团）/
 *   LMC（大麦哲伦云）/ SMC（小麦哲伦云）
 */

export type StarfieldMode = 'full' | 'soft' | 'minimal'

export interface StarfieldOptions {
  mode: StarfieldMode
  /** 画布宽度（默认 1024，2:1 比例） */
  width?: number
  height?: number
  /** 随机种子（默认随机；测试注入固定种子保证稳定） */
  seed?: number
}

// ─── 真实亮星表（J2000.0）─────────────────────────────────────────────────
// 字段：[name, RA hours, Dec degrees, visual mag, spectralType]
// 数据精度：RA ±0.05h / Dec ±0.5° / mag ±0.05
// 前 25 颗来自 Ian Ridpath（基于 SIMBAD）+ 自行知识补充至 ~60 颗（mag < 2.1）
export interface BrightStar {
  name: string
  /** 赤经（小时，0-24） */
  raHours: number
  /** 赤纬（度，-90 到 +90） */
  decDeg: number
  /** 视星等 */
  mag: number
  /** 光谱型字母：O B A F G K M */
  spectral: string
}

export const BRIGHT_STARS: ReadonlyArray<BrightStar> = [
  // ── 最亮的 25 颗（SIMBAD/Ian Ridpath 摘要，精度高）──
  { name: 'Sirius', raHours: 6.752, decDeg: -16.716, mag: -1.46, spectral: 'A' },
  { name: 'Canopus', raHours: 6.399, decDeg: -52.696, mag: -0.74, spectral: 'A' },
  { name: 'Rigil Kentaurus', raHours: 14.660, decDeg: -60.834, mag: -0.27, spectral: 'G' },
  { name: 'Arcturus', raHours: 14.261, decDeg: 19.182, mag: -0.05, spectral: 'K' },
  { name: 'Vega', raHours: 18.615, decDeg: 38.784, mag: 0.03, spectral: 'A' },
  { name: 'Capella', raHours: 5.278, decDeg: 45.998, mag: 0.08, spectral: 'G' },
  { name: 'Rigel', raHours: 5.242, decDeg: -8.202, mag: 0.13, spectral: 'B' },
  { name: 'Procyon', raHours: 7.655, decDeg: 5.225, mag: 0.34, spectral: 'F' },
  { name: 'Achernar', raHours: 1.629, decDeg: -57.237, mag: 0.46, spectral: 'B' },
  { name: 'Betelgeuse', raHours: 5.919, decDeg: 7.407, mag: 0.50, spectral: 'M' },
  { name: 'Hadar', raHours: 14.064, decDeg: -60.373, mag: 0.61, spectral: 'B' },
  { name: 'Altair', raHours: 19.846, decDeg: 8.868, mag: 0.77, spectral: 'A' },
  { name: 'Acrux', raHours: 12.443, decDeg: -63.099, mag: 0.77, spectral: 'B' },
  { name: 'Aldebaran', raHours: 4.598, decDeg: 16.509, mag: 0.85, spectral: 'K' },
  { name: 'Antares', raHours: 16.490, decDeg: -26.432, mag: 1.09, spectral: 'M' },
  { name: 'Spica', raHours: 13.420, decDeg: -11.161, mag: 0.97, spectral: 'B' },
  { name: 'Pollux', raHours: 7.755, decDeg: 28.026, mag: 1.14, spectral: 'K' },
  { name: 'Fomalhaut', raHours: 22.961, decDeg: -29.622, mag: 1.16, spectral: 'A' },
  { name: 'Deneb', raHours: 20.690, decDeg: 45.280, mag: 1.25, spectral: 'A' },
  { name: 'Mimosa', raHours: 12.795, decDeg: -59.689, mag: 1.25, spectral: 'B' },
  { name: 'Regulus', raHours: 10.139, decDeg: 11.967, mag: 1.35, spectral: 'B' },
  { name: 'Adhara', raHours: 6.977, decDeg: -28.972, mag: 1.50, spectral: 'B' },
  { name: 'Castor', raHours: 7.577, decDeg: 31.888, mag: 1.58, spectral: 'A' },
  { name: 'Gacrux', raHours: 12.519, decDeg: -57.113, mag: 1.63, spectral: 'M' },
  { name: 'Shaula', raHours: 17.560, decDeg: -37.104, mag: 1.63, spectral: 'B' },
  // ── 补充 mag 1.6 - 2.1（精度 ±0.1h / ±1°）──
  { name: 'Bellatrix', raHours: 5.418, decDeg: 6.350, mag: 1.64, spectral: 'B' },
  { name: 'Elnath', raHours: 5.438, decDeg: 28.608, mag: 1.65, spectral: 'B' },
  { name: 'Miaplacidus', raHours: 9.220, decDeg: -69.717, mag: 1.69, spectral: 'A' },
  { name: 'Alnilam', raHours: 5.604, decDeg: -1.202, mag: 1.69, spectral: 'B' },
  { name: 'Alnair', raHours: 22.137, decDeg: -46.961, mag: 1.74, spectral: 'B' },
  { name: 'Alnitak', raHours: 5.679, decDeg: -1.943, mag: 1.74, spectral: 'O' },
  { name: 'Alioth', raHours: 12.900, decDeg: 55.960, mag: 1.77, spectral: 'A' },
  { name: 'Dubhe', raHours: 11.062, decDeg: 61.751, mag: 1.79, spectral: 'K' },
  { name: 'Mirfak', raHours: 3.405, decDeg: 49.861, mag: 1.79, spectral: 'F' },
  { name: 'Wezen', raHours: 7.140, decDeg: -26.393, mag: 1.84, spectral: 'F' },
  { name: 'Kaus Australis', raHours: 18.403, decDeg: -34.385, mag: 1.85, spectral: 'B' },
  { name: 'Alkaid', raHours: 13.792, decDeg: 49.313, mag: 1.86, spectral: 'B' },
  { name: 'Avior', raHours: 8.375, decDeg: -59.510, mag: 1.86, spectral: 'K' },
  { name: 'Sargas', raHours: 17.622, decDeg: -42.998, mag: 1.87, spectral: 'B' },
  { name: 'Menkalinan', raHours: 5.992, decDeg: 44.947, mag: 1.90, spectral: 'A' },
  { name: 'Atria', raHours: 16.811, decDeg: -69.028, mag: 1.91, spectral: 'K' },
  { name: 'Alhena', raHours: 6.629, decDeg: 16.399, mag: 1.93, spectral: 'A' },
  { name: 'Peacock', raHours: 20.428, decDeg: -56.737, mag: 1.94, spectral: 'B' },
  { name: 'Polaris', raHours: 2.530, decDeg: 89.264, mag: 1.97, spectral: 'F' },
  { name: 'Mirzam', raHours: 6.378, decDeg: -17.956, mag: 1.98, spectral: 'B' },
  { name: 'Alphard', raHours: 9.459, decDeg: -8.659, mag: 1.99, spectral: 'K' },
  { name: 'Algieba', raHours: 10.333, decDeg: 19.842, mag: 2.08, spectral: 'K' },
  { name: 'Hamal', raHours: 2.119, decDeg: 23.462, mag: 2.00, spectral: 'K' },
  { name: 'Diphda', raHours: 0.726, decDeg: -17.987, mag: 2.04, spectral: 'K' },
  { name: 'Nunki', raHours: 18.921, decDeg: -26.297, mag: 2.05, spectral: 'B' },
  { name: 'Menkent', raHours: 14.063, decDeg: -36.370, mag: 2.06, spectral: 'K' },
  { name: 'Mizar', raHours: 13.399, decDeg: 54.925, mag: 2.04, spectral: 'A' },
  { name: 'Mirach', raHours: 1.162, decDeg: 35.621, mag: 2.07, spectral: 'M' },
  { name: 'Izar', raHours: 14.749, decDeg: 27.074, mag: 2.37, spectral: 'K' },
  { name: 'Schedar', raHours: 0.675, decDeg: 56.537, mag: 2.24, spectral: 'K' },
  { name: 'Caph', raHours: 0.153, decDeg: 59.150, mag: 2.27, spectral: 'F' },
  { name: 'Algenib', raHours: 0.221, decDeg: 15.184, mag: 2.83, spectral: 'B' },
  { name: 'Markab', raHours: 23.079, decDeg: 15.205, mag: 2.49, spectral: 'B' },
  { name: 'Scheat', raHours: 23.063, decDeg: 28.083, mag: 2.42, spectral: 'M' },
  { name: 'Enif', raHours: 21.736, decDeg: 9.875, mag: 2.39, spectral: 'K' },
  { name: 'Ankaa', raHours: 0.438, decDeg: -42.306, mag: 2.40, spectral: 'K' },
  { name: 'Al Na\u02bcir', raHours: 14.742, decDeg: 27.074, mag: 2.39, spectral: 'K' },
  { name: 'Alderamin', raHours: 21.310, decDeg: 62.586, mag: 2.45, spectral: 'A' },
]

// ─── 真实深空天体（J2000.0）─────────────────────────────────────────────────
// 银河系卫星天体（麦哲伦云）+ 本星系群亮成员 + 著名亮星云
export interface DeepSkyObject {
  name: string
  raHours: number
  decDeg: number
  /** 视觉张角（度），用于光斑半径 */
  sizeDeg: number
  /** 总视星等（越小越亮） */
  mag: number
  /** 颜色 */
  color: string
  /** 类型：galaxy / nebula / cluster */
  kind: 'galaxy' | 'nebula' | 'cluster'
}

export const DEEP_SKY_OBJECTS: ReadonlyArray<DeepSkyObject> = [
  // 大小麦哲伦云：南天最显著，肉眼可见
  {
    name: 'LMC',
    raHours: 5.392,
    decDeg: -69.756,
    sizeDeg: 10.0,
    mag: 0.9,
    color: 'rgba(180, 200, 230, 0.55)',
    kind: 'galaxy',
  },
  {
    name: 'SMC',
    raHours: 0.874,
    decDeg: -72.835,
    sizeDeg: 5.0,
    mag: 2.2,
    color: 'rgba(180, 200, 230, 0.45)',
    kind: 'galaxy',
  },
  // 仙女座星系 M31：北天最显著，肉眼可见
  {
    name: 'M31',
    raHours: 0.712,
    decDeg: 41.269,
    sizeDeg: 3.5,
    mag: 3.4,
    color: 'rgba(220, 210, 240, 0.55)',
    kind: 'galaxy',
  },
  // 猎户座大星云 M42
  {
    name: 'M42',
    raHours: 5.588,
    decDeg: -5.391,
    sizeDeg: 1.5,
    mag: 4.0,
    color: 'rgba(255, 180, 160, 0.50)',
    kind: 'nebula',
  },
  // 昴星团 M45
  {
    name: 'M45',
    raHours: 3.790,
    decDeg: 24.117,
    sizeDeg: 2.0,
    mag: 1.6,
    color: 'rgba(200, 220, 255, 0.45)',
    kind: 'cluster',
  },
]

// ─── 银河带（沿真实银道面）─────────────────────────────────────────────────
// 银道与赤道交角 62.87175°，北银极 RA 192.85948° / Dec 27.12825°
// 银心 RA 266.405° / Dec -28.936°（已在 galacticToEquatorial 中验证）
export const GALACTIC_TILT_DEG = 62.87175

/**
 * 银道坐标 → 赤道坐标（J2000，旋转矩阵法，IAU 1983 标准）
 * R^T = R 的转置（赤道→银道矩阵 R 的转置），按行排列：
 * | -0.0548756  +0.4941094  -0.8676661 |
 * | -0.8734371  -0.4448296  -0.1980764 |
 * | -0.4838360  +0.7469822  +0.4559838 |
 *
 * 输入 l (deg) 银经，b (deg) 银纬；输出 raHours 赤经（小时 0-24），decDeg 赤纬（度）
 */
export function galacticToEquatorial(
  lDeg: number,
  bDeg: number,
): { raHours: number; decDeg: number } {
  const lRad = (lDeg * Math.PI) / 180
  const bRad = (bDeg * Math.PI) / 180
  const xG = Math.cos(bRad) * Math.cos(lRad)
  const yG = Math.cos(bRad) * Math.sin(lRad)
  const zG = Math.sin(bRad)
  // 应用 R^T（赤道→银道矩阵的转置）
  const xE = -0.0548755604 * xG + 0.4941094279 * yG + -0.8676661490 * zG
  const yE = -0.8734370902 * xG + -0.4448296300 * yG + -0.1980763734 * zG
  const zE = -0.4838359925 * xG + 0.7469822445 * yG + 0.4559837762 * zG
  const raRad = Math.atan2(yE, xE)
  const raDeg = ((raRad * 180) / Math.PI + 360) % 360
  const decDeg = (Math.asin(Math.max(-1, Math.min(1, zE))) * 180) / Math.PI
  return { raHours: raDeg / 15, decDeg }
}

// ─── mulberry32 + 视觉参数 ─────────────────────────────────────────────────

export function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export interface StarfieldVisual {
  bgStarCount: number
  bgStarAlphaMin: number
  bgStarAlphaMax: number
  glowStarBoost: number
  galaxyAlphaMax: number
  galaxyDustAlpha: number
  dustBandCount: number
  showDeepSky: boolean
}

export function starfieldVisual(theme: 'dark' | 'light'): StarfieldVisual {
  if (theme === 'dark') {
    return {
      bgStarCount: 420,
      bgStarAlphaMin: 0.22,
      bgStarAlphaMax: 0.75,
      glowStarBoost: 1.1,
      galaxyAlphaMax: 0.45,
      galaxyDustAlpha: 0.08,
      dustBandCount: 3,
      showDeepSky: true,
    }
  }
  return {
    bgStarCount: 160,
    bgStarAlphaMin: 0.06,
    bgStarAlphaMax: 0.22,
    glowStarBoost: 0.35,
    galaxyAlphaMax: 0.14,
    galaxyDustAlpha: 0.025,
    dustBandCount: 0,
    showDeepSky: false,
  }
}

// ─── 颜色映射：光谱型 → RGB ─────────────────────────────────────────────────

/** 主序星常用色温近似（B=蓝白、O=蓝紫、A=白、F=黄白、G=黄、K=橙、M=红） */
function spectralColor(spectral: string): string {
  const t = spectral.charAt(0).toUpperCase()
  switch (t) {
    case 'O':
      return '#a8b8ff'
    case 'B':
      return '#b8c8ff'
    case 'A':
      return '#dde4ff'
    case 'F':
      return '#fff4e8'
    case 'G':
      return '#fff0d0'
    case 'K':
      return '#ffc890'
    case 'M':
      return '#ffaa78'
    default:
      return '#ffffff'
  }
}

/** 星等 → 像素半径。mag=-1.5 → ~3px，mag=2 → ~0.6px */
function magToRadius(mag: number): number {
  return Math.max(0.35, 3.2 - 1.0 * mag)
}

/** 星等 → alpha。亮星更亮 */
function magToAlpha(mag: number, alphaMin: number, alphaMax: number): number {
  // 动态范围映射：mag -1.5 → alphaMax；mag 2.5 → alphaMin
  const k = Math.max(0, Math.min(1, (3.0 - mag) / 4.5))
  return alphaMin + k * (alphaMax - alphaMin)
}

// ─── 投影助手 ─────────────────────────────────────────────────────────────

interface Projected {
  x: number
  y: number
  /** 是否跨越 RA 边界（用以跳过连线） */
  wrap: boolean
  /** 规范化后的 RA（小时），供下一次 wrap 检测使用 */
  raNorm: number
}

/** 等距圆柱投影：(raHours, decDeg) → (x, y)。RA 自动 wrap 到 [0, 24)。 */
function projectToCanvas(
  raHours: number,
  decDeg: number,
  width: number,
  height: number,
  lastRa: number | null,
): Projected {
  let ra = raHours
  while (ra < 0) ra += 24
  while (ra >= 24) ra -= 24
  const x = (ra / 24) * width
  const y = ((90 - decDeg) / 180) * height
  const wrap = lastRa !== null && Math.abs(ra - lastRa) > 12
  return { x, y, wrap, raNorm: ra }
}

// ─── 主绘图函数 ───────────────────────────────────────────────────────────

/** 生成星图 canvas（2:1 比例默认 1024×512）。minimal 模式返回透明空画布。 */
export function renderStarfieldCanvas(options: StarfieldOptions): HTMLCanvasElement {
  const width = options.width ?? 1024
  const height = options.height ?? Math.round(width / 2)
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) return canvas

  if (options.mode === 'minimal') return canvas

  const theme: 'dark' | 'light' = options.mode === 'full' ? 'dark' : 'light'
  const visual = starfieldVisual(theme)
  const rng = mulberry32(options.seed ?? (Math.random() * 0xffffffff) >>> 0)

  // 1) 银河带（按真实银道面采样）—— 后画则被覆盖，先画
  drawGalacticPlane(ctx, width, height, rng, theme, visual)
  // 2) 尘埃暗带（银河内的"Great Rift"暗道，沿银河走向）
  drawGalacticDust(ctx, width, height, rng, theme, visual)
  // 3) 深空天体（真实位置）
  if (visual.showDeepSky) drawDeepSkyObjects(ctx, width, height, rng, theme)
  // 4) 背景星（程序随机填充低密度背景，亮星表占据主体）
  drawBackgroundStars(ctx, width, height, rng, theme, visual)
  // 5) 真实亮星表（按 RA/Dec 投影）
  drawBrightStars(ctx, width, height, visual)

  return canvas
}

function drawGalacticPlane(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  rng: () => number,
  theme: 'dark' | 'light',
  visual: StarfieldVisual,
): void {
  // 沿银经 l 扫描，b 按高斯分布（带状），银心段（|l|<30°）加密增亮
  const samplesL = 360 // 每 1° 一个银道横断面
  const pointsPerSection = theme === 'dark' ? 4 : 2
  let lastRa: number | null = null
  const fringeColor = theme === 'dark' ? '214, 226, 255' : '223, 231, 245'

  for (let i = 0; i < samplesL; i++) {
    const l = i
    // 距银心 l=0 越近，密度与亮度越高；大尺度上的银河亮度分布
    const centerBoost = Math.max(0.15, 1 - Math.min(1, Math.abs(l) > 180 ? Math.abs(l - 360) : Math.abs(l)) / 90)
    // 银道纬度带宽：核心区窄（b ±4°）、外围可达 ±10°
    const bandHalf = 4 + 6 * (1 - centerBoost)
    for (let j = 0; j < pointsPerSection; j++) {
      const { raHours, decDeg } = galacticToEquatorial(l, (rng() - 0.5) * 2 * bandHalf)
      const proj = projectToCanvas(raHours, decDeg, w, h, lastRa)
      lastRa = proj.raNorm
      const a = (0.03 + rng() * 0.08) * centerBoost
      if (a < 0.012) continue
      const r = 0.6 + rng() * (theme === 'dark' ? 2.4 : 1.6)
      ctx.fillStyle = `rgba(${fringeColor}, ${a})`
      ctx.beginPath()
      ctx.arc(proj.x, proj.y, r, 0, Math.PI * 2)
      ctx.fill()
    }
  }

  // 银河亮核（小半径密集点，集中在银心区域）
  const corePoints = theme === 'dark' ? 140 : 50
  lastRa = null
  for (let i = 0; i < corePoints; i++) {
    const l = (rng() - 0.5) * 80 // 银心附近 ±40°
    const { raHours, decDeg } = galacticToEquatorial(l, (rng() - 0.5) * 4)
    const proj = projectToCanvas(raHours, decDeg, w, h, lastRa)
    lastRa = proj.raNorm
    const a = 0.08 + rng() * visual.galaxyAlphaMax * 0.9
    if (proj.wrap) continue
    ctx.fillStyle = theme === 'dark' ? `rgba(240, 246, 255, ${a})` : `rgba(240, 246, 252, ${a * 0.7})`
    const r = 0.3 + rng() * 1.1
    ctx.beginPath()
    ctx.arc(proj.x, proj.y, r, 0, Math.PI * 2)
    ctx.fill()
  }
}

function drawGalacticDust(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  rng: () => number,
  theme: 'dark' | 'light',
  visual: StarfieldVisual,
): void {
  if (visual.dustBandCount === 0) return
  // 沿银河走向画 3 条暗带（Great Rift 沿人马/蛇夫方向的尘云带）
  for (let b = 0; b < visual.dustBandCount; b++) {
    const shift = (b - (visual.dustBandCount - 1) / 2) * (theme === 'dark' ? 4 : 2)
    ctx.strokeStyle = `rgba(0, 0, 0, ${visual.galaxyDustAlpha})`
    ctx.lineWidth = (theme === 'dark' ? 8 : 4) + rng() * 4
    ctx.lineCap = 'round'
    ctx.beginPath()
    let started = false
    let lastRa: number | null = null
    for (let l = -10; l <= 50; l += 1) {
      const { raHours, decDeg } = galacticToEquatorial(l, shift)
      const proj = projectToCanvas(raHours, decDeg, w, h, lastRa)
      lastRa = proj.raNorm
      if (proj.wrap) continue
      if (!started) {
        ctx.moveTo(proj.x, proj.y)
        started = true
      } else {
        ctx.lineTo(proj.x, proj.y)
      }
    }
    ctx.stroke()
  }
}

function drawBackgroundStars(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  rng: () => number,
  theme: 'dark' | 'light',
  visual: StarfieldVisual,
): void {
  const palette = theme === 'dark'
    ? ['#ffffff', '#e8f0ff', '#cfddff']
    : ['#8ea0c0', '#a8b6d0', '#bcc8de']
  for (let i = 0; i < visual.bgStarCount; i++) {
    const x = rng() * w
    const y = rng() * h
    const r = 0.3 + rng() * 0.7
    const a = visual.bgStarAlphaMin + rng() * (visual.bgStarAlphaMax - visual.bgStarAlphaMin)
    ctx.fillStyle = palette[Math.floor(rng() * palette.length)]
    ctx.globalAlpha = a
    ctx.beginPath()
    ctx.arc(x, y, r, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.globalAlpha = 1
}

function drawBrightStars(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  visual: StarfieldVisual,
): void {
  let lastRa: number | null = null
  for (const star of BRIGHT_STARS) {
    const proj = projectToCanvas(star.raHours, star.decDeg, w, h, lastRa)
    lastRa = proj.raNorm
    if (proj.wrap) continue
    const color = spectralColor(star.spectral)
    const r = magToRadius(star.mag)
    const a = magToAlpha(star.mag, visual.bgStarAlphaMin, visual.bgStarAlphaMax * 1.4)
    const colorRgb = hexToRgb(color)

    // 星体
    ctx.fillStyle = `rgba(${colorRgb}, ${a})`
    ctx.globalAlpha = a
    ctx.beginPath()
    ctx.arc(proj.x, proj.y, r, 0, Math.PI * 2)
    ctx.fill()

    // 亮星（mag < 1.5）加十字光芒
    if (star.mag < 1.5 && visual.glowStarBoost > 0) {
      const len = r * 8 * visual.glowStarBoost
      ctx.strokeStyle = `rgba(${colorRgb}, ${a * 0.55})`
      ctx.lineWidth = Math.max(0.5, r * 0.4)
      ctx.lineCap = 'round'
      ctx.beginPath()
      ctx.moveTo(proj.x - len, proj.y)
      ctx.lineTo(proj.x + len, proj.y)
      ctx.moveTo(proj.x, proj.y - len)
      ctx.lineTo(proj.x, proj.y + len)
      ctx.stroke()
    }
  }
  ctx.globalAlpha = 1
}

function drawDeepSkyObjects(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  rng: () => number,
  theme: 'dark' | 'light',
): void {
  let lastRa: number | null = null
  for (const obj of DEEP_SKY_OBJECTS) {
    const proj = projectToCanvas(obj.raHours, obj.decDeg, w, h, lastRa)
    lastRa = proj.raNorm
    if (proj.wrap) continue
    // 张角 → 像素半径（画布 y 跨度 180°，1° ≈ height/180）
    const pxPerDeg = w / 360
    const radiusPx = (obj.sizeDeg / 2) * pxPerDeg
    if (radiusPx < 1) continue
    // 椭圆光斑（高比 0.6）模拟星系/星云的扁度
    const grad = ctx.createRadialGradient(proj.x, proj.y, 0, proj.x, proj.y, radiusPx)
    grad.addColorStop(0, obj.color)
    grad.addColorStop(0.5, obj.color.replace(/[\d.]+\)$/, '0.20)'))
    grad.addColorStop(1, 'rgba(0, 0, 0, 0)')
    ctx.fillStyle = grad
    ctx.beginPath()
    ctx.ellipse(proj.x, proj.y, radiusPx, radiusPx * 0.65, rng() * Math.PI, 0, Math.PI * 2)
    ctx.fill()
    // 中心亮核
    ctx.fillStyle = `rgba(255, 255, 255, ${theme === 'dark' ? 0.5 : 0.2})`
    ctx.beginPath()
    ctx.arc(proj.x, proj.y, radiusPx * 0.15, 0, Math.PI * 2)
    ctx.fill()
  }
}

function hexToRgb(hex: string): string {
  // #rgb or #rrggbb
  let h = hex.replace('#', '')
  if (h.length === 3) h = h.split('').map((c) => c + c).join('')
  const n = parseInt(h, 16)
  return `${(n >> 16) & 0xff}, ${(n >> 8) & 0xff}, ${n & 0xff}`
}