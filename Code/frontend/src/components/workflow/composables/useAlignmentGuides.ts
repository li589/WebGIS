/**
 * Workflow canvas — snap grid + alignment guides (P1-5 split).
 */
import { ref, type ShallowRef } from 'vue'

import { getGraphNodes, type LGraphClass, type LGraphNodeClass } from '../litegraph-setup'

export interface AlignmentGuide {
  orientation: 'vertical' | 'horizontal'
  pos: number
  start: number
  end: number
}

/** 吸附网格边长（graph 坐标） */
export const SNAP_GRID_SIZE = 20
/** 边缘对齐吸附阈值（graph 坐标） */
const ALIGN_SNAP_THRESHOLD = 8

export function useAlignmentGuides(graphInstance: ShallowRef<LGraphClass | null>) {
  const alignmentGuides = ref<AlignmentGuide[]>([])

  function clearAlignmentGuides() {
    if (!alignmentGuides.value.length) return
    alignmentGuides.value = []
  }

  function snapToGrid(value: number, grid = SNAP_GRID_SIZE): number {
    return Math.round(value / grid) * grid
  }

  function nodeBounds(node: LGraphNodeClass) {
    const w = node.size?.[0] ?? 200
    const h = node.size?.[1] ?? 100
    return {
      left: node.pos[0],
      top: node.pos[1],
      right: node.pos[0] + w,
      bottom: node.pos[1] + h,
      centerX: node.pos[0] + w / 2,
      centerY: node.pos[1] + h / 2,
      w,
      h,
    }
  }

  /**
   * 拖动时：优先边缘磁吸到其他节点，否则吸附到网格。
   * hard=true 时用于松手落点，强制网格对齐。
   */
  function applySnapWhileDragging(
    draggedNode: LGraphNodeClass,
    selectedNodes: Record<string, LGraphNodeClass>,
    hard = false,
  ) {
    if (!graphInstance.value) return
    const selected = Object.values(selectedNodes)
    const movers = selected.length > 0 ? selected : [draggedNode]
    const primary = draggedNode
    const pb = nodeBounds(primary)
    const others = getGraphNodes(graphInstance.value).filter(
      (n) => !movers.some((m) => m.id === n.id),
    )

    let bestDx: number | null = null
    let bestDy: number | null = null
    let bestAbsDx = ALIGN_SNAP_THRESHOLD
    let bestAbsDy = ALIGN_SNAP_THRESHOLD

    for (const o of others) {
      const ob = nodeBounds(o)
      const xCandidates = [
        ob.left - pb.left,
        ob.right - pb.right,
        ob.centerX - pb.centerX,
        ob.left - pb.right,
        ob.right - pb.left,
      ]
      const yCandidates = [
        ob.top - pb.top,
        ob.bottom - pb.bottom,
        ob.centerY - pb.centerY,
        ob.top - pb.bottom,
        ob.bottom - pb.top,
      ]
      for (const dx of xCandidates) {
        const adx = Math.abs(dx)
        if (adx < bestAbsDx) {
          bestAbsDx = adx
          bestDx = dx
        }
      }
      for (const dy of yCandidates) {
        const ady = Math.abs(dy)
        if (ady < bestAbsDy) {
          bestAbsDy = ady
          bestDy = dy
        }
      }
    }

    // 边缘磁吸优先；否则吸附到网格（hard 仅表示松手再确认一次）
    void hard
    const dx = bestDx !== null ? bestDx : snapToGrid(primary.pos[0]) - primary.pos[0]
    const dy = bestDy !== null ? bestDy : snapToGrid(primary.pos[1]) - primary.pos[1]

    if (Math.abs(dx) < 0.01 && Math.abs(dy) < 0.01) return
    for (const n of movers) {
      n.pos[0] += dx
      n.pos[1] += dy
    }
  }

  /**
   * 计算当前拖动节点与其他节点的对齐辅助线。
   * 对齐线覆盖：拖动节点与参考节点之间的跨度（更易看清对齐目标）。
   */
  function computeAlignmentGuides(draggedNode: LGraphNodeClass) {
    if (!graphInstance.value) return
    const guides: AlignmentGuide[] = []
    const others = getGraphNodes(graphInstance.value).filter((n) => n.id !== draggedNode.id)
    const threshold = ALIGN_SNAP_THRESHOLD
    const db = nodeBounds(draggedNode)
    const pad = 24

    for (const o of others) {
      const ob = nodeBounds(o)
      const xPairs: Array<[number, number]> = [
        [ob.left, db.left],
        [ob.right, db.right],
        [ob.centerX, db.centerX],
        [ob.left, db.right],
        [ob.right, db.left],
      ]
      for (const [ref, cur] of xPairs) {
        if (Math.abs(ref - cur) <= threshold) {
          guides.push({
            orientation: 'vertical',
            pos: ref,
            start: Math.min(db.top, ob.top) - pad,
            end: Math.max(db.bottom, ob.bottom) + pad,
          })
        }
      }
      const yPairs: Array<[number, number]> = [
        [ob.top, db.top],
        [ob.bottom, db.bottom],
        [ob.centerY, db.centerY],
        [ob.top, db.bottom],
        [ob.bottom, db.top],
      ]
      for (const [ref, cur] of yPairs) {
        if (Math.abs(ref - cur) <= threshold) {
          guides.push({
            orientation: 'horizontal',
            pos: ref,
            start: Math.min(db.left, ob.left) - pad,
            end: Math.max(db.right, ob.right) + pad,
          })
        }
      }
    }
    alignmentGuides.value = guides
  }

  return {
    alignmentGuides,
    clearAlignmentGuides,
    applySnapWhileDragging,
    computeAlignmentGuides,
  }
}
