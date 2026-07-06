/**
 * 风场粒子流场动画 — Canvas 叠加层（性能优化版）。
 *
 * 核心优化：
 *   1. 粒子存储经纬度（而非像素坐标），缩放/平移时自动跟随地图
 *   2. 用 map.project 代替 map.unproject（project 更快）
 *   3. 按颜色分组批量绘制（减少 beginPath/stroke 调用）
 *   4. 地图交互时暂停动画，结束后恢复
 *   5. DPR 上限 2，避免高 DPI 屏幕画布过大
 */
import type { Map as MaplibreMap } from 'maplibre-gl'

// ── 类型 ────────────────────────────────────────────────

interface WindGridPoint {
  lat: number
  lon: number
  speed: number    // m/s
  direction: number // degrees, meteorological (where wind comes FROM)
}

interface WindGrid {
  rows: number
  cols: number
  south: number
  north: number
  west: number
  east: number
  points: WindGridPoint[][]  // [row][col]
}

export interface WindParticleOptions {
  particleCount?: number
  maxAge?: number       // 粒子最大寿命（帧）
  speedScale?: number   // 速度缩放（经纬度增量/(m/s)）
  fadeAlpha?: number    // 拖尾淡出系数 (0-1)
  lineWidth?: number
  colors?: string[]     // 风速色阶
  colorStops?: number[] // 色阶对应的风速值
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

/** 按风速值在色阶中插值取色，返回色阶索引和插值因子 */
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

/** 气象风向转 UV 分量（粒子移动方向 = 风去向） */
function windToUV(speed: number, directionDeg: number): [number, number] {
  const rad = ((directionDeg + 180) * Math.PI) / 180
  const u = speed * Math.sin(rad)   // 东西分量
  const v = -speed * Math.cos(rad)  // 南北分量（屏幕坐标取反）
  return [u, v]
}

// ── 从 GeoJSON 构建风场网格 ──────────────────────────────

function buildWindGridFromGeoJSON(geojson: WindGeoJSON): WindGrid | null {
  const features = geojson?.features || []
  if (features.length === 0) return null

  let maxRow = 0, maxCol = 0
  let minLat = Infinity, maxLat = -Infinity
  let minLon = Infinity, maxLon = -Infinity
  const pointMap = new Map<string, WindGridPoint>()

  // 从首个 feature 推断高度后缀，支持 10m / 80m / 120m / 180m 等多高度风场
  const firstProps = features[0]?.properties || {}
  const heightSuffix: string = firstProps.height ?? '10m'
  const speedKey = `wind_speed_${heightSuffix}`
  const directionKey = `wind_direction_${heightSuffix}`

  for (const f of features) {
    const coords = f.geometry?.coordinates
    if (!coords || f.geometry?.type !== 'Point') continue
    const lon = coords[0]
    const lat = coords[1]
    const props = f.properties || {}
    const row = props.row ?? 0
    const col = props.col ?? 0
    maxRow = Math.max(maxRow, row)
    maxCol = Math.max(maxCol, col)
    minLat = Math.min(minLat, lat)
    maxLat = Math.max(maxLat, lat)
    minLon = Math.min(minLon, lon)
    maxLon = Math.max(maxLon, lon)
    // 优先读 height 对应字段，回退到 10m 字段保证旧数据兼容
    const speed = props[speedKey] ?? props.wind_speed_10m ?? 0
    const direction = props[directionKey] ?? props.wind_direction_10m ?? 0
    pointMap.set(`${row}:${col}`, { lat, lon, speed, direction })
  }

  const rows = maxRow + 1
  const cols = maxCol + 1
  if (rows < 2 || cols < 2) return null

  const points: WindGridPoint[][] = []
  for (let r = 0; r < rows; r++) {
    points[r] = []
    for (let c = 0; c < cols; c++) {
      points[r][c] = pointMap.get(`${r}:${c}`) || { lat: 0, lon: 0, speed: 0, direction: 0 }
    }
  }

  return { rows, cols, south: minLat, north: maxLat, west: minLon, east: maxLon, points }
}

/** 双线性插值获取网格中任意位置的风速/风向 */
function interpolateWind(grid: WindGrid, lat: number, lon: number): WindGridPoint {
  const { rows, cols, south, north, west, east, points } = grid
  const clampedLat = Math.max(south, Math.min(north, lat))
  const clampedLon = Math.max(west, Math.min(east, lon))
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

// ── 粒子（存储经纬度，自动跟随地图缩放/平移） ──────────────

interface Particle {
  lat: number     // 地理纬度
  lon: number     // 地理经度
  plat: number    // 上一帧像素 x（用于绘制拖尾线段）
  platY: number   // 上一帧像素 y
  age: number     // 当前年龄（帧）
  maxAge: number
}

// ── 主类 ─────────────────────────────────────────────────

export class WindParticleCanvas {
  private map: MaplibreMap
  private canvas: HTMLCanvasElement
  private ctx: CanvasRenderingContext2D
  private grid: WindGrid | null = null
  private particles: Particle[] = []
  private rafId: number | null = null
  private options: Required<WindParticleOptions>
  private resizeObserver: ResizeObserver | null = null
  private moveHandler: (() => void) | null = null
  private movestartHandler: (() => void) | null = null
  private moveendHandler: (() => void) | null = null
  private resizeHandler: (() => void) | null = null
  private isMapInteracting = false
  private dpr = 1
  /** 上一次实际绘制的时间戳（用于帧率节流） */
  private lastDrawTime = 0
  /** 目标帧间隔（ms）：30fps ≈ 33ms，平衡流畅度与合成管线压力 */
  private readonly targetFrameInterval = 33
  /** canvas 相对于地图容器的偏移（像素），用于将全屏坐标转换为 canvas 内坐标 */
  private canvasOffsetX = 0
  private canvasOffsetY = 0
  /** 上一次粒子重建时的 zoom（用于判断缩放后是否需要调整粒子数） */
  private lastParticleZoom = 0

  private static readonly DEFAULT_COLORS = ['#10314b', '#1d6fa5', '#4bb9ff', '#84ddff', '#c4f3ff']
  private static readonly DEFAULT_STOPS = [0, 5, 10, 15, 20]
  /** 预解析的颜色 RGB 数组，避免每帧字符串解析 */
  private colorRgbCache: [number, number, number][] = []

  constructor(map: MaplibreMap, geojson: WindGeoJSON, options?: WindParticleOptions) {
    this.map = map
    this.options = {
      // 默认粒子数 300：在视觉效果与性能之间平衡，
      // 高于 300 在中低端设备上会显著拖慢合成管线
      particleCount: options?.particleCount ?? 300,
      maxAge: options?.maxAge ?? 50,
      speedScale: options?.speedScale ?? 0.00012,
      // fadeAlpha 0.025：拖尾衰减更慢，粒子轨迹更清晰可见
      fadeAlpha: options?.fadeAlpha ?? 0.025,
      // lineWidth 1.6：加粗粒子线段，提高在高清屏上的可见度
      lineWidth: options?.lineWidth ?? 1.6,
      colors: options?.colors ?? WindParticleCanvas.DEFAULT_COLORS,
      colorStops: options?.colorStops ?? WindParticleCanvas.DEFAULT_STOPS,
    }

    // 预解析颜色
    this.colorRgbCache = this.options.colors.map(hexToRgb)

    const container = map.getContainer()
    this.canvas = document.createElement('canvas')
    this.canvas.style.position = 'absolute'
    this.canvas.style.top = '0'
    this.canvas.style.left = '0'
    this.canvas.style.pointerEvents = 'none'
    this.canvas.style.zIndex = '5'
    this.canvas.className = 'wind-particle-canvas'
    container.appendChild(this.canvas)

    // desynchronized: true 让浏览器用独立线程合成 canvas，减少主线程阻塞
    this.ctx = this.canvas.getContext('2d', { desynchronized: true })!

    this.grid = buildWindGridFromGeoJSON(geojson)
    // 先适配 canvas 尺寸到网格投影范围，再初始化粒子
    this.updateCanvasBounds()
    if (this.grid) {
      // 构造时按当前 zoom 选择粒子数（LOD 策略）
      this.options.particleCount = this.resolveParticleCountForZoom(map.getZoom())
      this.lastParticleZoom = map.getZoom()
      this.initParticles()
    }

    // 地图交互时暂停动画 + 清除画布
    this.movestartHandler = () => {
      this.isMapInteracting = true
      // 拖动/缩放时清除拖尾，避免错位
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
    }
    this.moveHandler = () => {
      // 拖动过程中持续清除（粒子位置是经纬度，无需重算，但拖尾会错位）
      if (this.isMapInteracting) {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
      }
    }
    this.moveendHandler = () => {
      this.isMapInteracting = false
      // 重新计算 canvas 尺寸/位置（地图缩放/平移后网格投影范围变化）
      this.updateCanvasBounds()
      // LOD 策略：缩放后根据 zoom 动态调整粒子数
      // zoom 小（远视图）→ 粒子少（避免过密）；zoom 大（近视图）→ 粒子多（填充视口）
      const zoom = this.map.getZoom()
      const targetCount = this.resolveParticleCountForZoom(zoom)
      // 仅当粒子数变化超过 25% 时才重建，避免频繁初始化
      const currentCount = this.particles.length
      if (this.lastParticleZoom === 0 || Math.abs(targetCount - currentCount) / Math.max(currentCount, 1) > 0.25) {
        this.options.particleCount = targetCount
        this.initParticles()
        this.lastParticleZoom = zoom
      } else {
        // 粒子数不变，只重置上一帧像素坐标
        for (const p of this.particles) {
          const screen = this.map.project([p.lon, p.lat])
          p.plat = screen.x
          p.platY = screen.y
        }
      }
    }
    map.on('movestart', this.movestartHandler)
    map.on('move', this.moveHandler)
    map.on('moveend', this.moveendHandler)
    this.resizeHandler = () => this.updateCanvasBounds()
    map.on('resize', this.resizeHandler)

    this.resizeObserver = new ResizeObserver(() => this.updateCanvasBounds())
    this.resizeObserver.observe(container)
  }

  /**
   * 将 canvas 尺寸/位置适配到风场网格投影范围与视口的交集。
   * - 缩放小时：网格投影 < 视口，canvas = 网格范围（节省像素）
   * - 缩放大时：网格投影 > 视口，canvas = 视口范围（避免膨胀）
   */
  private updateCanvasBounds(): void {
    const container = this.map.getContainer()
    const vw = container.clientWidth
    const vh = container.clientHeight

    if (!this.grid) {
      // 无网格数据时退化为全屏
      this.dpr = 1
      this.canvas.width = vw
      this.canvas.height = vh
      this.canvas.style.width = `${vw}px`
      this.canvas.style.height = `${vh}px`
      this.canvas.style.left = '0px'
      this.canvas.style.top = '0px'
      this.canvasOffsetX = 0
      this.canvasOffsetY = 0
      this.ctx.setTransform(1, 0, 0, 1, 0, 0)
      return
    }

    // 投影网格四角到屏幕坐标
    const tl = this.map.project([this.grid.west, this.grid.north])
    const tr = this.map.project([this.grid.east, this.grid.north])
    const bl = this.map.project([this.grid.west, this.grid.south])
    const br = this.map.project([this.grid.east, this.grid.south])

    // 网格投影包围盒（加 margin 给粒子拖尾留空间）
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

    this.dpr = 1
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

  /** 根据 zoom 解析目标粒子数（LOD 策略） */
  private resolveParticleCountForZoom(zoom: number): number {
    // 远视图（zoom < 4）：粒子稀疏，避免视觉过密和性能浪费
    if (zoom < 4) return 150
    // 中视图（zoom 4-7）：标准粒子数
    if (zoom < 7) return 300
    // 近视图（zoom >= 7）：粒子密集，填充视口细节
    return 500
  }

  private initParticles(): void {
    if (!this.grid) return
    const { south, north, west, east } = this.grid
    this.particles = []
    for (let i = 0; i < this.options.particleCount; i++) {
      const lat = south + Math.random() * (north - south)
      const lon = west + Math.random() * (east - west)
      const screen = this.map.project([lon, lat])
      this.particles.push({
        lat,
        lon,
        plat: screen.x,
        platY: screen.y,
        age: Math.floor(Math.random() * this.options.maxAge),
        maxAge: this.options.maxAge + Math.floor(Math.random() * 20),
      })
    }
  }

  private resetParticle(p: Particle): void {
    if (!this.grid) return
    const { south, north, west, east } = this.grid
    p.lat = south + Math.random() * (north - south)
    p.lon = west + Math.random() * (east - west)
    const screen = this.map.project([p.lon, p.lat])
    p.plat = screen.x
    p.platY = screen.y
    p.age = 0
  }

  private animate = (now: number): void => {
    if (!this.grid || this.particles.length === 0) {
      this.rafId = requestAnimationFrame(this.animate)
      return
    }

    // 地图交互中时暂停粒子动画（只清除画布，已在 move 事件中处理）
    if (this.isMapInteracting) {
      this.lastDrawTime = now
      this.rafId = requestAnimationFrame(this.animate)
      return
    }

    // 帧率节流：canvas 2D 纹理上传在高 DPR 屏上较慢，
    // 限制到 ~30fps 避免压垮合成管线，同时给 maplibre 留出渲染空间
    if (this.lastDrawTime > 0 && now - this.lastDrawTime < this.targetFrameInterval) {
      this.rafId = requestAnimationFrame(this.animate)
      return
    }

    // 实际帧间隔（用于 dt 缩放，保持视觉速度与帧率无关）
    const dt = this.lastDrawTime > 0 ? Math.min((now - this.lastDrawTime) / 16.6, 4) : 1
    this.lastDrawTime = now

    // canvas 尺寸（已适配网格投影范围，远小于全屏）
    const cw = this.canvas.width
    const ch = this.canvas.height
    const ox = this.canvasOffsetX
    const oy = this.canvasOffsetY
    const { fadeAlpha, speedScale, lineWidth, colorStops } = this.options
    const colorCount = this.colorRgbCache.length

    // 拖尾淡出：用 destination-out 合成模式擦除部分像素，
    // 保持 canvas 透明（避免黑色背景遮挡底图），同时实现拖尾衰减效果
    this.ctx.globalCompositeOperation = 'destination-out'
    this.ctx.fillStyle = `rgba(0, 0, 0, ${Math.min(fadeAlpha * dt, 0.15)})`
    this.ctx.fillRect(0, 0, cw, ch)
    this.ctx.globalCompositeOperation = 'source-over'

    this.ctx.lineWidth = lineWidth
    this.ctx.lineCap = 'round'

    // 按颜色分组批量绘制：把粒子按色阶索引分组，每组只 stroke 一次
    const buckets: { px: number; py: number; x: number; y: number }[][] = []
    for (let i = 0; i < colorCount - 1; i++) buckets.push([])

    const project = this.map.project.bind(this.map)
    const grid = this.grid
    const scaledSpeed = speedScale * dt

    for (const p of this.particles) {
      // 保存上一帧像素坐标（屏幕坐标系，用于画拖尾线段）
      const prevX = p.plat
      const prevY = p.platY

      // 用经纬度插值风场
      const wind = interpolateWind(grid, p.lat, p.lon)
      const [u, v] = windToUV(wind.speed, wind.direction)

      // 风速 → 经纬度增量（dt 缩放保证不同帧率下视觉速度一致）
      p.lon += u * scaledSpeed
      p.lat += v * scaledSpeed
      p.age += dt

      // 超出网格边界或寿命到期 → 重生
      if (p.age > p.maxAge || p.lat < grid.south || p.lat > grid.north ||
          p.lon < grid.west || p.lon > grid.east) {
        this.resetParticle(p)
        continue
      }

      // 投影到屏幕坐标
      const screen = project([p.lon, p.lat])

      // 视口剔除（基于 canvas 范围，而非全屏）
      if (screen.x < ox - 10 || screen.x > ox + cw + 10 ||
          screen.y < oy - 10 || screen.y > oy + ch + 10) {
        p.plat = screen.x
        p.platY = screen.y
        continue
      }

      // 更新粒子的上一帧坐标为当前帧（供下一帧使用）
      p.plat = screen.x
      p.platY = screen.y

      // 跳过第一帧（没有上一帧位置）
      if (prevX === 0 && prevY === 0) continue

      // 拖尾过长时跳过（地图缩放后可能出现）
      const dx = screen.x - prevX
      const dy = screen.y - prevY
      if (Math.abs(dx) > 50 || Math.abs(dy) > 50) continue

      // 按色阶分组（转换为 canvas 内坐标）
      const { idx } = speedToColorIndex(wind.speed, colorStops)
      if (idx < buckets.length) {
        buckets[idx].push({
          px: prevX - ox,
          py: prevY - oy,
          x: screen.x - ox,
          y: screen.y - oy,
        })
      }
    }

    // 批量绘制：每个颜色桶只 stroke 一次
    for (let i = 0; i < buckets.length; i++) {
      const bucket = buckets[i]
      if (bucket.length === 0) continue

      // 用插值后的颜色（取桶中间色）
      const [r1, g1, b1] = this.colorRgbCache[i]
      const [r2, g2, b2] = this.colorRgbCache[i + 1]
      this.ctx.strokeStyle = `rgb(${(r1 + r2) >> 1},${(g1 + g2) >> 1},${(b1 + b2) >> 1})`

      this.ctx.beginPath()
      for (const seg of bucket) {
        this.ctx.moveTo(seg.px, seg.py)
        this.ctx.lineTo(seg.x, seg.y)
      }
      this.ctx.stroke()
    }

    this.rafId = requestAnimationFrame(this.animate)
  }

  /** 开始动画 */
  start(): void {
    if (this.rafId !== null) return
    this.rafId = requestAnimationFrame(this.animate)
  }

  /** 停止动画 */
  stop(): void {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId)
      this.rafId = null
    }
  }

  /** 更新风场数据（重新加载 GeoJSON） */
  updateGeoJSON(geojson: WindGeoJSON): void {
    this.grid = buildWindGridFromGeoJSON(geojson)
    if (this.grid) {
      this.initParticles()
    }
  }

  /** 销毁：移除 canvas、取消动画、清理事件 */
  destroy(): void {
    this.stop()
    if (this.movestartHandler) {
      this.map.off('movestart', this.movestartHandler)
      this.movestartHandler = null
    }
    if (this.moveHandler) {
      this.map.off('move', this.moveHandler)
      this.moveHandler = null
    }
    if (this.moveendHandler) {
      this.map.off('moveend', this.moveendHandler)
      this.moveendHandler = null
    }
    if (this.resizeHandler) {
      this.map.off('resize', this.resizeHandler)
      this.resizeHandler = null
    }
    if (this.resizeObserver) {
      this.resizeObserver.disconnect()
      this.resizeObserver = null
    }
    if (this.canvas.parentNode) {
      this.canvas.parentNode.removeChild(this.canvas)
    }
  }
}
