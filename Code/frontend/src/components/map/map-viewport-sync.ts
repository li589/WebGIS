export interface MapViewportBounds {
  getSouth: () => number
  getNorth: () => number
  getWest: () => number
  getEast: () => number
}

export interface MapViewportReader {
  getCenter: () => { lng: number; lat: number }
  getBounds: () => MapViewportBounds
  getZoom: () => number
  /** CSS px：地图容器宽度（用于中心锚定经度跨度） */
  getViewportWidthPx?: () => number
  /** CSS px：MapLibre transform.worldSize（一个世界的像素宽） */
  getWorldSizePx?: () => number
  getContainer?: () => { clientWidth: number }
  getCanvas?: () => { width: number; clientWidth?: number }
  transform?: { worldSize?: number }
}

export interface MapViewportSnapshot {
  center: { lng: number; lat: number }
  bbox: { west: number; south: number; east: number; north: number; crs: 'EPSG:4326' }
  zoom: number
}

function wrapLongitude(lng: number): number {
  let wrapped = lng
  while (wrapped > 180) wrapped -= 360
  while (wrapped < -180) wrapped += 360
  return wrapped
}

/** 将整段 [west,east] 平移，使 west ∈ [-180, 180) */
function shiftWestIntoPrincipal(west: number, east: number): { west: number; east: number } {
  let w = west
  let e = east
  while (w >= 180) {
    w -= 360
    e -= 360
  }
  while (w < -180) {
    w += 360
    e += 360
  }
  return { west: w, east: e }
}

/** 近全球：跨度≥此值则闭合为世界范围，避免日界线窄缝导致半屏/阴影细带 */
export const NEAR_GLOBAL_LNG_SPAN_DEG = 300

export function isNearGlobalLngSpan(spanDeg: number): boolean {
  return Number.isFinite(spanDeg) && spanDeg >= NEAR_GLOBAL_LNG_SPAN_DEG
}

/**
 * 归一化经度边界并处理反子午线穿越。
 *
 * 约定（与 ``tilesInBounds`` 对齐）：
 * - 输出 ``west ∈ [-180,180]``，``east`` 可 ``>180``（从 west 向东的连续跨度）
 * - MapLibre 已展开的 ``east > 180`` / ``west < -180`` **整段平移保留**，勿先各自折进
 *   [-180,180] 再比大小（会把亚洲–太平洋长路径误判成美洲短路径）
 * - ``east < west``：旧式跨日界线，将 east += 360
 * - 可选 ``centerLng``：若中心不在 [west,east] 内，取含中心的互补弧（修复
 *   「视口在亚太、bounds 却落在美洲」）；近全球且中心落在窄缝时退化为世界范围
 *
 * 共享给 map-viewport-sync.ts 与 wind-particle-canvas.ts。
 */
export function normalizeLngBounds(
  west: number,
  east: number,
  centerLng?: number,
): { west: number; east: number } {
  const rawSpan = east - west
  if (rawSpan >= 360) {
    return { west: -180, east: 180 }
  }

  let w = west
  let e = east
  // 已是连续区间（含 east>180）：整段平移，禁止对 east/west 各自 wrap
  if (e < w) {
    e += 360
  }
  ;({ west: w, east: e } = shiftWestIntoPrincipal(w, e))
  if (e - w >= 360) {
    return { west: -180, east: 180 }
  }

  if (centerLng !== undefined && Number.isFinite(centerLng)) {
    let c = centerLng
    while (c < w) c += 360
    while (c >= w + 360) c -= 360
    if (c > e) {
      const span = e - w
      const compSpan = 360 - span
      // 近全球视口：中心落在日界线窄缝 → 用世界范围，勿缩成一条缝
      if (span > 180 && compSpan < 30) {
        return { west: -180, east: 180 }
      }
      // 错半球：改用含相机中心的互补弧（如亚太视角却拿到美洲 bounds）
      w = e
      e = e + compSpan
      ;({ west: w, east: e } = shiftWestIntoPrincipal(w, e))
      if (e - w >= 360) {
        return { west: -180, east: 180 }
      }
    }
  }

  // 近全球：getBounds 常留日界线窄缝（如 -170..170），闭合为世界以免半屏空白
  if (isNearGlobalLngSpan(e - w)) {
    return { west: -180, east: 180 }
  }
  return { west: w, east: e }
}

/**
 * 以相机中心 ± 半屏经度估算可见弧（对齐 Windy `shouldWorldWrap` / `worldSize`）。
 * renderWorldCopies 下 getBounds 常只覆盖面积较大的一侧，另一侧以世界副本可见却不进 bbox。
 */
export function estimateLngBoundsFromCenter(
  centerLng: number,
  viewportWidthPx: number,
  worldSizePx: number,
): { west: number; east: number } | null {
  if (!(viewportWidthPx > 0) || !(worldSizePx > 0)) return null
  const halfSpanDeg = (viewportWidthPx * 360) / worldSizePx / 2
  if (!Number.isFinite(halfSpanDeg) || halfSpanDeg <= 0) return null
  if (halfSpanDeg >= 150) return { west: -180, east: 180 }
  const pad = Math.min(8, halfSpanDeg * 0.05)
  return normalizeLngBounds(centerLng - halfSpanDeg - pad, centerLng + halfSpanDeg + pad, centerLng)
}

function lngBoundsCrossesAntimeridian(b: { west: number; east: number }): boolean {
  return b.east > 180 || b.west < -180 || (b.east > b.west && b.west > 0 && b.east > 180)
}

/**
 * 在 getBounds 归一化弧与中心估弧之间择优，避免日界线附近「只亮大半半球」。
 */
export function preferVisibleLngBounds(
  fromBounds: { west: number; east: number },
  fromCenter: { west: number; east: number },
): { west: number; east: number } {
  const spanB = fromBounds.east - fromBounds.west
  const spanC = fromCenter.east - fromCenter.west
  if (!(spanB > 0) || !(spanC > 0)) return spanC > 0 ? fromCenter : fromBounds
  if (isNearGlobalLngSpan(spanC) || isNearGlobalLngSpan(spanB)) {
    return { west: -180, east: 180 }
  }

  const boundsCrosses = lngBoundsCrossesAntimeridian(fromBounds)
  const centerCrosses = lngBoundsCrossesAntimeridian(fromCenter)

  // 视觉已跨日界线而 getBounds 未跨 → 用中心估弧（修复大半半球空白）
  if (centerCrosses && !boundsCrosses) return fromCenter

  // getBounds 明显缩成单侧（面积较大的半球）→ 用更宽的中心估弧
  if (spanC > spanB * 1.15 + 5) return fromCenter

  // 二者都跨日界线：取较宽者，保证两侧瓦片/LonFrame 齐全
  if (centerCrosses && boundsCrosses) return spanC >= spanB ? fromCenter : fromBounds

  return fromBounds
}

function readViewportWidthPx(map: MapViewportReader): number | null {
  const explicit = map.getViewportWidthPx?.()
  if (explicit !== undefined && explicit > 0) return explicit
  const fromContainer = map.getContainer?.()?.clientWidth
  if (fromContainer !== undefined && fromContainer > 0) return fromContainer
  const canvas = map.getCanvas?.()
  if (canvas) {
    const cw = canvas.clientWidth || canvas.width
    if (cw > 0) return cw
  }
  return null
}

function readWorldSizePx(map: MapViewportReader): number | null {
  const explicit = map.getWorldSizePx?.()
  if (explicit !== undefined && explicit > 0) return explicit
  const fromTransform = map.transform?.worldSize
  if (fromTransform !== undefined && fromTransform > 0) return fromTransform
  return null
}

/**
 * 可见经度弧真源：normalize(getBounds) + 可选 center/worldSize 升级。
 * 瓦片、LonFrame、粒子 roam、流线撒种均应走此函数，禁止生产路径单独 normalizeLngBounds(getBounds)。
 */
export function resolveVisibleLngBounds(map: MapViewportReader): { west: number; east: number } {
  const center = map.getCenter()
  const bounds = map.getBounds()
  const fromBounds = normalizeLngBounds(bounds.getWest(), bounds.getEast(), center.lng)
  const widthPx = readViewportWidthPx(map)
  const worldPx = readWorldSizePx(map)
  if (widthPx !== null && worldPx !== null) {
    const fromCenter = estimateLngBoundsFromCenter(center.lng, widthPx, worldPx)
    if (fromCenter) return preferVisibleLngBounds(fromBounds, fromCenter)
  }
  return fromBounds
}

/**
 * 可见视口 bbox（经度走 resolveVisibleLngBounds；纬度可钳制）。
 * 粒子/流线默认 clampLat=[-85,85]；snapshot 用 [-90,90]。
 */
export function resolveVisibleViewportBBox(
  map: MapViewportReader,
  options?: { clampLat?: [number, number] },
): { west: number; south: number; east: number; north: number } {
  const [latMin, latMax] = options?.clampLat ?? ([-90, 90] as [number, number])
  const bounds = map.getBounds()
  const { west, east } = resolveVisibleLngBounds(map)
  return {
    west,
    east,
    south: Math.max(latMin, Math.min(latMax, bounds.getSouth())),
    north: Math.max(latMin, Math.min(latMax, bounds.getNorth())),
  }
}

export function buildMapViewportSnapshot(map: MapViewportReader): MapViewportSnapshot {
  const center = map.getCenter()
  const { west, south, east, north } = resolveVisibleViewportBBox(map, { clampLat: [-90, 90] })

  return {
    center: {
      lng: wrapLongitude(center.lng),
      lat: center.lat,
    },
    bbox: {
      west,
      south,
      east,
      north,
      crs: 'EPSG:4326',
    },
    zoom: map.getZoom(),
  }
}
