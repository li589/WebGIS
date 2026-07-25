/**
 * 浮点安全的地理工具：经度展开、中点、bounds 校验。
 * 与后端 `app.services.geo_math` 语义对齐。
 */

export function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

export function wrapLongitude(lng: number): number {
  if (!Number.isFinite(lng)) return lng
  let x = ((((lng + 180) % 360) + 360) % 360) - 180
  if (Math.abs(x + 180) < 1e-15) x = lng > 0 ? 180 : -180
  return x
}

/** 从 lng1 到 lng2 的最短经度差，(-180, 180] */
export function unwrapDeltaLongitude(lng1: number, lng2: number): number {
  return ((((lng2 - lng1 + 180) % 360) + 360) % 360) - 180
}

export function geographicMidpoint(
  lng1: number,
  lat1: number,
  lng2: number,
  lat2: number,
): { lng: number; lat: number } {
  if (![lng1, lat1, lng2, lat2].every(Number.isFinite)) {
    throw new Error('geographicMidpoint: 非有限坐标')
  }
  const dlon = unwrapDeltaLongitude(lng1, lng2)
  return {
    lng: wrapLongitude(lng1 + 0.5 * dlon),
    lat: (lat1 + lat2) / 2,
  }
}

/**
 * 规范化地理 bbox。跨日界线时将 east 展开到 (180, 360] 以保持 west < east
 *（与天气引擎/瓦片约定一致）；近全球则归一为 [-180,180]。
 */
export function normalizeLngLatBBox(
  west: number,
  south: number,
  east: number,
  north: number,
): [number, number, number, number] {
  if (![west, south, east, north].every(Number.isFinite)) {
    throw new Error(`非有限 bbox: [${west}, ${south}, ${east}, ${north}]`)
  }
  let s = Math.max(-90, Math.min(90, south))
  let n = Math.max(-90, Math.min(90, north))
  if (s > n) {
    const t = s
    s = n
    n = t
  }
  const w = west
  let e = east
  if (w < e && e - w <= 360) {
    if (e - w >= 359.999) return [-180, s, 180, n]
    return [w, s, e, n]
  }
  if (w > e) {
    e = e + 360
    if (e - w >= 359.999) return [-180, s, 180, n]
    return [w, s, e, n]
  }
  const pad = 1e-6
  return [w - pad, s, e + pad, n]
}

/**
 * MapLibre image overlay 可用的 WGS84 bounds。
 * 近全球 → [-180,s,180,n]；跨日界线区域允许 east∈(180,360]。
 */
export function overlaySafeWgs84Bounds(
  west: number,
  south: number,
  east: number,
  north: number,
): [number, number, number, number] {
  const [w, s, e, n] = normalizeLngLatBBox(west, south, east, north)
  const span = e - w
  if (span >= 359.999 || (w <= -179.999 && e >= 179.999) || (e > 180 && span > 180)) {
    return [-180, s, 180, n]
  }
  return [w, s, e, n]
}

/** 过滤非有限点，供 fitBounds 使用 */
export function filterFiniteLngLats(
  points: Array<{ lng: number; lat: number }>,
): Array<{ lng: number; lat: number }> {
  return points.filter((p) => Number.isFinite(p.lng) && Number.isFinite(p.lat))
}

/**
 * 对一组经度做相对展开后取最小包围盒 [west,east]（east 可能 >180）。
 */
export function lngSpanFromList(lngs: number[]): [number, number] | null {
  const finite = lngs.filter(Number.isFinite)
  if (!finite.length) return null
  const unwrapped = [finite[0]!]
  for (let i = 1; i < finite.length; i++) {
    let lon = finite[i]!
    const prev = unwrapped[i - 1]!
    while (lon - prev > 180) lon -= 360
    while (lon - prev < -180) lon += 360
    unwrapped.push(lon)
  }
  const west = Math.min(...unwrapped)
  const east = Math.max(...unwrapped)
  if (east - west >= 359.999) return [-180, 180]
  return [west, east]
}
