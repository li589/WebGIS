/**
 * 风场动画流线（流量场）— Canvas 2D。
 *
 * 视口内撒种子 → 双线性采样风场 → RK2 积分画折线；
 * 沿弧长用圆环光滑脉冲驱动高亮：相位绕回时丝滑衔接，无闪回起点。
 */
import type { Map as MaplibreMap } from 'maplibre-gl'
import type { WindGeoJSON } from './types'
import { MAP_EVENT_MOVE, MAP_EVENT_MOVEEND, MAP_EVENT_RESIZE, MIN_VISIBLE_ZOOM } from './types'
import { computeCanvasLayout, type CanvasLayout } from './canvas-utils'
import { buildWindGridFromGeoJSON, windToUV, type WindGrid } from './wind-grid'
import { interpolateWind } from './wind-particle-canvas'
import { unwrapLonIntoGridFrame } from './weather-grid-lattice'

const TARGET_FRAME_INTERVAL_MS = 33
const MAX_PIXEL_RATIO = 2
const MAX_STREAMLINES = 420
const MIN_STREAMLINES = 80
const STREAMLINES_PER_DEG2 = 2.2
const STEPS_PER_LINE = 36
const STEP_DEG = 0.2
const LINE_WIDTH = 1.45
const PHASE_SPEED = 0.018
/** 主亮斑沿轨迹归一化弧长的宽度（圆环度量） */
const PULSE_WIDTH = 0.28
/** 第二条：错开半周，形成「流出又流入」的连续感 */
const SECOND_PULSE_WIDTH = 0.2
const SECOND_PULSE_OFFSET = 0.5
/** 低于此透明度的边跳过，减 stroke 次数 */
const PULSE_ALPHA_EPS = 0.03

/**
 * 圆环上的光滑脉冲。`s`/`center`/`width` ∈ [0,1)；返回 [0,1]。
 * 在 0↔1 接缝处连续，避免亮条走到头闪回起点。
 */
export function wrappedPulse(s: number, center: number, width: number): number {
  if (!(width > 0)) return 0
  const ss = ((s % 1) + 1) % 1
  const cc = ((center % 1) + 1) % 1
  let d = Math.abs(ss - cc)
  if (d > 0.5) d = 1 - d
  const half = width * 0.5
  if (d >= half) return 0
  const t = d / half
  return 0.5 * (1 + Math.cos(Math.PI * t))
}

export interface StreamlineSeed {
  lat: number
  lon: number
  phase: number
}

/** 纯函数：按网格面积估算流线条数 */
export function computeStreamlineCountForGrid(grid: WindGrid): number {
  const area = Math.abs(grid.north - grid.south) * Math.abs(grid.east - grid.west)
  const count = Math.round(area * STREAMLINES_PER_DEG2)
  return Math.min(MAX_STREAMLINES, Math.max(MIN_STREAMLINES, count))
}

/** 纯函数：在网格范围内均匀撒种子（带相位抖动） */
export function buildStreamlineSeeds(
  grid: WindGrid,
  count: number,
  rng: () => number = Math.random,
): StreamlineSeed[] {
  const seeds: StreamlineSeed[] = []
  const n = Math.max(1, count)
  const cols = Math.ceil(Math.sqrt(n * (Math.abs(grid.east - grid.west) / Math.max(1e-6, Math.abs(grid.north - grid.south)))))
  const rows = Math.ceil(n / cols)
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      if (seeds.length >= n) break
      const u = (c + 0.35 + rng() * 0.3) / cols
      const v = (r + 0.35 + rng() * 0.3) / rows
      seeds.push({
        lon: grid.west + u * (grid.east - grid.west),
        lat: grid.south + v * (grid.north - grid.south),
        phase: rng(),
      })
    }
  }
  return seeds
}

/** 纯函数：从种子积分一条流线（经纬度折线） */
export function integrateStreamline(
  grid: WindGrid,
  seedLat: number,
  seedLon: number,
  steps = STEPS_PER_LINE,
  stepDeg = STEP_DEG,
): Array<{ lat: number; lon: number; speed: number }> {
  const path: Array<{ lat: number; lon: number; speed: number }> = []
  let lat = seedLat
  let lon = seedLon
  for (let i = 0; i < steps; i++) {
    const w0 = interpolateWind(grid, lat, lon)
    if (!Number.isFinite(w0.speed) || w0.speed < 0.15) break
    const [u0, v0] = windToUV(w0.speed, w0.direction)
    const speedScale = Math.min(1.8, 0.35 + w0.speed / 18)
    const h = stepDeg * speedScale
    const midLat = lat + (v0 / Math.max(w0.speed, 1e-3)) * h * 0.5
    const midLon = lon + (u0 / Math.max(w0.speed, 1e-3)) * h * 0.5
    const w1 = interpolateWind(grid, midLat, midLon)
    const [u1, v1] = windToUV(w1.speed, w1.direction)
    const s = Math.max(w1.speed, 1e-3)
    lat += (v1 / s) * h
    lon += (u1 / s) * h
    if (lat < grid.south || lat > grid.north || lon < grid.west || lon > grid.east) break
    path.push({ lat, lon, speed: w1.speed })
  }
  return path
}

export class WindStreamlineLayer {
  private map: MaplibreMap
  private canvas: HTMLCanvasElement
  private ctx: CanvasRenderingContext2D
  private grid: WindGrid | null = null
  private seeds: StreamlineSeed[] = []
  private paths: Array<Array<{ lat: number; lon: number; speed: number }>> = []
  private layout: CanvasLayout = { width: 0, height: 0, offsetX: 0, offsetY: 0, lonWrapOffset: 0 }
  private pixelRatio: number
  private rafId: number | null = null
  private lastFrameTs = 0
  private phase = 0
  private running = false
  private lastSeedZoom = 0
  private moveHandler: () => void
  private resizeHandler: () => void
  private visibilityHandler: () => void

  constructor(map: MaplibreMap, geojson: WindGeoJSON) {
    this.map = map
    this.pixelRatio = Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO)
    const container = map.getContainer()
    this.canvas = document.createElement('canvas')
    this.canvas.className = 'wind-streamline-canvas'
    this.canvas.style.position = 'absolute'
    this.canvas.style.top = '0'
    this.canvas.style.left = '0'
    this.canvas.style.pointerEvents = 'none'
    this.canvas.style.zIndex = '5'
    container.appendChild(this.canvas)
    const ctx = this.canvas.getContext('2d', { alpha: true })
    if (!ctx) throw new Error('WindStreamlineLayer: 2d context unavailable')
    this.ctx = ctx

    this.moveHandler = () => {
      this.syncLayout()
      // 显著缩放后按当前 grid 重撒种子，避免流线仍挤在缩放前的地理范围
      const zoom = this.map.getZoom()
      if (this.grid && (this.lastSeedZoom === 0 || Math.abs(zoom - this.lastSeedZoom) >= 0.35)) {
        this.reseedPathsForZoom(zoom)
      }
      this.draw()
    }
    this.resizeHandler = () => {
      this.syncLayout()
      this.draw()
    }
    this.visibilityHandler = () => {
      if (document.hidden) this.stopLoop()
      else if (this.running) this.startLoop()
    }
    map.on(MAP_EVENT_MOVE, this.moveHandler)
    map.on(MAP_EVENT_MOVEEND, this.moveHandler)
    map.on('zoomend', this.moveHandler)
    map.on(MAP_EVENT_RESIZE, this.resizeHandler)
    document.addEventListener('visibilitychange', this.visibilityHandler)

    this.updateGeoJSON(geojson)
    this.syncLayout()
    this.lastSeedZoom = map.getZoom()
  }

  updateGeoJSON(geojson: WindGeoJSON) {
    const nextGrid = buildWindGridFromGeoJSON(geojson)
    if (!nextGrid) {
      this.grid = null
      this.seeds = []
      this.paths = []
      return
    }

    // 数据未变：跳过
    if (this.grid && this.grid.checksum === nextGrid.checksum) {
      this.syncLayout()
      return
    }

    const target = computeStreamlineCountForGrid(nextGrid)
    const inBounds = (s: StreamlineSeed) => {
      const lon = unwrapLonIntoGridFrame(s.lon, nextGrid.west, nextGrid.east)
      return s.lat >= nextGrid.south && s.lat <= nextGrid.north
        && lon >= nextGrid.west && lon <= nextGrid.east
    }

    // 瓦片陆续补齐时保留已有种子，只增量补种 + 重积分，避免密度整屏抖动
    let seeds = this.seeds.filter(inBounds)
    if (seeds.length === 0) {
      seeds = buildStreamlineSeeds(nextGrid, target)
    } else if (seeds.length > target) {
      seeds = seeds.slice(0, target)
    } else if (seeds.length < target) {
      const extras = buildStreamlineSeeds(nextGrid, target - seeds.length)
      seeds = seeds.concat(extras)
    }

    this.grid = nextGrid
    this.seeds = seeds
    this.paths = seeds.map((s) => integrateStreamline(nextGrid, s.lat, s.lon))
    this.lastSeedZoom = this.map.getZoom()
    this.syncLayout()
  }

  /** 缩放后在现有 grid 上重撒/重积分，避免亮线挤在旧地理范围 */
  private reseedPathsForZoom(zoom: number) {
    if (!this.grid) return
    const target = computeStreamlineCountForGrid(this.grid)
    this.seeds = buildStreamlineSeeds(this.grid, target)
    this.paths = this.seeds.map((s) => integrateStreamline(this.grid!, s.lat, s.lon))
    this.lastSeedZoom = zoom
  }

  start() {
    this.running = true
    this.startLoop()
  }

  private startLoop() {
    if (this.rafId !== null) return
    const tick = (ts: number) => {
      this.rafId = requestAnimationFrame(tick)
      if (document.hidden) return
      if (ts - this.lastFrameTs < TARGET_FRAME_INTERVAL_MS) return
      this.lastFrameTs = ts
      this.phase = (this.phase + PHASE_SPEED) % 1
      this.draw()
    }
    this.rafId = requestAnimationFrame(tick)
  }

  private stopLoop() {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId)
      this.rafId = null
    }
  }

  /**
   * 全视口 canvas（与粒子层一致）；仅从 grid 取 lonWrapOffset。
   * 切勿把 canvas/DOM 误传给 computeCanvasLayout（其参数是 west/east/south/north）。
   */
  private syncLayout() {
    const container = this.map.getContainer()
    const vw = container.clientWidth
    const vh = container.clientHeight
    let lonWrapOffset = 0
    if (this.grid) {
      lonWrapOffset = computeCanvasLayout(
        this.map,
        this.grid.west,
        this.grid.east,
        this.grid.south,
        this.grid.north,
      ).lonWrapOffset
    }
    this.layout = {
      width: vw,
      height: vh,
      offsetX: 0,
      offsetY: 0,
      lonWrapOffset,
    }
    const dpr = this.pixelRatio
    const nextW = Math.round(vw * dpr)
    const nextH = Math.round(vh * dpr)
    if (this.canvas.width !== nextW || this.canvas.height !== nextH) {
      this.canvas.width = nextW
      this.canvas.height = nextH
    }
    this.canvas.style.width = `${vw}px`
    this.canvas.style.height = `${vh}px`
    this.canvas.style.left = '0px'
    this.canvas.style.top = '0px'
  }

  private draw() {
    const zoom = this.map.getZoom()
    if (this.layout.width <= 0 || this.layout.height <= 0) {
      this.syncLayout()
    }
    const ctx = this.ctx
    const w = this.canvas.width
    const h = this.canvas.height
    ctx.clearRect(0, 0, w, h)
    if (zoom < MIN_VISIBLE_ZOOM || !this.grid || this.paths.length === 0) return

    const wrap = this.layout.lonWrapOffset
    const dpr = this.pixelRatio

    ctx.save()
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    ctx.lineWidth = LINE_WIDTH * dpr

    for (let i = 0; i < this.paths.length; i++) {
      const path = this.paths[i]
      if (path.length < 2) continue
      const seedPhase = this.seeds[i]?.phase ?? 0
      const localPhase = (this.phase + seedPhase) % 1

      const pts: Array<{ x: number; y: number; speed: number }> = []
      for (const p of path) {
        const scr = this.map.project([p.lon + wrap, p.lat])
        pts.push({
          x: scr.x * dpr,
          y: scr.y * dpr,
          speed: p.speed,
        })
      }

      // 屏幕弧长累积，相位按弧长而非点序号滑动，速度更匀
      const cum: number[] = [0]
      for (let j = 1; j < pts.length; j++) {
        const dx = pts[j].x - pts[j - 1].x
        const dy = pts[j].y - pts[j - 1].y
        cum.push(cum[j - 1] + Math.hypot(dx, dy))
      }
      const totalLen = cum[cum.length - 1]
      if (totalLen < 2) continue

      // 底迹
      ctx.beginPath()
      ctx.strokeStyle = 'rgba(200, 228, 255, 0.32)'
      ctx.lineWidth = LINE_WIDTH * dpr
      ctx.moveTo(pts[0].x, pts[0].y)
      for (let j = 1; j < pts.length; j++) ctx.lineTo(pts[j].x, pts[j].y)
      ctx.stroke()

      // 圆环光滑脉冲：相位 % 1 绕回时亮斑从尾丝滑接到头，无闪回
      const phase2 = (localPhase + SECOND_PULSE_OFFSET) % 1
      for (let j = 0; j < pts.length - 1; j++) {
        const sMid = (cum[j] + cum[j + 1]) * 0.5 / totalLen
        const a = Math.max(
          wrappedPulse(sMid, localPhase, PULSE_WIDTH),
          wrappedPulse(sMid, phase2, SECOND_PULSE_WIDTH) * 0.72,
        )
        if (a < PULSE_ALPHA_EPS) continue
        const speed = (pts[j].speed + pts[j + 1].speed) * 0.5
        const bright = Math.min(1, 0.35 + speed / 24)
        const alpha = (0.28 + bright * 0.62) * a
        ctx.beginPath()
        ctx.strokeStyle = `rgba(255, 255, 255, ${alpha})`
        ctx.lineWidth = (LINE_WIDTH + bright * 1.05 * a) * dpr
        ctx.moveTo(pts[j].x, pts[j].y)
        ctx.lineTo(pts[j + 1].x, pts[j + 1].y)
        ctx.stroke()
      }
    }
    ctx.restore()
  }

  destroy() {
    this.running = false
    this.stopLoop()
    this.map.off(MAP_EVENT_MOVE, this.moveHandler)
    this.map.off(MAP_EVENT_MOVEEND, this.moveHandler)
    this.map.off('zoomend', this.moveHandler)
    this.map.off(MAP_EVENT_RESIZE, this.resizeHandler)
    document.removeEventListener('visibilitychange', this.visibilityHandler)
    this.canvas.remove()
    this.grid = null
    this.seeds = []
    this.paths = []
  }
}
