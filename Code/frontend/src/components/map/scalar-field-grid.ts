/**
 * 标量场规则网格（气温 / 降水 / 气压等）。
 * 布局与 wind-grid 一致：row0=北，col0=西；孔洞用局部均值填充。
 * 跨赤道时补齐中间纬度行，保证 WebGL UV 与地理纬度线性一致。
 */
import type { WindGeoJSON } from './types'
import {
  buildRegularLatticeAxis,
  detectLatticeResolution,
  nearestLatticeAxisIndex,
  unwrapLonsToMinimalSpan,
} from './weather-grid-lattice'

export interface ScalarGridPoint {
  lat: number
  lon: number
  value: number
  hasData: boolean
}

export interface ScalarGrid {
  rows: number
  cols: number
  south: number
  north: number
  west: number
  east: number
  points: ScalarGridPoint[][]
  checksum: number
}

function readMetric(
  props: Record<string, unknown> | null | undefined,
  metric: string,
): number | null {
  if (!props) return null
  const raw = props[metric]
  const n = typeof raw === 'number' ? raw : Number(raw)
  return Number.isFinite(n) ? n : null
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
 * 从 Point FeatureCollection 构建标量网格。
 * @returns null 表示数据不足（&lt;2×2）
 */
export function buildScalarGridFromGeoJSON(
  geojson: WindGeoJSON | { type: string; features?: unknown[] } | null | undefined,
  metric: string,
): ScalarGrid | null {
  const features = (geojson as WindGeoJSON | undefined)?.features
  if (!Array.isArray(features) || features.length === 0 || !metric) return null

  const rawPoints: Array<{ lat: number; lon: number; value: number }> = []
  let propRes: number | null = null

  for (const f of features) {
    const geom = f?.geometry as { type?: string; coordinates?: number[] } | undefined
    if (!geom || geom.type !== 'Point' || !Array.isArray(geom.coordinates)) continue
    const lon = Number(geom.coordinates[0])
    const lat = Number(geom.coordinates[1])
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue
    const value = readMetric(f.properties as Record<string, unknown>, metric)
    if (value === null) continue
    if (propRes === null) {
      propRes = readResolutionProp(f.properties as Record<string, unknown>)
    }
    rawPoints.push({ lat, lon, value })
  }

  if (rawPoints.length === 0) return null

  const unwrappedLons = unwrapLonsToMinimalSpan(rawPoints.map((p) => p.lon))
  for (let i = 0; i < rawPoints.length; i++) {
    rawPoints[i]!.lon = unwrappedLons[i]!
  }

  const latRes = propRes ?? detectLatticeResolution(rawPoints.map((p) => p.lat))
  const lonRes = propRes ?? detectLatticeResolution(rawPoints.map((p) => p.lon))
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

  const points: ScalarGridPoint[][] = []
  for (let r = 0; r < rows; r++) {
    points[r] = []
    for (let c = 0; c < cols; c++) {
      points[r]![c] = {
        lat: sortedLats[r]!,
        lon: sortedLons[c]!,
        value: 0,
        hasData: false,
      }
    }
  }

  for (const p of rawPoints) {
    const r = nearestLatticeAxisIndex(sortedLats, p.lat)
    const c = nearestLatticeAxisIndex(sortedLons, p.lon)
    if (points[r]![c]!.hasData) continue
    points[r]![c]!.value = p.value
    points[r]![c]!.hasData = true
  }

  // 局部均值仅填近邻小孔（半径≤2），大块瓦片缝留空 → alpha=0，避免假值
  const maxRadius = 2
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      if (points[r]![c]!.hasData) continue
      let sum = 0
      let n = 0
      for (let rr = Math.max(0, r - maxRadius); rr <= Math.min(rows - 1, r + maxRadius); rr++) {
        for (let cc = Math.max(0, c - maxRadius); cc <= Math.min(cols - 1, c + maxRadius); cc++) {
          if (!points[rr]![cc]!.hasData) continue
          const dr = rr - r
          const dc = cc - c
          const dist = Math.sqrt(dr * dr + dc * dc) || 1
          if (dist > maxRadius) continue
          const w = 1 / (dist * dist)
          sum += points[rr]![cc]!.value * w
          n += w
        }
      }
      if (n > 0) {
        points[r]![c]!.value = sum / n
        points[r]![c]!.hasData = true
      }
    }
  }

  let checksum = 0
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      checksum += points[r]![c]!.hasData ? points[r]![c]!.value : 0
    }
  }

  return {
    rows,
    cols,
    south: sortedLats[rows - 1]!,
    north: sortedLats[0]!,
    west: sortedLons[0]!,
    east: sortedLons[cols - 1]!,
    points,
    checksum,
  }
}

/** 从 legend_ticks 推断编码量程 */
export function resolveScalarValueRange(
  ticks: Array<number | string> | null | undefined,
  grid: ScalarGrid | null,
): { min: number; max: number } {
  const nums = (ticks ?? []).filter((t): t is number => typeof t === 'number' && Number.isFinite(t))
  if (nums.length >= 2) {
    return { min: Math.min(...nums), max: Math.max(...nums) }
  }
  if (!grid) return { min: 0, max: 1 }
  let min = Number.POSITIVE_INFINITY
  let max = Number.NEGATIVE_INFINITY
  for (const row of grid.points) {
    for (const p of row) {
      if (!p.hasData) continue
      min = Math.min(min, p.value)
      max = Math.max(max, p.value)
    }
  }
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) {
    return { min: Number.isFinite(min) ? min - 1 : 0, max: Number.isFinite(max) ? max + 1 : 1 }
  }
  return { min, max }
}
