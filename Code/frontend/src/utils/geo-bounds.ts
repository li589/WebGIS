/**
 * 纯地理边界计算工具（无组件依赖）。
 *
 * 从 components/map/map-viewport-sync.ts 提取，供 stores/ 与 components/ 共享。
 */

/** 近全球：跨度≥此值则闭合为世界范围，避免日界线窄缝导致半屏/阴影细带 */
export const NEAR_GLOBAL_LNG_SPAN_DEG = 300

export function isNearGlobalLngSpan(spanDeg: number): boolean {
  return Number.isFinite(spanDeg) && spanDeg >= NEAR_GLOBAL_LNG_SPAN_DEG
}

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
