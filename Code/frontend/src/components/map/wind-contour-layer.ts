/**
 * 风速等值线（Isotach）渲染层 — Canvas 2D 叠加。
 *
 * 用 Marching Squares 算法从风场网格提取等值线，
 * 在 5/10/15 m/s 处绘制等风速线，颜色渐变表示风速级别。
 *
 * DPI 处理与布局计算与 WindBarbLayer/WindParticleCanvas 一致：
 *   - pixelRatio = min(devicePixelRatio, 2)
 *   - canvas 尺寸 = layout 尺寸 × dpr
 *   - draw 时所有坐标乘以 dpr
 *   - 布局计算复用 computeCanvasLayout
 */
import type { Map as MaplibreMap } from 'maplibre-gl'
import { DEFAULT_HEIGHT_SUFFIX, MAP_EVENT_MOVE, MAP_EVENT_MOVEEND, MAP_EVENT_RESIZE } from './types'
import type { WindGeoJSON } from './types'
import { computeCanvasLayout, type CanvasLayout } from './canvas-utils'

interface GridData {
  rows: number
  cols: number
  south: number
  north: number
  west: number
  east: number
  speeds: number[][]  // [row][col]
}

// ── 渲染参数常量 ─────────────────────────────────────────

/** 等值线 LOD 缩放阈值 */
const CONTOUR_ZOOM_HIDE = 3        // zoom < 3 不绘制
const CONTOUR_ZOOM_FILTER_HIGH = 4 // zoom < 4 仅显示强风级别
const CONTOUR_ZOOM_ALL_LEVELS = 7  // zoom < 7 显示默认级别
const CONTOUR_ZOOM_LABEL_THRESHOLD = 5   // zoom > 5 且段数够多才绘制标注
const CONTOUR_ZOOM_LABEL_COUNT_BREAK = 8 // zoom > 8 时标注数量翻倍

/** 等值线标注参数 */
const MIN_SEGMENTS_FOR_LABELS = 10
const LABEL_COUNT_CLOSE_VIEW = 12
const LABEL_COUNT_DEFAULT = 6

/** 等值线标注字体大小（像素） */
const CONTOUR_LABEL_FONT_SIZE = 10

/** Marching Squares 插值 epsilon（避免除零） */
const INTERPOLATION_EPSILON = 0.001

/** 等值线段视口剔除边距（像素） */
const CONTOUR_SEGMENT_CULLING_MARGIN_PX = 30

/** DPI 上限（防止超高分屏幕创建过大 canvas） */
const MAX_PIXEL_RATIO = 2

export class WindContourLayer {
  private map: MaplibreMap
  private canvas: HTMLCanvasElement
  private ctx: CanvasRenderingContext2D
  private pixelRatio: number
  private layout: CanvasLayout = { width: 0, height: 0, offsetX: 0, offsetY: 0, lonWrapOffset: 0 }
  private gridData: GridData | null = null
  private moveHandler: () => void
  private resizeHandler: () => void
  private isVisible = true
  private rafId: number | null = null
  /** 经度 wrap 偏移量（来自 computeCanvasLayout），用于将等值线端点投影到可见世界副本 */
  private lonWrapOffset = 0

  constructor(map: MaplibreMap, geojson: WindGeoJSON, _options?: { levels?: number[] }) {
    this.map = map
    this.pixelRatio = Math.min(window.devicePixelRatio, MAX_PIXEL_RATIO)

    const container = map.getContainer()
    this.canvas = document.createElement('canvas')
    this.canvas.style.position = 'absolute'
    this.canvas.style.top = '0'
    this.canvas.style.left = '0'
    this.canvas.style.pointerEvents = 'none'
    this.canvas.style.zIndex = '4'
    // 默认弱化等值线，避免抢粒子主体（Windy 风格以粒子+色底为主）
    this.canvas.style.opacity = '0.32'
    this.canvas.className = 'wind-contour-canvas'
    container.appendChild(this.canvas)

    this.ctx = this.canvas.getContext('2d', { alpha: true })!
    this.loadData(geojson)
    this.updateLayout()
    console.log(`[${performance.now().toFixed(1)}ms] [WindContourLayer] constructor`, 'grid', this.gridData ? `${this.gridData.rows}x${this.gridData.cols}` : 'null')

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

  /** 调整等值线整体透明度（0~1） */
  setOpacity(opacity: number): void {
    const clamped = Math.max(0, Math.min(1, opacity))
    this.canvas.style.opacity = String(clamped)
  }

  /** 计算 canvas 尺寸/位置，使用共享的 computeCanvasLayout */
  private updateLayout(): void {
    if (!this.gridData) {
      // 无数据时退化为全屏 canvas
      const container = this.map.getContainer()
      const vw = container.clientWidth
      const vh = container.clientHeight
      const dpr = this.pixelRatio
      this.canvas.width = Math.round(vw * dpr)
      this.canvas.height = Math.round(vh * dpr)
      this.canvas.style.width = `${vw}px`
      this.canvas.style.height = `${vh}px`
      this.canvas.style.left = '0px'
      this.canvas.style.top = '0px'
      this.layout = { width: vw, height: vh, offsetX: 0, offsetY: 0, lonWrapOffset: 0 }
      return
    }

    const { south, north, west, east } = this.gridData
    this.layout = computeCanvasLayout(this.map, west, east, south, north)
    this.lonWrapOffset = this.layout.lonWrapOffset
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
    if (features.length === 0) return

    // 从首个 feature 推断高度后缀，支持 10m / 80m / 120m / 180m 等多高度风场
    const firstProps = features[0]?.properties || {}
    const heightSuffix: string = firstProps.height ?? DEFAULT_HEIGHT_SUFFIX
    const speedKey = `wind_speed_${heightSuffix}`

    // 收集所有点的数据和量化后的唯一经纬度
    // 不依赖后端 row/col —— 多瓦片合并时各瓦片的 row/col 是相对内部的，会互相冲突覆盖
    const QUANT = 1000 // 0.001° 精度，合并浮点误差
    interface RawPoint { lat: number; lon: number; speed: number }
    const rawPoints: RawPoint[] = []
    const latQuantSet = new Set<number>()
    const lonQuantSet = new Set<number>()

    for (const f of features) {
      if (f.geometry?.type !== 'Point') continue
      const coords = f.geometry.coordinates
      const props = f.properties || {}
      const speed = Number(props[speedKey] ?? props.wind_speed_10m ?? 0)
      rawPoints.push({ lat: coords[1], lon: coords[0], speed })
      latQuantSet.add(Math.round(coords[1] * QUANT))
      lonQuantSet.add(Math.round(coords[0] * QUANT))
    }

    if (rawPoints.length === 0) return

    // 排序：lat 降序（北→南），lon 升序（西→东）
    const sortedLats = Array.from(latQuantSet).sort((a, b) => b - a)
    const sortedLons = Array.from(lonQuantSet).sort((a, b) => a - b)
    const rows = sortedLats.length
    const cols = sortedLons.length
    if (rows < 2 || cols < 2) return

    const latIndex = new Map<number, number>()
    sortedLats.forEach((q, i) => latIndex.set(q, i))
    const lonIndex = new Map<number, number>()
    sortedLons.forEach((q, i) => lonIndex.set(q, i))

    // 构建二维 speeds 数组，缺失点用最近邻填充（多瓦片合并时边缘区域可能没有数据）
    // 注意：不能用 0 填充——Marching Squares 会围绕零速孔洞绘制等值线，
    // 在瓦片边界产生"拼接状/十字/菱形"伪影，与用户报告的"等压线拼接问题"一致。
    const speeds: number[][] = []
    const hasData: boolean[][] = []
    for (let r = 0; r < rows; r++) {
      speeds[r] = new Array(cols).fill(0)
      hasData[r] = new Array(cols).fill(false)
    }
    for (const p of rawPoints) {
      const r = latIndex.get(Math.round(p.lat * QUANT))!
      const c = lonIndex.get(Math.round(p.lon * QUANT))!
      speeds[r][c] = p.speed
      hasData[r][c] = true
    }

    // 多源 BFS 最近邻填充：所有数据单元同时入队，BFS 同时扩展，
    // 最先到达孔洞的源即最近邻，用其速度值填充该孔洞。
    const MISSING = rows * cols - rawPoints.length
    if (MISSING > 0) {
      const queue: Array<[number, number, number, number]> = [] // [r, c, srcR, srcC]
      const visited = hasData // 复用：数据单元已"访问"
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          if (visited[r][c]) queue.push([r, c, r, c])
        }
      }
      let head = 0
      const DIRS: ReadonlyArray<readonly [number, number]> = [[-1, 0], [1, 0], [0, -1], [0, 1]]
      while (head < queue.length) {
        const [r, c, srcR, srcC] = queue[head++]
        for (const [dr, dc] of DIRS) {
          const nr = r + dr
          const nc = c + dc
          if (nr < 0 || nr >= rows || nc < 0 || nc >= cols) continue
          if (visited[nr][nc]) continue
          visited[nr][nc] = true
          speeds[nr][nc] = speeds[srcR][srcC]
          queue.push([nr, nc, srcR, srcC])
        }
      }
    }

    this.gridData = {
      rows, cols,
      south: sortedLats[rows - 1] / QUANT,
      north: sortedLats[0] / QUANT,
      west: sortedLons[0] / QUANT,
      east: sortedLons[cols - 1] / QUANT,
      speeds,
    }
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
          if (Math.abs(diff) < INTERPOLATION_EPSILON) return 0.5
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
    const dpr = this.pixelRatio
    const ctx = this.ctx
    // clearRect 使用 canvas 实际像素尺寸（已乘 dpr）
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)

    const zoom = this.map.getZoom()
    if (zoom < CONTOUR_ZOOM_HIDE) return

    // 视口剔除基于 CSS 像素的 layout 范围
    const { width: cw, height: ch, offsetX: ox, offsetY: oy } = this.layout

    // LOD 策略：根据 zoom 动态选择等值线级别
    // zoom 小（看大范围）→ 只显示高级别（10/15），避免线条过密
    // zoom 大（看小范围）→ 增加细密级别（2.5/5/7.5/10/12.5/15/17.5/20），展示更多细节
    const activeLevels = this.resolveActiveLevels(zoom)

    for (const level of activeLevels) {
      const segments = this.marchingSquares(level.value)
      ctx.strokeStyle = level.color
      ctx.lineWidth = level.width * dpr
      ctx.lineCap = 'round'
      ctx.lineJoin = 'round'

      for (const seg of segments) {
        const p1 = this.map.project([seg[0][0] + this.lonWrapOffset, seg[0][1]])
        const p2 = this.map.project([seg[1][0] + this.lonWrapOffset, seg[1][1]])
        // 视口剔除（基于 canvas CSS 像素范围）
        if ((p1.x < ox - CONTOUR_SEGMENT_CULLING_MARGIN_PX && p2.x < ox - CONTOUR_SEGMENT_CULLING_MARGIN_PX) ||
            (p1.x > ox + cw + CONTOUR_SEGMENT_CULLING_MARGIN_PX && p2.x > ox + cw + CONTOUR_SEGMENT_CULLING_MARGIN_PX) ||
            (p1.y < oy - CONTOUR_SEGMENT_CULLING_MARGIN_PX && p2.y < oy - CONTOUR_SEGMENT_CULLING_MARGIN_PX) ||
            (p1.y > oy + ch + CONTOUR_SEGMENT_CULLING_MARGIN_PX && p2.y > oy + ch + CONTOUR_SEGMENT_CULLING_MARGIN_PX)) continue
        ctx.beginPath()
        ctx.moveTo((p1.x - ox) * dpr, (p1.y - oy) * dpr)
        ctx.lineTo((p2.x - ox) * dpr, (p2.y - oy) * dpr)
        ctx.stroke()
      }

      // 在等值线上标注数值（采样若干段）
      if (segments.length > MIN_SEGMENTS_FOR_LABELS && zoom > CONTOUR_ZOOM_LABEL_THRESHOLD) {
        ctx.fillStyle = level.color.replace(/[\d.]+\)$/, '0.9)')
        ctx.font = `${CONTOUR_LABEL_FONT_SIZE * dpr}px monospace`
        // 标注密度也随 zoom 调整：zoom 大时标注更多
        const targetLabelCount = zoom > CONTOUR_ZOOM_LABEL_COUNT_BREAK ? LABEL_COUNT_CLOSE_VIEW : LABEL_COUNT_DEFAULT
        const labelInterval = Math.max(1, Math.floor(segments.length / targetLabelCount))
        for (let i = 0; i < segments.length; i += labelInterval) {
          const mid: [number, number] = [
            (segments[i][0][0] + segments[i][1][0]) / 2,
            (segments[i][0][1] + segments[i][1][1]) / 2,
          ]
          const screen = this.map.project([mid[0] + this.lonWrapOffset, mid[1]])
          // 标注位置也转换为 canvas 内坐标
          if (screen.x < ox - CONTOUR_SEGMENT_CULLING_MARGIN_PX || screen.x > ox + cw + CONTOUR_SEGMENT_CULLING_MARGIN_PX ||
              screen.y < oy - CONTOUR_SEGMENT_CULLING_MARGIN_PX || screen.y > oy + ch + CONTOUR_SEGMENT_CULLING_MARGIN_PX) continue
          ctx.fillText(level.label, (screen.x - ox + 3) * dpr, (screen.y - oy - 3) * dpr)
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

    if (zoom < CONTOUR_ZOOM_FILTER_HIGH) {
      // 远视图：只显示高级别，避免线条过密
      return [10, 15].map(make)
    }
    if (zoom < CONTOUR_ZOOM_ALL_LEVELS) {
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
    this.updateLayout()
    console.log(`[${performance.now().toFixed(1)}ms] [WindContourLayer] updateGeoJSON`, 'grid', this.gridData ? `${this.gridData.rows}x${this.gridData.cols}` : 'null')
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
    if (this.canvas.parentNode) {
      this.canvas.parentNode.removeChild(this.canvas)
    }
  }
}
