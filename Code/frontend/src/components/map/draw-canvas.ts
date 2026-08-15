/**
 * 绘制要素标注层 — Canvas 2D 渲染。
 *
 * 职责：
 *   1. 渲染当前绘制中的顶点手柄（小圆圈 + 序号）
 *   2. 渲染鼠标预览线（虚线连接最后顶点和鼠标位置）
 *   3. 渲染选中要素的高亮边框
 *   4. 矩形模式预览
 *
 * 复用模式：参考 measure-canvas.ts 的 Canvas 创建、地图事件钩子、rAF 节流。
 */
import type { Map as MaplibreMap } from 'maplibre-gl'
import type { DrawVertex, DrawFeature, DrawMode } from '../../stores/draw-store'

const MAX_PIXEL_RATIO = 2
const VERTEX_RADIUS = 6
const VERTEX_STROKE = '#fff'
const VERTEX_FILL = '#2b7fff'
const VERTEX_FILL_FIRST = '#f59e0b'
const VERTEX_STROKE_WIDTH = 2
const PREVIEW_STROKE = 'rgba(43, 127, 255, 0.75)'
const PREVIEW_DASH = [6, 4]
const SELECTED_STROKE = '#f59e0b'
const SELECTED_WIDTH = 3

interface ScreenPoint {
  x: number
  y: number
}

interface CanvasLayout {
  width: number
  height: number
  offsetX: number
  offsetY: number
}

function computeCanvasLayout(map: MaplibreMap): CanvasLayout {
  const container = map.getContainer()
  const rect = container.getBoundingClientRect()
  return { width: rect.width, height: rect.height, offsetX: 0, offsetY: 0 }
}

export class DrawCanvas {
  private map: MaplibreMap
  private canvas: HTMLCanvasElement
  private ctx: CanvasRenderingContext2D
  private pixelRatio: number
  private layout: CanvasLayout = { width: 0, height: 0, offsetX: 0, offsetY: 0 }
  private visible = false
  private rafId: number | null = null
  private resizeObserver: ResizeObserver | null = null

  private vertices: DrawVertex[] = []
  private features: DrawFeature[] = []
  private hoverPoint: DrawVertex | null = null
  private isDrawing = false
  private selectedIndex: number | null = null

  private moveHandler: (() => void) | null = null
  private moveendHandler: (() => void) | null = null
  private zoomHandler: (() => void) | null = null

  constructor(map: MaplibreMap) {
    this.map = map
    this.pixelRatio = Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO)

    this.canvas = document.createElement('canvas')
    this.canvas.style.position = 'absolute'
    this.canvas.style.top = '0'
    this.canvas.style.left = '0'
    this.canvas.style.pointerEvents = 'none'
    this.canvas.className = 'draw-canvas'
    this.canvas.style.zIndex = '7'
    this.canvas.style.display = 'none'

    const container = map.getContainer()
    container.appendChild(this.canvas)

    this.ctx = this.canvas.getContext('2d')!
    this.resize()
    this.resizeObserver = new ResizeObserver(() => this.resize())
    this.resizeObserver.observe(container)
  }

  private resize(): void {
    this.layout = computeCanvasLayout(this.map)
    const w = this.layout.width * this.pixelRatio
    const h = this.layout.height * this.pixelRatio
    this.canvas.width = w
    this.canvas.height = h
    this.canvas.style.width = this.layout.width + 'px'
    this.canvas.style.height = this.layout.height + 'px'
    this.ctx.setTransform(this.pixelRatio, 0, 0, this.pixelRatio, 0, 0)
    if (this.visible) this.scheduleRender()
  }

  updateState(
    vertices: DrawVertex[],
    features: DrawFeature[],
    hoverPoint: DrawVertex | null,
    isDrawing: boolean,
    _drawMode: DrawMode,
    selectedIndex: number | null,
  ): void {
    this.vertices = vertices
    this.features = features
    this.hoverPoint = hoverPoint
    this.isDrawing = isDrawing
    this.selectedIndex = selectedIndex
    if (this.visible) this.scheduleRender()
  }

  show(): void {
    if (this.visible) return
    this.visible = true
    this.canvas.style.display = ''
    this.resize()

    this.moveHandler = () => this.scheduleRender()
    this.moveendHandler = () => this.scheduleRender()
    this.zoomHandler = () => this.scheduleRender()
    this.map.on('move', this.moveHandler)
    this.map.on('moveend', this.moveendHandler)
    this.map.on('zoom', this.zoomHandler)

    this.scheduleRender()
  }

  hide(): void {
    this.visible = false
    this.canvas.style.display = 'none'
    if (this.moveHandler) this.map.off('move', this.moveHandler)
    if (this.moveendHandler) this.map.off('moveend', this.moveendHandler)
    if (this.zoomHandler) this.map.off('zoom', this.zoomHandler)
    this.moveHandler = null
    this.moveendHandler = null
    this.zoomHandler = null
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId)
      this.rafId = null
    }
  }

  private scheduleRender(): void {
    if (this.rafId !== null) return
    this.rafId = requestAnimationFrame(() => {
      this.rafId = null
      this.render()
    })
  }

  private project(lng: number, lat: number): ScreenPoint {
    const p = this.map.project([lng, lat])
    return { x: p.x + this.layout.offsetX, y: p.y + this.layout.offsetY }
  }

  private render(): void {
    const ctx = this.ctx
    const { width, height } = this.layout
    ctx.clearRect(0, 0, width, height)

    // 矩形模式预览由 draw-module 的 GeoJSON preview 层渲染，本层不重复绘制

    // 顶点手柄
    if (this.vertices.length > 0) {
      this.renderVertexHandles(ctx)
    }

    // 预览线
    if (this.isDrawing && this.hoverPoint && this.vertices.length > 0) {
      this.renderPreviewLine(ctx)
    }

    // 选中要素高亮
    if (this.selectedIndex !== null && this.selectedIndex < this.features.length) {
      this.renderSelectedFeature(ctx, this.selectedIndex)
    }
  }

  private renderVertexHandles(ctx: CanvasRenderingContext2D): void {
    for (let i = 0; i < this.vertices.length; i++) {
      const v = this.vertices[i]
      const sp = this.project(v.lng, v.lat)
      const isFirst = i === 0

      ctx.beginPath()
      ctx.arc(sp.x, sp.y, VERTEX_RADIUS, 0, Math.PI * 2)
      ctx.fillStyle = isFirst ? VERTEX_FILL_FIRST : VERTEX_FILL
      ctx.fill()
      ctx.strokeStyle = VERTEX_STROKE
      ctx.lineWidth = VERTEX_STROKE_WIDTH
      ctx.stroke()

      if (this.vertices.length > 1) {
        ctx.fillStyle = VERTEX_STROKE
        ctx.font = '10px sans-serif'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText(String(i + 1), sp.x, sp.y)
      }
    }
  }

  private renderPreviewLine(ctx: CanvasRenderingContext2D): void {
    const last = this.vertices[this.vertices.length - 1]
    const lastSp = this.project(last.lng, last.lat)
    const hoverSp = this.project(this.hoverPoint!.lng, this.hoverPoint!.lat)

    ctx.beginPath()
    ctx.setLineDash(PREVIEW_DASH)
    ctx.moveTo(lastSp.x, lastSp.y)
    ctx.lineTo(hoverSp.x, hoverSp.y)
    ctx.strokeStyle = PREVIEW_STROKE
    ctx.lineWidth = 2
    ctx.stroke()
    ctx.setLineDash([])
  }

  private renderSelectedFeature(ctx: CanvasRenderingContext2D, index: number): void {
    const feature = this.features[index]
    if (!feature) return

    const coords =
      feature.geometry.type === 'Polygon'
        ? feature.geometry.coordinates[0]
        : feature.geometry.coordinates

    if (coords.length < 2) return

    ctx.beginPath()
    const first = this.project(coords[0][0], coords[0][1])
    ctx.moveTo(first.x, first.y)
    for (let i = 1; i < coords.length; i++) {
      const sp = this.project(coords[i][0], coords[i][1])
      ctx.lineTo(sp.x, sp.y)
    }
    if (feature.geometry.type === 'Polygon') {
      ctx.closePath()
    }
    ctx.strokeStyle = SELECTED_STROKE
    ctx.lineWidth = SELECTED_WIDTH
    ctx.setLineDash([8, 4])
    ctx.stroke()
    ctx.setLineDash([])
  }

  dispose(): void {
    this.hide()
    if (this.resizeObserver) {
      this.resizeObserver.disconnect()
      this.resizeObserver = null
    }
    if (this.canvas.parentNode) {
      this.canvas.parentNode.removeChild(this.canvas)
    }
  }
}
