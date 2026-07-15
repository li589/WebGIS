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
const TRAIL_LENGTH = 32

/**
 * 粒子年龄阶段分界（相对 maxAge 的比例）。
 * 新生粒子淡入、中期完整不透明、老化粒子淡出，避免粒子在台风眼、
 * 汇流、发散流等交汇点突然出现/消失造成视觉混乱。
 */
const AGE_BAND_YOUNG_RATIO = 0.12
const AGE_BAND_OLD_RATIO = 0.78
const AGE_BAND_ALPHAS = [0.22, 1.0, 0.30] as const

/** 粒子默认配置（稀疏柔和风格：少量粒子 + 慢速流动 + 细线） */
const DEFAULT_PARTICLE_OPTIONS = {
  particleCount: 800,
  maxAge: 110,
  speedScale: 0.028,
  fadeAlpha: 0.024,
  lineWidth: 1.2,
} as const

/** 粒子数量上限（防止过大网格导致性能问题） */
const MAX_PARTICLE_COUNT = 2000

/** 粒子数量下限 */
const MIN_PARTICLE_COUNT = 300

/** DPI 上限（防止超高分屏幕创建过大 canvas） */
const MAX_PIXEL_RATIO = 2

/** zoomFactor 上限，防止低缩放级别下粒子速度过快导致视觉混乱（线条抽搐） */
const MAX_ZOOM_FACTOR = 4

/**
 * 根据网格面积动态计算粒子数量。
 * 面积越大粒子越多，但受上限约束。
 * 密度约为每平方度 5 个粒子，保持稀疏柔和的视觉效果，
 * 避免密集区域粒子轨迹互相交错造成视觉混乱。
 */
function computeParticleCountForGrid(grid: WindGrid): number {
  const area = Math.abs(grid.north - grid.south) * Math.abs(grid.east - grid.west)
  const count = Math.round(area * 5)
  return Math.min(MAX_PARTICLE_COUNT, Math.max(MIN_PARTICLE_COUNT, count))
}

/** 静风速度阈值（m/s）：低于此值视为静风区域，重置粒子以避免聚集。
 *  海洋低风速区粒子易停滞堆积，重置后重新随机分布，使海域曲线更均匀。 */
const MIN_WIND_SPEED_FOR_RENDER = 0.5

/** 粒子寿命随机上界增量（使寿命有随机分布） */
const MAX_AGE_RANDOM_RANGE = 20

/** 默认颜色梯度（参考 Windy.com 风速色阶，蓝→青→绿→黄→红→紫） */
const DEFAULT_PARTICLE_COLORS = [
  '#6271b8', // 0 m/s   — 蓝
  '#3d6ea3', // 2.5     — 深蓝
  '#4a94aa', // 5       — 青蓝
  '#4a9294', // 7.5     — 青
  '#4d8e7c', // 10      — 青绿
  '#4ca44c', // 12.5    — 绿
  '#67a436', // 15      — 黄绿
  '#a28740', // 17.5    — 黄
  '#a26d5c', // 20      — 橙
  '#8d3f5c', // 25      — 红
  '#974b91', // 30      — 品红
  '#5f64a0', // 35+     — 紫
]

/** 默认风速断点（m/s），与颜色梯度对应 */
const DEFAULT_WIND_SPEED_STOPS = [0, 2.5, 5, 7.5, 10, 12.5, 15, 17.5, 20, 25, 30, 35]

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

  // ── 缺失单元反距离加权（IDW）填充 ──────────────────────────────
  // 多瓦片合并时，不同瓦片的网格点不完全对齐，会在并集网格中产生"孔洞"。
  // 最近邻填充会让大片孔洞继承同一数据源，形成规则的方向/速度斑块（看起来像竖直栅栏）。
  // 改用局部 IDW（限制搜索半径 + 1/r^2 权重）对周围有数据单元加权插值，
  // 既填补孔洞又保留瓦片内部的真实风向细节，避免远距离数据过度平滑。
  const MISSING_CELL_COUNT = rows * cols - rawPoints.length
  if (MISSING_CELL_COUNT > 0) {
    // 搜索半径：最多 8 个单元格；瓦片边界通常只偏移 0.5~1 个网格步长，
    // 太大半径会让插值结果趋同，丢失局部风场特征。
    const maxRadius = Math.min(8, Math.max(rows, cols))
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        if (hasData[r][c]) continue
        let sumWeight = 0
        let sumSpeed = 0
        let sumUSin = 0
        let sumUCos = 0
        let found = false
        const rStart = Math.max(0, r - maxRadius)
        const rEnd = Math.min(rows, r + maxRadius + 1)
        const cStart = Math.max(0, c - maxRadius)
        const cEnd = Math.min(cols, c + maxRadius + 1)
        for (let rr = rStart; rr < rEnd; rr++) {
          for (let cc = cStart; cc < cEnd; cc++) {
            if (!hasData[rr][cc]) continue
            const dr = rr - r
            const dc = cc - c
            const dist = Math.sqrt(dr * dr + dc * dc)
            if (dist === 0) continue
            // 1/r^2 权重：近处点影响更大，远处快速衰减，保留局部特征
            const weight = 1 / (dist * dist)
            const src = points[rr][cc]
            sumWeight += weight
            sumSpeed += src.speed * weight
            // 对 u/v 分量加权，避免角度平均的环绕问题
            const dirRad = (src.direction + WIND_DIRECTION_OFFSET) * DEG_TO_RAD
            sumUSin += Math.sin(dirRad) * src.speed * weight
            sumUCos += Math.cos(dirRad) * src.speed * weight
            found = true
          }
        }
        if (found && sumWeight > 0) {
          const avgSpeed = sumSpeed / sumWeight
          const avgURad = Math.atan2(sumUSin / sumWeight, sumUCos / sumWeight)
          const avgDirection = ((avgURad / DEG_TO_RAD) - WIND_DIRECTION_OFFSET + 360) % 360
          points[r][c].speed = avgSpeed
          points[r][c].direction = avgDirection
          hasData[r][c] = true
        }
      }
    }
  }

  // ── 最终保护：IDW 无法填充的单元格（完全没有附近数据）清零 ──────
  // 当大量瓦片加载失败时，网格中可能存在大范围"孤岛"——周围没有任何有效数据点。
  // 这些单元格的 speed/direction 仍为 NaN，会导致 interpolateWind 产生 NaN 经纬度，
  // 进而触发 map.project() 崩溃（Invalid LngLat object: (NaN, NaN)）。
  // 将剩余 NaN 清零，使粒子在这些区域静止，避免崩溃。
  let unfilledCount = 0
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      if (!hasData[r][c]) {
        points[r][c].speed = 0
        points[r][c].direction = 0
        unfilledCount++
      }
    }
  }
  if (unfilledCount > 0) {
    debugLog('WindParticleCanvas', 'buildWindGrid unfilled cells zeroed', unfilledCount)
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

  // NaN 保护：如果任一角点数据无效，回退到最近的有效角点
  const isValid = (p: WindGridPoint) => Number.isFinite(p.speed) && Number.isFinite(p.direction)
  const validPoints = [p00, p01, p10, p11].filter(isValid)
  if (validPoints.length === 0) {
    // 完全没有有效数据，返回零向量（静止），避免 NaN 传播导致 map.project 崩溃
    return { lat: clampedLat, lon: clampedLon, speed: 0, direction: 0 }
  }
  if (validPoints.length < 4) {
    // 部分角点无效：使用最近有效角点的值（非插值，避免 NaN 污染）
    const ref = validPoints[0]
    return { lat: clampedLat, lon: clampedLon, speed: ref.speed, direction: ref.direction }
  }

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

  // 最终保护：插值结果仍可能因浮点精度问题产生 NaN
  const finalSpeed = Number.isFinite(speed) ? speed : 0
  const finalDirection = Number.isFinite(direction) ? direction : 0

  return { lat: clampedLat, lon: clampedLon, speed: finalSpeed, direction: finalDirection }
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
    if (zoom < 2) return Math.min(baseCount, 160)
    if (zoom < 3) return Math.min(baseCount, 320)
    if (zoom < 5) return Math.min(baseCount, 600)
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

  /** 循环边界：粒子移出网格时从对面边界重新进入，保持流线连续。返回是否发生了 wrap。 */
  private wrapParticle(p: Particle): boolean {
    if (!this.grid) return false
    const { south, north, west, east } = this.grid
    let wrapped = false
    if (p.lat < south) { p.lat = north - (south - p.lat); wrapped = true }
    else if (p.lat > north) { p.lat = south + (p.lat - north); wrapped = true }
    if (p.lon < west) { p.lon = east - (west - p.lon); wrapped = true }
    else if (p.lon > east) { p.lon = west + (p.lon - east); wrapped = true }
    return wrapped
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

    // 按年龄阶段 × 颜色分组收集粒子轨迹
    // ageColorSubpaths[band][colorIdx] = [len0, x0,y0,..., len1, ...]
    // 年龄阶段使粒子淡入/淡出，避免交汇点突然出现/消失造成视觉混乱
    const ageBandCount = AGE_BAND_ALPHAS.length
    const ageColorSubpaths: number[][][] = []
    for (let bi = 0; bi < ageBandCount; bi++) {
      const bandSubpaths: number[][] = []
      for (let i = 0; i < this.colorRgbCache.length - 1; i++) {
        bandSubpaths.push([])
      }
      ageColorSubpaths.push(bandSubpaths)
    }

    for (const p of this.particles) {
      const wind = interpolateWind(grid, p.lat, p.lon)

      // 静风区域重置粒子：避免粒子在低风速区（如海洋静风带）停滞堆积，
      // 重置后重新随机分布到网格内，使海域曲线分布更均匀，减少密集交错。
      if (wind.speed < MIN_WIND_SPEED_FOR_RENDER) {
        this.resetParticle(p)
        continue
      }

      const [u, v] = windToUV(wind.speed, wind.direction)

      // 粒子在经纬度网格上运动：经向 1° 的地面距离随纬度变化（cos(lat)）。
      // 这里对 u（东西向）按 cos(lat) 做补偿，使 Mercator 投影上的粒子轨迹
      // 方向与真实风向一致，避免中高纬地区出现“竖直线条”。
      const cosLat = Math.max(Math.cos(p.lat * DEG_TO_RAD), 0.1)
      p.lon += (u / cosLat) * scaledSpeed
      p.lat += v * scaledSpeed
      p.age += dt

      if (p.age > p.maxAge) {
        this.resetParticle(p)
        continue
      }

      const wrapped = this.wrapParticle(p)

      const screen = project([p.lon + this.lonWrapOffset, p.lat])
      const cx = (screen.x - offsetX) * dpr
      const cy = (screen.y - offsetY) * dpr

      // wrap 后重置轨迹，避免跨网格边界的连线
      if (wrapped) {
        p.trail = [cx, cy]
        continue
      }

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

      // 按风速分组收集，并根据粒子年龄选择透明度阶段（淡入/正常/淡出）
      const { idx } = speedToColorIndex(wind.speed, colorStops)
      const ageRatio = p.age / p.maxAge
      const bandIdx = ageRatio < AGE_BAND_YOUNG_RATIO ? 0 : ageRatio > AGE_BAND_OLD_RATIO ? ageBandCount - 1 : 1
      const subpaths = ageColorSubpaths[bandIdx][idx]
      if (subpaths) {
        // 写入子路径：[点数, x0, y0, x1, y1, ...]
        subpaths.push(trail.length >> 1)  // 点数
        for (let k = 0; k < trail.length; k++) {
          subpaths.push(trail[k])
        }
      }
    }

    // === 3. 按年龄阶段 × 颜色分组批量绘制轨迹（二次贝塞尔曲线平滑）===
    // 年龄阶段透明度：新生粒子淡入、老化粒子淡出，避免台风眼、汇流、发散流等
    // 交汇点处粒子突然出现/消失造成视觉混乱
    // quadraticCurveTo 中点插值消除折线感，使旋转/交汇区域轨迹更流畅
    const bandAlpha = 0.55
    const colorCount = this.colorRgbCache.length - 1
    for (let bi = 0; bi < ageBandCount; bi++) {
      const ageAlpha = AGE_BAND_ALPHAS[bi]
      for (let i = 0; i < colorCount; i++) {
        const subpaths = ageColorSubpaths[bi][i]
        if (subpaths.length === 0) continue

        const [r, g, bl] = this.colorRgbCache[i]
        ctx.strokeStyle = `rgb(${r},${g},${bl})`
        const speedRatio = i / Math.max(1, colorCount - 1)
        ctx.globalAlpha = (bandAlpha + speedRatio * 0.25) * ageAlpha

        ctx.beginPath()
        let si = 0
        while (si < subpaths.length) {
          const ptCount = subpaths[si]
          si++
          const x0 = subpaths[si]
          const y0 = subpaths[si + 1]
          ctx.moveTo(x0, y0)

          if (ptCount <= 2) {
            ctx.lineTo(subpaths[si + 2], subpaths[si + 3])
          } else if (ptCount === 3) {
            ctx.quadraticCurveTo(subpaths[si + 2], subpaths[si + 3], subpaths[si + 4], subpaths[si + 5])
          } else {
            const lastK = (ptCount - 1) * 2
            for (let k = 2; k < lastK; k += 2) {
              const pcx = subpaths[si + k]
              const pcy = subpaths[si + k + 1]
              const mx = (pcx + subpaths[si + k + 2]) / 2
              const my = (pcy + subpaths[si + k + 3]) / 2
              ctx.quadraticCurveTo(pcx, pcy, mx, my)
            }
            ctx.lineTo(subpaths[si + lastK], subpaths[si + lastK + 1])
          }
          si += ptCount * 2
        }
        ctx.stroke()
      }
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

  /** 动态更新粒子色阶（配色方案切换时调用） */
  setColors(colors: string[]): void {
    if (!colors.length) return
    this.options.colors = colors
    this.colorRgbCache = colors.map(hexToRgb)
    // 清除画布以避免旧色阶残留
    if (this.ctx) {
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
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
      } else if (oldGrid.rows !== this.grid.rows || oldGrid.cols !== this.grid.cols) {
        // 网格尺寸变化（如新瓦片扩展了经纬度范围）：需要重置粒子以适配新边界
        this.updateParticlesForNewGrid(targetCount)
      } else {
        // 网格尺寸不变但数据变化（如瓦片补充了更多数据点）：仅更新网格引用，
        // 保留粒子轨迹，避免频繁重置导致轨迹无法积累（"竖条线"的根本原因）
        debugLog('WindParticleCanvas', 'updateGeoJSON same-size grid data updated, keeping particles')
        if (this.particles.length !== targetCount) {
          this.updateParticlesForNewGrid(targetCount)
        }
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
