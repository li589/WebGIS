/**
 * 地图视口读取与可见范围计算（纯函数，基于接口抽象，无组件/MapLibre 依赖）。
 *
 * 从 components/map/map-viewport-sync.ts 整体迁移（D1 依赖倒置修复）：
 * stores/ 与 services/ 应依赖本模块；components/map/map-viewport-sync.ts
 * 保留 re-export 以兼容既有组件导入。
 */
import { isNearGlobalLngSpan, normalizeLngBounds } from './geo-bounds'

export { NEAR_GLOBAL_LNG_SPAN_DEG, isNearGlobalLngSpan, normalizeLngBounds } from './geo-bounds'

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
