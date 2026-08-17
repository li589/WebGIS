/**
 * CRS 转换器 — proj4 包装 + GCJ-02/BD-09 委托 + 偏移应用。
 *
 * 镜像后端 `_crs_transformer.py`：
 * - 加密坐标系（GCJ02/BD09）路由到 `gcj-bd.ts`，不走 proj4
 * - EPSG 系走 `proj4(src, tgt, [lng, lat])`
 * - 偏移在 CRS 转换**之后**应用
 * - bounds：边加密采样 + 日界线展开 + 投影域钳位，避免 EASE 全球网格
 *   因浮点越界导致 west≈east≈-180
 */
import proj4 from 'proj4'
import {
  gcj02ToWgs84,
  wgs84ToGcj02,
  bd09ToGcj02,
  gcj02ToBd09,
  bd09ToWgs84,
  wgs84ToBd09,
} from './gcj-bd'
import type { TransformOptions } from './crs-types'

const ENCRYPTED_CODES = new Set(['GCJ02', 'BD09'])
const WGS84 = 'EPSG:4326'
const GEOGRAPHIC_TARGETS = new Set(['EPSG:4326', 'EPSG:4490', 'EPSG:4258'])

/** NSIDC EASE-Grid 2.0 Global 投影域半宽/半高（米） */
// eslint-disable-next-line no-loss-of-precision -- NSIDC EASE-Grid 2.0 spec constants
const EASE2_ULX = 17367530.445161516

const EASE2_ULY = 7314540.830865865
const EASE2_LAT_MAX = 85.04456642797585

function isEncrypted(code: string): boolean {
  return ENCRYPTED_CODES.has(code) || ENCRYPTED_CODES.has(code.replace('-', ''))
}

function normalizeCode(code: string): string {
  const map: Record<string, string> = { 'GCJ-02': 'GCJ02', 'BD-09': 'BD09' }
  return map[code] ?? code
}

/**
 * 单点转换。加密系走 gcj-bd.ts，EPSG 系走 proj4。
 * 偏移在 CRS 转换**后**应用（与后端一致）。
 */
export function transformPoint(
  lng: number,
  lat: number,
  sourceCode: string,
  targetCode: string,
  opts: TransformOptions = {},
): [number, number] {
  const src = normalizeCode(sourceCode)
  const tgt = normalizeCode(targetCode)
  let result: [number, number]
  if (src === tgt) {
    result = [lng, lat]
  } else if (isEncrypted(src) || isEncrypted(tgt)) {
    result = transformEncrypted(lng, lat, src, tgt)
  } else {
    result = proj4(src, tgt, [lng, lat]) as [number, number]
  }
  if (!Number.isFinite(result[0]) || !Number.isFinite(result[1])) {
    throw new Error(`坐标转换结果非有限值: ${src}→${tgt} (${lng}, ${lat})`)
  }
  return [result[0] + (opts.lngOffset ?? 0), result[1] + (opts.latOffset ?? 0)]
}

// 投影域钳位表（与后端 grid_presets._PROJECTED_DOMAIN_BY_CRS 一致）
const PROJECTED_DOMAIN_BY_CRS: Record<string, [number, number]> = {
  'EPSG:6933': [EASE2_ULX, EASE2_ULY],
  'EPSG:6931': [9010000, 9010000],
  'EPSG:6932': [9010000, 9010000],
  'EPSG:3408': [9073690, 9073690],
  'EPSG:3409': [9073690, 9073690],
  'EPSG:3410': [17334194, 7356861],
}

function clampProjectedBounds(
  bounds: [number, number, number, number],
  sourceCode: string,
): [number, number, number, number] {
  const src = normalizeCode(sourceCode)
  const domain = PROJECTED_DOMAIN_BY_CRS[src]
  if (!domain) return bounds
  const eps = 1e-6
  const xmax = domain[0] - eps
  const ymax = domain[1] - eps
  const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))
  return [
    clamp(bounds[0], -xmax, xmax),
    clamp(bounds[1], -ymax, ymax),
    clamp(bounds[2], -xmax, xmax),
    clamp(bounds[3], -ymax, ymax),
  ]
}

/** 沿矩形四边加密采样（含四角），用于投影→地理时捕捉极值 */
function densifyRectangleEdges(
  west: number,
  south: number,
  east: number,
  north: number,
  densifyPts = 21,
): Array<[number, number]> {
  const n = Math.max(2, densifyPts)
  const pts: Array<[number, number]> = []
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1)
    pts.push([west + (east - west) * t, south])
    pts.push([west + (east - west) * t, north])
    pts.push([west, south + (north - south) * t])
    pts.push([east, south + (north - south) * t])
  }
  return pts
}

/** 将经度序列相对首点展开，避免 ±180 折返破坏 min/max */
function unwrapLongitudes(lons: number[]): number[] {
  if (!lons.length) return []
  const out = [lons[0]!]
  for (let i = 1; i < lons.length; i++) {
    let lon = lons[i]!
    const prev = out[i - 1]!
    while (lon - prev > 180) lon -= 360
    while (lon - prev < -180) lon += 360
    out.push(lon)
  }
  return out
}

function snapLon(v: number): number {
  if (!Number.isFinite(v)) return v
  if (Math.abs(v - 180) < 1e-9 || Math.abs(v + 180) < 1e-9) {
    return v > 0 ? 180 : -180
  }
  // 归一到 (-180, 180]
  let x = ((((v + 180) % 360) + 360) % 360) - 180
  if (x === -180 && v > 0) x = 180
  return x
}

function normalizeGeographicBounds(
  west: number,
  south: number,
  east: number,
  north: number,
  sourceSpanHint?: number,
): [number, number, number, number] {
  south = Math.max(-90, Math.min(90, south))
  north = Math.max(-90, Math.min(90, north))
  if (south > north) {
    const t = south
    south = north
    north = t
  }

  const easeSpan = 2 * EASE2_ULX
  const looksGlobalSrc =
    sourceSpanHint != null && Math.abs(sourceSpanHint - easeSpan) / easeSpan < 1e-6
  const lonSpan = Math.abs(east - west)
  const collapsed = lonSpan < 1e-6 || (looksGlobalSrc && lonSpan < 1.0)
  const easeLat = Math.abs(south + EASE2_LAT_MAX) < 0.15 && Math.abs(north - EASE2_LAT_MAX) < 0.15

  if (collapsed && (looksGlobalSrc || easeLat)) {
    return [-180, Math.max(south, -EASE2_LAT_MAX), 180, Math.min(north, EASE2_LAT_MAX)]
  }

  west = snapLon(west)
  east = snapLon(east)

  if (Math.abs(Math.abs(east - west) - 360) < 1e-6 || (west <= -179.999 && east >= 179.999)) {
    return [-180, south, 180, north]
  }

  if (west > east) {
    if (looksGlobalSrc || easeLat) return [-180, south, 180, north]
    if (east + 360 - west < 180) east += 360
  }

  if (west >= east) {
    if (looksGlobalSrc || easeLat) {
      return [-180, Math.max(south, -EASE2_LAT_MAX), 180, Math.min(north, EASE2_LAT_MAX)]
    }
    throw new Error(`规范化后经度无效: west=${west}, east=${east}`)
  }

  return [west, south, east, north]
}

/**
 * bounds 转换：边加密采样 + 日界线展开 + 地理规范化。
 * 比四角 min/max 更能抵抗全球投影（EASE/CEA）的浮点与折返问题。
 */
export function transformBounds(
  bounds: [number, number, number, number], // [west, south, east, north]
  sourceCode: string,
  targetCode: string,
): [number, number, number, number] {
  const src = normalizeCode(sourceCode)
  const tgt = normalizeCode(targetCode)
  if (src === tgt) return [...bounds] as [number, number, number, number]

  const clamped = clampProjectedBounds(bounds, src)
  const [w0, s0, e0, n0] = clamped
  if (!(w0 < e0 && s0 < n0)) {
    throw new Error(`无效源 bounds: [${w0}, ${s0}, ${e0}, ${n0}]`)
  }
  const sourceSpan = Math.abs(e0 - w0)

  const samples = densifyRectangleEdges(w0, s0, e0, n0, 21)
  const transformed = samples.map(([x, y]) => transformPoint(x, y, src, tgt))

  if (GEOGRAPHIC_TARGETS.has(tgt)) {
    const lats = transformed.map((p) => p[1])
    const lonsUnwrapped = unwrapLongitudes(transformed.map((p) => p[0]))
    const south = Math.min(...lats)
    const north = Math.max(...lats)
    let west = Math.min(...lonsUnwrapped)
    let east = Math.max(...lonsUnwrapped)
    // 展开后跨度接近 360 → 全球
    if (east - west > 359.5) {
      west = -180
      east = 180
    } else {
      west = snapLon(west)
      east = snapLon(east)
      if (east < west) east += 360
      if (east - west > 359.5) {
        west = -180
        east = 180
      } else if (east > 180) {
        // 单段不跨日界线的常规区域：若 unwrap 推到 >180，收回
        const altWest = snapLon(Math.min(...transformed.map((p) => p[0])))
        const altEast = snapLon(Math.max(...transformed.map((p) => p[0])))
        if (altWest < altEast) {
          west = altWest
          east = altEast
        }
      }
    }
    return normalizeGeographicBounds(west, south, east, north, sourceSpan)
  }

  const xs = transformed.map((p) => p[0])
  const ys = transformed.map((p) => p[1])
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]
}

/** 批量点转换（CSV/POI 提交时用） */
export function transformPointsBatch(
  points: Array<[number, number]>,
  sourceCode: string,
  targetCode: string,
  opts: TransformOptions = {},
): Array<[number, number]> {
  return points.map(([lng, lat]) => transformPoint(lng, lat, sourceCode, targetCode, opts))
}

function transformEncrypted(lng: number, lat: number, src: string, tgt: string): [number, number] {
  if (src === 'GCJ02' && tgt === WGS84) return gcj02ToWgs84(lng, lat)
  if (src === WGS84 && tgt === 'GCJ02') return wgs84ToGcj02(lng, lat)
  if (src === 'BD09' && tgt === 'GCJ02') return bd09ToGcj02(lng, lat)
  if (src === 'GCJ02' && tgt === 'BD09') return gcj02ToBd09(lng, lat)
  if (src === 'BD09' && tgt === WGS84) return bd09ToWgs84(lng, lat)
  if (src === WGS84 && tgt === 'BD09') return wgs84ToBd09(lng, lat)
  const wgs = src === 'BD09' ? bd09ToWgs84(lng, lat) : gcj02ToWgs84(lng, lat)
  if (tgt === 'BD09') return wgs84ToBd09(wgs[0], wgs[1])
  if (tgt === 'GCJ02') return wgs84ToGcj02(wgs[0], wgs[1])
  return proj4(WGS84, tgt, wgs) as [number, number]
}
