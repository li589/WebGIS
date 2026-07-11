/**
 * 风场粒子流动画 — Canvas 2D 渲染。
 *
 * 使用粒子追踪方式可视化风场向量场：
 *   1. 大量粒子在网格中随机分布，跟随风向移动
 *   2. Canvas 2D 天然支持轨迹累积（fillRect 淡化旧轨迹）
 *   3. 粒子颜色按风速分级，拖尾长度反映风速大小
 *   4. 帧率节流到 30fps，给 maplibre 留出渲染空间
 */
import type { Map as MaplibreMap } from 'maplibre-gl'
import type { WindGeoJSON } from './types'
import { DEFAULT_HEIGHT_SUFFIX, MAP_EVENT_MOVE, MAP_EVENT_MOVESTART, MAP_EVENT_MOVEEND, MAP_EVENT_RESIZE, MIN_VISIBLE_ZOOM } from './types'
import { computeCanvasLayout, type CanvasLayout } from './canvas-utils'

// ── 渲染参数常量 ─────────────────────────────────────────

/** 弧度转换常数（Math.PI / 180） */
const DEG_TO_RAD = Math.PI / 180

/** 气象风向偏移量：气象风向是风来向，需加 180° 转为数学风向（风去向） */
const WIND_DIRECTION_OFFSET = 180

/** 节流帧间隔，约 30fps（ms） */
const TARGET_FRAME_INTERVAL_MS = 33

/** 60fps 每帧毫秒数（用于 dt 归一化） */
const MS_PER_60FPS_FRAME = 1000 / 60

/** dt 归一化上界（防止标签页失焦后恢复时粒子跳帧） */
const MAX_DT_FRAMES = 4

/** 视口剔除边距（像素），使边缘粒子不突然消失 */
const VIEWPORT_CULLING_MARGIN_PX = 10

/** 拖尾长度限制（像素），防止跳帧时线段过长 */
const MAX_TRAIL_LENGTH_PX = 80

/** 粒子数变化触发重初始化的阈值（25%） */
const PARTICLE_COUNT_CHANGE_THRESHOLD = 0.25

/** 每个粒子的轨迹历史长度（点数），越大曲线越长越平滑 */
const TRAIL_LENGTH = 20

/** 粒子默认配置（稀疏柔和风格：少量粒子 + 慢速流动 + 细线） */
const DEFAULT_PARTICLE_OPTIONS = {
  particleCount: 1500,
  maxAge: 60,
  speedScale: 0.008,
  fadeAlpha: 0.028,
  lineWidth: 1.0,
} as const

/** 粒子数量上限（防止过大网格导致性能问题） */
const MAX_PARTICLE_COUNT = 4000

/** 粒子数量下限 */
const MIN_PARTICLE_COUNT = 500

/** DPI 上限（防止超高分屏幕创建过大 canvas） */
const MAX_PIXEL_RATIO = 2

/** zoomFactor 上限，防止低缩放级别下粒子速度过快导致视觉混乱（线条抽搐） */
const MAX_ZOOM_FACTOR = 4

/**
 * 根据网格面积动态计算粒子数量。
 * 面积越大粒子越多，但受上限约束。
 * 密度约为每平方度 7 个粒子，保持稀疏柔和的视觉效果。
 */
function computeParticleCountForGrid(grid: WindGrid): number {
  const area = Math.abs(grid.north - grid.south) * Math.abs(grid.east - grid.west)
  const count = Math.round(area * 7)
  return Math.min(MAX_PARTICLE_COUNT, Math.max(MIN_PARTICLE_COUNT, count))
}

/** 粒子寿命随机上界增量（使寿命有随机分布） */
const MAX_AGE_RANDOM_RANGE = 20

/** 默认颜色梯度（风速从低到高） */
const DEFAULT_PARTICLE_COLORS = ['#10314b', '#1d6fa5', '#4bb9ff', '#84ddff', '#c4f3ff']

/** 默认风速断点（m/s），与颜色梯度对应 */
const DEFAULT_WIND_SPEED_STOPS = [0, 5, 10, 15, 20]

// ── 类型 ─────────────────────────────────────────────────

interface WindGridPoint {
  lat: number
  lon: number
  speed: number
  direction: number
}

interface WindGrid {
  rows: number
  cols: number
  south: number
  north: number
  west: number
  east: number
  points: WindGridPoint[][]
  checksum: number
}

export interface WindParticleOptions {
  particleCount?: number
  maxAge?: number
  speedScale?: number
  fadeAlpha?: number
  lineWidth?: number
  colors?: string[]
  colorStops?: number[]
}

// ── 工具函数 ─────────────────────────────────────────────

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ]
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t
}

function speedToColorIndex(speed: number, stops: number[]): { idx: number; t: number } {
  if (speed <= stops[0]) return { idx: 0, t: 0 }
  if (speed >= stops[stops.length - 1]) return { idx: stops.length - 2, t: 1 }
  for (let i = 0; i < stops.length - 1; i++) {
    if (speed >= stops[i] && speed <= stops[i + 1]) {
      return { idx: i, t: (speed - stops[i]) / (stops[i + 1] - stops[i]) }
    }
  }
  return { idx: stops.length - 2, t: 1 }
}

/** 调试日志辅助：带相对时间戳前缀 */
function debugLog(module: string, ...args: unknown[]) {
  console.log(`[${performance.now().toFixed(1)}ms] [${module}]`, ...args)
}

function windToUV(speed: number, directionDeg: number): [number, number] {
  // 气象风向是风来向，加 180° 转为风去向 θ
  // u = speed * sin(θ)（东为正），v = speed * cos(θ)（北为正）
  const rad = (directionDeg + WIND_DIRECTION_OFFSET) * DEG_TO_RAD
  const u = speed * Math.sin(rad)
  const v = speed * Math.cos(rad)
  return [u, v]
}

// ── GeoJSON → 风场网格 ──────────────────────────────────

/** 经纬度量化精度（0.001°，约 100m），用于合并浮点误差导致的微小差异 */
const GRID_COORD_QUANTIZE_FACTOR = 1000

function buildWindGridFromGeoJSON(geojson: WindGeoJSON): WindGrid | null {
  const features = geojson?.features || []
  if (features.length === 0) return null

  const firstProps = features[0]?.properties || {}
  const heightSuffix: string = firstProps.height ?? DEFAULT_HEIGHT_SUFFIX
  const speedKey = `wind_speed_${heightSuffix}`
  const directionKey = `wind_direction_${heightSuffix}`

  // 收集所有点的数据和量化后的唯一经纬度
  // 不依赖后端的 row/col 属性 —— 多瓦片合并时各瓦片的 row/col 是相对内部的，会互相冲突覆盖
  interface RawPoint { lat: number; lon: number; speed: number; direction: number }
  const rawPoints: RawPoint[] = []
  const latQuantSet = new Set<number>()
  const lonQuantSet = new Set<number>()

  for (const f of features) {
    const coords = f.geometry?.coordinates
    if (!coords || f.geometry?.type !== 'Point') continue
    const lon = coords[0]
    const lat = coords[1]
    const props = f.properties || {}
    const speed = (props[speedKey] ?? props.wind_speed_10m ?? 0) as number
    const direction = (props[directionKey] ?? props.wind_direction_10m ?? 0) as number
    rawPoints.push({ lat, lon, speed, direction })
    latQuantSet.add(Math.round(lat * GRID_COORD_QUANTIZE_FACTOR))
    lonQuantSet.add(Math.round(lon * GRID_COORD_QUANTIZE_FACTOR))
  }

  if (rawPoints.length === 0) return null

  // 排序：lat 降序（北→南，row 0 = 最北），lon 升序（西→东，col 0 = 最西）
  const sortedLats = Array.from(latQuantSet).sort((a, b) => b - a)
  const sortedLons = Array.from(lonQuantSet).sort((a, b) => a - b)
  const rows = sortedLats.length
  const cols = sortedLons.length
  if (rows < 2 || cols < 2) return null

  // 量化值 → 网格索引映射
  const latIndex = new Map<number, number>()
  sortedLats.forEach((q, i) => latIndex.set(q, i))
  const lonIndex = new Map<number, number>()
  sortedLons.forEach((q, i) => lonIndex.set(q, i))

  // 构建二维网格，先初始化所有点的坐标（值占位为 NaN 标记"无数据"）
  const NO_DATA = Number.NaN
  const points: WindGridPoint[][] = []
  const hasData: boolean[][] = []
  for (let r = 0; r < rows; r++) {
    points[r] = []
    hasData[r] = []
    for (let c = 0; c < cols; c++) {
      points[r][c] = {
        lat: sortedLats[r] / GRID_COORD_QUANTIZE_FACTOR,
        lon: sortedLons[c] / GRID_COORD_QUANTIZE_FACTOR,
        speed: NO_DATA,
        direction: NO_DATA,
      }
      hasData[r][c] = false
    }
  }
  // 填入实际数据点
  for (const p of rawPoints) {
    const r = latIndex.get(Math.round(p.lat * GRID_COORD_QUANTIZE_FACTOR))!
    const c = lonIndex.get(Math.round(p.lon * GRID_COORD_QUANTIZE_FACTOR))!
    points[r][c] = { lat: p.lat, lon: p.lon, speed: p.speed, direction: p.direction }
    hasData[r][c] = true
  }

  // ── 缺失单元最近邻填充（多源 BFS） ──────────────────────────────
  // 多瓦片合并时，不同瓦片的纬度/经度覆盖范围不完全一致，会在并集网格中产生"孔洞"。
  // 若用 0 填充，会在瓦片边界产生 speed=0 的"静风区"，视觉上表现为：
  //   - 块状边界（每个瓦片轮廓清晰可见）
  //   - 四瓦片交汇处的十字/菱形零速伪影
  //   - 等值线绕零速区产生拼接状线条
  //   - 粒子进入零速区后方向丢失、流线断裂
  // 解决方案：用多源 BFS 将每个孔洞单元填充为最近的数据单元的值（曼哈顿距离）。
  // 所有数据单元同时作为源点入队，BFS 同时向外扩展，最先到达孔洞的源即最近邻。
  const MISSING_CELL_COUNT = rows * cols - rawPoints.length
  if (MISSING_CELL_COUNT > 0) {
    // BFS 队列：[row, col, srcRow, srcCol]
    const queue: Array<[number, number, number, number]> = []
    const visited: boolean[][] = hasData // 复用：数据单元已"访问"
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        if (visited[r][c]) {
          queue.push([r, c, r, c])
        }
      }
    }
    let head = 0
    // 四邻域方向：上、下、左、右
    const DIRS: ReadonlyArray<readonly [number, number]> = [[-1, 0], [1, 0], [0, -1], [0, 1]]
    while (head < queue.length) {
      const [r, c, srcR, srcC] = queue[head++]
      for (const [dr, dc] of DIRS) {
        const nr = r + dr
        const nc = c + dc
        if (nr < 0 || nr >= rows || nc < 0 || nc >= cols) continue
        if (visited[nr][nc]) continue
        visited[nr][nc] = true
        // 用最近数据源的速度/方向填充（保留本单元的 lat/lon）
        const src = points[srcR][srcC]
        points[nr][nc].speed = src.speed
        points[nr][nc].direction = src.direction
        queue.push([nr, nc, srcR, srcC])
      }
    }
  }

  const south = sortedLats[rows - 1] / GRID_COORD_QUANTIZE_FACTOR
  const north = sortedLats[0] / GRID_COORD_QUANTIZE_FACTOR
  const west = sortedLons[0] / GRID_COORD_QUANTIZE_FACTOR
  const east = sortedLons[cols - 1] / GRID_COORD_QUANTIZE_FACTOR

  let checksum = 0
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const p = points[r][c]
      checksum += p.speed + p.direction
    }
  }

  debugLog('WindParticleCanvas', 'buildWindGrid', 'rows', rows, 'cols', cols, 'rawPoints', rawPoints.length, 'missing', MISSING_CELL_COUNT, 'bounds', { west, south, east, north }, 'checksum', checksum)
  return { rows, cols, south, north, west, east, points, checksum }
}

function interpolateWind(grid: WindGrid, lat: number, lon: number): WindGridPoint {
  const { rows, cols, south, north, west, east, points } = grid
  const clampedLat = Math.max(south, Math.min(north, lat))
  const clampedLon = Math.max(west, Math.min(east, lon))
  // buildWindGridFromGeoJSON 按 lat 降序排序（row 0 = 最北，row rows-1 = 最南）
  // 所以 fy 应该用 (north - lat) / (north - south)
  const fy = ((north - clampedLat) / (north - south)) * (rows - 1)
  const fx = ((clampedLon - west) / (east - west)) * (cols - 1)
  const r0 = Math.floor(fy)
  const c0 = Math.floor(fx)
  const r1 = Math.min(r0 + 1, rows - 1)
  const c1 = Math.min(c0 + 1, cols - 1)
  const tr = fy - r0
  const tc = fx - c0

  const p00 = points[r0][c0]
  const p01 = points[r0][c1]
  const p10 = points[r1][c0]
  const p11 = points[r1][c1]

  const speed = lerp(lerp(p00.speed, p01.speed, tc), lerp(p10.speed, p11.speed, tc), tr)
  const interpDir = (d1: number, d2: number, t: number) => {
    let diff = d2 - d1
    if (diff > 180) diff -= 360
    if (diff < -180) diff += 360
    return (d1 + diff * t + 360) % 360
  }
  const direction = interpDir(
    interpDir(p00.direction, p01.direction, tc),
    interpDir(p10.direction, p11.direction, tc),
    tr,
  )

  return { lat: clampedLat, lon: clampedLon, speed, direction }
}

// ── 粒子数据结构 ─────────────────────────────────────────

interface Particle {
  lat: number
  lon: number
  /** 轨迹历史，canvas 坐标对 [x0,y0, x1,y1, ...]，最新点在末尾 */
  trail: number[]
  age: number
  maxAge: number
}

// ── 主类 ─────────────────────────────────────────────────

export class WindParticleCanvas {
  private map: MaplibreMap
  private canvas: HTMLCanvasElement
  private ctx: CanvasRenderingContext2D
  private pixelRatio: number
  private layout: CanvasLayout = { width: 0, height: 0, offsetX: 0, offsetY: 0, lonWrapOffset: 0 }
  private grid: WindGrid | null = null
  private particles: Particle[] = []
  private rafId: number | null = null
  private options: Required<WindParticleOptions>
  private resizeObserver: ResizeObserver | null = null
  private movestartHandler: (() => void) | null = null
  private moveendHandler: (() => void) | null = null
  private moveHandler: (() => void) | null = null
  private resizeHandler: (() => void) | null = null
  private moveRafId: number | null = null
  private isMapInteracting = false
  private lastDrawTime = 0
  private lastParticleZoom = 0
  /** 经度 wrap 偏移量（来自 computeCanvasLayout），用于将粒子经度投影到可见世界副本 */
  private lonWrapOffset = 0

  /** 预解析的颜色 RGB 数组（避免每帧字符串解析） */
  private colorRgbCache: [number, number, number][] = []
  /** 调试帧计数器（用于降频日志） */
  private debugFrame = 0

  constructor(map: MaplibreMap, geojson: WindGeoJSON, options?: WindParticleOptions) {
    this.map = map
    this.options = {
      particleCount: options?.particleCount ?? DEFAULT_PARTICLE_OPTIONS.particleCount,
      maxAge: options?.maxAge ?? DEFAULT_PARTICLE_OPTIONS.maxAge,
      speedScale: options?.speedScale ?? DEFAULT_PARTICLE_OPTIONS.speedScale,
      fadeAlpha: options?.fadeAlpha ?? DEFAULT_PARTICLE_OPTIONS.fadeAlpha,
      lineWidth: options?.lineWidth ?? DEFAULT_PARTICLE_OPTIONS.lineWidth,
      colors: options?.colors ?? DEFAULT_PARTICLE_COLORS,
      colorStops: options?.colorStops ?? DEFAULT_WIND_SPEED_STOPS,
    }

    this.pixelRatio = Math.min(window.devicePixelRatio, MAX_PIXEL_RATIO)

    // 创建 Canvas 2D 叠加层
    this.canvas = document.createElement('canvas')
    this.canvas.style.position = 'absolute'
    this.canvas.style.top = '0'
    this.canvas.style.left = '0'
    this.canvas.style.pointerEvents = 'none'
    this.canvas.className = 'wind-particle-canvas'
    this.canvas.style.zIndex = '5'
    map.getContainer().appendChild(this.canvas)

    const ctx = this.canvas.getContext('2d', { alpha: true })
    if (!ctx) throw new Error('Canvas 2D context not available')
    this.ctx = ctx

    this.colorRgbCache = this.options.colors.map(hexToRgb)

    this.grid = buildWindGridFromGeoJSON(geojson)
    debugLog('WindParticleCanvas', 'constructor grid', this.grid ? `${this.grid.rows}x${this.grid.cols}` : 'null', 'features', geojson.features?.length, 'zoom', map.getZoom())
    this.updateCanvasBounds()
    if (this.grid) {
      this.options.particleCount = this.resolveParticleCountForZoom(map.getZoom())
      this.lastParticleZoom = map.getZoom()
      this.initParticles()
    }

    this.setupMapEvents()
    this.resizeObserver = new ResizeObserver(() => this.updateCanvasBounds())
    this.resizeObserver.observe(map.getContainer())
  }

  private setupMapEvents(): void {
    this.movestartHandler = () => {
      this.isMapInteracting = true
      debugLog('WindParticleCanvas', 'movestart')
      // 缩放/平移开始时立即清除画布，防止动画期间旧尺寸的轨迹残留（旧 canvas 位置/大小已不匹配新视图）
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
    }
    this.moveHandler = () => {
      // 用独立的 rAF 节流，避免与 animate 循环的 rafId 冲突
      if (this.moveRafId !== null) return
      this.moveRafId = requestAnimationFrame(() => {
        this.moveRafId = null
        if (!this.isMapInteracting || !this.grid) return
        // 平移/缩放期间持续更新 canvas 位置，使粒子跟随地图移动
        this.updateCanvasBounds()
        // 重新投影粒子到新位置（只保留最后一个点，避免轨迹拉伸）
        const { offsetX, offsetY } = this.layout
        const dpr = this.pixelRatio
        for (const p of this.particles) {
          const screen = this.map.project([p.lon + this.lonWrapOffset, p.lat])
          const x = (screen.x - offsetX) * dpr
          const y = (screen.y - offsetY) * dpr
          p.trail = [x, y]
        }
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
      })
    }
    this.moveendHandler = () => {
      this.isMapInteracting = false
      debugLog('WindParticleCanvas', 'moveend')
      this.updateCanvasBounds()
      // 地图交互结束后清除 canvas，避免旧位置的轨迹残留
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
      // 重置所有粒子的轨迹，避免跨帧拖尾跳变
      if (this.grid) {
        const { offsetX, offsetY } = this.layout
        const dpr = this.pixelRatio
        for (const p of this.particles) {
          const screen = this.map.project([p.lon + this.lonWrapOffset, p.lat])
          const x = (screen.x - offsetX) * dpr
          const y = (screen.y - offsetY) * dpr
          p.trail = [x, y]
        }
      }
      const zoom = this.map.getZoom()
      const targetCount = this.resolveParticleCountForZoom(zoom)
      const currentCount = this.particles.length
      const countChanged = this.lastParticleZoom === 0 || Math.abs(targetCount - currentCount) / Math.max(currentCount, 1) > PARTICLE_COUNT_CHANGE_THRESHOLD
      debugLog('WindParticleCanvas', 'moveend', 'zoom', zoom, 'targetCount', targetCount, 'currentCount', currentCount, 'countChanged', countChanged)
      if (countChanged) {
        this.options.particleCount = targetCount
        this.initParticles()
        this.lastParticleZoom = zoom
      }
    }
    this.resizeHandler = () => {
      debugLog('WindParticleCanvas', 'resize')
      this.updateCanvasBounds()
    }

    this.map.on(MAP_EVENT_MOVESTART, this.movestartHandler)
    this.map.on(MAP_EVENT_MOVE, this.moveHandler)
    this.map.on(MAP_EVENT_MOVEEND, this.moveendHandler)
    this.map.on(MAP_EVENT_RESIZE, this.resizeHandler)
  }

  private updateCanvasBounds(): void {
    const oldLayout = this.layout
    if (!this.grid) {
      const container = this.map.getContainer()
      this.layout = {
        width: container.clientWidth,
        height: container.clientHeight,
        offsetX: 0,
        offsetY: 0,
        lonWrapOffset: 0,
      }
      this.lonWrapOffset = 0
      if (oldLayout.width !== this.layout.width || oldLayout.height !== this.layout.height) {
        debugLog('WindParticleCanvas', 'updateCanvasBounds (no grid)', `${this.layout.width}x${this.layout.height}`)
      }
      this.resizeCanvas()
      return
    }
    this.layout = computeCanvasLayout(
      this.map,
      this.grid.west,
      this.grid.east,
      this.grid.south,
      this.grid.north,
    )
    // 同步 lonWrapOffset，供 initParticles/resetParticle/draw 中的 project 调用使用
    this.lonWrapOffset = this.layout.lonWrapOffset
    if (oldLayout.width !== this.layout.width || oldLayout.height !== this.layout.height || oldLayout.offsetX !== this.layout.offsetX || oldLayout.offsetY !== this.layout.offsetY || oldLayout.lonWrapOffset !== this.layout.lonWrapOffset) {
      debugLog('WindParticleCanvas', 'updateCanvasBounds', `${oldLayout.width}x${oldLayout.height}@${oldLayout.offsetX},${oldLayout.offsetY}`, '->', `${this.layout.width}x${this.layout.height}@${this.layout.offsetX},${this.layout.offsetY}`, 'wrap', this.lonWrapOffset)
    }
    this.resizeCanvas()
  }

  private resizeCanvas(): void {
    const { width, height, offsetX, offsetY } = this.layout
    const dpr = this.pixelRatio
    this.canvas.width = Math.round(width * dpr)
    this.canvas.height = Math.round(height * dpr)
    this.canvas.style.width = `${width}px`
    this.canvas.style.height = `${height}px`
    this.canvas.style.left = `${offsetX}px`
    this.canvas.style.top = `${offsetY}px`
    // 清除画布（尺寸变化后内容已失效）
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
  }

  private resolveParticleCountForZoom(zoom: number): number {
    if (!this.grid) return DEFAULT_PARTICLE_OPTIONS.particleCount
    const baseCount = computeParticleCountForGrid(this.grid)
    // 低缩放级别降级粒子数量，避免全球视图下视觉混乱和性能下降
    if (zoom < 2) return Math.min(baseCount, 200)
    if (zoom < 3) return Math.min(baseCount, 500)
    return baseCount
  }

  private createRandomParticle(): Particle {
    const { south, north, west, east } = this.grid!
    const { offsetX, offsetY } = this.layout
    const dpr = this.pixelRatio
    const lat = south + Math.random() * (north - south)
    const lon = west + Math.random() * (east - west)
    const screen = this.map.project([lon + this.lonWrapOffset, lat])
    const x = (screen.x - offsetX) * dpr
    const y = (screen.y - offsetY) * dpr
    return {
      lat,
      lon,
      trail: [x, y],
      age: Math.floor(Math.random() * this.options.maxAge),
      maxAge: this.options.maxAge + Math.floor(Math.random() * MAX_AGE_RANDOM_RANGE),
    }
  }

  private initParticles(): void {
    if (!this.grid) return
    const targetCount = this.resolveParticleCountForZoom(this.map.getZoom())
    this.options.particleCount = targetCount
    this.particles = []
    for (let i = 0; i < targetCount; i++) {
      this.particles.push(this.createRandomParticle())
    }
    debugLog('WindParticleCanvas', 'initParticles', targetCount, 'zoom', this.map.getZoom())
  }

  private resetParticle(p: Particle): void {
    if (!this.grid) return
    const { south, north, west, east } = this.grid
    const { offsetX, offsetY } = this.layout
    const dpr = this.pixelRatio
    p.lat = south + Math.random() * (north - south)
    p.lon = west + Math.random() * (east - west)
    const screen = this.map.project([p.lon + this.lonWrapOffset, p.lat])
    const x = (screen.x - offsetX) * dpr
    const y = (screen.y - offsetY) * dpr
    p.trail = [x, y]
    p.age = 0
  }

  private animate = (now: number): void => {
    this.debugFrame++
    if (!this.grid || this.particles.length === 0) {
      if (this.debugFrame % 60 === 0) {
        debugLog('WindParticleCanvas', 'animate no-op', 'grid', !!this.grid, 'particles', this.particles.length)
      }
      this.rafId = requestAnimationFrame(this.animate)
      return
    }

    if (this.isMapInteracting) {
      this.lastDrawTime = now
      if (this.debugFrame % 60 === 0) {
        debugLog('WindParticleCanvas', 'animate interacting', 'frame', this.debugFrame)
      }
      this.rafId = requestAnimationFrame(this.animate)
      return
    }

    if (this.lastDrawTime > 0 && now - this.lastDrawTime < TARGET_FRAME_INTERVAL_MS) {
      this.rafId = requestAnimationFrame(this.animate)
      return
    }

    const dt = this.lastDrawTime > 0 ? Math.min((now - this.lastDrawTime) / MS_PER_60FPS_FRAME, MAX_DT_FRAMES) : 1
    this.lastDrawTime = now

    if (this.debugFrame % 60 === 0) {
      const totalTrail = this.particles.reduce((sum, p) => sum + p.trail.length, 0)
      const avgTrail = totalTrail / this.particles.length
      const minTrail = Math.min(...this.particles.map(p => p.trail.length))
      const maxTrail = Math.max(...this.particles.map(p => p.trail.length))
      debugLog('WindParticleCanvas', 'animate frame', this.debugFrame, 'particles', this.particles.length, 'avgTrail', avgTrail.toFixed(1), 'minTrail', minTrail, 'maxTrail', maxTrail, 'dt', dt.toFixed(2))
    }

    this.draw(dt)
    this.rafId = requestAnimationFrame(this.animate)
  }

  private draw(dt: number): void {
    const ctx = this.ctx
    const dpr = this.pixelRatio
    const { width, height, offsetX, offsetY } = this.layout
    const { fadeAlpha, speedScale, colorStops, lineWidth } = this.options
    const grid = this.grid!
    const project = this.map.project.bind(this.map)

    // 低缩放级别下隐藏粒子流（风场数据仅覆盖局部区域，全球视图下粒子流无意义且视觉混乱）
    // 与 WindBarbLayer / WindContourLayer 的 MIN_VISIBLE_ZOOM 保持一致
    const zoom = this.map.getZoom()
    if (zoom < MIN_VISIBLE_ZOOM) {
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
      return
    }

    // 根据缩放级别动态调整速度比例：低 zoom 时粒子经纬度移动量需更大
    // 使用更温和的指数（5-zoom 而非 6-zoom），配合 MAX_ZOOM_FACTOR=4 防止低 zoom 时速度过快导致线条抽搐
    const zoomFactor = Math.min(Math.pow(2, 5 - zoom), MAX_ZOOM_FACTOR)
    const scaledSpeed = speedScale * zoomFactor * dt

    // === 1. 拖尾衰减：destination-out 模式淡化旧轨迹 ===
    ctx.globalCompositeOperation = 'destination-out'
    ctx.globalAlpha = Math.min(fadeAlpha * dt, 0.15)
    ctx.fillStyle = '#000'
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height)

    // === 2. 更新粒子位置 & 收集轨迹到颜色分组 ===
    ctx.globalCompositeOperation = 'source-over'
    ctx.lineWidth = lineWidth * dpr
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'

    const w = width * dpr
    const h = height * dpr
    const maxTrailPoints = TRAIL_LENGTH * 2

    // 每个颜色分组收集粒子轨迹的多段子路径
    // subpaths: [len0, x0,y0,x1,y1..., len1, x0,y0,...]
    const colorSubpaths: number[][] = []
    for (let i = 0; i < this.colorRgbCache.length - 1; i++) {
      colorSubpaths.push([])
    }

    for (const p of this.particles) {
      const wind = interpolateWind(grid, p.lat, p.lon)
      const [u, v] = windToUV(wind.speed, wind.direction)

      p.lon += u * scaledSpeed
      p.lat += v * scaledSpeed
      p.age += dt

      if (
        p.age > p.maxAge ||
        p.lat < grid.south || p.lat > grid.north ||
        p.lon < grid.west || p.lon > grid.east
      ) {
        this.resetParticle(p)
        continue
      }

      const screen = project([p.lon + this.lonWrapOffset, p.lat])
      const cx = (screen.x - offsetX) * dpr
      const cy = (screen.y - offsetY) * dpr

      // 视口剔除
      if (cx < -VIEWPORT_CULLING_MARGIN_PX || cx > w + VIEWPORT_CULLING_MARGIN_PX ||
          cy < -VIEWPORT_CULLING_MARGIN_PX || cy > h + VIEWPORT_CULLING_MARGIN_PX) {
        p.trail = [cx, cy]
        continue
      }

      // 跳帧保护：如果新点与上一个点距离过大，重置轨迹
      const trail = p.trail
      const lastIdx = trail.length - 2
      if (lastIdx >= 0) {
        const dx = cx - trail[lastIdx]
        const dy = cy - trail[lastIdx + 1]
        if (Math.abs(dx) > MAX_TRAIL_LENGTH_PX || Math.abs(dy) > MAX_TRAIL_LENGTH_PX) {
          p.trail = [cx, cy]
          continue
        }
      }

      // 追加新点到轨迹
      trail.push(cx, cy)
      // 限制轨迹长度（保留最新的 TRAIL_LENGTH 个点）
      if (trail.length > maxTrailPoints) {
        trail.splice(0, trail.length - maxTrailPoints)
      }

      // 轨迹至少需要 2 个点才能画线
      if (trail.length < 4) continue

      // 按风速分组收集
      const { idx } = speedToColorIndex(wind.speed, colorStops)
      const subpaths = colorSubpaths[idx]
      if (subpaths) {
        // 写入子路径：[点数, x0, y0, x1, y1, ...]
        subpaths.push(trail.length >> 1)  // 点数
        for (let k = 0; k < trail.length; k++) {
          subpaths.push(trail[k])
        }
      }
    }

    // === 3. 按颜色分组批量绘制轨迹（每条轨迹是一条连续 polyline）===
    for (let i = 0; i < colorSubpaths.length; i++) {
      const subpaths = colorSubpaths[i]
      if (subpaths.length === 0) continue

      const [r1, g1, b1] = this.colorRgbCache[i]
      const [r2, g2, b2] = this.colorRgbCache[i + 1]
      const r = ((r1 + r2) >> 1)
      const g = ((g1 + g2) >> 1)
      const b = ((b1 + b2) >> 1)

      ctx.strokeStyle = `rgb(${r},${g},${b})`
      ctx.globalAlpha = 0.75

      ctx.beginPath()
      let si = 0
      while (si < subpaths.length) {
        const ptCount = subpaths[si]
        si++
        // moveTo 第一个点
        ctx.moveTo(subpaths[si], subpaths[si + 1])
        // lineTo 后续点
        for (let k = 2; k < ptCount * 2; k += 2) {
          ctx.lineTo(subpaths[si + k], subpaths[si + k + 1])
        }
        si += ptCount * 2
      }
      ctx.stroke()
    }

    ctx.globalAlpha = 1
  }

  start(): void {
    if (this.rafId !== null) return
    this.rafId = requestAnimationFrame(this.animate)
  }

  stop(): void {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId)
      this.rafId = null
    }
  }

  updateGeoJSON(geojson: WindGeoJSON): void {
    const oldGrid = this.grid
    this.grid = buildWindGridFromGeoJSON(geojson)
    debugLog('WindParticleCanvas', 'updateGeoJSON', 'oldGrid', oldGrid ? `${oldGrid.rows}x${oldGrid.cols}@${oldGrid.checksum}` : 'null', 'newGrid', this.grid ? `${this.grid.rows}x${this.grid.cols}@${this.grid.checksum}` : 'null', 'features', geojson.features?.length)
    if (this.grid) {
      if (oldGrid && oldGrid.rows === this.grid.rows && oldGrid.cols === this.grid.cols && oldGrid.checksum === this.grid.checksum) {
        debugLog('WindParticleCanvas', 'updateGeoJSON skip identical grid')
        return
      }
      this.updateCanvasBounds()
      const targetCount = this.resolveParticleCountForZoom(this.map.getZoom())
      if (!oldGrid) {
        this.initParticles()
      } else {
        this.updateParticlesForNewGrid(targetCount)
      }
    } else {
      console.warn('[WindParticleCanvas] Failed to create grid from GeoJSON')
    }
  }

  /**
   * 数据更新时保留区域内粒子的地理坐标，但重置 trail 为当前屏幕位置。
   * 避免：1) 全量重置导致粒子流稀疏中断；2) 保留旧 trail 导致位置错乱伪影。
   */
  private updateParticlesForNewGrid(targetCount: number): void {
    if (!this.grid) return
    const { south, north, west, east } = this.grid
    const { offsetX, offsetY } = this.layout
    const dpr = this.pixelRatio
    let keptCount = 0
    let resetCount = 0
    for (const p of this.particles) {
      const inBounds = p.lat >= south && p.lat <= north && p.lon >= west && p.lon <= east
      if (!inBounds) {
        this.resetParticle(p)
        resetCount++
      } else {
        // 保留粒子地理坐标，仅重置 trail 为当前屏幕位置（清除旧 trail 伪影）
        const screen = this.map.project([p.lon + this.lonWrapOffset, p.lat])
        const x = (screen.x - offsetX) * dpr
        const y = (screen.y - offsetY) * dpr
        p.trail = [x, y]
        p.age = 0
        keptCount++
      }
    }
    if (this.particles.length < targetCount) {
      while (this.particles.length < targetCount) {
        this.particles.push(this.createRandomParticle())
      }
    } else if (this.particles.length > targetCount) {
      this.particles.length = targetCount
    }
    this.options.particleCount = targetCount
    debugLog('WindParticleCanvas', 'updateParticlesForNewGrid', 'kept', keptCount, 'reset', resetCount, 'target', targetCount, 'current', this.particles.length)
  }

  destroy(): void {
    this.stop()
    if (this.moveRafId !== null) { cancelAnimationFrame(this.moveRafId); this.moveRafId = null }
    if (this.movestartHandler) { this.map.off(MAP_EVENT_MOVESTART, this.movestartHandler); this.movestartHandler = null }
    if (this.moveHandler) { this.map.off(MAP_EVENT_MOVE, this.moveHandler); this.moveHandler = null }
    if (this.moveendHandler) { this.map.off(MAP_EVENT_MOVEEND, this.moveendHandler); this.moveendHandler = null }
    if (this.resizeHandler) { this.map.off(MAP_EVENT_RESIZE, this.resizeHandler); this.resizeHandler = null }
    if (this.resizeObserver) { this.resizeObserver.disconnect(); this.resizeObserver = null }
    if (this.canvas.parentElement) {
      this.canvas.parentElement.removeChild(this.canvas)
    }
  }
}
