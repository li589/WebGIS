/**
 * 程序化深空星图生成器（纯函数，可单测）——科研/商用视觉级。
 *
 * 渲染分层（自下而上）：
 *  1. 深空底色（近黑微蓝渐变）
 *  2. 银河云气：离屏低分辨率逐像素渲染——真实银道面几何
 *     （带亮度沿银经衰减、核球椭圆高斯、带宽随银经变化）× fBm 分形噪声
 *     云气调制 × Great Rift 尘埃暗带（沿银心→天鹅座方向的真实暗带），
 *     再双线性放大到全画布形成柔和云气质感
 *  3. 银河亮云团（恒星形成区：人马-盾牌段、天鹅段等真实银经位置的大尺度亮云）
 *  4. 背景星场：银道面密度加权的拒绝采样 + 高斯 PSF（光晕+核心亮点）
 *  5. 真实亮星表：径向渐变 glow 光晕 + 锥形渐隐衍射光芒（非实心十字线）
 *  6. 深空天体（真实位置的星系/星云/星团）
 *
 * 天文数据：
 *  - 亮星表：Hipparcos/Yale BSC 肉眼亮星（mag < 2.1），精度 RA ±0.05h / Dec ±0.5°
 *  - 银道几何：J2000 银道↔赤道 IAU 1983 旋转矩阵；银心 RA 266.405° / Dec -28.936°
 *  - 银河面亮度定性特征：银心段最亮最宽、反银心最弱最窄、
 *    Great Rift 尘埃暗带位于银道面 b∈[-3°,+3°]、l∈[0°,90°]（银心→天鹅座）
 */

export type StarfieldMode = 'full' | 'soft' | 'minimal'

export interface StarfieldOptions {
  mode: StarfieldMode
  /** 画布宽度（默认 2048，2:1 比例） */
  width?: number
  height?: number
  /** 随机种子（默认随机；测试注入固定种子保证稳定） */
  seed?: number
}

// ─── 真实亮星表（J2000.0）─────────────────────────────────────────────────
// 字段：[name, RA hours, Dec degrees, visual mag, spectralType]
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
  { name: 'Rigil Kentaurus', raHours: 14.66, decDeg: -60.834, mag: -0.27, spectral: 'G' },
  { name: 'Arcturus', raHours: 14.261, decDeg: 19.182, mag: -0.05, spectral: 'K' },
  { name: 'Vega', raHours: 18.615, decDeg: 38.784, mag: 0.03, spectral: 'A' },
  { name: 'Capella', raHours: 5.278, decDeg: 45.998, mag: 0.08, spectral: 'G' },
  { name: 'Rigel', raHours: 5.242, decDeg: -8.202, mag: 0.13, spectral: 'B' },
  { name: 'Procyon', raHours: 7.655, decDeg: 5.225, mag: 0.34, spectral: 'F' },
  { name: 'Achernar', raHours: 1.629, decDeg: -57.237, mag: 0.46, spectral: 'B' },
  { name: 'Betelgeuse', raHours: 5.919, decDeg: 7.407, mag: 0.5, spectral: 'M' },
  { name: 'Hadar', raHours: 14.064, decDeg: -60.373, mag: 0.61, spectral: 'B' },
  { name: 'Altair', raHours: 19.846, decDeg: 8.868, mag: 0.77, spectral: 'A' },
  { name: 'Acrux', raHours: 12.443, decDeg: -63.099, mag: 0.77, spectral: 'B' },
  { name: 'Aldebaran', raHours: 4.598, decDeg: 16.509, mag: 0.85, spectral: 'K' },
  { name: 'Antares', raHours: 16.49, decDeg: -26.432, mag: 1.09, spectral: 'M' },
  { name: 'Spica', raHours: 13.42, decDeg: -11.161, mag: 0.97, spectral: 'B' },
  { name: 'Pollux', raHours: 7.755, decDeg: 28.026, mag: 1.14, spectral: 'K' },
  { name: 'Fomalhaut', raHours: 22.961, decDeg: -29.622, mag: 1.16, spectral: 'A' },
  { name: 'Deneb', raHours: 20.69, decDeg: 45.28, mag: 1.25, spectral: 'A' },
  { name: 'Mimosa', raHours: 12.795, decDeg: -59.689, mag: 1.25, spectral: 'B' },
  { name: 'Regulus', raHours: 10.139, decDeg: 11.967, mag: 1.35, spectral: 'B' },
  { name: 'Adhara', raHours: 6.977, decDeg: -28.972, mag: 1.5, spectral: 'B' },
  { name: 'Castor', raHours: 7.577, decDeg: 31.888, mag: 1.58, spectral: 'A' },
  { name: 'Gacrux', raHours: 12.519, decDeg: -57.113, mag: 1.63, spectral: 'M' },
  { name: 'Shaula', raHours: 17.56, decDeg: -37.104, mag: 1.63, spectral: 'B' },
  // ── 补充 mag 1.6 - 2.1（精度 ±0.1h / ±1°）──
  { name: 'Bellatrix', raHours: 5.418, decDeg: 6.35, mag: 1.64, spectral: 'B' },
  { name: 'Elnath', raHours: 5.438, decDeg: 28.608, mag: 1.65, spectral: 'B' },
  { name: 'Miaplacidus', raHours: 9.22, decDeg: -69.717, mag: 1.69, spectral: 'A' },
  { name: 'Alnilam', raHours: 5.604, decDeg: -1.202, mag: 1.69, spectral: 'B' },
  { name: 'Alnair', raHours: 22.137, decDeg: -46.961, mag: 1.74, spectral: 'B' },
  { name: 'Alnitak', raHours: 5.679, decDeg: -1.943, mag: 1.74, spectral: 'O' },
  { name: 'Alioth', raHours: 12.9, decDeg: 55.96, mag: 1.77, spectral: 'A' },
  { name: 'Dubhe', raHours: 11.062, decDeg: 61.751, mag: 1.79, spectral: 'K' },
  { name: 'Mirfak', raHours: 3.405, decDeg: 49.861, mag: 1.79, spectral: 'F' },
  { name: 'Wezen', raHours: 7.14, decDeg: -26.393, mag: 1.84, spectral: 'F' },
  { name: 'Kaus Australis', raHours: 18.403, decDeg: -34.385, mag: 1.85, spectral: 'B' },
  { name: 'Alkaid', raHours: 13.792, decDeg: 49.313, mag: 1.86, spectral: 'B' },
  { name: 'Avior', raHours: 8.375, decDeg: -59.51, mag: 1.86, spectral: 'K' },
  { name: 'Sargas', raHours: 17.622, decDeg: -42.998, mag: 1.87, spectral: 'B' },
  { name: 'Menkalinan', raHours: 5.992, decDeg: 44.947, mag: 1.9, spectral: 'A' },
  { name: 'Atria', raHours: 16.811, decDeg: -69.028, mag: 1.91, spectral: 'K' },
  { name: 'Alhena', raHours: 6.629, decDeg: 16.399, mag: 1.93, spectral: 'A' },
  { name: 'Peacock', raHours: 20.428, decDeg: -56.737, mag: 1.94, spectral: 'B' },
  { name: 'Polaris', raHours: 2.53, decDeg: 89.264, mag: 1.97, spectral: 'F' },
  { name: 'Mirzam', raHours: 6.378, decDeg: -17.956, mag: 1.98, spectral: 'B' },
  { name: 'Alphard', raHours: 9.459, decDeg: -8.659, mag: 1.99, spectral: 'K' },
  { name: 'Algieba', raHours: 10.333, decDeg: 19.842, mag: 2.08, spectral: 'K' },
  { name: 'Hamal', raHours: 2.119, decDeg: 23.462, mag: 2.0, spectral: 'K' },
  { name: 'Diphda', raHours: 0.726, decDeg: -17.987, mag: 2.04, spectral: 'K' },
  { name: 'Nunki', raHours: 18.921, decDeg: -26.297, mag: 2.05, spectral: 'B' },
  { name: 'Menkent', raHours: 14.063, decDeg: -36.37, mag: 2.06, spectral: 'K' },
  { name: 'Mizar', raHours: 13.399, decDeg: 54.925, mag: 2.04, spectral: 'A' },
  { name: 'Mirach', raHours: 1.162, decDeg: 35.621, mag: 2.07, spectral: 'M' },
  { name: 'Izar', raHours: 14.749, decDeg: 27.074, mag: 2.37, spectral: 'K' },
  { name: 'Schedar', raHours: 0.675, decDeg: 56.537, mag: 2.24, spectral: 'K' },
  { name: 'Caph', raHours: 0.153, decDeg: 59.15, mag: 2.27, spectral: 'F' },
  { name: 'Algenib', raHours: 0.221, decDeg: 15.184, mag: 2.83, spectral: 'B' },
  { name: 'Markab', raHours: 23.079, decDeg: 15.205, mag: 2.49, spectral: 'B' },
  { name: 'Scheat', raHours: 23.063, decDeg: 28.083, mag: 2.42, spectral: 'M' },
  { name: 'Enif', raHours: 21.736, decDeg: 9.875, mag: 2.39, spectral: 'K' },
  { name: 'Ankaa', raHours: 0.438, decDeg: -42.306, mag: 2.4, spectral: 'K' },
  { name: 'Alderamin', raHours: 21.31, decDeg: 62.586, mag: 2.45, spectral: 'A' },
]

// ─── 真实深空天体（J2000.0）─────────────────────────────────────────────────
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
  {
    name: 'M31',
    raHours: 0.712,
    decDeg: 41.269,
    sizeDeg: 3.5,
    mag: 3.4,
    color: 'rgba(220, 210, 240, 0.55)',
    kind: 'galaxy',
  },
  {
    name: 'M42',
    raHours: 5.588,
    decDeg: -5.391,
    sizeDeg: 1.5,
    mag: 4.0,
    color: 'rgba(255, 180, 160, 0.50)',
    kind: 'nebula',
  },
  {
    name: 'M45',
    raHours: 3.79,
    decDeg: 24.117,
    sizeDeg: 2.0,
    mag: 1.6,
    color: 'rgba(200, 220, 255, 0.45)',
    kind: 'cluster',
  },
]

// ─── 银道几何（J2000，IAU 1983）─────────────────────────────────────────────
export const GALACTIC_TILT_DEG = 62.87175

/** 银道→赤道旋转矩阵（R^T，按行主序） */
const _G2E = [
  -0.0548755604, 0.4941094279, -0.867666149,
  -0.8734370902, -0.44482963, -0.1980763734,
  -0.4838359925, 0.7469822445, 0.4559837762,
]
/** 赤道→银道旋转矩阵（R = (R^T)^T，按行主序） */
const _E2G = [
  -0.0548755604, -0.8734370902, -0.4838359925,
  0.4941094279, -0.44482963, 0.7469822445,
  -0.867666149, -0.1980763734, 0.4559837762,
]

export function galacticToEquatorial(
  lDeg: number,
  bDeg: number,
): { raHours: number; decDeg: number } {
  const lRad = (lDeg * Math.PI) / 180
  const bRad = (bDeg * Math.PI) / 180
  const xG = Math.cos(bRad) * Math.cos(lRad)
  const yG = Math.cos(bRad) * Math.sin(lRad)
  const zG = Math.sin(bRad)
  const xE = _G2E[0] * xG + _G2E[1] * yG + _G2E[2] * zG
  const yE = _G2E[3] * xG + _G2E[4] * yG + _G2E[5] * zG
  const zE = _G2E[6] * xG + _G2E[7] * yG + _G2E[8] * zG
  const raDeg = ((Math.atan2(yE, xE) * 180) / Math.PI + 360) % 360
  const decDeg = (Math.asin(Math.max(-1, Math.min(1, zE))) * 180) / Math.PI
  return { raHours: raDeg / 15, decDeg }
}

/** 赤道→银道（J2000 逆变换）。输出 l/b 度。 */
export function equatorialToGalactic(
  raHours: number,
  decDeg: number,
): { lDeg: number; bDeg: number } {
  const raRad = (raHours * 15 * Math.PI) / 180
  const decRad = (decDeg * Math.PI) / 180
  const xE = Math.cos(decRad) * Math.cos(raRad)
  const yE = Math.cos(decRad) * Math.sin(raRad)
  const zE = Math.sin(decRad)
  const xG = _E2G[0] * xE + _E2G[1] * yE + _E2G[2] * zE
  const yG = _E2G[3] * xE + _E2G[4] * yE + _E2G[5] * zE
  const zG = _E2G[6] * xE + _E2G[7] * yE + _E2G[8] * zE
  const lDeg = ((Math.atan2(yG, xG) * 180) / Math.PI + 360) % 360
  const bDeg = (Math.asin(Math.max(-1, Math.min(1, zG))) * 180) / Math.PI
  return { lDeg, bDeg }
}

// ─── 随机数 + 视觉参数 ─────────────────────────────────────────────────────

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
      bgStarCount: 3200,
      bgStarAlphaMin: 0.1,
      bgStarAlphaMax: 0.85,
      glowStarBoost: 1.15,
      galaxyAlphaMax: 0.85,
      galaxyDustAlpha: 0.55,
      dustBandCount: 3,
      showDeepSky: true,
    }
  }
  return {
    bgStarCount: 600,
    bgStarAlphaMin: 0.04,
    bgStarAlphaMax: 0.2,
    glowStarBoost: 0.3,
    galaxyAlphaMax: 0.15,
    galaxyDustAlpha: 0.05,
    dustBandCount: 0,
    showDeepSky: false,
  }
}

// ─── fBm value noise（云气纹理）────────────────────────────────────────────

/** 整数格点 hash → [0,1)。用于 value noise 的晶格值。 */
function hash2(ix: number, iy: number, seed: number): number {
  let h = (ix * 374761393 + iy * 668265263 + seed * 1442695041) | 0
  h = Math.imul(h ^ (h >>> 13), 1274126177)
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296
}

function quintic(t: number): number {
  return t * t * t * (t * (t * 6 - 15) + 10)
}

/** 单倍频 value noise，输入为连续坐标（银道坐标弧度），保证跨 RA 边界连续。 */
function valueNoise(x: number, y: number, seed: number): number {
  const ix = Math.floor(x)
  const iy = Math.floor(y)
  const fx = quintic(x - ix)
  const fy = quintic(y - iy)
  const v00 = hash2(ix, iy, seed)
  const v10 = hash2(ix + 1, iy, seed)
  const v01 = hash2(ix, iy + 1, seed)
  const v11 = hash2(ix + 1, iy + 1, seed)
  const a = v00 + (v10 - v00) * fx
  const b = v01 + (v11 - v01) * fx
  return a + (b - a) * fy
}

/** 5 倍频 fBm：银河云气的多尺度结构（大尺度绵延 + 小尺度碎絮）。 */
function fbm(x: number, y: number, seed: number): number {
  let sum = 0
  let amp = 0.5
  let norm = 0
  for (let o = 0; o < 5; o++) {
    sum += amp * valueNoise(x, y, seed + o * 101)
    norm += amp
    x *= 2.03
    y *= 2.03
    amp *= 0.55
  }
  return sum / norm
}

// ─── 银河面亮度模型（定性吻合真实银河特征）──────────────────────────────────

/** 银经归一化距离 d ∈ [0,180]（银心 0 → 反银心 180）。 */
function galacticDistance(lDeg: number): number {
  const l = lDeg > 180 ? 360 - lDeg : lDeg
  return l
}

/**
 * 银河带亮度（银道坐标系）。
 * - 沿银经衰减：银心段 (d<40°) 最亮，反银心 (d→180°) 最弱（真实对比 ~6 mag，视觉取 ~6 倍）
 * - 带宽随银经：银心宽（σ≈10°，含核球方向盘面叠加），反银心窄（σ≈4°）
 * - 核球：|l|<~30°、|b|<~12° 椭圆高斯（真实银河核球尺度）
 */
function galaxyBandIntensity(lDeg: number, bDeg: number): { band: number; bulge: number } {
  const d = galacticDistance(lDeg)
  const alongL = Math.exp(-((d / 62) ** 2))
  const brightness = 0.16 + 0.84 * alongL + 0.18 * Math.exp(-(((d - 95) / 55) ** 2))
  const sigma = 4.5 + 5.5 * Math.exp(-((d / 70) ** 2))
  const band = brightness * Math.exp(-((bDeg / sigma) ** 2))

  // 核球（真实：约 l∈±30°, b∈±12° 的椭球状隆起，长轴沿银道面）
  const dl = Math.min(d, 360 - lDeg) // 有符号近银心距离
  const bulge = 0.95 * Math.exp(
    -0.5 * ((dl / 18) ** 2 + (bDeg / 9) ** 2),
  )
  return { band, bulge }
}

/**
 * Great Rift 尘埃暗带（银河内最显著的视觉特征）：
 * 沿银道面 b∈[-3°,+3°]、从银心 (l≈0) 延伸到天鹅座 (l≈80°) 的暗裂隙。
 * 返回 [0,1] 的遮蔽强度，用第二噪声通道调制出碎絮边缘。
 */
function dustRiftIntensity(lDeg: number, bDeg: number, seed: number): number {
  const d = galacticDistance(lDeg)
  // 暗带主要在银心→天鹅座段（真实 Great Rift 走向）
  const along = Math.exp(-((d / 42) ** 2))
  // 贴银道面（真实暗带紧贴 b≈0°，略偏南）
  const vertical = Math.exp(-(((bDeg + 1.2) / 2.4) ** 2))
  const clump = 0.35 + 0.65 * fbm(lDeg * 0.06, bDeg * 0.11 + 40, seed)
  return along * vertical * clump
}

// ─── 颜色工具 ──────────────────────────────────────────────────────────────

function spectralColor(spectral: string): string {
  const t = spectral.charAt(0).toUpperCase()
  switch (t) {
    case 'O': return '#a8b8ff'
    case 'B': return '#b8c8ff'
    case 'A': return '#dde4ff'
    case 'F': return '#fff4e8'
    case 'G': return '#fff0d0'
    case 'K': return '#ffc890'
    case 'M': return '#ffaa78'
    default: return '#ffffff'
  }
}

function hexToRgb(hex: string): string {
  let h = hex.replace('#', '')
  if (h.length === 3) h = h.split('').map((c) => c + c).join('')
  const n = parseInt(h, 16)
  return `${(n >> 16) & 0xff}, ${(n >> 8) & 0xff}, ${n & 0xff}`
}

/** 星等 → 核心像素半径（PSF 半宽）。mag=-1.5 → ~2.6px，mag=2 → ~0.5px。 */
function magToRadius(mag: number): number {
  return Math.max(0.4, 2.8 - 0.95 * mag)
}

/** 星等 → 亮度 alpha。 */
function magToAlpha(mag: number, alphaMin: number, alphaMax: number): number {
  const k = Math.max(0, Math.min(1, (3.0 - mag) / 4.5))
  return alphaMin + k * (alphaMax - alphaMin)
}

// ─── 投影 ──────────────────────────────────────────────────────────────────

interface Projected {
  x: number
  y: number
  wrap: boolean
  raNorm: number
}

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

// ─── 主入口 ────────────────────────────────────────────────────────────────

/**
 * 生成星图 canvas（2:1 比例，默认 2048×1024）。
 * minimal 模式返回透明空画布。
 */
export function renderStarfieldCanvas(options: StarfieldOptions): HTMLCanvasElement {
  const width = options.width ?? 2048
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
  const noiseSeed = (options.seed ?? 1) % 9973 || 7

  // 1) 深空底色（近黑微蓝的垂直渐变）
  drawDeepSpaceBase(ctx, width, height, theme)

  // 2) 银河云气（低分辨率逐像素 fBm + 面亮度模型，双线性放大成柔和云气）
  drawGalacticHaze(ctx, width, height, theme, visual, noiseSeed)

  // 3) 银河亮云团（恒星形成区，沿真实银经位置的大尺度亮云）
  drawStarFormingRegions(ctx, width, height, rng, theme, visual)

  // 4) 深空天体（真实位置）
  if (visual.showDeepSky) drawDeepSkyObjects(ctx, width, height, theme)

  // 5) 背景星场（银道面密度加权 + 高斯 PSF）
  drawBackgroundStars(ctx, width, height, rng, theme, visual, noiseSeed)

  // 6) 真实亮星表（glow 光晕 + 渐隐衍射光芒）
  drawBrightStars(ctx, width, height, visual)

  return canvas
}

// ─── 1) 深空底色 ──────────────────────────────────────────────────────────

function drawDeepSpaceBase(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  theme: 'dark' | 'light',
): void {
  ctx.fillStyle = theme === 'dark' ? '#02040a' : '#0a1220'
  ctx.fillRect(0, 0, w, h)
  if (theme === 'dark') {
    // 大尺度极微弱的天光渐变（顶部略蓝，底部略紫黑），避免纯平死黑
    const grad = ctx.createLinearGradient(0, 0, 0, h)
    grad.addColorStop(0, 'rgba(10, 18, 38, 0.55)')
    grad.addColorStop(0.5, 'rgba(4, 8, 18, 0)')
    grad.addColorStop(1, 'rgba(12, 8, 24, 0.4)')
    ctx.fillStyle = grad
    ctx.fillRect(0, 0, w, h)
  }
}

// ─── 2) 银河云气（核心视觉） ────────────────────────────────────────────────

/**
 * 在低分辨率离屏画布（w/4 × h/4）逐像素计算银河面亮度：
 * intensity(l, b) = (band×云气fBm + bulge×核球噪声) × (1 - rift×尘埃遮蔽)
 * 颜色沿银经从银心暖白过渡到外盘冷蓝，再放大绘制到主画布。
 *
 * 用 ImageData 直接写像素（避免 205K 次 fillRect 调用开销），
 * 双线性放大自带云气柔化——真实银河的雾状质感正源于此。
 */
function drawGalacticHaze(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  theme: 'dark' | 'light',
  visual: StarfieldVisual,
  noiseSeed: number,
): void {
  const lw = Math.max(320, Math.round(w / 4))
  const lh = Math.max(160, Math.round(h / 4))
  const off = document.createElement('canvas')
  off.width = lw
  off.height = lh
  const offCtx = off.getContext('2d')
  if (!offCtx) return

  const img = offCtx.createImageData(lw, lh)
  const data = img.data
  const alphaScale = visual.galaxyAlphaMax
  const dustScale = visual.galaxyDustAlpha
  const warm = [255, 244, 222] // 银心/核球暖白（老年恒星群主导）
  const cool = [172, 194, 238] // 外盘/旋臂冷蓝（年轻恒星+瑞利散射）

  for (let py = 0; py < lh; py++) {
    const dec = 90 - ((py + 0.5) / lh) * 180
    for (let px = 0; px < lw; px++) {
      const ra = ((px + 0.5) / lw) * 24
      // 赤道 → 银道（噪声与模型都在银道坐标系，保证跨 RA 边界连续）
      const { lDeg, bDeg } = equatorialToGalactic(ra, dec)
      const { band, bulge } = galaxyBandIntensity(lDeg, bDeg)

      // 云气调制：两层 fBm（大尺度绵延 + 小尺度碎絮）
      const lr = (lDeg * Math.PI) / 180
      const br = (bDeg * Math.PI) / 180
      const cloudLarge = fbm(lr * 2.2, br * 2.2, noiseSeed)
      const cloudFine = fbm(lr * 6.5, br * 6.5, noiseSeed + 500)
      const cloud = 0.55 + 0.45 * (0.6 * cloudLarge + 0.4 * cloudFine)

      // 尘埃暗带遮蔽
      const rift = dustRiftIntensity(lDeg, bDeg, noiseSeed + 900)

      // 合成面亮度
      let intensity = band * cloud + bulge * (0.7 + 0.3 * cloudLarge)
      intensity *= 1 - rift * dustScale
      intensity = Math.max(0, Math.min(1, intensity))

      if (intensity < 0.004) continue

      // 颜色：距银心按银经混合暖→冷
      const d = galacticDistance(lDeg)
      const mixK = Math.min(1, d / 150) * 0.85
      const r = warm[0] + (cool[0] - warm[0]) * mixK
      const g = warm[1] + (cool[1] - warm[1]) * mixK
      const b = warm[2] + (cool[2] - warm[2]) * mixK

      const idx = (py * lw + px) * 4
      data[idx] = r
      data[idx + 1] = g
      data[idx + 2] = b
      data[idx + 3] = Math.round(255 * intensity * alphaScale)
    }
  }

  offCtx.putImageData(img, 0, 0)

  // 双线性放大到全画布（云气柔化）+ 轻微整体叠加
  ctx.save()
  ctx.imageSmoothingEnabled = true
  ctx.imageSmoothingQuality = 'high'
  ctx.globalCompositeOperation = theme === 'dark' ? 'lighter' : 'source-over'
  ctx.drawImage(off, 0, 0, lw, lh, 0, 0, w, h)
  ctx.restore()
}

// ─── 3) 银河亮云团（恒星形成区） ──────────────────────────────────────────

/** 真实银河亮段的银经位置（人马-盾牌恒星形成区、天鹅亮段、船底亮段）。 */
const _STAR_CLOUDS: ReadonlyArray<{ l: number; b: number; size: number; boost: number }> = [
  { l: 6, b: 0.5, size: 7.5, boost: 1.0 }, // 人马 M8/M17/M16 恒星形成区群
  { l: 18, b: 1.5, size: 6.5, boost: 0.9 }, // 盾牌-蛇夫亮云
  { l: 28, b: -0.5, size: 6.0, boost: 0.8 }, // 盾牌臂亮段
  { l: 45, b: -2.0, size: 5.0, boost: 0.55 }, // 天鹰-盾牌裂隙南亮云
  { l: 78, b: 1.0, size: 6.0, boost: 0.7 }, // 天鹅座亮段（北天银河最亮段）
  { l: 90, b: -1.5, size: 4.5, boost: 0.45 }, // 天鹅-仙王延续
  { l: 285, b: -1.0, size: 5.0, boost: 0.55 }, // 船底臂亮段（南天银河）
  { l: 305, b: 0.5, size: 4.5, boost: 0.5 }, // 船帆-船尾亮段
  { l: 337, b: -2.0, size: 4.0, boost: 0.4 }, // 麒麟亮段（近反银心）
]

function drawStarFormingRegions(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  rng: () => number,
  theme: 'dark' | 'light',
  visual: StarfieldVisual,
): void {
  const pxPerDeg = w / 360
  let lastRa: number | null = null
  for (const cloud of _STAR_CLOUDS) {
    const { raHours, decDeg } = galacticToEquatorial(cloud.l, cloud.b)
    const proj = projectToCanvas(raHours, decDeg, w, h, lastRa)
    lastRa = proj.raNorm
    if (proj.wrap) continue
    const radius = cloud.size * pxPerDeg
    if (radius < 2) continue
    const alpha = cloud.boost * visual.galaxyAlphaMax * (theme === 'dark' ? 0.32 : 0.1)
    // 双层 glow：内层暖白亮核 + 外层大范围淡蓝晕
    const inner = ctx.createRadialGradient(proj.x, proj.y, 0, proj.x, proj.y, radius * 0.45)
    inner.addColorStop(0, `rgba(255, 248, 235, ${alpha * 0.85})`)
    inner.addColorStop(1, 'rgba(255, 248, 235, 0)')
    const outer = ctx.createRadialGradient(proj.x, proj.y, 0, proj.x, proj.y, radius)
    outer.addColorStop(0, `rgba(190, 208, 245, ${alpha * 0.4})`)
    outer.addColorStop(0.6, `rgba(190, 208, 245, ${alpha * 0.18})`)
    outer.addColorStop(1, 'rgba(190, 208, 245, 0)')
    ctx.fillStyle = outer
    ctx.beginPath()
    ctx.arc(proj.x, proj.y, radius, 0, Math.PI * 2)
    ctx.fill()
    ctx.fillStyle = inner
    ctx.beginPath()
    ctx.arc(proj.x, proj.y, radius * 0.45, 0, Math.PI * 2)
    ctx.fill()
    // 云团内撒几颗微亮恒星（真实：恒星形成区内有年轻亮星群）
    if (theme === 'dark') {
      const sparkle = Math.round(6 + cloud.boost * 10)
      for (let i = 0; i < sparkle; i++) {
        const ang = rng() * Math.PI * 2
        const dist = rng() * radius * 0.8
        const sx = proj.x + Math.cos(ang) * dist
        const sy = proj.y + Math.sin(ang) * dist * 0.6
        ctx.fillStyle = `rgba(235, 242, 255, ${0.25 + rng() * 0.4})`
        ctx.beginPath()
        ctx.arc(sx, sy, 0.4 + rng() * 0.6, 0, Math.PI * 2)
        ctx.fill()
      }
    }
  }
}

// ─── 4) 背景星场（银道面密度加权 + 高斯 PSF） ───────────────────────────────

/**
 * 背景星：拒绝采样近似真实恒星密度分布——
 * 银道面附近（|b| 小）恒星密度显著更高（视线穿过银河盘的累积效应）。
 * 每颗星 = 中心亮核（~0.5px）+ 径向渐变光晕（高斯 PSF 视觉近似）。
 */
function drawBackgroundStars(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  rng: () => number,
  theme: 'dark' | 'light',
  visual: StarfieldVisual,
  noiseSeed: number,
): void {
  const palette = theme === 'dark'
    ? ['#ffffff', '#e8f0ff', '#cfddff', '#fff2dd', '#ffd9b8']
    : ['#8ea0c0', '#a8b6d0', '#bcc8de']
  const maxAttempts = visual.bgStarCount * 6
  let placed = 0
  let attempts = 0

  while (placed < visual.bgStarCount && attempts < maxAttempts) {
    attempts++
    // 均匀球面采样（等距圆柱 y 均匀即可近似；严格球面用 z 均匀——视觉差异小，用 cos 分布）
    const dec = Math.asin(rng() * 2 - 1) * (180 / Math.PI)
    const ra = rng() * 24
    const { lDeg, bDeg } = equatorialToGalactic(ra, dec)
    // 银道面密度权重（带强度 + 局部云气团块）
    const { band } = galaxyBandIntensity(lDeg, bDeg)
    const lr = (lDeg * Math.PI) / 180
    const br = (bDeg * Math.PI) / 180
    const cloud = fbm(lr * 3.0, br * 3.0, noiseSeed + 300)
    const density = 0.22 + 0.78 * Math.min(1, band * (0.6 + 0.6 * cloud))
    if (rng() > density) continue
    placed++

    const x = (ra / 24) * w
    const y = ((90 - dec) / 180) * h
    const r = 0.35 + rng() * 0.75
    const a = visual.bgStarAlphaMin + rng() * (visual.bgStarAlphaMax - visual.bgStarAlphaMin)
    const color = palette[Math.floor(rng() * palette.length)]
    const rgb = hexToRgb(color)

    // 高斯 PSF：外层光晕（径向渐变）+ 中心亮核
    const halo = ctx.createRadialGradient(x, y, 0, x, y, r * 3.4)
    halo.addColorStop(0, `rgba(${rgb}, ${a * 0.85})`)
    halo.addColorStop(0.35, `rgba(${rgb}, ${a * 0.32})`)
    halo.addColorStop(1, `rgba(${rgb}, 0)`)
    ctx.fillStyle = halo
    ctx.beginPath()
    ctx.arc(x, y, r * 3.4, 0, Math.PI * 2)
    ctx.fill()
    // 中心核心（发光体的"点"）
    if (a > 0.3) {
      ctx.fillStyle = `rgba(255, 255, 255, ${Math.min(1, a * 1.2)})`
      ctx.beginPath()
      ctx.arc(x, y, Math.max(0.4, r * 0.45), 0, Math.PI * 2)
      ctx.fill()
    }
  }
}

// ─── 5) 真实亮星（glow + 渐隐衍射光芒） ────────────────────────────────────

/**
 * 亮星渲染（对照科研可视化软件风格）：
 * - 主体：径向渐变 glow（白热核心 → 光谱色晕 → 透明）
 * - 衍射光芒：4 条主芒（垂直/水平）+ 4 条次芒（45° 斜向），
 *   每条从星心向外线性渐隐（createLinearGradient），锥形收窄视觉
 */
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
    const rgb = hexToRgb(color)
    const r = magToRadius(star.mag)
    const a = magToAlpha(star.mag, visual.bgStarAlphaMin, visual.bgStarAlphaMax * 1.35)

    // 主体 glow：三层径向渐变（核 → 色晕 → 透明）
    const core = ctx.createRadialGradient(proj.x, proj.y, 0, proj.x, proj.y, r * 4.2)
    core.addColorStop(0, `rgba(255, 255, 255, ${Math.min(1, a * 1.25)})`)
    core.addColorStop(0.18, `rgba(${rgb}, ${a * 0.9})`)
    core.addColorStop(0.5, `rgba(${rgb}, ${a * 0.28})`)
    core.addColorStop(1, `rgba(${rgb}, 0)`)
    ctx.fillStyle = core
    ctx.beginPath()
    ctx.arc(proj.x, proj.y, r * 4.2, 0, Math.PI * 2)
    ctx.fill()

    // 衍射光芒（仅最亮星 mag < 1.2）：8 条渐隐细芒
    if (star.mag < 1.2 && visual.glowStarBoost > 0) {
      drawDiffractionSpikes(ctx, proj.x, proj.y, r, a, rgb, visual.glowStarBoost)
    }
  }
}

/** 衍射光芒：4 长芒（正交）+ 4 短芒（对角），每条从中心线性渐隐。 */
function drawDiffractionSpikes(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  r: number,
  alpha: number,
  rgb: string,
  boost: number,
): void {
  const mainLen = r * (9 + 5 * boost) // 主芒长度
  const diagLen = mainLen * 0.45 // 次芒长度
  const spike = (
    len: number,
    angle: number,
    width: number,
    a: number,
  ) => {
    const ex = x + Math.cos(angle) * len
    const ey = y + Math.sin(angle) * len
    const grad = ctx.createLinearGradient(x, y, ex, ey)
    grad.addColorStop(0, `rgba(${rgb}, ${a})`)
    grad.addColorStop(0.35, `rgba(${rgb}, ${a * 0.45})`)
    grad.addColorStop(1, `rgba(${rgb}, 0)`)
    ctx.strokeStyle = grad
    ctx.lineWidth = width
    ctx.lineCap = 'round'
    ctx.beginPath()
    ctx.moveTo(x, y)
    ctx.lineTo(ex, ey)
    ctx.stroke()
  }
  // 4 条主芒（垂直/水平）
  const mainAlpha = Math.min(0.6, alpha * 0.5 * boost)
  const mainWidth = Math.max(0.6, r * 0.28)
  for (const angle of [0, Math.PI / 2, Math.PI, -Math.PI / 2]) {
    spike(mainLen, angle, mainWidth, mainAlpha)
  }
  // 4 条次芒（45° 对角）
  const diagAlpha = mainAlpha * 0.5
  const diagWidth = Math.max(0.5, mainWidth * 0.7)
  for (const angle of [Math.PI / 4, (3 * Math.PI) / 4, (5 * Math.PI) / 4, (7 * Math.PI) / 4]) {
    spike(diagLen, angle, diagWidth, diagAlpha)
  }
}

// ─── 6) 深空天体 ───────────────────────────────────────────────────────────

function drawDeepSkyObjects(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  theme: 'dark' | 'light',
): void {
  let lastRa: number | null = null
  const pxPerDeg = w / 360
  for (const obj of DEEP_SKY_OBJECTS) {
    const proj = projectToCanvas(obj.raHours, obj.decDeg, w, h, lastRa)
    lastRa = proj.raNorm
    if (proj.wrap) continue
    const radiusPx = (obj.sizeDeg / 2) * pxPerDeg
    if (radiusPx < 1) continue
    // 主光斑（椭圆，扁度模拟盘面/棒状）
    const grad = ctx.createRadialGradient(proj.x, proj.y, 0, proj.x, proj.y, radiusPx)
    grad.addColorStop(0, obj.color)
    grad.addColorStop(0.5, obj.color.replace(/[\d.]+\)$/, '0.20)'))
    grad.addColorStop(1, 'rgba(0, 0, 0, 0)')
    ctx.fillStyle = grad
    ctx.beginPath()
    ctx.ellipse(proj.x, proj.y, radiusPx, radiusPx * 0.65, 0, 0, Math.PI * 2)
    ctx.fill()
    // 中心亮核
    ctx.fillStyle = `rgba(255, 255, 255, ${theme === 'dark' ? 0.5 : 0.2})`
    ctx.beginPath()
    ctx.arc(proj.x, proj.y, radiusPx * 0.15, 0, Math.PI * 2)
    ctx.fill()
  }
}
