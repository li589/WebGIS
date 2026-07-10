/**
 * 风羽（Wind Barb）渲染层 — Canvas 2D。
 *
 * 在风场网格点上绘制标准气象风羽符号：
 *   - 短线 = 5 m/s
 *   - 长线 = 10 m/s
 *   - 三角旗 = 50 m/s
 *   - 杆方向 = 风吹来的方向（气象风向）
 *
 * 使用 Canvas 2D API 批量绘制，仅在地图移动/缩放时重绘。
 */
import type { Map as MaplibreMap } from 'maplibre-gl'
import type { WindGeoJSON } from './types'
import { DEFAULT_HEIGHT_SUFFIX, MAP_EVENT_MOVE, MAP_EVENT_MOVEEND, MAP_EVENT_RESIZE } from './types'
import { computeCanvasLayout, type CanvasLayout } from './canvas-utils'

// ── 渲染参数常量 ─────────────────────────────────────────

/** 风羽圆圈固定半径（像素） */
const BARB_CIRCLE_RADIUS_PX = 2.0

/** 三角旗间距系数（相对于 barbSize） */
const FLAG_SPACING_RATIO = 0.25

/** 三角旗垂直边宽度（像素） */
const FLAG_PERP_WIDTH_PX = 6

/** 气象风速单位（m/s）：三角旗=50，长线=10，短横线=5 */
const BARB_FLAG_UNIT = 50
const BARB_LONG_BARB_UNIT = 10
const BARB_SHORT_BARB_UNIT = 5

/** 风羽线段最小长度（像素），过滤过短线段 */
const MIN_BARB_LINE_LENGTH_PX = 0.5

/** 长线沿杆位置增量系数（相对于 flagSpacing） */
const LONG_BARB_POS_INCREMENT_RATIO = 0.6

/** 短线长度比例（相对于长线） */
const SHORT_BARB_LENGTH_RATIO = 0.55

/** 风羽 LOD 目标间距（像素） */
const BARB_TARGET_SPACING_PX = 86

/** 风羽视口剔除边距（像素） */
const BARB_VIEWPORT_CULLING_MARGIN_PX = 60

/** LOD 最低可视 zoom（设为 0 使全球视图下也可见风羽） */
const BARB_MIN_VISIBLE_ZOOM = 0

/** DPI 上限（防止超高分屏幕创建过大 canvas） */
const MAX_PIXEL_RATIO = 2

/** 线条宽度（像素，乘以 dpr） */
const BARB_LINE_WIDTH = 1.2

// ── 类型定义 ─────────────────────────────────────────────

interface WindBarbData {
  lat: number
  lon: number
  speed: number
  direction: number
  row: number
  col: number
}

/** 线段几何 */
interface LineSegment {
  x1: number
  y1: number
  x2: number
  y2: number
}

/** 单个风羽的几何构建结果 */
interface BarbGeometry {
  lineSegments: LineSegment[]
  circles: { x: number; y: number }[]
}

/** 批量构建结果 */
interface AllBarbsGeometry {
  lineSegments: LineSegment[]
  circles: { x: number; y: number }[]
}

// ── 主类 ─────────────────────────────────────────────────

export class WindBarbLayer {
  private map: MaplibreMap
  private canvas: HTMLCanvasElement
  private ctx: CanvasRenderingContext2D
  private pixelRatio: number
  private layout: CanvasLayout = { width: 0, height: 0, offsetX: 0, offsetY: 0, lonWrapOffset: 0 }

  private data: WindBarbData[] = []

  private moveHandler: () => void
  private resizeHandler: () => void
  private rafId: number | null = null
  private isVisible = true
  private barbSize: number
  private gridCols = 0

  // 线条颜色（RGB 0-1 → 转换为 CSS rgba 字符串时乘以 255）
  private readonly STEM_COLOR = { r: 0.863, g: 0.941, b: 1.0, a: 0.90 }
  private readonly CIRCLE_COLOR = { r: 0.706, g: 0.902, b: 1.0, a: 0.80 }

  constructor(map: MaplibreMap, geojson: WindGeoJSON, options?: { barbSize?: number }) {
    this.map = map
    this.barbSize = options?.barbSize ?? 24
    this.pixelRatio = Math.min(window.devicePixelRatio, MAX_PIXEL_RATIO)

    // 创建 Canvas 2D 叠加层
    this.canvas = document.createElement('canvas')
    this.canvas.style.position = 'absolute'
    this.canvas.style.top = '0'
    this.canvas.style.left = '0'
    this.canvas.style.pointerEvents = 'none'
    this.canvas.style.zIndex = '6'
    this.canvas.className = 'wind-barb-canvas'
    map.getContainer().appendChild(this.canvas)

    const ctx = this.canvas.getContext('2d', { alpha: true })
    if (!ctx) throw new Error('Canvas 2D context not available')
    this.ctx = ctx

    this.loadData(geojson)
    this.updateLayout()

    // 用 rAF 节流：move 事件高频触发，但每帧只重绘一次
    this.moveHandler = () => {
      if (this.rafId !== null) return
      this.rafId = requestAnimationFrame(() => {
        this.rafId = null
        this.updateLayout()
        this.draw()
      })
    }
    this.resizeHandler = () => { this.updateLayout(); this.draw() }
    map.on(MAP_EVENT_MOVE, this.moveHandler)
    map.on(MAP_EVENT_MOVEEND, this.moveHandler)
    map.on(MAP_EVENT_RESIZE, this.resizeHandler)
  }

  private updateLayout(): void {
    this.layout = computeCanvasLayout(
      this.map,
      -180, 180, -90, 90, // 全局范围（风羽不一定有完整网格）
    )
    const { width, height, offsetX, offsetY } = this.layout
    const dpr = this.pixelRatio
    this.canvas.width = Math.round(width * dpr)
    this.canvas.height = Math.round(height * dpr)
    this.canvas.style.width = `${width}px`
    this.canvas.style.height = `${height}px`
    this.canvas.style.left = `${offsetX}px`
    this.canvas.style.top = `${offsetY}px`
  }

  private loadData(geojson: WindGeoJSON): void {
    const features = geojson?.features || []
    this.data = []
    this.gridCols = 0
    const firstProps = features[0]?.properties || {}
    const heightSuffix = firstProps.height ?? DEFAULT_HEIGHT_SUFFIX
    const speedKey = `wind_speed_${heightSuffix}`
    const directionKey = `wind_direction_${heightSuffix}`

    // 收集所有点和量化后的唯一经纬度
    // 不依赖后端 row/col —— 多瓦片合并时各瓦片的 row/col 是相对内部的，会互相冲突
    const QUANT = 1000 // 0.001° 精度，合并浮点误差
    interface RawPoint { lat: number; lon: number; speed: number; direction: number }
    const rawPoints: RawPoint[] = []
    const latQuantSet = new Set<number>()
    const lonQuantSet = new Set<number>()

    for (const f of features) {
      if (f.geometry?.type !== 'Point') continue
      const coords = f.geometry.coordinates
      const props = f.properties || {}
      const speed = (props[speedKey] ?? props.wind_speed_10m ?? 0) as number
      const direction = (props[directionKey] ?? props.wind_direction_10m ?? 0) as number
      rawPoints.push({ lat: coords[1], lon: coords[0], speed, direction })
      latQuantSet.add(Math.round(coords[1] * QUANT))
      lonQuantSet.add(Math.round(coords[0] * QUANT))
    }

    if (rawPoints.length === 0) return

    // 排序：lat 降序（北→南），lon 升序（西→东）
    const sortedLats = Array.from(latQuantSet).sort((a, b) => b - a)
    const sortedLons = Array.from(lonQuantSet).sort((a, b) => a - b)

    // 量化值 → 全局网格索引映射，确保多瓦片合并后抽稀逻辑正确
    const latIndex = new Map<number, number>()
    sortedLats.forEach((q, i) => latIndex.set(q, i))
    const lonIndex = new Map<number, number>()
    sortedLons.forEach((q, i) => lonIndex.set(q, i))

    for (const p of rawPoints) {
      this.data.push({
        lat: p.lat,
        lon: p.lon,
        speed: p.speed,
        direction: p.direction,
        row: latIndex.get(Math.round(p.lat * QUANT))!,
        col: lonIndex.get(Math.round(p.lon * QUANT))!,
      })
    }
    this.gridCols = sortedLons.length
  }

  /**
   * 计算单个风羽符号的所有线段和圆圈。
   * 几何计算逻辑：杆方向、三角旗、长线、短线均按气象风羽标准。
   */
  private buildBarbGeometry(
    cx: number, cy: number,   // canvas 内中心坐标
    dirCos: number, dirSin: number,  // 杆方向单位向量（cos/sin）
    speed: number,
  ): BarbGeometry {
    const size = this.barbSize
    // 垂直于杆的单位向量（逆时针 90°）
    const perpCos = dirCos   // 旋转 90°: (cos, sin) -> (-sin, cos)
    const perpSin = -dirSin

    const lineSegments: LineSegment[] = []
    const circles: { x: number; y: number }[] = []

    // 气象风向：风吹来的方向，杆从圆圈指向风吹来的方向
    // stem: 从 (cx, cy) 指向 (cx + stemDx, cy + stemDy)
    const stemDx = -dirSin * size  // 负 sin = cos(90°+θ)
    const stemDy =  dirCos * size  //  cos(90°+θ) = -sin(θ)

    // 圆圈
    circles.push({ x: cx, y: cy })

    // 三角旗参数
    const flagSpacing = size * FLAG_SPACING_RATIO
    const perpX = perpCos * FLAG_PERP_WIDTH_PX
    const perpY = perpSin * FLAG_PERP_WIDTH_PX

    // 风速分解
    let remaining = Math.round(speed)
    const flags50 = Math.floor(remaining / BARB_FLAG_UNIT); remaining -= flags50 * BARB_FLAG_UNIT
    const flags10 = Math.floor(remaining / BARB_LONG_BARB_UNIT); remaining -= flags10 * BARB_LONG_BARB_UNIT
    const flags5  = Math.floor(remaining / BARB_SHORT_BARB_UNIT)

    const addLine = (x1: number, y1: number, x2: number, y2: number) => {
      const dx = x2 - x1, dy = y2 - y1
      const len = Math.hypot(dx, dy)
      if (len < MIN_BARB_LINE_LENGTH_PX) return
      lineSegments.push({ x1, y1, x2, y2 })
    }

    // 杆
    addLine(cx, cy, cx + stemDx, cy + stemDy)

    let pos = 0

    // 三角旗（50 m/s）
    for (let i = 0; i < flags50; i++) {
      const fx = cx + stemDx - pos * (-stemDx / size) * flagSpacing
      const fy = cy + stemDy - pos * (-stemDy / size) * flagSpacing
      const ex = fx - perpX * 2
      const ey = fy - perpY * 2
      const bx = fx - (-stemDx / size) * flagSpacing
      const by = fy - (-stemDy / size) * flagSpacing
      addLine(fx, fy, ex, ey)
      addLine(ex, ey, bx, by)
      addLine(bx, by, fx, fy)
      pos += 1
    }

    // 长线（10 m/s）
    for (let i = 0; i < flags10; i++) {
      const fx = cx + stemDx - pos * (-stemDx / size) * flagSpacing
      const fy = cy + stemDy - pos * (-stemDy / size) * flagSpacing
      addLine(fx, fy, fx + perpX, fy + perpY)
      pos += LONG_BARB_POS_INCREMENT_RATIO
    }

    // 短线（5 m/s）— 短一半
    if (flags5 > 0) {
      const fx = cx + stemDx - pos * (-stemDx / size) * flagSpacing
      const fy = cy + stemDy - pos * (-stemDy / size) * flagSpacing
      addLine(fx, fy, fx + perpX * SHORT_BARB_LENGTH_RATIO, fy + perpY * SHORT_BARB_LENGTH_RATIO)
    }

    return { lineSegments, circles }
  }

  /** 批量计算所有风羽符号几何，含 LOD 采样和视口剔除 */
  private buildAllBarbs(): AllBarbsGeometry {
    const zoom = this.map.getZoom()
    if (zoom < BARB_MIN_VISIBLE_ZOOM || this.data.length === 0) {
      return { lineSegments: [], circles: [] }
    }

    const { width: cw, height: ch, offsetX: ox, offsetY: oy } = this.layout
    if (cw < 1 || ch < 1) {
      return { lineSegments: [], circles: [] }
    }

    // LOD：估算步长
    const targetSpacingPx = BARB_TARGET_SPACING_PX
    let gridPixelSize = 1
    if (this.data.length >= 2) {
      const p0 = this.map.project([this.data[0].lon, this.data[0].lat])
      const p1 = this.map.project([this.data[1].lon, this.data[1].lat])
      gridPixelSize = Math.hypot(p1.x - p0.x, p1.y - p0.y)
    }
    const step = Math.max(1, Math.round(targetSpacingPx / Math.max(gridPixelSize, 1)))

    const allLineSegments: LineSegment[] = []
    const allCircles: { x: number; y: number }[] = []

    for (const d of this.data) {
      if (d.row % step !== 0 || d.col % step !== 0) continue
      const screen = this.map.project([d.lon, d.lat])
      const cx = screen.x - ox
      const cy = screen.y - oy
      // 视口裁剪
      if (cx < -BARB_VIEWPORT_CULLING_MARGIN_PX || cx > cw + BARB_VIEWPORT_CULLING_MARGIN_PX ||
          cy < -BARB_VIEWPORT_CULLING_MARGIN_PX || cy > ch + BARB_VIEWPORT_CULLING_MARGIN_PX) continue

      const rad = (d.direction * Math.PI) / 180
      const dirCos = Math.cos(rad)
      const dirSin = Math.sin(rad)

      const { lineSegments, circles } = this.buildBarbGeometry(cx, cy, dirCos, dirSin, d.speed)

      for (const seg of lineSegments) allLineSegments.push(seg)
      for (const c of circles) allCircles.push(c)
    }

    return { lineSegments: allLineSegments, circles: allCircles }
  }

  private draw(): void {
    if (!this.isVisible) return
    const zoom = this.map.getZoom()
    if (zoom < BARB_MIN_VISIBLE_ZOOM) return

    const ctx = this.ctx
    const dpr = this.pixelRatio

    // 清除画布
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)

    const { lineSegments, circles } = this.buildAllBarbs()
    if (lineSegments.length === 0 && circles.length === 0) return

    // 绘制所有线条（批量一次 stroke）
    if (lineSegments.length > 0) {
      const c = this.STEM_COLOR
      ctx.strokeStyle = `rgba(${Math.round(c.r * 255)},${Math.round(c.g * 255)},${Math.round(c.b * 255)},${c.a})`
      ctx.lineWidth = BARB_LINE_WIDTH * dpr
      ctx.lineCap = 'round'
      ctx.lineJoin = 'round'

      ctx.beginPath()
      for (const seg of lineSegments) {
        ctx.moveTo(seg.x1 * dpr, seg.y1 * dpr)
        ctx.lineTo(seg.x2 * dpr, seg.y2 * dpr)
      }
      ctx.stroke()
    }

    // 绘制所有圆圈
    if (circles.length > 0) {
      const c = this.CIRCLE_COLOR
      ctx.fillStyle = `rgba(${Math.round(c.r * 255)},${Math.round(c.g * 255)},${Math.round(c.b * 255)},${c.a})`
      const radius = BARB_CIRCLE_RADIUS_PX * dpr
      for (const circle of circles) {
        ctx.beginPath()
        ctx.arc(circle.x * dpr, circle.y * dpr, radius, 0, Math.PI * 2)
        ctx.fill()
      }
    }
  }

  setVisible(visible: boolean): void {
    this.isVisible = visible
    if (!visible) {
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
    } else {
      this.draw()
    }
  }

  updateGeoJSON(geojson: WindGeoJSON): void {
    this.loadData(geojson)
    this.updateLayout()
    this.draw()
  }

  destroy(): void {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId)
      this.rafId = null
    }
    this.map.off(MAP_EVENT_MOVE, this.moveHandler)
    this.map.off(MAP_EVENT_MOVEEND, this.moveHandler)
    this.map.off(MAP_EVENT_RESIZE, this.resizeHandler)
    if (this.canvas.parentElement) {
      this.canvas.parentElement.removeChild(this.canvas)
    }
  }
}
