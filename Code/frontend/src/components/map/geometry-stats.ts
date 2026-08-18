/**
 * 矢量几何自动统计 — 测地线面积与周长。
 *
 * 球面近似（WGS84 等面积半径），遵循 measure-geo.ts「避免引入 turf.js」的惯例。
 * 面积采用 Chamberlain–Duquette 球面盈余公式，逐环累加、洞为负贡献；
 * 经度连续化（unwrap）保证跨反经线（180°）多边形正确。
 * 球面近似相对椭球测地线误差 < 0.5%，满足 UI 展示需求。
 */
import { haversineDistance } from './measure-geo'

/** WGS84 等面积（authalic）半径（米） */
const AUTHALIC_RADIUS_M = 6371007.181

/** 角度转弧度 */
function toRad(deg: number): number {
  return (deg * Math.PI) / 180
}

type Ring = GeoJSON.Position[]

/** 单环的有符号球面面积（m²），环不闭合亦可；<3 个有效点返回 0 */
function ringSignedAreaM2(ring: Ring): number {
  const pts = ring.filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]))
  if (pts.length < 3) return 0
  let total = 0
  let prevLng = pts[0][0]
  let prevLat = pts[0][1]
  for (let i = 1; i <= pts.length; i++) {
    // 末尾回到首点，闭合环时该边贡献为 0
    const cur = i < pts.length ? pts[i] : pts[0]
    let lng = cur[0]
    const lat = cur[1]
    // 经度连续化：跨反经线时把 Δλ 拉回 (-180, 180]
    while (lng - prevLng > 180) lng -= 360
    while (lng - prevLng < -180) lng += 360
    total += toRad(lng - prevLng) * (2 + Math.sin(toRad(prevLat)) + Math.sin(toRad(lat)))
    prevLng = lng
    prevLat = lat
  }
  return (total * AUTHALIC_RADIUS_M ** 2) / 2
}

/** 单环测地线周长（米），按闭合处理（首尾相连） */
function ringPerimeterM(ring: Ring): number {
  const pts = ring.filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]))
  let total = 0
  for (let i = 0; i < pts.length; i++) {
    const cur = pts[i]
    const next = pts[(i + 1) % pts.length]
    total += haversineDistance({ lng: cur[0], lat: cur[1] }, { lng: next[0], lat: next[1] })
  }
  return total
}

/** 开路径测地线长度（米），不闭合（LineString 用） */
function pathLengthM(points: Ring): number {
  const pts = points.filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]))
  let total = 0
  for (let i = 0; i < pts.length - 1; i++) {
    total += haversineDistance(
      { lng: pts[i][0], lat: pts[i][1] },
      { lng: pts[i + 1][0], lat: pts[i + 1][1] },
    )
  }
  return total
}

/**
 * 测地线面积（m²）。Polygon = |外环| − Σ|洞|；MultiPolygon 逐面累加；
 * 非面几何（点/线）返回 0。
 */
export function geodesicAreaM2(geometry: GeoJSON.Geometry | null | undefined): number {
  if (!geometry) return 0
  if (geometry.type === 'Polygon') {
    const rings = geometry.coordinates as Ring[]
    if (rings.length === 0) return 0
    let area = Math.abs(ringSignedAreaM2(rings[0]))
    for (let i = 1; i < rings.length; i++) area -= Math.abs(ringSignedAreaM2(rings[i]))
    return Math.max(area, 0)
  }
  if (geometry.type === 'MultiPolygon') {
    let area = 0
    for (const poly of geometry.coordinates as Ring[][]) {
      if (poly.length === 0) continue
      let a = Math.abs(ringSignedAreaM2(poly[0]))
      for (let i = 1; i < poly.length; i++) a -= Math.abs(ringSignedAreaM2(poly[i]))
      area += Math.max(a, 0)
    }
    return area
  }
  return 0
}

/**
 * 测地线周长（米）。Polygon/MultiPolygon 累加全部环（含洞）；
 * LineString/MultiLineString 返回线总长；点几何返回 0。
 */
export function geodesicPerimeterM(geometry: GeoJSON.Geometry | null | undefined): number {
  if (!geometry) return 0
  switch (geometry.type) {
    case 'Polygon':
      return (geometry.coordinates as Ring[]).reduce((s, r) => s + ringPerimeterM(r), 0)
    case 'MultiPolygon':
      return (geometry.coordinates as Ring[][]).reduce(
        (s, poly) => s + poly.reduce((s2, r) => s2 + ringPerimeterM(r), 0),
        0,
      )
    case 'LineString':
      return pathLengthM(geometry.coordinates as Ring)
    case 'MultiLineString':
      return (geometry.coordinates as Ring[]).reduce((s, r) => s + pathLengthM(r), 0)
    default:
      return 0
  }
}

export interface GeometrySummary {
  /** 测地线面积（m²），仅统计面要素 */
  areaM2: number
  /** 测地线周长/线总长（m） */
  perimeterM: number
  /** 面要素数量 */
  polygonCount: number
  /** 线要素数量 */
  lineCount: number
}

/** 汇总 FeatureCollection 的测地线几何统计 */
export function summarizeFeatureCollection(fc: GeoJSON.FeatureCollection): GeometrySummary {
  const summary: GeometrySummary = { areaM2: 0, perimeterM: 0, polygonCount: 0, lineCount: 0 }
  for (const f of fc.features) {
    const g = f.geometry
    if (!g) continue
    const area = geodesicAreaM2(g)
    summary.areaM2 += area
    if (area > 0) summary.polygonCount += 1
    if (g.type === 'LineString' || g.type === 'MultiLineString') summary.lineCount += 1
    summary.perimeterM += geodesicPerimeterM(g)
  }
  return summary
}

/**
 * 格式化面积：自动切换 m² / km²。
 * - < 10000 m² → "850 m²"
 * - < 100 km² → "12.35 km²"（2 位小数）
 * >= 100 km² → "123.4 km²"（1 位小数）
 */
export function formatArea(m2: number): string {
  if (!Number.isFinite(m2) || m2 < 0) return '--'
  if (m2 < 10000) return `${m2.toFixed(0)} m²`
  if (m2 < 1e8) return `${(m2 / 1e6).toFixed(2)} km²`
  return `${(m2 / 1e6).toFixed(1)} km²`
}

/**
 * 格式化长度/周长：自动切换 m / km。
 * - < 1000 m → "850 m"
 * - < 10000 m → "1.23 km"
 * >= 10000 m → "12.3 km"
 */
export function formatLength(m: number): string {
  if (!Number.isFinite(m) || m < 0) return '--'
  if (m < 1000) return `${m.toFixed(0)} m`
  if (m < 10000) return `${(m / 1000).toFixed(2)} km`
  return `${(m / 1000).toFixed(1)} km`
}
