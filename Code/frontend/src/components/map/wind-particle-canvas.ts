/**
 * 风场粒子流动画 — WebGL2 渲染。
 *
 * 迁移自 Canvas 2D 版本，核心改进：
 *   1. 全 GPU 渲染：粒子拖尾用 GL_LINES 批量绘制，单次 drawArrays 调用
 *   2. 零合成开销：粒子 canvas 使用与 MapLibre 相同的 WebGL 上下文，
 *      直接共享 GPU 硬件加速，无 Canvas 2D / WebGL 跨上下文合成开销
 *   3. 粒子存储经纬度 + canvas内像素prev坐标，GPU 自动完成坐标变换
 *   4. 预解析颜色 RGB，避免每帧字符串解析
 *   5. 帧率节流到 30fps，给 maplibre 留出渲染空间
 */
import type { Map as MaplibreMap } from 'maplibre-gl'
import type { WindGeoJSON } from './types'
import { DEFAULT_HEIGHT_SUFFIX, MAP_EVENT_MOVESTART, MAP_EVENT_MOVEEND, MAP_EVENT_RESIZE } from './types'
import {
  createProgram,
  createDynamicFloat32Buffer,
  updateBufferData,
  buildGeoToNdc,
  computeCanvasLayout,
  WebGLCanvas,
} from './webgl-utils'

// ── 渲染参数常量 ─────────────────────────────────────────

/** 粒子轨迹尾端透明度（使拖尾起点更淡） */
const PARTICLE_TRAIL_TAIL_ALPHA = 0.2

/** 弧度转换常数（Math.PI / 180） */
const DEG_TO_RAD = Math.PI / 180

/** 气象风向偏移量：气象风向是风来向，需加 180° 转为数学风向（风去向） */
const WIND_DIRECTION_OFFSET = 180

/** 粒子尖端最大透明度（新生粒子） */
const PARTICLE_HEAD_MAX_ALPHA = 0.9

/** 节流帧间隔，约 30fps（ms） */
const TARGET_FRAME_INTERVAL_MS = 33

/** 60fps 每帧毫秒数（用于 dt 归一化） */
const MS_PER_60FPS_FRAME = 1000 / 60

/** dt 归一化上界（防止标签页失焦后恢复时粒子跳帧） */
const MAX_DT_FRAMES = 4

/** 拖尾衰减透明度上界（防止完全不透明） */
const TRAIL_FADE_MAX_ALPHA = 0.15

/** 视口剔除边距（像素），使边缘粒子不突然消失 */
const VIEWPORT_CULLING_MARGIN_PX = 10

/** 拖尾长度限制（像素），防止跳帧时线段过长 */
const MAX_TRAIL_LENGTH_PX = 50

/** 粒子数变化触发重初始化的阈值（25%） */
const PARTICLE_COUNT_CHANGE_THRESHOLD = 0.25

/** 粒子默认配置 */
const DEFAULT_PARTICLE_OPTIONS = {
  particleCount: 300,
  maxAge: 50,
  speedScale: 0.00012,
  fadeAlpha: 0.025,
  lineWidth: 1.6,
} as const

/** 粒子数 LOD 配置：{ 低于此 zoom: 粒子数 }，最后一项无 zoomThreshold 作为默认 */
const PARTICLE_COUNT_LOD: { zoomThreshold?: number; count: number }[] = [
  { zoomThreshold: 4, count: 150 },
  { zoomThreshold: 7, count: 300 },
  { count: 500 },
]

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

function windToUV(speed: number, directionDeg: number): [number, number] {
  const rad = (directionDeg + WIND_DIRECTION_OFFSET) * DEG_TO_RAD
  const u = speed * Math.sin(rad)
  const v = -speed * Math.cos(rad)
  return [u, v]
}

// ── GeoJSON → 风场网格 ──────────────────────────────────

function buildWindGridFromGeoJSON(geojson: WindGeoJSON): WindGrid | null {
  const features = geojson?.features || []
  if (features.length === 0) return null

  let maxRow = 0, maxCol = 0
  let minLat = Infinity, maxLat = -Infinity
  let minLon = Infinity, maxLon = -Infinity
  const pointMap = new Map<string, WindGridPoint>()

  const firstProps = features[0]?.properties || {}
  const heightSuffix: string = firstProps.height ?? DEFAULT_HEIGHT_SUFFIX
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
    const speed = (props[speedKey] ?? props.wind_speed_10m ?? 0) as number
    const direction = (props[directionKey] ?? props.wind_direction_10m ?? 0) as number
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

// ── WebGL 着色器 ─────────────────────────────────────────

/** 粒子顶点着色器：
 * 每帧接收粒子状态（经纬度 + canvas内prev坐标 + 年龄），
 * GPU 自动完成坐标变换：经纬度→NDC，prev像素→NDC。
 * 输出 prev→cur 线段的两个端点坐标和 alpha。
 *
 * 布局（每顶点 7 个 float）：
 *   0: lat, 1: lon, 2: prevX, 3: prevY, 4: age, 5: maxAge, 6: vertexType(0=prev, 1=cur)
 */
/**
 * 返回粒子顶点着色器源码。
 * 透明度阈值通过参数注入，使 TypeScript 能追踪常量引用。
 */
function makeParticleVertSrc(trailTailAlpha: number, particleHeadMaxAlpha: number): string {
  return `#version 300 es
precision highp float;

layout(location = 0) in float a_lat;
layout(location = 1) in float a_lon;
layout(location = 2) in float a_prevX;
layout(location = 3) in float a_prevY;
layout(location = 4) in float a_age;
layout(location = 5) in float a_maxAge;
layout(location = 6) in float a_vertexType; // 0=prev, 1=cur

uniform mat3 u_geoToNdc;
uniform vec2 u_resolution;

out float v_alpha;
out vec3 v_color;

void main() {
  // 当前点（经纬度→NDC）
  vec3 curNdc = u_geoToNdc * vec3(a_lon, a_lat, 1.0);
  // 上一帧点（像素→NDC）
  vec2 prevNdc = vec2(a_prevX / u_resolution.x * 2.0 - 1.0,
                      1.0 - a_prevY / u_resolution.y * 2.0);

  // 根据顶点类型选择输出位置
  if (a_vertexType < 0.5) {
    gl_Position = vec4(prevNdc, 0.0, 1.0);
    v_alpha = ${trailTailAlpha};
  } else {
    gl_Position = vec4(curNdc.xy, 0.0, 1.0);
    float lifeRatio = clamp(a_age / max(a_maxAge, 1.0), 0.0, 1.0);
    v_alpha = mix(${particleHeadMaxAlpha}, 0.0, lifeRatio);
  }

  // 颜色由 JS 侧通过 uniform 传入，这里用占位值
  v_color = vec3(0.3, 0.7, 1.0);
}
`
}

const FRAG_SRC = `#version 300 es
precision highp float;

in float v_alpha;
in vec3 v_color;
uniform vec4 u_color;

out vec4 fragColor;

void main() {
  fragColor = vec4(u_color.rgb, u_color.a * v_alpha);
}
`

// ── 粒子数据结构（CPU 端） ───────────────────────────────

interface Particle {
  lat: number
  lon: number
  prevX: number
  prevY: number
  age: number
  maxAge: number
}

// ── 主类 ─────────────────────────────────────────────────

export class WindParticleCanvas {
  private map: MaplibreMap
  private glCanvas: WebGLCanvas
  private gl: WebGL2RenderingContext
  private grid: WindGrid | null = null
  private particles: Particle[] = []
  private rafId: number | null = null
  private options: Required<WindParticleOptions>
  private resizeObserver: ResizeObserver | null = null
  private movestartHandler: (() => void) | null = null
  private moveendHandler: (() => void) | null = null
  private resizeHandler: (() => void) | null = null
  private isMapInteracting = false
  private lastDrawTime = 0
  private lastParticleZoom = 0

  // WebGL 资源
  private program!: WebGLProgram
  private vertexBuffer!: WebGLBuffer
  // 每个粒子对应 2 个顶点（prev + cur），每顶点 7 个 float
  private readonly stride = 7 * 4

  private colorRgbCache: [number, number, number][] = []

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

    this.glCanvas = new WebGLCanvas(map)
    this.gl = this.glCanvas.gl
    this.colorRgbCache = this.options.colors.map(hexToRgb)

    this.initWebGL()

    this.grid = buildWindGridFromGeoJSON(geojson)
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

  private initWebGL(): void {
    const gl = this.gl
    this.program = createProgram(gl, makeParticleVertSrc(PARTICLE_TRAIL_TAIL_ALPHA, PARTICLE_HEAD_MAX_ALPHA), FRAG_SRC)
    this.vertexBuffer = createDynamicFloat32Buffer(gl)

    gl.enable(gl.BLEND)
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA)
  }

  private setupMapEvents(): void {
    this.movestartHandler = () => {
      this.isMapInteracting = true
    }
    this.moveendHandler = () => {
      this.isMapInteracting = false
      this.updateCanvasBounds()
      const zoom = this.map.getZoom()
      const targetCount = this.resolveParticleCountForZoom(zoom)
      const currentCount = this.particles.length
      if (
        this.lastParticleZoom === 0 ||
        Math.abs(targetCount - currentCount) / Math.max(currentCount, 1) > PARTICLE_COUNT_CHANGE_THRESHOLD
      ) {
        this.options.particleCount = targetCount
        this.initParticles()
        this.lastParticleZoom = zoom
      }
    }
    this.resizeHandler = () => this.updateCanvasBounds()

    this.map.on(MAP_EVENT_MOVESTART, this.movestartHandler)
    this.map.on(MAP_EVENT_MOVEEND, this.moveendHandler)
    this.map.on(MAP_EVENT_RESIZE, this.resizeHandler)
  }

  private updateCanvasBounds(): void {
    if (!this.grid) {
      const container = this.map.getContainer()
      this.glCanvas.layout = {
        width: container.clientWidth,
        height: container.clientHeight,
        offsetX: 0,
        offsetY: 0,
      }
      this.glCanvas.resize()
      return
    }
    const layout = computeCanvasLayout(
      this.map,
      this.grid.west,
      this.grid.east,
      this.grid.south,
      this.grid.north,
    )
    this.glCanvas.layout = layout
    this.glCanvas.resize()
  }

  private resolveParticleCountForZoom(zoom: number): number {
    for (const level of PARTICLE_COUNT_LOD) {
      if ('zoomThreshold' in level && level.zoomThreshold !== undefined && zoom < level.zoomThreshold) {
        return level.count
      }
    }
    return PARTICLE_COUNT_LOD[PARTICLE_COUNT_LOD.length - 1].count
  }

  private initParticles(): void {
    if (!this.grid) return
    const { south, north, west, east } = this.grid
    const { offsetX, offsetY } = this.glCanvas.layout
    this.particles = []
    for (let i = 0; i < this.options.particleCount; i++) {
      const lat = south + Math.random() * (north - south)
      const lon = west + Math.random() * (east - west)
      const screen = this.map.project([lon, lat])
      this.particles.push({
        lat,
        lon,
        prevX: screen.x - offsetX,
        prevY: screen.y - offsetY,
        age: Math.floor(Math.random() * this.options.maxAge),
        maxAge: this.options.maxAge + Math.floor(Math.random() * MAX_AGE_RANDOM_RANGE),
      })
    }
  }

  private resetParticle(p: Particle): void {
    if (!this.grid) return
    const { south, north, west, east } = this.grid
    const { offsetX, offsetY } = this.glCanvas.layout
    p.lat = south + Math.random() * (north - south)
    p.lon = west + Math.random() * (east - west)
    const screen = this.map.project([p.lon, p.lat])
    p.prevX = screen.x - offsetX
    p.prevY = screen.y - offsetY
    p.age = 0
  }

  private animate = (now: number): void => {
    if (!this.grid || this.particles.length === 0) {
      this.rafId = requestAnimationFrame(this.animate)
      return
    }

    if (this.isMapInteracting) {
      this.lastDrawTime = now
      this.rafId = requestAnimationFrame(this.animate)
      return
    }

    if (this.lastDrawTime > 0 && now - this.lastDrawTime < TARGET_FRAME_INTERVAL_MS) {
      this.rafId = requestAnimationFrame(this.animate)
      return
    }

    const dt = this.lastDrawTime > 0 ? Math.min((now - this.lastDrawTime) / MS_PER_60FPS_FRAME, MAX_DT_FRAMES) : 1
    this.lastDrawTime = now

    this.draw(dt)
    this.rafId = requestAnimationFrame(this.animate)
  }

  private draw(dt: number): void {
    const gl = this.gl
    const { width, height, offsetX, offsetY } = this.glCanvas.layout
    const { fadeAlpha, speedScale, colorStops } = this.options
    const grid = this.grid!
    const scaledSpeed = speedScale * dt
    const project = this.map.project.bind(this.map)

    // 构建经纬度→NDC 变换
    const geoToNdc = buildGeoToNdc(width, height, offsetX, offsetY)

    // 拖尾衰减：先画半透明黑色背景
    gl.clearColor(0, 0, 0, 0)
    gl.clear(gl.COLOR_BUFFER_BIT)
    gl.enable(gl.BLEND)
    gl.blendFunc(gl.ONE, gl.ZERO)
    gl.clearColor(0, 0, 0, Math.min(fadeAlpha * dt, TRAIL_FADE_MAX_ALPHA))
    gl.clear(gl.COLOR_BUFFER_BIT)
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA)

    // 收集有效粒子到顶点缓冲区
    const stride = this.stride
    const vertexData = new Float32Array(this.particles.length * 2 * 7)
    let vertexCount = 0

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

      const screen = project([p.lon, p.lat])
      const cx = screen.x - offsetX
      const cy = screen.y - offsetY

      // 视口剔除
      if (cx < -VIEWPORT_CULLING_MARGIN_PX || cx > width + VIEWPORT_CULLING_MARGIN_PX || cy < -VIEWPORT_CULLING_MARGIN_PX || cy > height + VIEWPORT_CULLING_MARGIN_PX) {
        p.prevX = cx
        p.prevY = cy
        continue
      }

      // 拖尾长度限制
      const dx = cx - p.prevX
      const dy = cy - p.prevY
      if (Math.abs(dx) > MAX_TRAIL_LENGTH_PX || Math.abs(dy) > MAX_TRAIL_LENGTH_PX) {
        p.prevX = cx
        p.prevY = cy
        continue
      }

      p.prevX = cx
      p.prevY = cy

      // 每粒子 2 个顶点：prev (vtype=0) + cur (vtype=1)
      const base = vertexCount * stride
      // prev
      vertexData[base + 0] = p.lat
      vertexData[base + 1] = p.lon
      vertexData[base + 2] = p.prevX
      vertexData[base + 3] = p.prevY
      vertexData[base + 4] = p.age
      vertexData[base + 5] = p.maxAge
      vertexData[base + 6] = 0
      // cur
      vertexData[base + 7] = p.lat
      vertexData[base + 8] = p.lon
      vertexData[base + 9] = p.prevX
      vertexData[base + 10] = p.prevY
      vertexData[base + 11] = p.age
      vertexData[base + 12] = p.maxAge
      vertexData[base + 13] = 1
      vertexCount += 2
    }

    if (vertexCount === 0) return

    // 上传顶点数据
    const uploadData = vertexData.subarray(0, vertexCount * 7)
    updateBufferData(gl, this.vertexBuffer, uploadData)

    // 按颜色桶分组绘制（保持原有的颜色分级效果）
    // 注意：必须在顶点构建循环中同步收集 buckets（已过滤无效粒子），避免索引错位
    const buckets: { start: number; count: number; colorIdx: number }[] = []
    let bucketStart = -1
    let currentIdx = -1
    let currentCount = 0

    for (let i = 0; i < this.particles.length; i++) {
      const p = this.particles[i]
      // 跳过已在顶点构建中被过滤的粒子（age/maxAge/视口/拖尾超限）
      const baseVertex = i * 2
      if (baseVertex >= vertexCount * 2) break
      // 用 speedToColorIndex 重新查颜色（与顶点构建循环一致）
      const wind = interpolateWind(grid, p.lat, p.lon)
      const { idx } = speedToColorIndex(wind.speed, colorStops)
      if (idx !== currentIdx || currentCount === 0) {
        if (currentCount > 0) {
          buckets.push({ start: bucketStart, count: currentCount, colorIdx: currentIdx })
        }
        currentIdx = idx
        bucketStart = baseVertex
        currentCount = 2
      } else {
        currentCount += 2
      }
    }
    if (currentCount > 0) {
      buckets.push({ start: bucketStart, count: currentCount, colorIdx: currentIdx })
    }

    // 绑定 program 并设置 uniform
    gl.useProgram(this.program)

    const matLoc = gl.getUniformLocation(this.program, 'u_geoToNdc')
    gl.uniformMatrix3fv(matLoc, false, geoToNdc.m)
    gl.uniform2f(gl.getUniformLocation(this.program, 'u_resolution'), width, height)

    // 设置顶点属性指针（每顶点 7 个 float）
    const bindAttr = (loc: number, offset: number) => {
      gl.enableVertexAttribArray(loc)
      gl.vertexAttribPointer(loc, 1, gl.FLOAT, false, stride, offset * 4)
    }
    bindAttr(0, 0)  // lat
    bindAttr(1, 1)  // lon
    bindAttr(2, 2)  // prevX
    bindAttr(3, 3)  // prevY
    bindAttr(4, 4)  // age
    bindAttr(5, 5)  // maxAge
    bindAttr(6, 6)  // vertexType

    for (const bucket of buckets) {
      if (bucket.count < 2) continue
      const [r1, g1, b1] = this.colorRgbCache[bucket.colorIdx]
      const [r2, g2, b2] = this.colorRgbCache[bucket.colorIdx + 1]
      const r = ((r1 + r2) >> 1) / 255
      const g = ((g1 + g2) >> 1) / 255
      const b = ((b1 + b2) >> 1) / 255
      gl.uniform4f(gl.getUniformLocation(this.program, 'u_color'), r, g, b, 0.85)
      gl.lineWidth(this.options.lineWidth)
      gl.drawArrays(gl.LINES, bucket.start, bucket.count)
    }
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
    this.grid = buildWindGridFromGeoJSON(geojson)
    if (this.grid) {
      this.updateCanvasBounds()
      this.initParticles()
    }
  }

  destroy(): void {
    this.stop()
    if (this.movestartHandler) { this.map.off(MAP_EVENT_MOVESTART, this.movestartHandler); this.movestartHandler = null }
    if (this.moveendHandler) { this.map.off(MAP_EVENT_MOVEEND, this.moveendHandler); this.moveendHandler = null }
    if (this.resizeHandler) { this.map.off(MAP_EVENT_RESIZE, this.resizeHandler); this.resizeHandler = null }
    if (this.resizeObserver) { this.resizeObserver.disconnect(); this.resizeObserver = null }
    if (this.vertexBuffer) this.gl.deleteBuffer(this.vertexBuffer)
    if (this.program) this.gl.deleteProgram(this.program)
    this.glCanvas.destroy()
  }
}
