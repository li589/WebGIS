/**
 * 风速等值线（Isotach）渲染层 — Canvas 叠加。
 *
 * 用 Marching Squares 算法从风场网格提取等值线，
 * 在 5/10/15 m/s 处绘制等风速线，颜色渐变表示风速级别。
 */
import type { Map as MaplibreMap } from 'maplibre-gl'

interface GridData {
  rows: number
  cols: number
  south: number
  north: number
  west: number
  east: number
  speeds: number[][]  // [row][col]
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

export class WindContourLayer {
  private map: MaplibreMap
  private canvas: HTMLCanvasElement
  private ctx: CanvasRenderingContext2D
  private gridData: GridData | null = null
  private levels: { value: number; color: string; width: number; label: string }[]
  private moveHandler: () => void
  private resizeHandler: () => void
  private isVisible = true
  private rafId: number | null = null
  private canvasOffsetX = 0
  private canvasOffsetY = 0

  constructor(map: MaplibreMap, geojson: WindGeoJSON, options?: { levels?: number[] }) {
    this.map = map
    const levelValues = options?.levels ?? [5, 10, 15]
    const colors = ['rgba(100, 180, 255, 0.5)', 'rgba(150, 220, 255, 0.6)', 'rgba(200, 240, 255, 0.7)']
    this.levels = levelValues.map((v, i) => ({
      value: v,
      color: colors[i % colors.length],
      width: i === 0 ? 1.0 : 1.3,
      label: `${v} m/s`,
    }))

    const container = map.getContainer()
    this.canvas = document.createElement('canvas')
    this.canvas.style.position = 'absolute'
    this.canvas.style.top = '0'
    this.canvas.style.left = '0'
    this.canvas.style.pointerEvents = 'none'
    this.canvas.style.zIndex = '4'
    this.canvas.className = 'wind-contour-canvas'
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

  /** 将 canvas 尺寸/位置适配到网格数据投影范围与视口的交集 */
  private updateCanvasBounds(): void {
    const container = this.map.getContainer()
    const vw = container.clientWidth
    const vh = container.clientHeight

    if (!this.gridData) {
      this.canvas.width = vw
      this.canvas.height = vh
      this.canvas.style.left = '0px'
      this.canvas.style.top = '0px'
      this.canvasOffsetX = 0
      this.canvasOffsetY = 0
      this.ctx.setTransform(1, 0, 0, 1, 0, 0)
      return
    }

    const { south, north, west, east } = this.gridData
    const tl = this.map.project([west, north])
    const tr = this.map.project([east, north])
    const bl = this.map.project([west, south])
    const br = this.map.project([east, south])
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
    if (features.length === 0) return

    let maxRow = 0, maxCol = 0
    let minLat = Infinity, maxLat = -Infinity, minLon = Infinity, maxLon = -Infinity
    const pointMap = new Map<string, { speed: number; lat: number; lon: number }>()

    // 从首个 feature 推断高度后缀，支持 10m / 80m / 120m / 180m 等多高度风场
    const firstProps = features[0]?.properties || {}
    const heightSuffix: string = firstProps.height ?? '10m'
    const speedKey = `wind_speed_${heightSuffix}`

    for (const f of features) {
      if (f.geometry?.type !== 'Point') continue
      const coords = f.geometry.coordinates
      const props = f.properties || {}
      const row = props.row ?? 0
      const col = props.col ?? 0
      maxRow = Math.max(maxRow, row)
      maxCol = Math.max(maxCol, col)
      minLat = Math.min(minLat, coords[1])
      maxLat = Math.max(maxLat, coords[1])
      minLon = Math.min(minLon, coords[0])
      maxLon = Math.max(maxLon, coords[0])
      const speed = props[speedKey] ?? props.wind_speed_10m ?? 0
      pointMap.set(`${row}:${col}`, { speed, lat: coords[1], lon: coords[0] })
    }

    const rows = maxRow + 1
    const cols = maxCol + 1
    const speeds: number[][] = []
    for (let r = 0; r < rows; r++) {
      speeds[r] = []
      for (let c = 0; c < cols; c++) {
        const p = pointMap.get(`${r}:${c}`)
        speeds[r][c] = p?.speed ?? 0
      }
    }

    this.gridData = { rows, cols, south: minLat, north: maxLat, west: minLon, east: maxLon, speeds }
  }

  /** 网格坐标 → 经纬度 */
  private gridToLngLat(row: number, col: number): [number, number] {
    if (!this.gridData) return [0, 0]
    const { rows, cols, south, north, west, east } = this.gridData
    const lon = west + (col / (cols - 1)) * (east - west)
    const lat = north - (row / (rows - 1)) * (north - south)
    return [lon, lat]
  }

  /** Marching Squares 提取单个级别的等值线段 */
  private marchingSquares(level: number): [number, number][][] {
    if (!this.gridData) return []
    const { rows, cols, speeds } = this.gridData
    const segments: [number, number][][] = []

    for (let r = 0; r < rows - 1; r++) {
      for (let c = 0; c < cols - 1; c++) {
        const tl = speeds[r][c]     // top-left
        const tr = speeds[r][c + 1]  // top-right
        const br = speeds[r + 1][c + 1] // bottom-right
        const bl = speeds[r + 1][c]  // bottom-left

        // 4 个角点是否大于等值线值
        const caseCode = (tl >= level ? 1 : 0) | (tr >= level ? 2 : 0) | (br >= level ? 4 : 0) | (bl >= level ? 8 : 0)

        // 线性插值交点位置（0-1）
        const interp = (a: number, b: number) => {
          const diff = b - a
          if (Math.abs(diff) < 0.001) return 0.5
          return (level - a) / diff
        }

        // 4 条边的交点
        const top = (): [number, number] => [r, c + interp(tl, tr)]
        const right = (): [number, number] => [r + interp(tr, br), c + 1]
        const bottom = (): [number, number] => [r + 1, c + interp(bl, br)]
        const left = (): [number, number] => [r + interp(tl, bl), c]

        // 网格坐标 → 经纬度
        const toLngLat = (gridPos: [number, number]): [number, number] => {
          return this.gridToLngLat(gridPos[0], gridPos[1])
        }

        switch (caseCode) {
          case 0: case 15: break
          case 1: case 14: segments.push([toLngLat(left()), toLngLat(top())]); break
          case 2: case 13: segments.push([toLngLat(top()), toLngLat(right())]); break
          case 3: case 12: segments.push([toLngLat(left()), toLngLat(right())]); break
          case 4: case 11: segments.push([toLngLat(right()), toLngLat(bottom())]); break
          case 5: segments.push([toLngLat(left()), toLngLat(top())]); segments.push([toLngLat(right()), toLngLat(bottom())]); break
          case 6: case 9: segments.push([toLngLat(top()), toLngLat(bottom())]); break
          case 7: case 8: segments.push([toLngLat(left()), toLngLat(bottom())]); break
          case 10: segments.push([toLngLat(left()), toLngLat(bottom())]); segments.push([toLngLat(top()), toLngLat(right())]); break
        }
      }
    }
    return segments
  }

  private draw(): void {
    if (!this.isVisible || !this.gridData) return
    const cw = this.canvas.width
    const ch = this.canvas.height
    const ox = this.canvasOffsetX
    const oy = this.canvasOffsetY
    this.ctx.clearRect(0, 0, cw, ch)

    const zoom = this.map.getZoom()
    if (zoom < 3) return

    // LOD 策略：根据 zoom 动态选择等值线级别
    // zoom 小（看大范围）→ 只显示高级别（10/15），避免线条过密
    // zoom 大（看小范围）→ 增加细密级别（2.5/5/7.5/10/12.5/15/17.5/20），展示更多细节
    const activeLevels = this.resolveActiveLevels(zoom)

    for (const level of activeLevels) {
      const segments = this.marchingSquares(level.value)
      this.ctx.strokeStyle = level.color
      this.ctx.lineWidth = level.width
      this.ctx.lineCap = 'round'
      this.ctx.lineJoin = 'round'

      for (const seg of segments) {
        const p1 = this.map.project(seg[0])
        const p2 = this.map.project(seg[1])
        // 视口剔除（基于 canvas 范围）
        if ((p1.x < ox - 30 && p2.x < ox - 30) ||
            (p1.x > ox + cw + 30 && p2.x > ox + cw + 30) ||
            (p1.y < oy - 30 && p2.y < oy - 30) ||
            (p1.y > oy + ch + 30 && p2.y > oy + ch + 30)) continue
        this.ctx.beginPath()
        this.ctx.moveTo(p1.x - ox, p1.y - oy)
        this.ctx.lineTo(p2.x - ox, p2.y - oy)
        this.ctx.stroke()
      }

      // 在等值线上标注数值（采样若干段）
      if (segments.length > 0 && zoom > 5) {
        this.ctx.fillStyle = level.color.replace(/[\d.]+\)$/, '0.9)')
        this.ctx.font = '10px monospace'
        // 标注密度也随 zoom 调整：zoom 大时标注更多
        const targetLabelCount = zoom > 8 ? 12 : 6
        const labelInterval = Math.max(1, Math.floor(segments.length / targetLabelCount))
        for (let i = 0; i < segments.length; i += labelInterval) {
          const mid: [number, number] = [
            (segments[i][0][0] + segments[i][1][0]) / 2,
            (segments[i][0][1] + segments[i][1][1]) / 2,
          ]
          const screen = this.map.project(mid)
          // 标注位置也转换为 canvas 内坐标
          if (screen.x < ox - 30 || screen.x > ox + cw + 30 ||
              screen.y < oy - 30 || screen.y > oy + ch + 30) continue
          this.ctx.fillText(level.label, screen.x - ox + 3, screen.y - oy - 3)
        }
      }
    }
  }

  /** 根据 zoom 解析当前应绘制的等值线级别（LOD 策略） */
  private resolveActiveLevels(zoom: number): { value: number; color: string; width: number; label: string }[] {
    // 颜色定义：低级别淡色，高级别亮色
    const colorFor = (v: number) => {
      if (v <= 2.5) return 'rgba(100, 180, 255, 0.35)'
      if (v <= 5) return 'rgba(100, 180, 255, 0.5)'
      if (v <= 10) return 'rgba(150, 220, 255, 0.6)'
      if (v <= 15) return 'rgba(200, 240, 255, 0.7)'
      return 'rgba(240, 250, 255, 0.8)'
    }
    const widthFor = (v: number) => (v <= 5 ? 1.0 : 1.3)
    const make = (v: number) => ({ value: v, color: colorFor(v), width: widthFor(v), label: `${v} m/s` })

    if (zoom < 4) {
      // 远视图：只显示高级别，避免线条过密
      return [10, 15].map(make)
    }
    if (zoom < 7) {
      // 中视图：标准 5/10/15
      return [5, 10, 15].map(make)
    }
    // 近视图：增加 2.5 步长的细密级别
    return [2.5, 5, 7.5, 10, 12.5, 15, 17.5, 20].map(make)
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
