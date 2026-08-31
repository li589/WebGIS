/**
 * Agent 伴侣挂件：拖动几何 + 左右贴边吸附（纯函数，可单测）。
 */

export type CompanionDock = 'left' | 'right' | 'none'

export interface CompanionPoint {
  x: number
  y: number
}

export interface CompanionBounds {
  width: number
  height: number
}

export interface CompanionSnapResult {
  x: number
  y: number
  dock: CompanionDock
}

/** 贴边判定阈值（px） */
export const COMPANION_DOCK_THRESHOLD_PX = 24

/** 贴边半隐藏时露出的 peek 宽度（px） */
export const COMPANION_PEEK_PX = 22

export const COMPANION_SIZE_PX = 56

/** 对话面板默认尺寸（可被 CSS resize 放大） */
export const AGENT_CHAT_PANEL_WIDTH_PX = 420
export const AGENT_CHAT_PANEL_MAX_HEIGHT_PX = 560

/**
 * 将指针位置限制在舞台内，并在靠近左右边缘时吸附为 dock。
 */
export function snapCompanionPosition(
  point: CompanionPoint,
  stage: CompanionBounds,
  size = COMPANION_SIZE_PX,
  threshold = COMPANION_DOCK_THRESHOLD_PX,
): CompanionSnapResult {
  const maxX = Math.max(0, stage.width - size)
  const maxY = Math.max(0, stage.height - size)
  const x = Math.min(maxX, Math.max(0, point.x))
  const y = Math.min(maxY, Math.max(0, point.y))

  if (x <= threshold) {
    return { x: 0, y, dock: 'left' }
  }
  if (x >= maxX - threshold) {
    return { x: maxX, y, dock: 'right' }
  }
  return { x, y, dock: 'none' }
}

/** 贴边半隐藏时的视觉偏移（向边外移，只留 peek） */
export function companionDockOffset(
  dock: CompanionDock,
  size = COMPANION_SIZE_PX,
  peek = COMPANION_PEEK_PX,
): number {
  const hidden = Math.max(0, size - peek)
  if (dock === 'left') return -hidden
  if (dock === 'right') return hidden
  return 0
}

/** 位移是否视为拖动（而非点击） */
export function isCompanionDragGesture(
  dx: number,
  dy: number,
  thresholdPx = 6,
): boolean {
  return Math.hypot(dx, dy) >= thresholdPx
}
