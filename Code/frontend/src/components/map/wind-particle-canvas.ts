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
import {
  MAP_EVENT_MOVE,
  MAP_EVENT_MOVESTART,
  MAP_EVENT_MOVEEND,
  MAP_EVENT_RESIZE,
  MIN_VISIBLE_ZOOM,
} from './types'
import { computeCanvasLayout, type CanvasLayout } from './canvas-utils'
import { normalizeLngBounds } from './map-viewport-sync'
import { unwrapLonIntoGridFrame } from './weather-grid-lattice'
import {
  buildWindGridFromGeoJSON,
  windToUV,
  uvToSpeedDirection,
  type WindGrid,
  type WindGridPoint,
} from './wind-grid'

// ── 渲染参数常量 ─────────────────────────────────────────

/** 弧度转换常数（Math.PI / 180） */
const DEG_TO_RAD = Math.PI / 180

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
const AGE_BAND_ALPHAS = [0.45, 1.0, 0.42] as const

/**
 * 粒子默认配置（对照 Windy.app WindMap.js，商业密度加码）：
 * - 近白统一粒子色（色场交给底层色底）
 * - 约 10/°²，远景更满
 * - trailFade 更慢 → 线条更连贯
 */
const DEFAULT_PARTICLE_OPTIONS = {
  particleCount: 1200,
  maxAge: 110,
  speedScale: 0.026,
  fadeAlpha: 0.012,
  lineWidth: 1.9,
} as const

/** 粒子数量上限（防止过大网格导致性能问题） */
const MAX_PARTICLE_COUNT = 3600

/** 粒子数量下限 */
const MIN_PARTICLE_COUNT = 400

/** 对照 WindMap dropRate / dropRateBump：高风速区更频繁重生 */
const PARTICLE_DROP_RATE = 0.004
const PARTICLE_DROP_RATE_BUMP = 0.014
const PARTICLE_DROP_SPEED_REF = 25

/** DPI 上限（防止超高分屏幕创建过大 canvas） */
const MAX_PIXEL_RATIO = 2

/** 面积密度：每平方度粒子数 */
const PARTICLES_PER_DEG2 = 10

/**
 * 根据网格面积动态计算粒子数量。
 * 密度约每平方度 10 个，受上下限约束。
 */
function computeParticleCountForGrid(grid: WindGrid): number {
  const area = Math.abs(grid.north - grid.south) * Math.abs(grid.east - grid.west)
  const count = Math.round(area * PARTICLES_PER_DEG2)
  return Math.min(MAX_PARTICLE_COUNT, Math.max(MIN_PARTICLE_COUNT, count))
}

/** 供单测读取密度计算（不导出内部网格构建细节） */
export function __testComputeParticleCountForArea(areaDeg2: number): number {
  const count = Math.round(areaDeg2 * PARTICLES_PER_DEG2)
  return Math.min(MAX_PARTICLE_COUNT, Math.max(MIN_PARTICLE_COUNT, count))
}

/**
 * 真静风 / 无数据阈值（m/s）。
 * 旧值 0.5 会把大片海洋「弱风」当成静风并不断 resetParticle，
 * 粒子被反复踢出海域 → 海面几乎无线条，但 heatmap 色底仍显示「已加载」。
 * 仅对接近 0 的格子跳过绘制；弱风用下方视觉下限保证短迹可见。
 */
const MIN_WIND_SPEED_FOR_RENDER = 0.05
/** 弱风平流视觉下限（m/s）：略抬位移保证海面可见，但勿过高以免「假风」乱线 */
const MIN_ADVECT_SPEED_FOR_TRAIL = 0.35

/** 粒子寿命随机上界增量（使寿命有随机分布） */
const MAX_AGE_RANDOM_RANGE = 20

/**
 * 默认近白粒子（对照 Windy particleColor [1,1,1,0.8]）。
 * 风速着色交给底层 heatmap；粒子只表达流向。
 */
const DEFAULT_PARTICLE_COLORS = ['#f2f6ff', '#f2f6ff', '#ffffff', '#ffffff']

/** 默认风速断点（m/s），与近白色阶对应（色差极小，仅作插值锚点） */
const DEFAULT_WIND_SPEED_STOPS = [0, 8, 20, 35]

// ── 类型 ─────────────────────────────────────────────────

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
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)]
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

export function interpolateWind(grid: WindGrid, lat: number, lon: number): WindGridPoint {
  const { rows, cols, south, north, west, east, points } = grid
  const clampedLat = Math.max(south, Math.min(north, lat))
  // 网格可能处于解包经度框（east>180）；查询 lon 常在 [-180,180]
  const framedLon = unwrapLonIntoGridFrame(lon, west, east)
  const clampedLon = Math.max(west, Math.min(east, framedLon))
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

  // 对 (u, v) 分量做双线性插值，而非对 speed/direction 分别插值。
  const [u00, v00] = windToUV(p00.speed, p00.direction)
  const [u01, v01] = windToUV(p01.speed, p01.direction)
  const [u10, v10] = windToUV(p10.speed, p10.direction)
  const [u11, v11] = windToUV(p11.speed, p11.direction)
  const u = lerp(lerp(u00, u01, tc), lerp(u10, u11, tc), tr)
  const v = lerp(lerp(v00, v01, tc), lerp(v10, v11, tc), tr)
  const { speed, direction } = uvToSpeedDirection(u, v)

  // 最终保护：插值结果仍可能因浮点精度问题产生 NaN
  const finalSpeed = Number.isFinite(speed) ? speed : 0
  const finalDirection = Number.isFinite(direction) ? direction : 0

  return { lat: clampedLat, lon: clampedLon, speed: finalSpeed, direction: finalDirection }
}

/** 供单测读取：直接对一个 2×2 网格四角点做 U/V 双线性插值（不经过完整 buildWindGridFromGeoJSON） */
export function __testInterpolateWindUV(
  corners: {
    nw: WindGridPoint
    ne: WindGridPoint
    sw: WindGridPoint
    se: WindGridPoint
  },
  bounds: { south: number; north: number; west: number; east: number },
  lat: number,
  lon: number,
): { speed: number; direction: number } {
  const grid: WindGrid = {
    rows: 2,
    cols: 2,
    south: bounds.south,
    north: bounds.north,
    west: bounds.west,
    east: bounds.east,
    // row 0 = 最北：[nw, ne]；row 1 = 最南：[sw, se]
    points: [
      [corners.nw, corners.ne],
      [corners.sw, corners.se],
    ],
    checksum: 0,
  }
  const result = interpolateWind(grid, lat, lon)
  return { speed: result.speed, direction: result.direction }
}

/** 视口 bbox 类型（grid 与 viewport 共用） */
export interface WindRoamBounds {
  south: number
  north: number
  west: number
  east: number
}

/**
 * 检测网格地理范围是否发生显著平移（缩放/平移后新瓦片覆盖不同区域）。
 * 当边界偏移超过网格跨度的 15% 时认为发生了平移，需要重撒粒子。
 */
function gridBoundsShifted(a: WindGrid, b: WindGrid): boolean {
  const lonSpan = Math.max(Math.abs(a.east - a.west), 1)
  const latSpan = Math.max(Math.abs(a.north - a.south), 1)
  const dWest = Math.abs(a.west - b.west)
  const dEast = Math.abs(a.east - b.east)
  const dSouth = Math.abs(a.south - b.south)
  const dNorth = Math.abs(a.north - b.north)
  return (dWest + dEast) / lonSpan > 0.15 || (dSouth + dNorth) / latSpan > 0.15
}

/**
 * 从 MapLibre-style bounds 计算视口 bbox。
 *
 * 经度归一化与反子午线处理复用 map-viewport-sync 的 normalizeLngBounds，
 * 避免两处独立维护相同逻辑。
 *
 * 纬度钳制到 [-85, 85]：Web Mercator 投影在 ±85.05° 以外无法表示，
 * 粒子 canvas 基于 Mercator 渲染，钳制避免极地区域投影奇异。
 *（map-viewport-sync 保留 [-90, 90] 因其 bbox 也用于点查询等非渲染用途。）
 *
 * 抽离为纯函数以便单测；类方法 updateViewportBBox 是它的薄包装。
 */
export function computeViewportBBoxFromBounds(bounds: {
  getWest: () => number
  getEast: () => number
  getSouth: () => number
  getNorth: () => number
}): WindRoamBounds {
  const { west, east } = normalizeLngBounds(bounds.getWest(), bounds.getEast())
  return {
    south: Math.max(-85, bounds.getSouth()),
    north: Math.min(85, bounds.getNorth()),
    west,
    east,
  }
}

/**
 * 粒子活动范围：取 grid 边界与 viewport 边界的外包络。
 * - grid 未加载时返回 viewportBBox（仅视口范围）
 * - viewport 未初始化时返回 grid（旧行为，仅 grid 范围）
 * - 两者都有时返回并集（让粒子在视口已平移到 grid 外时仍能分布到新区域，
 *   用 grid 边缘格点的风场做外推；新瓦片到达后 grid 重建，范围自然收紧）
 *
 * 当 grid 使用解包经度（east&gt;180）时，把 viewport 经度卷入同一连续框，
 * 避免 Math.min/max 把跨日界线并成「穿过美洲」的假跨度 → 半屏空白。
 */
export function mergeRoamBounds(
  grid: WindRoamBounds | null,
  viewport: WindRoamBounds | null,
): WindRoamBounds | null {
  if (!grid) return viewport
  if (!viewport) return grid
  const vw = unwrapLonIntoGridFrame(viewport.west, grid.west, grid.east)
  const ve = unwrapLonIntoGridFrame(viewport.east, grid.west, grid.east)
  // east 可能被卷到 west 西侧（短路径视口）；保证 east>=west 供粒子均匀撒点
  const west = Math.min(grid.west, vw, ve)
  let east = Math.max(grid.east, vw, ve)
  if (east < west) {
    east += 360
  }
  return {
    south: Math.min(grid.south, viewport.south),
    north: Math.max(grid.north, viewport.north),
    west,
    east,
  }
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

  /**
   * 用户当前视口 bbox（来自 map.getBounds()），用于在 grid 未覆盖新区域时
   * 扩展粒子活动范围。grid 受瓦片加载进度限制，新视口可能已平移到 grid 外；
   * 若粒子被锁在旧 grid 边界内（resetParticle/wrapParticle），新区域会视觉空白。
   * 通过 getEffectiveRoamBounds() 取 grid 与 viewport 的外包络解决此问题。
   */
  private viewportBBox: WindRoamBounds | null = null

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
    debugLog(
      'WindParticleCanvas',
      'constructor grid',
      this.grid ? `${this.grid.rows}x${this.grid.cols}` : 'null',
      'features',
      geojson.features?.length,
      'zoom',
      map.getZoom(),
    )
    this.updateCanvasBounds(true)
    this.updateViewportBBox()
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
      // 不再 clearRect：平移时由 move 重投影 + animate 继续画，避免「已加载区域闪空」
    }
    this.moveHandler = () => {
      // 用独立的 rAF 节流，避免与 animate 循环的 rafId 冲突
      if (this.moveRafId !== null) return
      this.moveRafId = requestAnimationFrame(() => {
        this.moveRafId = null
        if (!this.isMapInteracting || !this.grid) return
        const sizeChanged = this.updateCanvasBounds()
        this.reprojectParticleTrailsForInteract()
        // 清旧屏坐标残影后立刻重画一帧（dt=0：不推进、不淡化），避免缩放期间整幅空白
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
        this.draw(0)
        void sizeChanged
      })
    }
    this.moveendHandler = () => {
      this.isMapInteracting = false
      debugLog('WindParticleCanvas', 'moveend')
      this.updateCanvasBounds()
      // 视口 bbox 必须在 reprojectParticleTrailsForInteract 之前更新，
      // 让 reset/getEffectiveRoamBounds 拿到最新视口范围
      this.updateViewportBBox()
      const zoom = this.map.getZoom()
      const targetCount = this.resolveParticleCountForZoom(zoom)
      const currentCount = this.particles.length
      const zoomDelta = this.lastParticleZoom === 0 ? 99 : Math.abs(zoom - this.lastParticleZoom)
      // 缩放后旧粒子仍聚在原先地理范围 → 画面上只剩「缩放前那一块」；
      // 显著变焦时按新视口∪grid 重撒，避免画布像被裁切。
      // 阈值从 0.35 降到 0.22：用户小幅缩放后也期望新区域有粒子覆盖。
      const countChanged =
        Math.abs(targetCount - currentCount) / Math.max(currentCount, 1) >
        PARTICLE_COUNT_CHANGE_THRESHOLD
      const shouldReseed = zoomDelta >= 0.22 || countChanged || this.particles.length === 0
      debugLog(
        'WindParticleCanvas',
        'moveend',
        'zoom',
        zoom,
        'targetCount',
        targetCount,
        'currentCount',
        currentCount,
        'zoomDelta',
        zoomDelta,
        'reseed',
        shouldReseed,
      )
      if (shouldReseed && this.grid) {
        this.options.particleCount = targetCount
        this.initParticles()
        this.lastParticleZoom = zoom
      } else if (this.grid) {
        this.reprojectParticleTrailsForInteract()
      }
    }
    this.resizeHandler = () => {
      debugLog('WindParticleCanvas', 'resize')
      this.updateCanvasBounds()
    }

    this.map.on(MAP_EVENT_MOVESTART, this.movestartHandler)
    this.map.on(MAP_EVENT_MOVE, this.moveHandler)
    this.map.on(MAP_EVENT_MOVEEND, this.moveendHandler)
    // zoomend：部分手势路径 moveend 与 zoom 不同步；保证缩放后重投影与粒子密度
    this.map.on('zoomend', this.moveendHandler)
    this.map.on(MAP_EVENT_RESIZE, this.resizeHandler)
  }

  /**
   * 粒子层使用全视口 canvas（仅从 computeCanvasLayout 取 lonWrapOffset）。
   * 若按数据 bbox 裁切，平移时 width/height 每帧变化 → 重建缓冲区 → 已加载区域闪空。
   *
   * @param recalcWrapOffset 是否重新计算 lonWrapOffset。仅在网格数据变化时为 true，
   *   交互期间保持偏移稳定，避免用户点击/平移导致 offset 在 0 和 ±360 之间跳变，
   *   使粒子突然投影到不可见世界副本 → 半球空白。
   */
  private updateCanvasBounds(recalcWrapOffset = false): boolean {
    const container = this.map.getContainer()
    const vw = container.clientWidth
    const vh = container.clientHeight
    let lonWrapOffset = this.lonWrapOffset
    if (recalcWrapOffset && this.grid) {
      lonWrapOffset = computeCanvasLayout(
        this.map,
        this.grid.west,
        this.grid.east,
        this.grid.south,
        this.grid.north,
      ).lonWrapOffset
    }
    const old = this.layout
    this.layout = {
      width: vw,
      height: vh,
      offsetX: 0,
      offsetY: 0,
      lonWrapOffset,
    }
    this.lonWrapOffset = lonWrapOffset
    if (old.width !== vw || old.height !== vh || old.lonWrapOffset !== lonWrapOffset) {
      debugLog('WindParticleCanvas', 'updateCanvasBounds', `${vw}x${vh}`, 'wrap', lonWrapOffset)
    }
    return this.resizeCanvas()
  }

  /** @returns 是否因尺寸变化而重建了 canvas 缓冲区 */
  private resizeCanvas(): boolean {
    const { width, height, offsetX, offsetY } = this.layout
    const dpr = this.pixelRatio
    const nextW = Math.round(width * dpr)
    const nextH = Math.round(height * dpr)
    const sizeChanged = this.canvas.width !== nextW || this.canvas.height !== nextH
    // 赋值 canvas.width/height 会清空缓冲区；尺寸不变时只改 CSS 位移，避免平移闪空
    if (sizeChanged) {
      this.canvas.width = nextW
      this.canvas.height = nextH
    }
    this.canvas.style.width = `${width}px`
    this.canvas.style.height = `${height}px`
    this.canvas.style.left = `${offsetX}px`
    this.canvas.style.top = `${offsetY}px`
    return sizeChanged
  }

  private resolveParticleCountForZoom(zoom: number): number {
    if (!this.grid) return DEFAULT_PARTICLE_OPTIONS.particleCount
    const baseCount = computeParticleCountForGrid(this.grid)
    // 低缩放降密度，避免全球/大范围视图线条糊成一片
    if (zoom < 2) return Math.min(baseCount, 480)
    if (zoom < 3) return Math.min(baseCount, 900)
    if (zoom < 5) return Math.min(baseCount, 1800)
    return baseCount
  }

  /**
   * 交互（平移/缩放）时把粒子轨迹重投影为「当前位置 + 沿风向短 stub」。
   * 单点 trail 画不出线；缩放中若只留 [x,y] 会看起来像闪空后消失。
   */
  private reprojectParticleTrailsForInteract(): void {
    if (!this.grid) return
    const { offsetX, offsetY } = this.layout
    const dpr = this.pixelRatio
    const stubDeg = 0.04
    for (const p of this.particles) {
      const wind = interpolateWind(this.grid, p.lat, p.lon)
      const screen0 = this.map.project([p.lon + this.lonWrapOffset, p.lat])
      const x0 = (screen0.x - offsetX) * dpr
      const y0 = (screen0.y - offsetY) * dpr
      if (!Number.isFinite(wind.speed) || wind.speed < MIN_WIND_SPEED_FOR_RENDER) {
        p.trail = [x0, y0, x0 + 1, y0]
        continue
      }
      const advectSpeed = Math.max(wind.speed, MIN_ADVECT_SPEED_FOR_TRAIL)
      // 与 draw() 的 RK2 midpoint 保持一致：先用当前点风场算半步，
      // 再用 midpoint 风场推出 stub 终点，避免交互拖动时方向与正常推进不一致
      const [u0, v0] = windToUV(advectSpeed, wind.direction)
      const cosLat0 = Math.max(Math.cos(p.lat * DEG_TO_RAD), 0.1)
      const halfDeg = stubDeg * 0.5
      const midLon = p.lon + (u0 / cosLat0) * halfDeg
      const midLat = p.lat + v0 * halfDeg
      const windMid = interpolateWind(this.grid, midLat, midLon)
      const advectSpeedMid = Math.max(windMid.speed, MIN_ADVECT_SPEED_FOR_TRAIL)
      const [uMid, vMid] = windToUV(advectSpeedMid, windMid.direction)
      const cosLatMid = Math.max(Math.cos(midLat * DEG_TO_RAD), 0.1)
      const lon1 = p.lon + (uMid / cosLatMid) * stubDeg
      const lat1 = p.lat + vMid * stubDeg
      const screen1 = this.map.project([lon1 + this.lonWrapOffset, lat1])
      const x1 = (screen1.x - offsetX) * dpr
      const y1 = (screen1.y - offsetY) * dpr
      p.trail = [x0, y0, x1, y1]
    }
  }

  /**
   * 从 map.getBounds() 读取当前视口 bbox 并存入 viewportBBox。
   * 跨 ±180° 经线时（east < west）将 east 扩展到 (180, 360) 区间，
   * 保留"从 west 向东到 east"的短路径语义，与 map-viewport-sync 保持一致。
   */
  private updateViewportBBox(): void {
    this.viewportBBox = computeViewportBBoxFromBounds(this.map.getBounds())
  }

  /**
   * 粒子活动范围：智能合并 grid 与 viewport 边界。
   * - grid 未加载时返回 viewportBBox（仅视口范围）
   * - viewport 未初始化时返回 grid（旧行为，仅 grid 范围）
   * - 视口完全包含在 grid 内（缩放后的典型情况）：返回视口 + 20% 边距，
   *   避免粒子均匀撒在整个旧网格区域而视口内几乎没有。
   * - 视口超出 grid（平移后新区域无数据）：返回并集，让粒子能分布到新区域。
   *
   * 直接传 this.grid 给 mergeRoamBounds：WindGrid 结构兼容 WindRoamBounds
   *（均有 south/north/west/east），避免每次调用分配临时对象（wrapParticle 每帧每粒子调用）。
   */
  private getEffectiveRoamBounds(): WindRoamBounds | null {
    const grid = this.grid
    const viewport = this.viewportBBox
    if (!grid) return viewport
    if (!viewport) return grid

    // 判断视口是否完全包含在 grid 内（经度解包后比较）
    const vw = unwrapLonIntoGridFrame(viewport.west, grid.west, grid.east)
    const ve = unwrapLonIntoGridFrame(viewport.east, grid.west, grid.east)
    const vpWest = Math.min(vw, ve)
    const vpEast = Math.max(vw, ve)
    const vpContained =
      vpWest >= grid.west &&
      vpEast <= grid.east &&
      viewport.south >= grid.south &&
      viewport.north <= grid.north

    if (vpContained) {
      // 视口在 grid 内：以视口为主 + 20% 边距，保证粒子集中在可见区域。
      // 边距让边缘粒子不会突然消失，平移时仍有少量粒子在视口外等待进入。
      const lonSpan = vpEast - vpWest
      const latSpan = viewport.north - viewport.south
      const lonMargin = lonSpan * 0.2
      const latMargin = latSpan * 0.2
      return {
        south: Math.max(grid.south, viewport.south - latMargin),
        north: Math.min(grid.north, viewport.north + latMargin),
        west: Math.max(grid.west, vpWest - lonMargin),
        east: Math.min(grid.east, vpEast + lonMargin),
      }
    }

    // 视口超出 grid：用并集，让粒子能覆盖到 grid 外的新区域
    return mergeRoamBounds(grid, viewport)
  }

  private createRandomParticle(): Particle {
    const bounds = this.getEffectiveRoamBounds()
    if (!bounds) {
      // 兜底：grid 与 viewport 都未初始化时返回原点占位粒子（不应到达此处）
      return { lat: 0, lon: 0, trail: [0, 0, 1, 0], age: 0, maxAge: this.options.maxAge }
    }
    const { south, north, west, east } = bounds
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
      trail: [x, y, x + 1, y],
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
    // 用 getEffectiveRoamBounds 而非 grid：视口已平移到 grid 外时，
    // 新粒子能落到新视口区域（用 grid 边缘风场外推），避免新区域空白
    const bounds = this.getEffectiveRoamBounds()
    if (!bounds) return
    const { south, north, west, east } = bounds
    const { offsetX, offsetY } = this.layout
    const dpr = this.pixelRatio
    p.lat = south + Math.random() * (north - south)
    p.lon = west + Math.random() * (east - west)
    const screen = this.map.project([p.lon + this.lonWrapOffset, p.lat])
    const x = (screen.x - offsetX) * dpr
    const y = (screen.y - offsetY) * dpr
    p.trail = [x, y, x + 1, y]
    p.age = 0
  }

  /** 循环边界：粒子移出活动范围时从对面边界重新进入，保持流线连续。返回是否发生了 wrap。 */
  private wrapParticle(p: Particle): boolean {
    const bounds = this.getEffectiveRoamBounds()
    if (!bounds) return false
    const { south, north, west, east } = bounds
    let wrapped = false
    if (p.lat < south) {
      p.lat = north - (south - p.lat)
      wrapped = true
    } else if (p.lat > north) {
      p.lat = south + (p.lat - north)
      wrapped = true
    }
    if (p.lon < west) {
      p.lon = east - (west - p.lon)
      wrapped = true
    } else if (p.lon > east) {
      p.lon = west + (p.lon - east)
      wrapped = true
    }
    return wrapped
  }

  private animate = (now: number): void => {
    this.debugFrame++
    if (!this.grid || this.particles.length === 0) {
      if (this.debugFrame % 60 === 0) {
        debugLog(
          'WindParticleCanvas',
          'animate no-op',
          'grid',
          !!this.grid,
          'particles',
          this.particles.length,
        )
      }
      this.rafId = requestAnimationFrame(this.animate)
      return
    }

    if (this.isMapInteracting) {
      // 交互中仍保持可见：重投影短迹后清屏重画（避免 alpha 叠加以致糊成一片）
      this.lastDrawTime = now
      this.reprojectParticleTrailsForInteract()
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
      this.draw(0)
      this.rafId = requestAnimationFrame(this.animate)
      return
    }

    if (this.lastDrawTime > 0 && now - this.lastDrawTime < TARGET_FRAME_INTERVAL_MS) {
      this.rafId = requestAnimationFrame(this.animate)
      return
    }

    const dt =
      this.lastDrawTime > 0
        ? Math.min((now - this.lastDrawTime) / MS_PER_60FPS_FRAME, MAX_DT_FRAMES)
        : 1
    this.lastDrawTime = now

    if (this.debugFrame % 60 === 0) {
      const totalTrail = this.particles.reduce((sum, p) => sum + p.trail.length, 0)
      const avgTrail = totalTrail / this.particles.length
      const minTrail = Math.min(...this.particles.map((p) => p.trail.length))
      const maxTrail = Math.max(...this.particles.map((p) => p.trail.length))
      debugLog(
        'WindParticleCanvas',
        'animate frame',
        this.debugFrame,
        'particles',
        this.particles.length,
        'avgTrail',
        avgTrail.toFixed(1),
        'minTrail',
        minTrail,
        'maxTrail',
        maxTrail,
        'dt',
        dt.toFixed(2),
      )
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

    // 根据缩放级别动态调整速度比例：低 zoom 时粒子经纬度移动量需更大，但封顶更严以防抽搐
    const zoomFactor = Math.min(Math.pow(2, Math.max(0, 4.2 - zoom)), 2.4)
    // 粒子位移用更小 dt 上限，防止标签页切回等跳帧时长线条突刺；
    // 拖尾衰减仍按真实 dt 计算（见下方指数模型），保证视觉连续。
    const advectDt = Math.min(dt, 2)
    const scaledSpeed = speedScale * zoomFactor * advectDt
    const freezeFrame = dt <= 0

    // === 1. 拖尾衰减：destination-out 模式淡化旧轨迹（冻结帧不淡化，避免缩放时被擦光）===
    if (!freezeFrame) {
      ctx.globalCompositeOperation = 'destination-out'
      // 帧率无关的指数衰减：连续 N 帧 × fadeAlpha ≡ 单帧 1 - (1-fadeAlpha)^N。
      // 旧线性模型 fadeAlpha*dt 在 dt 较大时被 0.15 cap 饱和，造成"一阵一阵"。
      // dt 已在 animate() 被 MAX_DT_FRAMES=4 钳制，指数函数自身有界（趋于 1）。
      ctx.globalAlpha = 1 - Math.pow(1 - fadeAlpha, dt)
      ctx.fillStyle = '#000'
      ctx.fillRect(0, 0, this.canvas.width, this.canvas.height)
    }

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

      // 仅真静风/无数据才跳过；弱风（常见于海洋）仍绘制，否则粒子会被「吸」到陆上风区
      if (!Number.isFinite(wind.speed) || wind.speed < MIN_WIND_SPEED_FOR_RENDER) {
        if (!freezeFrame) this.resetParticle(p)
        continue
      }

      if (!freezeFrame) {
        // RK2 (midpoint) 平流积分：先用当前点风场估算半步位置，再用半步位置
        // 重采样风场推进一步。比 Euler 一阶在曲率大的旋转流场（台风眼、急流）
        // 中更准确，避免粒子向外螺旋伪影。
        // 数学：k1 = f(x_n)；k2 = f(x_n + h/2·k1)；x_{n+1} = x_n + h·k2
        const advectSpeed0 = Math.max(wind.speed, MIN_ADVECT_SPEED_FOR_TRAIL)
        const [u0, v0] = windToUV(advectSpeed0, wind.direction)

        // 粒子在经纬度网格上运动：经向 1° 的地面距离随纬度变化（cos(lat)）。
        // 这里对 u（东西向）按 cos(lat) 做补偿，使 Mercator 投影上的粒子轨迹
        // 方向与真实风向一致，避免中高纬地区出现“竖直线条”。
        const cosLat0 = Math.max(Math.cos(p.lat * DEG_TO_RAD), 0.1)
        const halfSpeed = scaledSpeed * 0.5
        const midLon = p.lon + (u0 / cosLat0) * halfSpeed
        const midLat = p.lat + v0 * halfSpeed

        // 在 midpoint 重采样风场；interpolateWind 内部已 clamp 到 grid 边界，
        // 外推用边缘格点值，保证 midpoint 即使落到 grid 外也能给出连续向量
        const windMid = interpolateWind(grid, midLat, midLon)
        const advectSpeedMid = Math.max(windMid.speed, MIN_ADVECT_SPEED_FOR_TRAIL)
        const [uMid, vMid] = windToUV(advectSpeedMid, windMid.direction)
        const cosLatMid = Math.max(Math.cos(midLat * DEG_TO_RAD), 0.1)
        p.lon += (uMid / cosLatMid) * scaledSpeed
        p.lat += vMid * scaledSpeed
        p.age += dt

        // 高风速区提高重生概率，拖尾更“活”（对照 Windy dropRateBump）
        const dropChance =
          (PARTICLE_DROP_RATE +
            PARTICLE_DROP_RATE_BUMP * Math.min(1, wind.speed / PARTICLE_DROP_SPEED_REF)) *
          dt
        if (p.age > p.maxAge || Math.random() < dropChance) {
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
        if (
          cx < -VIEWPORT_CULLING_MARGIN_PX ||
          cx > w + VIEWPORT_CULLING_MARGIN_PX ||
          cy < -VIEWPORT_CULLING_MARGIN_PX ||
          cy > h + VIEWPORT_CULLING_MARGIN_PX
        ) {
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
      }

      // 轨迹至少需要 2 个点才能画线
      const trail = p.trail
      if (trail.length < 4) continue

      // 按风速分组收集，并根据粒子年龄选择透明度阶段（淡入/正常/淡出）
      const { idx } = speedToColorIndex(wind.speed, colorStops)
      const ageRatio = p.age / p.maxAge
      const bandIdx =
        ageRatio < AGE_BAND_YOUNG_RATIO ? 0 : ageRatio > AGE_BAND_OLD_RATIO ? ageBandCount - 1 : 1
      const subpaths = ageColorSubpaths[bandIdx][idx]
      if (subpaths) {
        // 写入子路径：[点数, x0, y0, x1, y1, ...]
        subpaths.push(trail.length >> 1) // 点数
        for (let k = 0; k < trail.length; k++) {
          subpaths.push(trail[k])
        }
      }
    }

    // === 3. 按年龄阶段 × 颜色分组批量绘制轨迹（二次贝塞尔曲线平滑）===
    // 年龄阶段透明度：新生粒子淡入、老化粒子淡出，避免台风眼、汇流、发散流等
    // 交汇点处粒子突然出现/消失造成视觉混乱
    // quadraticCurveTo 中点插值消除折线感，使旋转/交汇区域轨迹更流畅
    const bandAlpha = 0.78
    const colorCount = this.colorRgbCache.length - 1
    for (let bi = 0; bi < ageBandCount; bi++) {
      const ageAlpha = AGE_BAND_ALPHAS[bi]
      for (let i = 0; i < colorCount; i++) {
        const subpaths = ageColorSubpaths[bi][i]
        if (subpaths.length === 0) continue

        const [r, g, bl] = this.colorRgbCache[i]
        ctx.strokeStyle = `rgb(${r},${g},${bl})`
        const speedRatio = i / Math.max(1, colorCount - 1)
        ctx.globalAlpha = (bandAlpha + speedRatio * 0.22) * ageAlpha

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
            ctx.quadraticCurveTo(
              subpaths[si + 2],
              subpaths[si + 3],
              subpaths[si + 4],
              subpaths[si + 5],
            )
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
    const nextKey = colors.join('|')
    const prevKey = (this.options.colors ?? []).join('|')
    if (nextKey === prevKey && this.colorRgbCache.length === colors.length) {
      return
    }
    this.options.colors = colors
    this.colorRgbCache = colors.map(hexToRgb)
    // 色阶段数必须与 colorStops 对齐，否则 speedToColorIndex 会越界丢线
    if (colors.length >= 2) {
      const maxSpeed = DEFAULT_WIND_SPEED_STOPS[DEFAULT_WIND_SPEED_STOPS.length - 1]
      this.options.colorStops = Array.from(
        { length: colors.length },
        (_, i) => (maxSpeed * i) / (colors.length - 1),
      )
    }
    // 仅在色阶真正变化时清屏，避免瓦片流式到达时反复闪空
    if (this.ctx) {
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
    }
    // 立刻补一帧，避免 clear 后等到下一节流帧才出现「空白一段时间」
    if (this.grid && this.particles.length > 0) {
      this.draw(0)
    }
  }

  updateGeoJSON(geojson: WindGeoJSON): void {
    const oldGrid = this.grid
    const nextGrid = buildWindGridFromGeoJSON(geojson)
    debugLog(
      'WindParticleCanvas',
      'updateGeoJSON',
      'oldGrid',
      oldGrid ? `${oldGrid.rows}x${oldGrid.cols}@${oldGrid.checksum}` : 'null',
      'newGrid',
      nextGrid ? `${nextGrid.rows}x${nextGrid.cols}@${nextGrid.checksum}` : 'null',
      'features',
      geojson.features?.length,
    )
    if (!nextGrid) {
      // 缩放换瓦瞬间合并结果可能过稀建不出网格：保留旧网格，避免粒子整层消失
      console.warn('[WindParticleCanvas] Failed to create grid from GeoJSON; keeping previous grid')
      return
    }
    this.grid = nextGrid
    if (
      oldGrid &&
      oldGrid.rows === this.grid.rows &&
      oldGrid.cols === this.grid.cols &&
      oldGrid.checksum === this.grid.checksum
    ) {
      debugLog('WindParticleCanvas', 'updateGeoJSON skip identical grid')
      return
    }
    this.updateCanvasBounds(true)
    const targetCount = this.resolveParticleCountForZoom(this.map.getZoom())
    if (!oldGrid) {
      this.initParticles()
    } else if (oldGrid.rows !== this.grid.rows || oldGrid.cols !== this.grid.cols) {
      // 网格尺寸变化（如新瓦片扩展了经纬度范围）：需要重置粒子以适配新边界
      this.updateParticlesForNewGrid(targetCount)
    } else if (gridBoundsShifted(oldGrid, this.grid)) {
      // 网格尺寸不变但地理范围平移（缩放后新瓦片覆盖不同区域）：
      // 旧粒子仍聚在原先地理范围 → 新区域空白，需重撒到新边界
      debugLog('WindParticleCanvas', 'updateGeoJSON bounds shifted, redistributing particles')
      this.updateParticlesForNewGrid(targetCount)
    } else {
      // 网格尺寸与范围不变但数据变化（如瓦片补充了更多数据点）：仅更新网格引用，
      // 保留粒子轨迹，避免频繁重置导致轨迹无法积累（“竖条线”的根本原因）
      debugLog('WindParticleCanvas', 'updateGeoJSON same-size grid data updated, keeping particles')
      if (this.particles.length !== targetCount) {
        this.updateParticlesForNewGrid(targetCount)
      }
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
        p.trail = [x, y, x + 1, y]
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
    debugLog(
      'WindParticleCanvas',
      'updateParticlesForNewGrid',
      'kept',
      keptCount,
      'reset',
      resetCount,
      'target',
      targetCount,
      'current',
      this.particles.length,
    )
  }

  destroy(): void {
    this.stop()
    if (this.moveRafId !== null) {
      cancelAnimationFrame(this.moveRafId)
      this.moveRafId = null
    }
    if (this.movestartHandler) {
      this.map.off(MAP_EVENT_MOVESTART, this.movestartHandler)
      this.movestartHandler = null
    }
    if (this.moveHandler) {
      this.map.off(MAP_EVENT_MOVE, this.moveHandler)
      this.moveHandler = null
    }
    if (this.moveendHandler) {
      this.map.off(MAP_EVENT_MOVEEND, this.moveendHandler)
      this.map.off('zoomend', this.moveendHandler)
      this.moveendHandler = null
    }
    if (this.resizeHandler) {
      this.map.off(MAP_EVENT_RESIZE, this.resizeHandler)
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
