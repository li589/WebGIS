/**
 * Canvas 2D 共享工具 — 布局计算。
 * 所有 Canvas 2D 叠加层（粒子流、等值线、风羽）共享此模块。
 */
import type { Map as MaplibreMap } from 'maplibre-gl'

/** Canvas 布局边距（像素），确保网格边缘不被裁剪 */
const CANVAS_LAYOUT_MARGIN_PX = 40

// ── Canvas 尺寸管理 ───────────────────────────────────────

export interface CanvasLayout {
  width: number
  height: number
  offsetX: number
  offsetY: number
  /**
   * 经度 wrap 偏移量（0 或 ±360 的倍数）。
   * 在 renderWorldCopies 模式下，map.project() 只返回主世界副本位置。
   * 当用户跨越日界线平移时，网格经度需要加上此偏移量才能投影到可见副本。
   * 调用方在 project 单个点时应使用 [lon + lonWrapOffset, lat]。
   */
  lonWrapOffset: number
}

/**
 * 根据地图投影的网格范围，计算 Canvas 的最佳尺寸和偏移。
 * canvas 直接覆盖网格投影区域（非全屏），节省像素量。
 *
 * 修复：处理 renderWorldCopies: true 下的世界副本投影。
 * map.project() 只返回主世界副本位置，当用户跨越日界线平移时，
 * 网格可能在副本世界可见，但投影到主世界（屏幕外），导致 canvas 定位错误。
 * 通过将网格经度 wrap 到可见中心附近来修复此问题。
 */
export function computeCanvasLayout(
  map: MaplibreMap,
  gridWest: number,
  gridEast: number,
  gridSouth: number,
  gridNorth: number,
  margin = CANVAS_LAYOUT_MARGIN_PX,
): CanvasLayout {
  const container = map.getContainer()
  const vw = container.clientWidth
  const vh = container.clientHeight

  // 处理 renderWorldCopies 模式下的世界副本投影
  // 仅当网格经度范围 < 360° 时执行 wrap（全局范围 -180~180 不需要 wrap，
  // 否则 wrap 会将两端折叠到同一点，导致 canvas 尺寸坍缩）
  const gridLonSpan = gridEast - gridWest
  let lonWrapOffset = 0
  let projWest = gridWest
  let projEast = gridEast

  if (gridLonSpan < 360) {
    // 用相机中心而非 bounds 均值：大范围缩放时 getBounds 常接近 ±180，
    // 均值≈0，会把东亚等区域误判到错误世界副本 → 半屏/贴边空白。
    // 宽跨度（>180°）直接以相机中心为对齐参考，避免 (west+east)/2 落在错误世界。
    const visibleCenterLon = map.getCenter().lng
    const gridCenterLon = gridLonSpan > 180 ? visibleCenterLon : (gridWest + gridEast) / 2

    // 计算将 gridCenter 对齐到 visibleCenter 附近所需的偏移量（±360 的倍数）
    let offset = 0
    let adjusted = gridCenterLon
    while (adjusted < visibleCenterLon - 180) {
      adjusted += 360
      offset += 360
    }
    while (adjusted > visibleCenterLon + 180) {
      adjusted -= 360
      offset -= 360
    }

    if (offset !== 0) {
      lonWrapOffset = offset
      projWest = gridWest + offset
      projEast = gridEast + offset
    }
  }

  // 投影网格四角到屏幕坐标（使用 wrap 后的经度）
  const tl = map.project([projWest, gridNorth])
  const tr = map.project([projEast, gridNorth])
  const bl = map.project([projWest, gridSouth])
  const br = map.project([projEast, gridSouth])

  const gridMinX = Math.min(tl.x, tr.x, bl.x, br.x) - margin
  const gridMaxX = Math.max(tl.x, tr.x, bl.x, br.x) + margin
  const gridMinY = Math.min(tl.y, tr.y, bl.y, br.y) - margin
  const gridMaxY = Math.max(tl.y, tr.y, bl.y, br.y) + margin

  // 裁剪到视口范围
  const minX = Math.max(gridMinX, 0)
  const maxX = Math.min(gridMaxX, vw)
  const minY = Math.max(gridMinY, 0)
  const maxY = Math.min(gridMaxY, vh)

  const width = Math.max(1, Math.round(maxX - minX))
  const height = Math.max(1, Math.round(maxY - minY))

  return {
    width,
    height,
    offsetX: Math.round(minX),
    offsetY: Math.round(minY),
    lonWrapOffset,
  }
}

// ── Globe 模式抗飞线工具 ───────────────────────────────────────

const DEG2RAD_GLOBE = Math.PI / 180
/**
 * 当前 MapLibre 投影是否为 globe（球面）。
 * mercator 投影下所有多边形顶点都在屏幕正面，无需特殊处理。
 */
export function isGlobeProjection(map: MaplibreMap): boolean {
  try {
    return map.getProjection?.()?.type === 'globe'
  } catch {
    return false
  }
}

/**
 * 经纬度 → 单位球 3D 坐标（与 MapLibre globe_to_clip.glsl 一致）。
 * 半径 1，单位与 globe 矩阵约定的 unit sphere 对齐。
 */
export function lngLatToGlobeSphere(lon: number, latDeg: number): [number, number, number] {
  const lat = Math.max(-85.051129, Math.min(85.051129, latDeg))
  const lonR = lon * DEG2RAD_GLOBE
  const latR = lat * DEG2RAD_GLOBE
  const cosLat = Math.cos(latR)
  return [cosLat * Math.sin(lonR), Math.sin(latR), cosLat * Math.cos(lonR)]
}

/**
 * 在 MapLibre 内部 transform 不可见的私有字段时（不鼓励），退化为"以屏幕中心
 * 经纬度为可见半球中心"的近似判断。球面距离 > 90° 的顶点一定在镜头背面。
 *
 * 球面距离公式（haversine，省略 asin 取 cos 取最值以保持 O(1)）：
 *   cos(d/R) = sinφ1·sinφ2 + cosφ1·cosφ2·cos(Δλ)
 */
export function isLngLatOnGlobeVisibleSide(
  map: MaplibreMap,
  lng: number,
  lat: number,
): boolean {
  if (!isGlobeProjection(map)) return true
  // 优先尝试 MapLibre 私有 transform.elevation / cameraPos（极少见公开）。
  // 失败时退化到 getCenter 近似——center 位于屏幕中央经纬度、pitch=0 时与镜头方向一致；
  // 偏离球面中央的可见角约 75°，所以阈值取 100°（含边缘余量）。
  const c = map.getCenter()
  const sin1 = Math.sin(lat * DEG2RAD_GLOBE)
  const sin2 = Math.sin(c.lat * DEG2RAD_GLOBE)
  const cos1 = Math.cos(lat * DEG2RAD_GLOBE)
  const cos2 = Math.cos(c.lat * DEG2RAD_GLOBE)
  const dLon = (lng - c.lng) * DEG2RAD_GLOBE
  const cosD = sin1 * sin2 + cos1 * cos2 * Math.cos(dLon)
  // cosD ∈ [-1, 1]；-1 = 完全背面（antipode），1 = 完全正面
  return cosD > -0.18 // 约 100°，给屏幕边缘留余量
}

/**
 * 把经纬度多段（连续 ring）拆成不跨 antimeridian（±180°）的子段。
 *
 * 为什么：globe 模式下两点经度突越 ±180° 时，map.project 会把"亚洲"和"美洲"
 * 都投到主屏幕，但两点之间的连边会"绕过地球背面"——屏幕上看是一条横跨中央
 * 的飞线。mercator 模式下不需要拆（地球是平的，连边天然是直线）。
 *
 * 入参：coords = [[lng, lat], ...]（不闭合，多段共享）
 * 返回：[[lng, lat], ...][]——按 antimeridian 切分后的子段。
 */
export function splitCoordsOnAntimeridian(
  coords: ReadonlyArray<readonly [number, number]>,
): Array<Array<[number, number]>> {
  if (coords.length < 2) return [coords.map((c) => [c[0], c[1]] as [number, number])]
  const segments: Array<Array<[number, number]>> = []
  let current: Array<[number, number]> = [[coords[0][0], coords[0][1]]]
  for (let i = 1; i < coords.length; i++) {
    const prev = current[current.length - 1]
    const next = coords[i]
    const dLon = Math.abs(next[0] - prev[0])
    if (dLon > 180) {
      // 跨 antimeridian：把当前子段入列，新开一段
      segments.push(current)
      current = [[next[0], next[1]]]
    } else {
      current.push([next[0], next[1]])
    }
  }
  if (current.length > 0) segments.push(current)
  return segments
}

/**
 * Globe 模式下的"屏幕可见性 + antimeridian 安全"通用投影过滤。
 * 用于把一组多边形顶点拆成"屏幕内可见、连续、不跨 antimeridian"的子段。
 *
 * 返回：每个子段是已经过滤掉背面顶点的 [[lng, lat], ...]；
 * 调用方直接 lineTo 即可，不会有飞线、不会有大跨距。
 */
export function clipCoordsForGlobe(
  map: MaplibreMap,
  coords: ReadonlyArray<readonly [number, number]>,
): Array<Array<[number, number]>> {
  if (!isGlobeProjection(map)) {
    return [coords.map((c) => [c[0], c[1]] as [number, number])]
  }
  const segments = splitCoordsOnAntimeridian(coords)
  return segments
    .map((seg) => seg.filter(([lng, lat]) => isLngLatOnGlobeVisibleSide(map, lng, lat)))
    .filter((seg) => seg.length >= 2)
}