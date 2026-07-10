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
    const bounds = map.getBounds()
    const visibleCenterLon = (bounds.getWest() + bounds.getEast()) / 2
    const gridCenterLon = (gridWest + gridEast) / 2

    // 计算将 gridCenter 对齐到 visibleCenter 附近所需的偏移量（±360 的倍数）
    let offset = 0
    let adjusted = gridCenterLon
    while (adjusted < visibleCenterLon - 180) { adjusted += 360; offset += 360 }
    while (adjusted > visibleCenterLon + 180) { adjusted -= 360; offset -= 360 }

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
