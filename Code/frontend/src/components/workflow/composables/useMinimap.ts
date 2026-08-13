/**
 * Workflow canvas — minimap draw / interact / timer (P1-5 split).
 */
import type { Ref, ShallowRef } from 'vue'

import { getMinimapColors } from '../canvas-theme'
import { getGraphNodes, type LGraphCanvasClass, type LGraphClass } from '../litegraph-setup'

export function useMinimap(
  minimapRef: Ref<HTMLCanvasElement | null>,
  graphInstance: ShallowRef<LGraphClass | null>,
  canvasInstance: ShallowRef<LGraphCanvasClass | null>,
  canvasRef: Ref<HTMLCanvasElement | null>,
) {
  let _minimapTimer: ReturnType<typeof setInterval> | null = null
  let _minimapMousedownHandlerRef: ((e: MouseEvent) => void) | null = null
  let _minimapMouseupHandlerRef: (() => void) | null = null
  let _minimapMousemoveHandlerRef: ((e: MouseEvent) => void) | null = null

  function drawMinimap() {
    const mm = minimapRef.value
    const graph = graphInstance.value
    const canvas = canvasInstance.value
    if (!mm || !graph || !canvas) return
    const ctx = mm.getContext('2d')
    if (!ctx) return

    const W = mm.width
    const H = mm.height
    ctx.clearRect(0, 0, W, H)
    const mmColors = getMinimapColors()
    ctx.fillStyle = mmColors.bg
    ctx.fillRect(0, 0, W, H)

    const nodes = getGraphNodes(graph)
    if (nodes.length === 0) return

    // 计算所有节点的边界框
    let minX = Infinity,
      minY = Infinity,
      maxX = -Infinity,
      maxY = -Infinity
    for (const n of nodes) {
      const w = n.size?.[0] ?? 200
      const h = n.size?.[1] ?? 100
      minX = Math.min(minX, n.pos[0])
      minY = Math.min(minY, n.pos[1])
      maxX = Math.max(maxX, n.pos[0] + w)
      maxY = Math.max(maxY, n.pos[1] + h)
    }
    // 加 padding 避免节点贴边
    const pad = 40
    minX -= pad
    minY -= pad
    maxX += pad
    maxY += pad
    const contentW = maxX - minX
    const contentH = maxY - minY
    if (contentW <= 0 || contentH <= 0) return

    // 计算缩放比例（保持长宽比，fit 到 minimap）
    const scale = Math.min(W / contentW, H / contentH)
    const offsetX = (W - contentW * scale) / 2
    const offsetY = (H - contentH * scale) / 2

    // graph 坐标 → minimap 坐标
    const toMx = (x: number) => (x - minX) * scale + offsetX
    const toMy = (y: number) => (y - minY) * scale + offsetY

    // 绘制每个节点的矩形
    for (const n of nodes) {
      const w = n.size?.[0] ?? 200
      const h = n.size?.[1] ?? 100
      const x = toMx(n.pos[0])
      const y = toMy(n.pos[1])
      const nw = Math.max(2, w * scale)
      const nh = Math.max(2, h * scale)
      // 按引擎类型着色（module/* 属于 python_provider）
      const t = n.type ?? ''
      let color = mmColors.default
      if (t.startsWith('weather/')) color = mmColors.weather
      else if (t.startsWith('module/') || t.startsWith('python_provider/'))
        color = mmColors.pythonProvider
      else if (t.startsWith('gee/')) color = mmColors.gee
      ctx.fillStyle = color
      ctx.globalAlpha = n.selected ? 1.0 : 0.7
      ctx.fillRect(x, y, nw, nh)
    }
    ctx.globalAlpha = 1.0

    // 绘制当前视口框（橙色矩形）
    const ds = (canvas as unknown as { ds?: { offset: [number, number]; scale: number } }).ds
    const mainCanvas = canvasRef.value
    if (ds && mainCanvas) {
      // 视口在 graph 坐标系中的范围
      const viewLeft = -ds.offset[0] / ds.scale
      const viewTop = -ds.offset[1] / ds.scale
      const viewW = mainCanvas.width / ds.scale
      const viewH = mainCanvas.height / ds.scale
      const vx = toMx(viewLeft)
      const vy = toMy(viewTop)
      const vw = viewW * scale
      const vh = viewH * scale
      ctx.strokeStyle = mmColors.viewport
      ctx.lineWidth = 1
      ctx.setLineDash([3, 3])
      ctx.strokeRect(vx, vy, vw, vh)
      ctx.setLineDash([])
    }
  }

  /**
   * 将 minimap 上的点击/拖动位置转换为 graph 坐标，并同步主画布视口中心。
   */
  function syncMinimapToViewport(e: MouseEvent) {
    const mm = minimapRef.value
    const graph = graphInstance.value
    const canvas = canvasInstance.value
    if (!mm || !graph || !canvas) return

    const rect = mm.getBoundingClientRect()
    const px = e.clientX - rect.left
    const py = e.clientY - rect.top

    // 反推 graph 坐标（与 drawMinimap 中的计算对应）
    const nodes = getGraphNodes(graph)
    if (nodes.length === 0) return
    let minX = Infinity,
      minY = Infinity,
      maxX = -Infinity,
      maxY = -Infinity
    for (const n of nodes) {
      const w = n.size?.[0] ?? 200
      const h = n.size?.[1] ?? 100
      minX = Math.min(minX, n.pos[0])
      minY = Math.min(minY, n.pos[1])
      maxX = Math.max(maxX, n.pos[0] + w)
      maxY = Math.max(maxY, n.pos[1] + h)
    }
    const pad = 40
    minX -= pad
    minY -= pad
    maxX += pad
    maxY += pad
    const contentW = maxX - minX
    const contentH = maxY - minY
    if (contentW <= 0 || contentH <= 0) return

    const scale = Math.min(mm.width / contentW, mm.height / contentH)
    const offsetX = (mm.width - contentW * scale) / 2
    const offsetY = (mm.height - contentH * scale) / 2
    // minimap 坐标 → graph 坐标
    const gx = (px - offsetX) / scale + minX
    const gy = (py - offsetY) / scale + minY

    // 将主画布视口中心对齐到 (gx, gy)
    const ds = (canvas as unknown as { ds?: { offset: [number, number]; scale: number } }).ds
    const mainCanvas = canvasRef.value
    if (!ds || !mainCanvas) return
    ds.offset[0] = -gx * ds.scale + mainCanvas.width / 2
    ds.offset[1] = -gy * ds.scale + mainCanvas.height / 2
    canvas.setDirty(true, true)
  }

  /**
   * 绑定 minimap 点击/拖动事件：将点击位置同步到主画布视口中心。
   */
  function bindMinimapInteractions() {
    const mm = minimapRef.value
    if (!mm) return

    _minimapMousedownHandlerRef = (e: MouseEvent) => {
      syncMinimapToViewport(e)
      // 进入拖动模式
      _minimapMousemoveHandlerRef = (ev: MouseEvent) => syncMinimapToViewport(ev)
      mm.addEventListener('mousemove', _minimapMousemoveHandlerRef)
      _minimapMouseupHandlerRef = () => {
        if (_minimapMousemoveHandlerRef) {
          mm.removeEventListener('mousemove', _minimapMousemoveHandlerRef)
          _minimapMousemoveHandlerRef = null
        }
        if (_minimapMouseupHandlerRef) {
          mm.removeEventListener('mouseup', _minimapMouseupHandlerRef)
          _minimapMouseupHandlerRef = null
        }
      }
      mm.addEventListener('mouseup', _minimapMouseupHandlerRef)
    }
    mm.addEventListener('mousedown', _minimapMousedownHandlerRef)
  }

  function startMinimapTimer(intervalMs = 200) {
    if (_minimapTimer) clearInterval(_minimapTimer)
    _minimapTimer = setInterval(drawMinimap, intervalMs)
    drawMinimap()
  }

  function disposeMinimap() {
    if (_minimapTimer) {
      clearInterval(_minimapTimer)
      _minimapTimer = null
    }
    const mm = minimapRef.value
    if (mm) {
      if (_minimapMousedownHandlerRef) {
        mm.removeEventListener('mousedown', _minimapMousedownHandlerRef)
        _minimapMousedownHandlerRef = null
      }
      if (_minimapMousemoveHandlerRef) {
        mm.removeEventListener('mousemove', _minimapMousemoveHandlerRef)
        _minimapMousemoveHandlerRef = null
      }
      if (_minimapMouseupHandlerRef) {
        mm.removeEventListener('mouseup', _minimapMouseupHandlerRef)
        _minimapMouseupHandlerRef = null
      }
    }
  }

  return {
    bindMinimapInteractions,
    startMinimapTimer,
    disposeMinimap,
  }
}
