/**
 * 与后端 field_mapping 对齐的全球格网 / 半开瓦片几何。
 *
 * 格心：(i+0.5)*res；瓦片只决定「哪个格心由谁发出」（半开归属），
 * 格元本身是全球贴合矩形，不裁进瓦片框——否则格网边与 Mercator 瓦片边
 * 不对齐时会在边界留下横/纵空隙。
 */

export interface LngLatBounds {
  west: number
  south: number
  east: number
  north: number
}

const GRID_AXIS_EPS = 1e-9
/** 贴合格元外扩（度），仅覆盖 MapLibre fill 邻边抗锯齿发丝缝，肉眼无叠框 */
const CELL_SEAM_EPS_DEG = 1e-7

/** 与后端 point_in_tile_half_open 一致；支持 east>180 的归一化视口跨度 */
export function pointInTileHalfOpen(
  lon: number,
  lat: number,
  bounds: LngLatBounds,
  options?: { includeEast?: boolean; includeSouth?: boolean },
): boolean {
  const includeEast = options?.includeEast === true
  const includeSouth = options?.includeSouth === true
  let x = lon
  // 视口裁剪：normalizeLngBounds 可能令 east∈(180,540]
  if (bounds.east > 180 || bounds.east < bounds.west) {
    while (x < bounds.west) x += 360
    while (x >= bounds.west + 360) x -= 360
  }
  const lonOk = x >= bounds.west && (includeEast ? x <= bounds.east : x < bounds.east)
  const latOk = lat <= bounds.north && (includeSouth ? lat >= bounds.south : lat > bounds.south)
  return lonOk && latOk
}

/**
 * 将经度解包到「最小连续跨度」坐标系（结果中 east 可能 &gt;180）。
 *
 * 跨日界线的亚洲–太平洋等点集若按 [-180,180] 直接排序，会错误形成穿过美洲的
 * 假长跨度（&gt;180° 空洞），粒子/流量场只在半屏有数据。算法：在圆环上找最大空隙并切开。
 */
export function unwrapLonsToMinimalSpan(lons: readonly number[]): number[] {
  if (lons.length === 0) return []
  const sorted = [...new Set(lons.filter((v) => Number.isFinite(v)))].sort((a, b) => a - b)
  if (sorted.length <= 1) return lons.map((x) => x)

  let maxGap = -1
  let gapAfterIdx = sorted.length - 1
  for (let i = 0; i < sorted.length - 1; i++) {
    const gap = sorted[i + 1]! - sorted[i]!
    if (gap > maxGap) {
      maxGap = gap
      gapAfterIdx = i
    }
  }
  const wrapGap = sorted[0]! + 360 - sorted[sorted.length - 1]!
  if (wrapGap > maxGap) {
    // 最大空隙在日界线外侧 → [-180,180] 内已连续
    return lons.map((x) => x)
  }

  const cutLon = sorted[gapAfterIdx]!
  return lons.map((lon) => (lon <= cutLon ? lon + 360 : lon))
}

/** 将查询经度卷入网格的连续经度框 [west, west+360) */
export function unwrapLonIntoGridFrame(lon: number, west: number, east: number): number {
  if (!(east > west)) return lon
  let x = lon
  // 仅解包框（east>180 或跨度很大）才 ±360 卷入；普通区域略越界交给 clamp，
  // 避免 lon 稍小于 west 时跳到 west+360 采样到错误边缘。
  if (east > 180 || east - west > 180) {
    while (x < west) x += 360
    while (x >= west + 360) x -= 360
  }
  return x
}

/** 将任意经/纬度吸附到全球格心 (i+0.5)*res（落在 [i·res,(i+1)·res) 的点） */
export function snapToLatticeCenter(value: number, resolution: number): number {
  const res = Number(resolution)
  if (!(res > 0) || !Number.isFinite(value)) return value
  const i = Math.floor((value + GRID_AXIS_EPS) / res)
  return (i + 0.5) * res
}

/** 格心对应的全局格网整数下标 */
export function latticeIndex(value: number, resolution: number): number {
  const res = Number(resolution)
  if (!(res > 0) || !Number.isFinite(value)) return 0
  return Math.floor((value + GRID_AXIS_EPS) / res)
}

/**
 * 从样本坐标推断全球格网步长。
 * 取「小间隙」的中位数，忽略缺瓦造成的大洞（例如跨赤道未加载时南北点相距数倍 res），
 * 否则步长被拉大 → 格元无法贴合 → 赤道附近整条空白带。
 */
export function detectLatticeResolution(
  values: readonly number[],
  fallback = 0.25,
): number {
  const unique = Array.from(
    new Set(
      values.filter((v) => Number.isFinite(v)).map((v) => Math.round(v * 1e6) / 1e6),
    ),
  ).sort((a, b) => a - b)
  if (unique.length < 2) return fallback
  const gaps: number[] = []
  for (let i = 1; i < unique.length; i++) {
    const g = unique[i]! - unique[i - 1]!
    if (g > 1e-9) gaps.push(g)
  }
  if (gaps.length === 0) return fallback
  const minGap = Math.min(...gaps)
  // 大于 ~2.5× 最小间隙的视为缺行/缺列空洞，不参与步长估计
  const small = gaps.filter((g) => g <= minGap * 2.5 + 1e-9).sort((a, b) => a - b)
  const mid = small[Math.floor(small.length / 2)] ?? minGap
  // 与后端 zoom_to_resolution 下限对齐
  return Math.max(0.05, mid)
}

/**
 * 将样本点展成等间距轴（补齐中间缺行/缺列），供纹理 UV 按地理线性采样。
 * 跨赤道 / 多 z 合并时若只用「出现过的纬度」建行，行距不规则，
 * `(north-lat)/(north-south)` 会把南半球采到北半球纹素 → 半幅错乱或空白。
 *
 * 轴从实际 min→max 按检测到的步长均分（不强制吸附到全局 (i+0.5)*res），
 * 以兼容测试坐标与非严格格点源；天气瓦片本身已在格心上，结果与全球格网一致。
 *
 * @param descending true → 北→南（风/标量 row0=北）；false → 升序
 */
export function buildRegularLatticeAxis(
  values: readonly number[],
  options?: { resolution?: number; descending?: boolean },
): number[] {
  const finite = values.filter((v) => Number.isFinite(v))
  if (finite.length === 0) return []
  const unique = Array.from(
    new Set(finite.map((v) => Math.round(v * 1e6) / 1e6)),
  ).sort((a, b) => a - b)
  if (unique.length === 1) return [...unique]

  const res = Math.max(
    0.05,
    options?.resolution && options.resolution > 0
      ? options.resolution
      : detectLatticeResolution(unique),
  )
  const lo = unique[0]!
  const hi = unique[unique.length - 1]!
  const nSteps = Math.max(1, Math.round((hi - lo) / res))
  const step = (hi - lo) / nSteps
  const axis: number[] = []
  for (let k = 0; k <= nSteps; k++) {
    axis.push(lo + k * step)
  }
  if (options?.descending) axis.reverse()
  return axis
}

/** 在等间距轴上找最近下标（越界钳制） */
export function nearestLatticeAxisIndex(axis: readonly number[], value: number): number {
  if (axis.length === 0) return 0
  if (axis.length === 1) return 0
  const first = axis[0]!
  const last = axis[axis.length - 1]!
  const step = (last - first) / (axis.length - 1)
  if (!(Math.abs(step) > 1e-12)) return 0
  const idx = Math.round((value - first) / step)
  return Math.max(0, Math.min(axis.length - 1, idx))
}

/** 由格心生成严格半格贴合的格元（邻格共享边、无面积重叠） */
export function latticeCellBounds(
  lon: number,
  lat: number,
  resolution: number,
  options?: { seamEps?: number },
): LngLatBounds {
  const res = Math.max(1e-9, Number(resolution) || 0.25)
  const cl = snapToLatticeCenter(lon, res)
  const ct = snapToLatticeCenter(lat, res)
  const half = res / 2
  const eps = options?.seamEps ?? CELL_SEAM_EPS_DEG
  return {
    west: cl - half - eps,
    east: cl + half + eps,
    south: ct - half - eps,
    north: ct + half + eps,
  }
}

/**
 * 轴对齐矩形与半开瓦片框求交（调试 / 特殊用途）。
 * 连续色场渲染不要用：会在格网边≠瓦片边时挖出空隙。
 */
export function intersectCellWithTileHalfOpen(
  cell: LngLatBounds,
  tile: LngLatBounds,
  options?: { includeEast?: boolean; includeSouth?: boolean },
): LngLatBounds | null {
  const includeEast = options?.includeEast === true
  const includeSouth = options?.includeSouth === true
  const west = Math.max(cell.west, tile.west)
  // 半开归属：includeEast=false 时排除东边界（减极小 eps），与 pointInTileHalfOpen 对齐
  const eastLimit = includeEast ? tile.east : tile.east - GRID_AXIS_EPS
  const southLimit = includeSouth ? tile.south : tile.south + GRID_AXIS_EPS
  const east = Math.min(cell.east, eastLimit)
  const south = Math.max(cell.south, southLimit)
  const north = Math.min(cell.north, tile.north)

  if (!(west < east - GRID_AXIS_EPS)) return null
  if (!(south < north - GRID_AXIS_EPS)) return null
  return { west, south, east, north }
}

export function boundsToPolygonRing(bounds: LngLatBounds): number[][] {
  return [
    [bounds.west, bounds.south],
    [bounds.east, bounds.south],
    [bounds.east, bounds.north],
    [bounds.west, bounds.north],
    [bounds.west, bounds.south],
  ]
}
