/**
 * ControlPanel 尺寸/偏移纯函数：缩放与拖动分离，便于单测。
 *
 * 约定：
 * - 拖动只改 offset（位置记忆），永不改 width/height
 * - 缩放只改 width/height；对边是否钉住由布局（CSS dock）或 offset 补偿决定
 * - 右侧 dock + 左下手柄：布局已钉右上，禁止再补偿 offset（否则倍移）
 */

export function clampPanelDim(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

export function clampPanelOffset(value: number, limit: number): number {
  return Math.min(limit, Math.max(-limit, value))
}

/**
 * 由手柄位置计算下一帧宽高（尚未 clamp）。
 * bottom-left：向左拖变宽、向下拖变高；右上角应在布局层保持不动。
 */
export function nextSizeFromResizeDelta(options: {
  handlePosition: 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left'
  baseWidth: number
  baseHeight: number
  deltaX: number
  deltaY: number
}): { width: number; height: number } {
  const fromLeft = options.handlePosition === 'bottom-left' || options.handlePosition === 'top-left'
  const fromTop = options.handlePosition === 'top-left' || options.handlePosition === 'top-right'
  return {
    width: fromLeft ? options.baseWidth - options.deltaX : options.baseWidth + options.deltaX,
    height: fromTop ? options.baseHeight - options.deltaY : options.baseHeight + options.deltaY,
  }
}

/**
 * 是否在 resize 时用 transform 补偿对边。
 * - 右侧 dock（analysis）：CSS 已钉右缘，补偿会与布局叠加倍移 → false
 * - 仅当手柄在左/上且布局未钉对边时才 true
 */
export function shouldCompensateOffsetOnResize(options: {
  panelKey?: string
  handlePosition: 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left'
  /** 布局层已钉住右缘（右侧 dock + fit-content） */
  layoutPinsRightEdge?: boolean
}): boolean {
  if (options.layoutPinsRightEdge) return false
  if (options.panelKey === 'analysis') return false
  const fromLeft = options.handlePosition === 'bottom-left' || options.handlePosition === 'top-left'
  const fromTop = options.handlePosition === 'top-left' || options.handlePosition === 'top-right'
  return fromLeft || fromTop
}

/** 左侧手柄时，为钉住右缘所需的 offsetX（需在 compensate=true 时使用） */
export function offsetXToPinRightEdge(
  baseOffsetX: number,
  baseWidth: number,
  nextWidth: number,
  maxOffsetX: number,
): number {
  return clampPanelOffset(baseOffsetX + baseWidth - nextWidth, maxOffsetX)
}

/** 顶部手柄时，为钉住底缘所需的 offsetY */
export function offsetYToPinBottomEdge(
  baseOffsetY: number,
  baseHeight: number,
  nextHeight: number,
  maxOffsetY: number,
): number {
  return clampPanelOffset(baseOffsetY + baseHeight - nextHeight, maxOffsetY)
}

/** 右侧 dock 面板（分析框）：布局钉右，缩放不碰 offset */
export function isRightDockedPanel(panelKey: string | undefined): boolean {
  return panelKey === 'analysis'
}
