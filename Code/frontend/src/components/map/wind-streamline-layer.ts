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
import {
  computeViewportBBoxFromBounds,
  interpolateWind,
  type WindRoamBounds,
} from './wind-particle-canvas'
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
/** zoom-out 后 grid 面积显著增大时强制按视口重撒，避免旧种子+稀疏补种导致视口空 */
const AREA_RESEED_RATIO = 1.5
/** 视口撒种边距（相对视口跨度） */
const SEED_VIEWPORT_MARGIN = 0.15

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

export interface StreamlineSeedBounds {
  west: number
  east: number
  south: number
  north: number
}

/** 纯函数：按面积估算流线条数 */
export function computeStreamlineCountForArea(areaDeg2: number): number {
  const count = Math.round(Math.abs(areaDeg2) * STREAMLINES_PER_DEG2)
  return Math.min(MAX_STREAMLINES, Math.max(MIN_STREAMLINES, count))
}

/** 纯函数：按网格面积估算流线条数 */
export function computeStreamlineCountForGrid(grid: WindGrid): number {
  const area = Math.abs(grid.north - grid.south) * Math.abs(grid.east - grid.west)
  return computeStreamlineCountForArea(area)
}

/**
 * 流量场撒种范围：视口（含边距）与 grid 的交集。
 * 大范围 zoom-out 后若仍按全 grid 均匀撒种，MAX_STREAMLINES 摊到全球会令视口几乎空白。
 */
export function resolveStreamlineSeedBounds(
  grid: StreamlineSeedBounds,
  viewport: WindRoamBounds | null,
): StreamlineSeedBounds {
  if (!viewport) {
    return { west: grid.west, east: grid.east, south: grid.south, north: grid.north }
  }
  const vw = unwrapLonIntoGridFrame(viewport.west, grid.west, grid.east)
  const ve = unwrapLonIntoGridFrame(viewport.east, grid.west, grid.east)
  const vpWest = Math.min(vw, ve)
  const vpEast = Math.max(vw, ve)
  const lonSpan = Math.max(1e-6, vpEast - vpWest)
  const latSpan = Math.max(1e-6, viewport.north - viewport.south)
  const lonMargin = lonSpan * SEED_VIEWPORT_MARGIN
  const latMargin = latSpan * SEED_VIEWPORT_MARGIN
  const west = Math.max(grid.west, vpWest - lonMargin)
  const east = Math.min(grid.east, vpEast + lonMargin)
  const south = Math.max(grid.south, viewport.south - latMargin)
  const north = Math.min(grid.north, viewport.north + latMargin)
  if (!(east > west) || !(north > south)) {
    return { west: grid.west, east: grid.east, south: grid.south, north: grid.north }
  }
  return { west, east, south, north }
}

/** renderWorldCopies：主世界投影在屏外时，±360 副本仍可能在视口内 */
export function streamlineLonWrapOffsets(baseWrap: number): number[] {
  return [baseWrap - 360, baseWrap, baseWrap + 360]
}

/** 纯函数：在给定范围内均匀撒种子（带相位抖动） */
export function buildStreamlineSeeds(
  bounds: StreamlineSeedBounds,
  count: number,
  rng: () => number = Math.random,
): StreamlineSeed[] {
  const seeds: StreamlineSeed[] = []
  const n = Math.max(1, count)
  const lonSpan = Math.abs(bounds.east - bounds.west)
  const latSpan = Math.max(1e-6, Math.abs(bounds.north - bounds.south))
  const cols = Math.ceil(Math.sqrt(n * (lonSpan / latSpan)))
  const rows = Math.ceil(n / cols)
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      if (seeds.length >= n) break
      const u = (c + 0.35 + rng() * 0.3) / cols
      const v = (r + 0.35 + rng() * 0.3) / rows
      seeds.push({
        lon: bounds.west + u * (bounds.east - bounds.west),
        lat: bounds.south + v * (bounds.north - bounds.south),
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
  /** 与粒子层一致：仅在数据变化时重算，避免交互中 0↔±360 跳变导致半球空白 */
  private lonWrapOffset = 0
  private pixelRatio: number
  private rafId: number | null = null
  private lastFrameTs = 0
  private phase = 0
  private running = false
  private lastSeedZoom = 0
  private moveHandler: () => void
  private moveEndHandler: () => void
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
      this.syncLayout(false)
      this.draw()
    }
    this.moveEndHandler = () => {
      this.syncLayout(false)
      const zoom = this.map.getZoom()
      if (this.grid && (this.lastSeedZoom === 0 || Math.abs(zoom - this.lastSeedZoom) >= 0.35)) {
        this.reseedPathsForZoom(zoom)
      }
      this.draw()
    }
    this.resizeHandler = () => {
      this.syncLayout(false)
      this.draw()
    }
    this.visibilityHandler = () => {
      if (document.hidden) this.stopLoop()
      else if (this.running) this.startLoop()
    }
    map.on(MAP_EVENT_MOVE, this.moveHandler)
    map.on(MAP_EVENT_MOVEEND, this.moveEndHandler)
    map.on('zoomend', this.moveEndHandler)
    map.on(MAP_EVENT_RESIZE, this.resizeHandler)
    document.addEventListener('visibilitychange', this.visibilityHandler)

    this.updateGeoJSON(geojson)
    this.syncLayout(true)
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

    // 数据未变：跳过重撒，但仍刷新 wrap（视口可能已变）
    if (this.grid && this.grid.checksum === nextGrid.checksum) {
      this.syncLayout(true)
      return
    }

    const viewport = this.readViewportBBox()
    const seedBounds = resolveStreamlineSeedBounds(nextGrid, viewport)
    const target = computeStreamlineCountForArea(
      Math.abs(seedBounds.north - seedBounds.south) * Math.abs(seedBounds.east - seedBounds.west),
    )

    const old = this.grid
    const oldArea = old ? Math.abs(old.north - old.south) * Math.abs(old.east - old.west) : 0
    const newArea =
      Math.abs(nextGrid.north - nextGrid.south) * Math.abs(nextGrid.east - nextGrid.west)
    const areaGrew = !old || newArea > oldArea * AREA_RESEED_RATIO

    const inSeedBounds = (s: StreamlineSeed) => {
      const lon = unwrapLonIntoGridFrame(s.lon, seedBounds.west, seedBounds.east)
      return (
        s.lat >= seedBounds.south &&
        s.lat <= seedBounds.north &&
        lon >= seedBounds.west &&
        lon <= seedBounds.east
      )
    }

    // zoom-out 揭示大片新区：整列按视口重撒，保证密度；瓦片微调则增量保留
    let seeds: StreamlineSeed[]
    if (areaGrew || this.seeds.length === 0) {
      seeds = buildStreamlineSeeds(seedBounds, target)
    } else {
      seeds = this.seeds.filter(inSeedBounds)
      if (seeds.length === 0) {
        seeds = buildStreamlineSeeds(seedBounds, target)
      } else if (seeds.length > target) {
        seeds = seeds.slice(0, target)
      } else if (seeds.length < target) {
        const extras = buildStreamlineSeeds(seedBounds, target - seeds.length)
        seeds = seeds.concat(extras)
      }
    }

    this.grid = nextGrid
    this.seeds = seeds
    this.paths = seeds.map((s) => integrateStreamline(nextGrid, s.lat, s.lon))
    this.lastSeedZoom = this.map.getZoom()
    this.syncLayout(true)
  }

  /** 缩放后按当前视口∩grid 重撒/重积分，避免亮线挤在旧地理范围或摊稀到全球 */
  private reseedPathsForZoom(zoom: number) {
    if (!this.grid) return
    const seedBounds = resolveStreamlineSeedBounds(this.grid, this.readViewportBBox())
    const target = computeStreamlineCountForArea(
      Math.abs(seedBounds.north - seedBounds.south) * Math.abs(seedBounds.east - seedBounds.west),
    )
    this.seeds = buildStreamlineSeeds(seedBounds, target)
    this.paths = this.seeds.map((s) => integrateStreamline(this.grid!, s.lat, s.lon))
    this.lastSeedZoom = zoom
    this.syncLayout(true)
  }

  private readViewportBBox(): WindRoamBounds | null {
    try {
      return computeViewportBBoxFromBounds(this.map.getBounds())
    } catch {
      return null
    }
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
   * @param recalcWrapOffset 仅在网格变化 / zoomend 重撒时为 true，交互中保持稳定。
   */
  private syncLayout(recalcWrapOffset = false) {
    const container = this.map.getContainer()
    const vw = container.clientWidth
    const vh = container.clientHeight
    if (recalcWrapOffset && this.grid) {
      this.lonWrapOffset = computeCanvasLayout(
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
      lonWrapOffset: this.lonWrapOffset,
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
      this.syncLayout(false)
    }
    const ctx = this.ctx
    const w = this.canvas.width
    const h = this.canvas.height
    ctx.clearRect(0, 0, w, h)
    if (zoom < MIN_VISIBLE_ZOOM || !this.grid || this.paths.length === 0) return

    const wraps = streamlineLonWrapOffsets(this.layout.lonWrapOffset)
    const dpr = this.pixelRatio
    const margin = 40 * dpr

    ctx.save()
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    ctx.lineWidth = LINE_WIDTH * dpr

    for (let i = 0; i < this.paths.length; i++) {
      const path = this.paths[i]
      if (path.length < 2) continue
      const seedPhase = this.seeds[i]?.phase ?? 0
      const localPhase = (this.phase + seedPhase) % 1

      for (const wrap of wraps) {
        const pts: Array<{ x: number; y: number; speed: number }> = []
        let anyOnScreen = false
        for (const p of path) {
          const scr = this.map.project([p.lon + wrap, p.lat])
          const x = scr.x * dpr
          const y = scr.y * dpr
          if (x >= -margin && x <= w + margin && y >= -margin && y <= h + margin) {
            anyOnScreen = true
          }
          pts.push({ x, y, speed: p.speed })
        }
        if (!anyOnScreen) continue

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
          const sMid = ((cum[j] + cum[j + 1]) * 0.5) / totalLen
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
    }
    ctx.restore()
  }

  destroy() {
    this.running = false
    this.stopLoop()
    this.map.off(MAP_EVENT_MOVE, this.moveHandler)
    this.map.off(MAP_EVENT_MOVEEND, this.moveEndHandler)
    this.map.off('zoomend', this.moveEndHandler)
    this.map.off(MAP_EVENT_RESIZE, this.resizeHandler)
    document.removeEventListener('visibilitychange', this.visibilityHandler)
    this.canvas.remove()
    this.grid = null
    this.seeds = []
    this.paths = []
  }
}
