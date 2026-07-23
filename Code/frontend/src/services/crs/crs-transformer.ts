/**
 * CRS 转换器 — proj4 包装 + GCJ-02/BD-09 委托 + 偏移应用。
 *
 * 镜像后端 `_crs_transformer.py`：
 * - 加密坐标系（GCJ02/BD09）路由到 `gcj-bd.ts`，不走 proj4
 * - EPSG 系走 `proj4(src, tgt, [lng, lat])`
 * - 偏移在 CRS 转换**之后**应用（per user spec "在此基础上引入了偏移"）
 *
 * 使用示例::
 *
 *     import { transformPoint } from '@/services/crs'
 *     const [lng, lat] = transformPoint(116.39747, 39.9088, 'GCJ02', 'EPSG:4326')
 *     // [116.391226, 39.907397]
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
  return [result[0] + (opts.lngOffset ?? 0), result[1] + (opts.latOffset ?? 0)]
}

/** bounds 四角点转换（投影系精确，加密系四角分别转换） */
export function transformBounds(
  bounds: [number, number, number, number], // [west, south, east, north]
  sourceCode: string,
  targetCode: string,
): [number, number, number, number] {
  const [w, s, e, n] = bounds
  const corners: Array<[number, number]> = [
    [w, s],
    [e, s],
    [e, n],
    [w, n],
  ]
  const transformed = corners.map(([lng, lat]) => transformPoint(lng, lat, sourceCode, targetCode))
  const lngs = transformed.map((p) => p[0])
  const lats = transformed.map((p) => p[1])
  return [Math.min(...lngs), Math.min(...lats), Math.max(...lngs), Math.max(...lats)]
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

// 内部：加密系 6 条直连路径 + 通用路径（经 WGS84 中转）
function transformEncrypted(lng: number, lat: number, src: string, tgt: string): [number, number] {
  // 直连
  if (src === 'GCJ02' && tgt === WGS84) return gcj02ToWgs84(lng, lat)
  if (src === WGS84 && tgt === 'GCJ02') return wgs84ToGcj02(lng, lat)
  if (src === 'BD09' && tgt === 'GCJ02') return bd09ToGcj02(lng, lat)
  if (src === 'GCJ02' && tgt === 'BD09') return gcj02ToBd09(lng, lat)
  if (src === 'BD09' && tgt === WGS84) return bd09ToWgs84(lng, lat)
  if (src === WGS84 && tgt === 'BD09') return wgs84ToBd09(lng, lat)
  // 通用路径：经 WGS84 中转
  const wgs = src === 'BD09' ? bd09ToWgs84(lng, lat) : gcj02ToWgs84(lng, lat)
  if (tgt === 'BD09') return wgs84ToBd09(wgs[0], wgs[1])
  if (tgt === 'GCJ02') return wgs84ToGcj02(wgs[0], wgs[1])
  // 加密系 → EPSG 系：先转 WGS84 再 proj4
  return proj4(WGS84, tgt, wgs) as [number, number]
}
