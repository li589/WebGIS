/**
 * 风场网格构建 — 共享模块（Canvas 2D 与 WebGL 渲染路径共用）。
 *
 * 网格约定：
 *   - rows × cols，row 0 = 最北（lat 降序），col 0 = 最西（lon 升序）
 *   - 轴为全球对齐等间距格心（跨赤道 / 多 z 合并也先补齐中间格），保证
 *     纹理 UV `(north-lat)/(north-south)` 与行下标一致
 *   - 多瓦片合并产生的"孔洞"用局部 IDW（1/r² 权重，限制半径）填充
 *   - 无法填充的"孤岛"单元清零，避免 NaN 进入投影/渲染
 */
import { DEFAULT_HEIGHT_SUFFIX, type WindGeoJSON } from './types'
import {
  buildRegularLatticeAxis,
  detectLatticeResolution,
  nearestLatticeAxisIndex,
  unwrapLonsToMinimalSpan,
} from './weather-grid-lattice'

/** 弧度转换常数（Math.PI / 180） */
const DEG_TO_RAD = Math.PI / 180

/** 气象风向偏移量：气象风向是风来向，需加 180° 转为数学风向（风去向） */
const WIND_DIRECTION_OFFSET = 180

export interface WindGridPoint {
  lat: number
  lon: number
  speed: number
  direction: number
}

export interface WindGrid {
  rows: number
  cols: number
  south: number
  north: number
  west: number
  east: number
  points: WindGridPoint[][]
  checksum: number
}

/** 气象风向 → (u, v) 分量。u = 东向（m/s），v = 北向（m/s）。 */
export function windToUV(speed: number, directionDeg: number): [number, number] {
  const rad = (directionDeg + WIND_DIRECTION_OFFSET) * DEG_TO_RAD
  const u = speed * Math.sin(rad)
  const v = speed * Math.cos(rad)
  return [u, v]
}

/** (u, v) → (speed, direction)。涡旋中心 (0,0) 返回静风。 */
export function uvToSpeedDirection(u: number, v: number): { speed: number; direction: number } {
  const speed = Math.sqrt(u * u + v * v)
  if (speed < 1e-6) return { speed: 0, direction: 0 }
  const dirRad = Math.atan2(u, v)
  const direction = (dirRad / DEG_TO_RAD - WIND_DIRECTION_OFFSET + 360) % 360
  return { speed, direction }
}

/** 调试日志辅助 */
function debugLog(module: string, ...args: unknown[]) {
  console.log(`[${performance.now().toFixed(1)}ms] [${module}]`, ...args)
}

function readResolutionProp(props: Record<string, unknown> | null | undefined): number | null {
  if (!props) return null
  const raw =
    Number(props.resolution) ||
    Number(props.grid_resolution) ||
    Number(props.step) ||
    Number(props.cell_size)
  return Number.isFinite(raw) && raw > 0 ? raw : null
}

/**
 * 从 GeoJSON 构建规则风场网格。
 * 返回 null 表示数据不足（无有效点或网格 < 2×2）。
 */
export function buildWindGridFromGeoJSON(geojson: WindGeoJSON): WindGrid | null {
  const features = geojson?.features || []
  if (features.length === 0) return null

  const firstProps = features[0]?.properties || {}
  const heightSuffix: string = firstProps.height ?? DEFAULT_HEIGHT_SUFFIX
  const speedKey = `wind_speed_${heightSuffix}`
  const directionKey = `wind_direction_${heightSuffix}`

  // 收集所有点的数据（经度稍后解包再量化）
  // 不依赖后端的 row/col 属性 —— 多瓦片合并时各瓦片的 row/col 是相对内部的，会互相冲突覆盖
  interface RawPoint {
    lat: number
    lon: number
    speed: number
    direction: number
  }
  const rawPoints: RawPoint[] = []
  let propRes: number | null = null

  for (const f of features) {
    const coords = f.geometry?.coordinates
    if (!coords || f.geometry?.type !== 'Point') continue
    const lon = coords[0]
    const lat = coords[1]
    const props = f.properties || {}
    if (propRes === null) propRes = readResolutionProp(props as Record<string, unknown>)
    const rawSpeed = props[speedKey] ?? props.wind_speed_10m
    const rawDir = props[directionKey] ?? props.wind_direction_10m
    const speed = typeof rawSpeed === 'number' ? rawSpeed : Number(rawSpeed)
    const direction = typeof rawDir === 'number' ? rawDir : Number(rawDir)
    // 缺测/非法：跳过，勿默认 0（否则瓦片缝出现静风/异常条带）
    if (!Number.isFinite(speed) || !Number.isFinite(direction)) continue
    rawPoints.push({ lat, lon, speed, direction })
  }

  if (rawPoints.length === 0) return null

  // 跨日界线点集：解包到最小连续经度跨度，避免「半屏有风、半屏空洞」
  const unwrappedLons = unwrapLonsToMinimalSpan(rawPoints.map((p) => p.lon))
  for (let i = 0; i < rawPoints.length; i++) {
    rawPoints[i].lon = unwrappedLons[i]!
  }

  const latRes = propRes ?? detectLatticeResolution(rawPoints.map((p) => p.lat))
  const lonRes = propRes ?? detectLatticeResolution(rawPoints.map((p) => p.lon))
  // 经纬共用较细步长，避免混分辨率时一向过粗留下赤道缝
  const res = Math.min(latRes, lonRes)

  const sortedLats = buildRegularLatticeAxis(
    rawPoints.map((p) => p.lat),
    { resolution: res, descending: true },
  )
  const sortedLons = buildRegularLatticeAxis(
    rawPoints.map((p) => p.lon),
    { resolution: res, descending: false },
  )
  const rows = sortedLats.length
  const cols = sortedLons.length
  if (rows < 2 || cols < 2) return null

  // 构建二维网格，先初始化坐标（值占位 NaN 标记"无数据"）
  const NO_DATA = Number.NaN
  const points: WindGridPoint[][] = []
  const hasData: boolean[][] = []
  for (let r = 0; r < rows; r++) {
    points[r] = []
    hasData[r] = []
    for (let c = 0; c < cols; c++) {
      points[r][c] = {
        lat: sortedLats[r]!,
        lon: sortedLons[c]!,
        speed: NO_DATA,
        direction: NO_DATA,
      }
      hasData[r][c] = false
    }
  }

  let placed = 0
  for (const p of rawPoints) {
    const r = nearestLatticeAxisIndex(sortedLats, p.lat)
    const c = nearestLatticeAxisIndex(sortedLons, p.lon)
    // 同格多点（混分辨率吸附）：保留先到者
    if (hasData[r]![c]) continue
    points[r]![c] = {
      lat: sortedLats[r]!,
      lon: sortedLons[c]!,
      speed: p.speed,
      direction: p.direction,
    }
    hasData[r]![c] = true
    placed += 1
  }

  // ── 缺失单元局部 IDW：仅填近邻小孔，避免跨「大块瓦片缝」长距插值出假值 ──
  const MISSING_CELL_COUNT = rows * cols - placed
  if (MISSING_CELL_COUNT > 0) {
    const maxRadius = 2
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        if (hasData[r]![c]) continue
        let sumWeight = 0
        let sumSpeed = 0
        let sumUSin = 0
        let sumUCos = 0
        let found = false
        const rStart = Math.max(0, r - maxRadius)
        const rEnd = Math.min(rows, r + maxRadius + 1)
        const cStart = Math.max(0, c - maxRadius)
        const cEnd = Math.min(cols, c + maxRadius + 1)
        for (let rr = rStart; rr < rEnd; rr++) {
          for (let cc = cStart; cc < cEnd; cc++) {
            if (!hasData[rr]![cc]) continue
            const dr = rr - r
            const dc = cc - c
            const dist = Math.sqrt(dr * dr + dc * dc)
            if (dist === 0 || dist > maxRadius) continue
            const weight = 1 / (dist * dist)
            const src = points[rr]![cc]!
            sumWeight += weight
            sumSpeed += src.speed * weight
            const dirRad = (src.direction + WIND_DIRECTION_OFFSET) * DEG_TO_RAD
            sumUSin += Math.sin(dirRad) * src.speed * weight
            sumUCos += Math.cos(dirRad) * src.speed * weight
            found = true
          }
        }
        if (found && sumWeight > 0) {
          const avgSpeed = sumSpeed / sumWeight
          const avgURad = Math.atan2(sumUSin / sumWeight, sumUCos / sumWeight)
          const avgDirection = (avgURad / DEG_TO_RAD - WIND_DIRECTION_OFFSET + 360) % 360
          points[r]![c]!.speed = avgSpeed
          points[r]![c]!.direction = avgDirection
          hasData[r]![c] = true
        }
      }
    }
  }

  // ── 仍无数据的单元：保留 NaN，由纹理 alpha=0 丢弃（勿造假风）──────
  let unfilledCount = 0
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      if (hasData[r]![c]) continue
      points[r]![c]!.speed = Number.NaN
      points[r]![c]!.direction = Number.NaN
      unfilledCount++
    }
  }
  if (unfilledCount > 0) {
    debugLog('WindGrid', 'buildWindGrid unfilled cells left empty', unfilledCount)
  }

  const south = sortedLats[rows - 1]!
  const north = sortedLats[0]!
  const west = sortedLons[0]!
  const east = sortedLons[cols - 1]!

  let checksum = 0
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const p = points[r]![c]!
      if (Number.isFinite(p.speed) && Number.isFinite(p.direction)) {
        checksum += p.speed + p.direction
      }
    }
  }

  debugLog(
    'WindGrid',
    'buildWindGrid',
    'rows',
    rows,
    'cols',
    cols,
    'rawPoints',
    rawPoints.length,
    'placed',
    placed,
    'missing',
    MISSING_CELL_COUNT,
    'res',
    res,
    'bounds',
    { west, south, east, north },
    'checksum',
    checksum,
  )
  return { rows, cols, south, north, west, east, points, checksum }
}
