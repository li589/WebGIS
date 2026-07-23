/**
 * 通用标量等值线（Canvas 2D + Marching Squares）。
 * 气压等压线：默认 4 hPa 步长；1000/1010/1020 加粗。
 */
import type { Map as MaplibreMap } from 'maplibre-gl'
import { MAP_EVENT_MOVE, MAP_EVENT_MOVEEND, MAP_EVENT_RESIZE } from './types'
import type { WindGeoJSON } from './types'
import { computeCanvasLayout, type CanvasLayout } from './canvas-utils'

interface GridData {
  rows: number
  cols: number
  south: number
  north: number
  west: number
  east: number
  values: number[][]
}

export interface ContourLevelSpec {
  value: number
  color: string
  width: number
  bold?: boolean
}

const QUANT = 1000
const CONTOUR_ZOOM_HIDE = 3
const INTERPOLATION_EPSILON = 0.001
const CULL_MARGIN = 30
const MAX_PIXEL_RATIO = 2

/** 从 legend_ticks 或默认范围生成气压等压线级别 */
export function buildPressureIsobarLevels(
  ticks: Array<number | string> | null | undefined,
): ContourLevelSpec[] {
  const nums = (ticks ?? []).filter((t): t is number => typeof t === 'number' && Number.isFinite(t))
  let min = 996
  let max = 1024
  if (nums.length >= 2) {
    min = Math.floor(Math.min(...nums) / 4) * 4
    max = Math.ceil(Math.max(...nums) / 4) * 4
  }
  const levels: ContourLevelSpec[] = []
  for (let v = min; v <= max; v += 4) {
    const bold = v % 10 === 0
    levels.push({
      value: v,
      color: bold ? 'rgba(255,255,255,0.72)' : 'rgba(220,230,255,0.45)',
      width: bold ? 1.6 : 0.9,
      bold,
    })
  }
  return levels
}

/**
 * 温度/降水等弱等值线：低 alpha、少级数，不抢主色带。
 * step 自动按 tick 跨度估算；无 tick 时用 fallbackRange。
 */
export function buildWeakScalarContourLevels(
  ticks: Array<number | string> | null | undefined,
  options?: {
    fallbackMin?: number
    fallbackMax?: number
    targetCount?: number
    alpha?: number
  },
): ContourLevelSpec[] {
  const nums = (ticks ?? []).filter((t): t is number => typeof t === 'number' && Number.isFinite(t))
  const targetCount = options?.targetCount ?? 6
  const alpha = options?.alpha ?? 0.22
  let min = options?.fallbackMin ?? 0
  let max = options?.fallbackMax ?? 1
  if (nums.length >= 2) {
    min = Math.min(...nums)
    max = Math.max(...nums)
  } else if (nums.length === 1) {
    min = nums[0] - 5
    max = nums[0] + 5
  }
  if (!(max > min)) {
    max = min + 1
  }
  const span = max - min
  const roughStep = span / Math.max(2, targetCount)
  const niceSteps = [0.1, 0.2, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50]
  let step = niceSteps[0]
  for (const s of niceSteps) {
    step = s
    if (s >= roughStep * 0.85) break
  }
  const start = Math.ceil(min / step) * step
  const levels: ContourLevelSpec[] = []
  for (let v = start; v <= max + step * 0.01; v += step) {
    const rounded = Math.round(v * 1000) / 1000
    const bold = levels.length % 2 === 0
    levels.push({
      value: rounded,
      color: bold ? `rgba(255,255,255,${alpha + 0.08})` : `rgba(230,240,255,${alpha})`,
      width: bold ? 0.85 : 0.55,
      bold,
    })
    if (levels.length >= targetCount + 2) break
  }
  return levels
}

export function isWeakContourLayerId(layerId: string | null | undefined): boolean {
  if (!layerId) return false
  return (
    layerId === 'temperature' ||
    layerId.startsWith('temperature-') ||
    layerId === 'precipitation' ||
    layerId.startsWith('precipitation')
  )
}

/** 测试：过滤 zoom LOD（低 zoom 只保留加粗线） */
export function filterContourLevelsForZoom(
  levels: ContourLevelSpec[],
  zoom: number,
): ContourLevelSpec[] {
  if (zoom < CONTOUR_ZOOM_HIDE) return []
  if (zoom < 5) return levels.filter((l) => l.bold)
  if (zoom < 7) return levels.filter((l) => l.bold || l.value % 8 === 0)
  return levels
}

export class ScalarContourLayer {
  private map: MaplibreMap
  private canvas: HTMLCanvasElement
  private ctx: CanvasRenderingContext2D
  private pixelRatio: number
  private layout: CanvasLayout = { width: 0, height: 0, offsetX: 0, offsetY: 0, lonWrapOffset: 0 }
  private gridData: GridData | null = null
  private metric: string
  private levels: ContourLevelSpec[]
  private unitLabel: string
  private moveHandler: () => void
  private resizeHandler: () => void
  private rafId: number | null = null
  private lonWrapOffset = 0

  constructor(
    map: MaplibreMap,
    options: {
      metric: string
      levels: ContourLevelSpec[]
      unitLabel?: string
      opacity?: number
    },
  ) {
    this.map = map
    this.metric = options.metric
    this.levels = options.levels
    this.unitLabel = options.unitLabel ?? ''
    this.pixelRatio = Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO)

    const container = map.getContainer()
    this.canvas = document.createElement('canvas')
    this.canvas.className = 'scalar-contour-canvas'
    this.canvas.style.cssText = `position:absolute;top:0;left:0;pointer-events:none;z-index:5;opacity:${options.opacity ?? 0.42}`
    container.appendChild(this.canvas)
    this.ctx = this.canvas.getContext('2d', { alpha: true })!

    this.moveHandler = () => {
      if (this.rafId !== null) return
      this.rafId = requestAnimationFrame(() => {
        this.rafId = null
        this.updateLayout()
        this.draw()
      })
    }
    this.resizeHandler = () => {
      this.updateLayout()
      this.draw()
    }
    map.on(MAP_EVENT_MOVE, this.moveHandler)
    map.on(MAP_EVENT_MOVEEND, this.moveHandler)
    map.on(MAP_EVENT_RESIZE, this.resizeHandler)
  }

  setData(geojson: WindGeoJSON, options?: { metric?: string; levels?: ContourLevelSpec[] }): void {
    if (options?.metric) this.metric = options.metric
    if (options?.levels) this.levels = options.levels
    this.loadData(geojson)
    this.updateLayout()
    this.draw()
  }

  destroy(): void {
    if (this.rafId !== null) cancelAnimationFrame(this.rafId)
    try {
      this.map.off(MAP_EVENT_MOVE, this.moveHandler)
      this.map.off(MAP_EVENT_MOVEEND, this.moveHandler)
      this.map.off(MAP_EVENT_RESIZE, this.resizeHandler)
    } catch {
      /* ignore */
    }
    this.canvas.remove()
  }

  private updateLayout(): void {
    if (!this.gridData) {
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
    const raw: Array<{ lat: number; lon: number; value: number }> = []
    const latSet = new Set<number>()
    const lonSet = new Set<number>()

    for (const f of features) {
      if (f.geometry?.type !== 'Point') continue
      const coords = f.geometry.coordinates
      const v = Number((f.properties as Record<string, unknown>)?.[this.metric])
      if (!Number.isFinite(v)) continue
      raw.push({ lat: coords[1], lon: coords[0], value: v })
      latSet.add(Math.round(coords[1] * QUANT))
      lonSet.add(Math.round(coords[0] * QUANT))
    }
    if (raw.length === 0) {
      this.gridData = null
      return
    }

    const sortedLats = Array.from(latSet).sort((a, b) => b - a)
    const sortedLons = Array.from(lonSet).sort((a, b) => a - b)
    const rows = sortedLats.length
    const cols = sortedLons.length
    if (rows < 2 || cols < 2) {
      this.gridData = null
      return
    }

    const latIndex = new Map(sortedLats.map((q, i) => [q, i]))
    const lonIndex = new Map(sortedLons.map((q, i) => [q, i]))
    const values: number[][] = []
    const hasData: boolean[][] = []
    for (let r = 0; r < rows; r++) {
      values[r] = new Array(cols).fill(0)
      hasData[r] = new Array(cols).fill(false)
    }
    for (const p of raw) {
      const r = latIndex.get(Math.round(p.lat * QUANT))!
      const c = lonIndex.get(Math.round(p.lon * QUANT))!
      values[r][c] = p.value
      hasData[r][c] = true
    }

    // BFS 最近邻填洞
    const queue: Array<[number, number, number, number]> = []
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        if (hasData[r][c]) queue.push([r, c, r, c])
      }
    }
    let head = 0
    const DIRS: Array<[number, number]> = [
      [-1, 0],
      [1, 0],
      [0, -1],
      [0, 1],
    ]
    while (head < queue.length) {
      const [r, c, sr, sc] = queue[head++]
      for (const [dr, dc] of DIRS) {
        const nr = r + dr
        const nc = c + dc
        if (nr < 0 || nr >= rows || nc < 0 || nc >= cols) continue
        if (hasData[nr][nc]) continue
        hasData[nr][nc] = true
        values[nr][nc] = values[sr][sc]
        queue.push([nr, nc, sr, sc])
      }
    }

    this.gridData = {
      rows,
      cols,
      south: sortedLats[rows - 1] / QUANT,
      north: sortedLats[0] / QUANT,
      west: sortedLons[0] / QUANT,
      east: sortedLons[cols - 1] / QUANT,
      values,
    }
  }

  private gridToLngLat(row: number, col: number): [number, number] {
    if (!this.gridData) return [0, 0]
    const { rows, cols, south, north, west, east } = this.gridData
    const lon = west + (col / (cols - 1)) * (east - west)
    const lat = north - (row / (rows - 1)) * (north - south)
    return [lon, lat]
  }

  private marchingSquares(level: number): [number, number][][] {
    if (!this.gridData) return []
    const { rows, cols, values } = this.gridData
    const segments: [number, number][][] = []
    const interp = (a: number, b: number) => {
      const diff = b - a
      if (Math.abs(diff) < INTERPOLATION_EPSILON) return 0.5
      return (level - a) / diff
    }

    for (let r = 0; r < rows - 1; r++) {
      for (let c = 0; c < cols - 1; c++) {
        const tl = values[r][c]
        const tr = values[r][c + 1]
        const br = values[r + 1][c + 1]
        const bl = values[r + 1][c]
        const code =
          (tl >= level ? 1 : 0) |
          (tr >= level ? 2 : 0) |
          (br >= level ? 4 : 0) |
          (bl >= level ? 8 : 0)
        const top = (): [number, number] => [r, c + interp(tl, tr)]
        const right = (): [number, number] => [r + interp(tr, br), c + 1]
        const bottom = (): [number, number] => [r + 1, c + interp(bl, br)]
        const left = (): [number, number] => [r + interp(tl, bl), c]
        const toLL = (g: [number, number]) => this.gridToLngLat(g[0], g[1])
        switch (code) {
          case 0:
          case 15:
            break
          case 1:
          case 14:
            segments.push([toLL(left()), toLL(top())])
            break
          case 2:
          case 13:
            segments.push([toLL(top()), toLL(right())])
            break
          case 3:
          case 12:
            segments.push([toLL(left()), toLL(right())])
            break
          case 4:
          case 11:
            segments.push([toLL(right()), toLL(bottom())])
            break
          case 5:
            segments.push([toLL(left()), toLL(top())], [toLL(right()), toLL(bottom())])
            break
          case 6:
          case 9:
            segments.push([toLL(top()), toLL(bottom())])
            break
          case 7:
          case 8:
            segments.push([toLL(left()), toLL(bottom())])
            break
          case 10:
            segments.push([toLL(left()), toLL(bottom())], [toLL(top()), toLL(right())])
            break
        }
      }
    }
    return segments
  }

  private draw(): void {
    if (!this.gridData) return
    const dpr = this.pixelRatio
    const ctx = this.ctx
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
    const zoom = this.map.getZoom()
    const active = filterContourLevelsForZoom(this.levels, zoom)
    if (active.length === 0) return

    const { width: cw, height: ch, offsetX: ox, offsetY: oy } = this.layout
    for (const level of active) {
      const segments = this.marchingSquares(level.value)
      ctx.strokeStyle = level.color
      ctx.lineWidth = level.width * dpr
      ctx.lineCap = 'round'
      ctx.lineJoin = 'round'
      for (const seg of segments) {
        const p1 = this.map.project([seg[0][0] + this.lonWrapOffset, seg[0][1]])
        const p2 = this.map.project([seg[1][0] + this.lonWrapOffset, seg[1][1]])
        if (
          (p1.x < ox - CULL_MARGIN && p2.x < ox - CULL_MARGIN) ||
          (p1.x > ox + cw + CULL_MARGIN && p2.x > ox + cw + CULL_MARGIN) ||
          (p1.y < oy - CULL_MARGIN && p2.y < oy - CULL_MARGIN) ||
          (p1.y > oy + ch + CULL_MARGIN && p2.y > oy + ch + CULL_MARGIN)
        )
          continue
        ctx.beginPath()
        ctx.moveTo((p1.x - ox) * dpr, (p1.y - oy) * dpr)
        ctx.lineTo((p2.x - ox) * dpr, (p2.y - oy) * dpr)
        ctx.stroke()
      }

      // 少量标注（加粗线）
      if (level.bold && zoom >= 5 && segments.length > 8) {
        const mid = segments[Math.floor(segments.length / 2)]
        if (mid) {
          const p = this.map.project([mid[0][0] + this.lonWrapOffset, mid[0][1]])
          ctx.fillStyle = 'rgba(255,255,255,0.75)'
          ctx.font = `${10 * dpr}px sans-serif`
          ctx.fillText(
            `${level.value}${this.unitLabel ? ` ${this.unitLabel}` : ''}`,
            (p.x - ox) * dpr,
            (p.y - oy) * dpr,
          )
        }
      }
    }
  }
}
