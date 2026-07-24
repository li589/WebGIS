/**
 * 测地线计算工具 — 用于测量模式的距离与角度计算。
 *
 * 实现 Haversine 公式计算球面测地线距离，以及初始方位角（bearing）。
 * 避免引入 turf.js 等外部依赖，保持前端 bundle 精简。
 */

/** WGS84 地球平均半径（米） */
const EARTH_RADIUS_M = 6371008.8

/** 角度转弧度 */
function toRad(deg: number): number {
  return (deg * Math.PI) / 180
}

/** 弧度转角度 */
function toDeg(rad: number): number {
  return (rad * 180) / Math.PI
}

export interface LngLat {
  lng: number
  lat: number
}

/**
 * Haversine 测地线距离（米）。
 *
 * 球面两点间最短距离，适用于中短距离路径测量。
 * 长距离（>1000km）误差 < 0.5%，满足可视化需求。
 */
export function haversineDistance(p1: LngLat, p2: LngLat): number {
  const φ1 = toRad(p1.lat)
  const φ2 = toRad(p2.lat)
  const Δφ = toRad(p2.lat - p1.lat)
  const Δλ = toRad(p2.lng - p1.lng)

  const a = Math.sin(Δφ / 2) ** 2 + Math.cos(φ1) * Math.cos(φ2) * Math.sin(Δλ / 2) ** 2
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))

  return EARTH_RADIUS_M * c
}

/**
 * 初始方位角（bearing），0° = 正北，顺时针递增。
 *
 * 返回值范围 [0, 360)。
 * 示例：东→90°，南→180°，西→270°。
 */
export function bearing(p1: LngLat, p2: LngLat): number {
  const φ1 = toRad(p1.lat)
  const φ2 = toRad(p2.lat)
  const Δλ = toRad(p2.lng - p1.lng)

  const y = Math.sin(Δλ) * Math.cos(φ2)
  const x = Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ)

  return (toDeg(Math.atan2(y, x)) + 360) % 360
}

/**
 * 格式化距离：自动切换 m / km 单位。
 *
 * - < 1000 m → "850 m"
 * - < 10000 m → "1.23 km"（2 位小数）
 * - >= 10000 m → "12.3 km"（1 位小数）
 */
export function formatDistance(m: number): string {
  if (!isFinite(m) || m < 0) return '--'
  if (m < 1000) return `${m.toFixed(0)} m`
  if (m < 10000) return `${(m / 1000).toFixed(2)} km`
  return `${(m / 1000).toFixed(1)} km`
}

/**
 * 格式化方位角：度 → "45.3°"。
 *
 * NaN 或无效值返回 "--"。
 */
export function formatBearing(deg: number): string {
  if (!isFinite(deg)) return '--'
  return `${deg.toFixed(1)}°`
}

/** 单段路径信息：距离 + 方位角 + 中点坐标 */
export interface SegmentInfo {
  /** 段距离（米） */
  distance: number
  /** 初始方位角（度，0=北，顺时针） */
  bearing: number
  /** 段中点坐标（用于标注定位） */
  midpoint: LngLat
}

/**
 * 计算路径的所有段信息与总距离。
 *
 * @param points 路径点列表（至少 2 个点才有段）
 * @returns { segments: 段信息列表, total: 总距离（米） }
 */
export function computeSegments(points: LngLat[]): {
  segments: SegmentInfo[]
  total: number
} {
  const segments: SegmentInfo[] = []
  let total = 0

  for (let i = 0; i < points.length - 1; i++) {
    const p1 = points[i]
    const p2 = points[i + 1]
    const dist = haversineDistance(p1, p2)
    const bear = bearing(p1, p2)
    const midpoint: LngLat = {
      lng: (p1.lng + p2.lng) / 2,
      lat: (p1.lat + p2.lat) / 2,
    }
    segments.push({ distance: dist, bearing: bear, midpoint })
    total += dist
  }

  return { segments, total }
}
