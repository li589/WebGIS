/**
 * 风羽（Wind Barb）渲染层 — Canvas 叠加。
 *
 * 在风场网格点上绘制标准气象风羽符号：
 *   - 短线 = 5 m/s
 *   - 长线 = 10 m/s
 *   - 三角旗 = 50 m/s
 *   - 杆方向 = 风吹来的方向（气象风向）
 *
 * 风羽不随帧动画，仅在地图移动/缩放时重绘。
 */
import type { Map as MaplibreMap } from 'maplibre-gl'

interface WindBarbData {
  lat: number
  lon: number
  speed: number
  direction: number
  row: number
  col: number
}

// ── GeoJSON 类型（轻量定义，仅覆盖风场图层用到的字段） ─────
interface WindGeoJSONFeature {
  type: 'Feature'
  geometry: { type: string; coordinates: number[] }
  properties: { wind_speed?: number; wind_direction?: number; [key: string]: any }
}
interface WindGeoJSON {
  type: 'FeatureCollection'
  features: WindGeoJSONFeature[]
}

export class WindBarbLayer {
  private map: MaplibreMap
  private canvas: HTMLCanvasElement
  private ctx: CanvasRenderingContext2D
  private data: WindBarbData[] = []
  private gridCols = 0
  private moveHandler: () => void
  private resizeHandler: () => void
  private isVisible = true
  private barbSize: number
  private rafId: number | null = null
  private canvasOffsetX = 0
  private canvasOffsetY = 0

  constructor(map: MaplibreMap, geojson: WindGeoJSON, options?: { barbSize?: number }) {
    this.map = map
    this.barbSize = options?.barbSize ?? 24

    const container = map.getContainer()
    this.canvas = document.createElement('canvas')
    this.canvas.style.position = 'absolute'
    this.canvas.style.top = '0'
    this.canvas.style.left = '0'
    this.canvas.style.pointerEvents = 'none'
    this.canvas.style.zIndex = '6'
    this.canvas.className = 'wind-barb-canvas'
    container.appendChild(this.canvas)

    this.ctx = this.canvas.getContext('2d', { desynchronized: true })!
    this.loadData(geojson)
    this.updateCanvasBounds()

    // 用 rAF 节流：move 事件高频触发，但每帧只重绘一次
    this.moveHandler = () => {
      if (this.rafId !== null) return
      this.rafId = requestAnimationFrame(() => {
        this.rafId = null
        this.updateCanvasBounds()
        this.draw()
      })
    }
    this.resizeHandler = () => { this.updateCanvasBounds(); this.draw() }
    map.on('move', this.moveHandler)
    map.on('moveend', this.moveHandler)
    map.on('resize', this.resizeHandler)
  }

  /** 将 canvas 尺寸/位置适配到数据点投影范围与视口的交集 */
  private updateCanvasBounds(): void {
    const container = this.map.getContainer()
    const vw = container.clientWidth
    const vh = container.clientHeight

    if (this.data.length === 0) {
      this.canvas.width = vw
      this.canvas.height = vh
      this.canvas.style.left = '0px'
      this.canvas.style.top = '0px'
      this.canvasOffsetX = 0
      this.canvasOffsetY = 0
      this.ctx.setTransform(1, 0, 0, 1, 0, 0)
      return
    }

    let minLat = Infinity, maxLat = -Infinity, minLon = Infinity, maxLon = -Infinity
    for (const d of this.data) {
      if (d.lat < minLat) minLat = d.lat
      if (d.lat > maxLat) maxLat = d.lat
      if (d.lon < minLon) minLon = d.lon
      if (d.lon > maxLon) maxLon = d.lon
    }

    const tl = this.map.project([minLon, maxLat])
    const tr = this.map.project([maxLon, maxLat])
    const bl = this.map.project([minLon, minLat])
    const br = this.map.project([maxLon, minLat])
    const margin = 40
    const gridMinX = Math.min(tl.x, tr.x, bl.x, br.x) - margin
    const gridMaxX = Math.max(tl.x, tr.x, bl.x, br.x) + margin
    const gridMinY = Math.min(tl.y, tr.y, bl.y, br.y) - margin
    const gridMaxY = Math.max(tl.y, tr.y, bl.y, br.y) + margin

    // 裁剪到视口范围，避免缩放放大时 canvas 尺寸膨胀
    const minX = Math.max(gridMinX, 0)
    const maxX = Math.min(gridMaxX, vw)
    const minY = Math.max(gridMinY, 0)
    const maxY = Math.min(gridMaxY, vh)
    const w = Math.max(1, Math.round(maxX - minX))
    const h = Math.max(1, Math.round(maxY - minY))

    this.canvas.width = w
    this.canvas.height = h
    this.canvas.style.width = `${w}px`
    this.canvas.style.height = `${h}px`
    this.canvas.style.left = `${Math.round(minX)}px`
    this.canvas.style.top = `${Math.round(minY)}px`
    this.canvasOffsetX = Math.round(minX)
    this.canvasOffsetY = Math.round(minY)
    this.ctx.setTransform(1, 0, 0, 1, 0, 0)
  }

  private loadData(geojson: WindGeoJSON): void {
    const features = geojson?.features || []
    this.data = []
    this.gridCols = 0
    // 保存全部数据点，采样在 draw 时按 zoom 动态进行（LOD 策略）
    // 从首个 feature 推断高度后缀，支持 10m / 80m / 120m / 180m 等多高度风场
    const firstProps = features[0]?.properties || {}
    const heightSuffix: string = firstProps.height ?? '10m'
    const speedKey = `wind_speed_${heightSuffix}`
    const directionKey = `wind_direction_${heightSuffix}`
    for (const f of features) {
      if (f.geometry?.type !== 'Point') continue
      const coords = f.geometry.coordinates
      const props = f.properties || {}
      this.data.push({
        lat: coords[1],
        lon: coords[0],
        speed: props[speedKey] ?? props.wind_speed_10m ?? 0,
        direction: props[directionKey] ?? props.wind_direction_10m ?? 0,
        row: props.row ?? 0,
        col: props.col ?? 0,
      })
      this.gridCols = Math.max(this.gridCols, (props.col ?? 0) + 1)
    }
  }

  /** 绘制单个风羽符号 */
  private drawBarb(ctx: CanvasRenderingContext2D, x: number, y: number, speed: number, direction: number): void {
    const size = this.barbSize
    // 气象风向：风吹来的方向。风羽杆从圆圈指向风吹来的方向。
    // direction 是气象风向（度），0=北风（从北吹来），杆应指向北方
    const rad = (direction * Math.PI) / 180
    // 杆方向（从圆圈出发，指向风吹来的方向）
    const stemDx = -Math.sin(rad) * size  // 北方向在屏幕上是向上（负 y）
    const stemDy = Math.cos(rad) * size

    ctx.save()
    ctx.translate(x, y)

    // 绘制圆圈（观测点）
    ctx.fillStyle = 'rgba(180, 230, 255, 0.8)'
    ctx.beginPath()
    ctx.arc(0, 0, 2, 0, Math.PI * 2)
    ctx.fill()

    // 绘制杆
    ctx.strokeStyle = 'rgba(220, 240, 255, 0.9)'
    ctx.lineWidth = 1.2
    ctx.beginPath()
    ctx.moveTo(0, 0)
    ctx.lineTo(stemDx, stemDy)
    ctx.stroke()

    // 计算旗的绘制位置（沿杆方向）
    // 旗垂直于杆方向，从杆末端向圆圈方向排列
    const perpX = -stemDy / size * 6  // 垂直于杆的方向（旗的长度）
    const perpY = stemDx / size * 6
    const flagStartX = stemDx
    const flagStartY = stemDy
    const flagSpacing = size * 0.25  // 旗之间的间距

    // 风速分解为 50/10/5 的组合
    let remaining = Math.round(speed)
    const flags50 = Math.floor(remaining / 50)
    remaining -= flags50 * 50
    const flags10 = Math.floor(remaining / 10)
    remaining -= flags10 * 10
    const flags5 = Math.floor(remaining / 5)

    let pos = 0
    ctx.fillStyle = 'rgba(220, 240, 255, 0.85)'

    // 三角旗（50 m/s）
    for (let i = 0; i < flags50; i++) {
      const fx = flagStartX - pos * stemDx / size * flagSpacing
      const fy = flagStartY - pos * stemDy / size * flagSpacing
      ctx.beginPath()
      ctx.moveTo(fx, fy)
      ctx.lineTo(fx + perpX * 2, fy + perpY * 2)
      ctx.lineTo(fx - stemDx / size * flagSpacing, fy - stemDy / size * flagSpacing)
      ctx.closePath()
      ctx.fill()
      pos += 1
    }

    // 长线（10 m/s）
    for (let i = 0; i < flags10; i++) {
      const fx = flagStartX - pos * stemDx / size * flagSpacing
      const fy = flagStartY - pos * stemDy / size * flagSpacing
      ctx.beginPath()
      ctx.moveTo(fx, fy)
      ctx.lineTo(fx + perpX, fy + perpY)
      ctx.stroke()
      pos += 0.6
    }

    // 短线（5 m/s）
    if (flags5 > 0) {
      const fx = flagStartX - pos * stemDx / size * flagSpacing
      const fy = flagStartY - pos * stemDy / size * flagSpacing
      const halfPerpX = perpX * 0.55
      const halfPerpY = perpY * 0.55
      ctx.beginPath()
      ctx.moveTo(fx, fy)
      ctx.lineTo(fx + halfPerpX, fy + halfPerpY)
      ctx.stroke()
    }

    ctx.restore()
  }

  private draw(): void {
    if (!this.isVisible) return
    const cw = this.canvas.width
    const ch = this.canvas.height
    const ox = this.canvasOffsetX
    const oy = this.canvasOffsetY
    this.ctx.clearRect(0, 0, cw, ch)

    // 只在合适的缩放级别绘制（太远不绘制）
    const zoom = this.map.getZoom()
    if (zoom < 3) return

    // LOD 策略：根据 zoom 动态调整风羽密度，目标屏幕间距 ~80px
    // 用网格首两点的屏幕距离估算单格像素大小
    const targetSpacingPx = 80
    let gridPixelSize = 0
    if (this.data.length >= 2) {
      const p0 = this.map.project([this.data[0].lon, this.data[0].lat])
      const p1 = this.map.project([this.data[1].lon, this.data[1].lat])
      gridPixelSize = Math.hypot(p1.x - p0.x, p1.y - p0.y)
    }
    // 行列采样步长 = 目标间距 / 单格像素，至少为 1
    const step = Math.max(1, Math.round(targetSpacingPx / Math.max(gridPixelSize, 1)))

    for (const d of this.data) {
      // 按 row/col 步长采样，保持网格均匀分布
      if (d.row % step !== 0 || d.col % step !== 0) continue
      const screen = this.map.project([d.lon, d.lat])
      // 视口剔除（基于 canvas 范围）
      if (screen.x < ox - 30 || screen.x > ox + cw + 30 ||
          screen.y < oy - 30 || screen.y > oy + ch + 30) continue
      // 转换为 canvas 内坐标
      this.drawBarb(this.ctx, screen.x - ox, screen.y - oy, d.speed, d.direction)
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
    this.draw()
  }

  destroy(): void {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId)
      this.rafId = null
    }
    this.map.off('move', this.moveHandler)
    this.map.off('moveend', this.moveHandler)
    this.map.off('resize', this.resizeHandler)
    if (this.canvas.parentNode) {
      this.canvas.parentNode.removeChild(this.canvas)
    }
  }
}
