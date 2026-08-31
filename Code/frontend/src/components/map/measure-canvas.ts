/**
 * 测量路径标注层 — Canvas 2D 渲染。
 *
 * 职责：
 *   1. 在每段路径中点绘制距离 + 方位角标签
 *   2. 根据缩放级别动态隐藏短距离段标签（像素距离 < 60px 时隐藏）
 *   3. 绘制鼠标悬停预览段（虚线 + 实时距离/角度）
 *   4. 在路径终点绘制总距离（高亮）
 *
 * 复用模式：参考 wind-particle-canvas.ts 的 Canvas 创建、地图事件钩子、rAF 节流。
 *
 * 注意：本模块只负责标注层（文字 + 预览虚线），路径线和圆点由 MapLibre GeoJSON Layer 渲染。
 */
import type { Map as MaplibreMap } from 'maplibre-gl'
import {
  computeSegments,
  formatDistance,
  formatBearing,
  haversineDistance,
  bearing,
  type LngLat,
} from './measure-geo'
import { isGlobeProjection, isLngLatOnGlobeVisibleSide } from './canvas-utils'
import type { MeasurePoint } from '../../stores/ui'

/** 标签显示的最小像素距离阈值：段在屏幕上的投影长度低于此值时隐藏标签 */
const MIN_PIXEL_FOR_LABEL = 60

/** DPI 上限（防止超高分屏创建过大 canvas） */
const MAX_PIXEL_RATIO = 2

/** 距离文字字号（px） */
const FONT_SIZE_DISTANCE = 12

/** 角度文字字号（px） */
const FONT_SIZE_BEARING = 10

/** 总距离文字字号（px，加粗） */
const FONT_SIZE_TOTAL = 13

/** 文字描边宽度（浅色描边提高地图底图对比度） */
const STROKE_WIDTH = 3

/** 标签距离段中点的偏移量（px，向上偏移避免压住线） */
const LABEL_OFFSET_Y = -8

/** 预览虚线线段长度（px） */
const DASH_PATTERN = [6, 4]

/**
 * Canvas 无法解析 CSS 变量；固定沿用深色模式下的可读配色：
 * 浅色描边 + 深色填充，在浅底/深底地图上均清晰。
 */
const LABEL_STROKE = '#f0faff'
const LABEL_FILL_DISTANCE = '#0a1626'
const LABEL_FILL_BEARING = '#1a2b42'
const LABEL_FILL_TOTAL = '#b91c1c'
const LABEL_FILL_PREVIEW = '#1e78c8'
const PREVIEW_STROKE = 'rgba(30, 120, 200, 0.75)'

// ── 类型 ─────────────────────────────────────────────────

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

// ── 工具函数 ─────────────────────────────────────────────

/** 计算两点在屏幕上的像素距离 */
function pixelDistance(p1: ScreenPoint, p2: ScreenPoint): number {
  const dx = p2.x - p1.x
  const dy = p2.y - p1.y
  return Math.sqrt(dx * dx + dy * dy)
}

/** 判断段标签是否应该显示（基于像素距离） */
function shouldShowLabel(p1Screen: ScreenPoint, p2Screen: ScreenPoint): boolean {
  return pixelDistance(p1Screen, p2Screen) >= MIN_PIXEL_FOR_LABEL
}

/**
 * 计算 Canvas 布局尺寸。
 *
 * Canvas 挂在 map container 内且 top/left=0，map.project() 已是容器坐标，无需再减 page offset。
 */
function computeCanvasLayout(map: MaplibreMap): CanvasLayout {
  const container = map.getContainer()
  const rect = container.getBoundingClientRect()
  return {
    width: rect.width,
    height: rect.height,
    offsetX: 0,
    offsetY: 0,
  }
}

// ── 主类 ─────────────────────────────────────────────────

export class MeasureCanvas {
  private map: MaplibreMap
  private canvas: HTMLCanvasElement
  private ctx: CanvasRenderingContext2D
  private pixelRatio: number
  private layout: CanvasLayout = { width: 0, height: 0, offsetX: 0, offsetY: 0 }
  private visible = false
  private rafId: number | null = null
  private resizeObserver: ResizeObserver | null = null

  // 测量状态
  private points: MeasurePoint[] = []
  private hoverPoint: MeasurePoint | null = null
  private isDrawing = false

  // 事件处理器引用（便于 dispose 时移除）
  private moveHandler: (() => void) | null = null
  private moveendHandler: (() => void) | null = null
  private zoomHandler: (() => void) | null = null
  private resizeHandler: (() => void) | null = null

  constructor(map: MaplibreMap) {
    this.map = map
    this.pixelRatio = Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO)

    // 创建 Canvas 2D 叠加层（zIndex=6，高于 wind-particle-canvas 的 5）
    this.canvas = document.createElement('canvas')
    this.canvas.style.position = 'absolute'
    this.canvas.style.top = '0'
    this.canvas.style.left = '0'
    this.canvas.style.pointerEvents = 'none'
    this.canvas.className = 'measure-canvas'
    this.canvas.style.zIndex = '6'
    this.canvas.style.display = 'none' // 初始隐藏
    map.getContainer().appendChild(this.canvas)

    const ctx = this.canvas.getContext('2d', { alpha: true })
    if (!ctx) throw new Error('MeasureCanvas: Canvas 2D context not available')
    this.ctx = ctx

    this.updateCanvasBounds()
    this.setupMapEvents()
    this.resizeObserver = new ResizeObserver(() => this.updateCanvasBounds())
    this.resizeObserver.observe(map.getContainer())
  }

  /** 设置 Canvas 尺寸（考虑 DPI） */
  private updateCanvasBounds(): void {
    this.layout = computeCanvasLayout(this.map)
    const { width, height } = this.layout
    const dpr = this.pixelRatio
    this.canvas.width = Math.round(width * dpr)
    this.canvas.height = Math.round(height * dpr)
    this.canvas.style.width = `${width}px`
    this.canvas.style.height = `${height}px`
    // 重置变换矩阵到 DPI 缩放
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    this.requestRedraw()
  }

  private setupMapEvents(): void {
    this.moveHandler = () => this.requestRedraw()
    this.moveendHandler = () => this.requestRedraw()
    this.zoomHandler = () => this.requestRedraw()
    this.resizeHandler = () => this.updateCanvasBounds()

    this.map.on('move', this.moveHandler)
    this.map.on('moveend', this.moveendHandler)
    this.map.on('zoom', this.zoomHandler)
    this.map.on('resize', this.resizeHandler)
  }

  /** 更新测量状态并触发重绘 */
  updateState(points: MeasurePoint[], hoverPoint: MeasurePoint | null, isDrawing: boolean): void {
    this.points = points
    this.hoverPoint = hoverPoint
    this.isDrawing = isDrawing
    this.requestRedraw()
  }

  /** 显示 Canvas */
  show(): void {
    this.visible = true
    this.canvas.style.display = 'block'
    this.requestRedraw()
  }

  /** 隐藏 Canvas */
  hide(): void {
    this.visible = false
    this.canvas.style.display = 'none'
    // 清除画布
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
  }

  /** 请求重绘（rAF 节流，避免高频 mousemove 触发过度重绘） */
  requestRedraw(): void {
    if (!this.visible) return
    if (this.rafId !== null) return
    this.rafId = requestAnimationFrame(() => {
      this.rafId = null
      this.draw()
    })
  }

  /** 将地理坐标投影到 canvas 内坐标（map.project 相对 map container，与 canvas 同源） */
  private projectToCanvas(lng: number, lat: number): ScreenPoint {
    const screen = this.map.project([lng, lat])
    return {
      x: screen.x,
      y: screen.y,
    }
  }

  /** 主绘制函数 */
  private draw(): void {
    if (!this.visible) return
    const ctx = this.ctx
    const { width, height } = this.layout

    // 清除画布
    ctx.clearRect(0, 0, width, height)

    if (this.points.length === 0) return

    // 将所有路径点投影到屏幕坐标
    const screenPoints = this.points.map((p) => this.projectToCanvas(p.lng, p.lat))

    // 计算段信息（距离 + 方位角）
    const lngLatPoints: LngLat[] = this.points.map((p) => ({ lng: p.lng, lat: p.lat }))
    const { segments, total } = computeSegments(lngLatPoints)

    // 绘制每段中点的距离 + 角度标签
    const onGlobe = isGlobeProjection(this.map)
    for (let i = 0; i < segments.length; i++) {
      const seg = segments[i]
      const p1 = screenPoints[i]
      const p2 = screenPoints[i + 1]
      const geo1 = this.points[i]
      const geo2 = this.points[i + 1]

      // globe 模式下不在球背面绘制距离标签，避免标签漂浮在不可见区域。
      if (
        onGlobe &&
        (!isLngLatOnGlobeVisibleSide(this.map, geo1.lng, geo1.lat) ||
          !isLngLatOnGlobeVisibleSide(this.map, geo2.lng, geo2.lat))
      ) {
        continue
      }
      if (!shouldShowLabel(p1, p2)) continue

      const midScreen: ScreenPoint = {
        x: (p1.x + p2.x) / 2,
        y: (p1.y + p2.y) / 2,
      }

      this.drawLabel(
        midScreen,
        formatDistance(seg.distance),
        FONT_SIZE_DISTANCE,
        LABEL_FILL_DISTANCE,
      )
      this.drawLabel(
        { x: midScreen.x, y: midScreen.y + FONT_SIZE_DISTANCE + 2 },
        formatBearing(seg.bearing),
        FONT_SIZE_BEARING,
        LABEL_FILL_BEARING,
      )
    }

    // 绘制预览段（如果还在绘制中且有 hoverPoint）
    if (this.isDrawing && this.hoverPoint && screenPoints.length > 0) {
      const lastPoint = screenPoints[screenPoints.length - 1]
      const hoverScreen = this.projectToCanvas(this.hoverPoint.lng, this.hoverPoint.lat)

      const lastGeo = this.points[this.points.length - 1]
      const hoverGeo = this.hoverPoint
      const previewHiddenOnGlobe =
        onGlobe &&
        (!isLngLatOnGlobeVisibleSide(this.map, lastGeo.lng, lastGeo.lat) ||
          !isLngLatOnGlobeVisibleSide(this.map, hoverGeo.lng, hoverGeo.lat) ||
          Math.abs(lastGeo.lng - hoverGeo.lng) > 180)

      if (!previewHiddenOnGlobe) {
        // 虚线预览
        ctx.save()
        ctx.strokeStyle = PREVIEW_STROKE
        ctx.lineWidth = 1.5
        ctx.setLineDash(DASH_PATTERN)
        ctx.beginPath()
        ctx.moveTo(lastPoint.x, lastPoint.y)
        ctx.lineTo(hoverScreen.x, hoverScreen.y)
        ctx.stroke()
        ctx.restore()

        // 预览段标签（仅当像素距离足够时）
        if (shouldShowLabel(lastPoint, hoverScreen)) {
          const lastLngLat: LngLat = {
            lng: this.points[this.points.length - 1].lng,
            lat: this.points[this.points.length - 1].lat,
          }
          const previewDist = haversineDistance(lastLngLat, this.hoverPoint)
          const previewBearing = bearing(lastLngLat, this.hoverPoint)
          const midScreen: ScreenPoint = {
            x: (lastPoint.x + hoverScreen.x) / 2,
            y: (lastPoint.y + hoverScreen.y) / 2,
          }
          this.drawLabel(
            midScreen,
            formatDistance(previewDist),
            FONT_SIZE_DISTANCE,
            LABEL_FILL_PREVIEW,
          )
          this.drawLabel(
            { x: midScreen.x, y: midScreen.y + FONT_SIZE_DISTANCE + 2 },
            formatBearing(previewBearing),
            FONT_SIZE_BEARING,
            LABEL_FILL_PREVIEW,
          )
        }
      }
    }

    // 在最后一个点绘制总距离（加粗高亮）
    if (segments.length > 0) {
      const lastScreen = screenPoints[screenPoints.length - 1]
      this.drawLabel(
        { x: lastScreen.x, y: lastScreen.y - 22 },
        `总计：${formatDistance(total)}`,
        FONT_SIZE_TOTAL,
        LABEL_FILL_TOTAL,
        true,
      )
    }
  }

  /** 绘制带浅色描边的文字标签（Canvas 不用 CSS 变量） */
  private drawLabel(
    pos: ScreenPoint,
    text: string,
    fontSize: number,
    fillColor: string,
    bold = false,
  ): void {
    const ctx = this.ctx
    ctx.save()
    ctx.font = `${bold ? 'bold ' : ''}${fontSize}px "Segoe UI", "Microsoft YaHei", sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.lineJoin = 'round'

    ctx.strokeStyle = LABEL_STROKE
    ctx.lineWidth = STROKE_WIDTH
    ctx.strokeText(text, pos.x, pos.y + LABEL_OFFSET_Y)

    ctx.fillStyle = fillColor
    ctx.fillText(text, pos.x, pos.y + LABEL_OFFSET_Y)
    ctx.restore()
  }

  /** 销毁：移除事件监听 + 移除 canvas */
  dispose(): void {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId)
      this.rafId = null
    }
    if (this.moveHandler) {
      this.map.off('move', this.moveHandler)
      this.moveHandler = null
    }
    if (this.moveendHandler) {
      this.map.off('moveend', this.moveendHandler)
      this.moveendHandler = null
    }
    if (this.zoomHandler) {
      this.map.off('zoom', this.zoomHandler)
      this.zoomHandler = null
    }
    if (this.resizeHandler) {
      this.map.off('resize', this.resizeHandler)
      this.resizeHandler = null
    }
    if (this.resizeObserver) {
      this.resizeObserver.disconnect()
      this.resizeObserver = null
    }
    if (this.canvas.parentElement) {
      this.canvas.parentElement.removeChild(this.canvas)
    }
  }
}
