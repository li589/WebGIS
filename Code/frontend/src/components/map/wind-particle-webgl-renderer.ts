/**
 * 风场粒子 WebGL 渲染层 — MapLibre CustomLayerInterface 实现。
 *
 * 架构（对照 Example/Windy.app WindMap.js）：
 *   - 以 `type: 'custom'` 注册到 MapLibre，但**不在 MapLibre 的 GL context 里绘制**；
 *     render() 仅缓存投影矩阵（modelViewProjectionMatrix）。
 *   - 创建**独立的 overlay canvas + 独立 WebGL context**，用自有 RAF 循环绘制。
 *   - 独立 canvas 挂在 map.getContainer() 上（与 Canvas 粒子路径一致），
 *     z-index 高于地图 canvas，叠在风速色底之上。
 *
 * 粒子模拟（B3，GPGPU ping-pong）：
 *   - 每个粒子 = 位置纹理中的一个纹素（RGBA8，16-bit 分割精度存 lon/lat）。
 *   - 更新 pass：fragment shader 读当前位置纹理、采样风场纹理、RK2 平流，
 *     写新位置到 ping-pong 另一张纹理。
 *   - 绘制 pass：readPixels 取位置 → CPU 投影到裁剪空间 → GL_POINTS
 *     （避开顶点着色器纹理采样/VTF；部分驱动上 VTF 会静默失败导致粒子全在视口外）。
 *
 * 渲染阶段：
 *   - B2：风场纹理颜色场 quad（粒子系统未就绪时的回退）。
 *   - B3：粒子平流（主路径，含 B4 拖尾衰减）。
 *   - 无风场数据时不绘制任何占位内容（避免生产环境出现调试视觉）。
 */
import type { CustomRenderMethodInput, Map as MaplibreMap } from 'maplibre-gl'
import type { WindGeoJSON } from './types'
import {
  WIND_FIELD_FRAGMENT_SHADER,
  WIND_FIELD_VERTEX_SHADER,
  PARTICLE_UPDATE_VERTEX_SHADER,
  PARTICLE_UPDATE_FRAGMENT_SHADER,
  PARTICLE_DRAW_CLIP_VERTEX_SHADER,
  PARTICLE_DRAW_SOFT_FRAGMENT_SHADER,
  TRAIL_FADE_FRAGMENT_SHADER,
  TRAIL_SCREEN_FRAGMENT_SHADER,
  lngLatToMercatorNormalized,
} from './wind-particle-webgl-shaders'
import { buildWindGridFromGeoJSON } from './wind-grid'
import {
  buildPaletteLUT,
  encodeWindGridToRGBA,
  WIND_TEXTURE_MAX_WIND,
  type EncodedWindTexture,
} from './wind-particle-webgl-texture'
import { resolveParticleResolution } from './wind-particle-gl-profile'
import { isPerfEnabled, perfMark } from '../../utils/perf-probe'

/** MapLibre resize 事件名 */
const MAP_EVENT_RESIZE = 'resize'

/** B2 风场颜色场默认不透明度 */
const FIELD_OPACITY = 0.75

// ── 粒子模拟参数（对照 Example/Windy.app WindMap.js，商业密度加码）─────────────
/** 平流速度：与点径匹配，略高于 0.02 以免拖尾断丝 */
const DEFAULT_SPEED_SCALE = 0.022
/** 点大小（设备像素）；略大于 Windy 3.0，帧间更易连成丝 */
const PARTICLE_POINT_SIZE = 4.0
/** 近白半透明，略提高 alpha 增强可见度 */
const PARTICLE_COLOR: [number, number, number, number] = [1.0, 1.0, 1.0, 0.92]
/** 60fps 每帧毫秒数（dt 归一化） */
const MS_PER_60FPS_FRAME = 1000 / 60
/** idle 目标 ~30fps */
const MS_PER_30FPS_FRAME = 1000 / 30
/** dt 归一化上界（防标签页失焦后跳帧） */
const MAX_DT_FRAMES = 4
/** moveend 后进入 idle 降帧的等待 */
const IDLE_AFTER_MOVE_MS = 1500
/**
 * 拖尾每帧保留比例（Windy 0.96；略提高使丝更长更连续）。
 * 帧率无关：每帧乘 Math.pow(TRAIL_FADE, dt)。
 */
const TRAIL_FADE = 0.975
/** 连续若干帧拿不到投影矩阵则标记失败，供 controller 回退 Canvas */
const MATRIX_MISS_FAIL_AFTER = 90

/** 编译单个 shader，失败时输出日志并返回 null（不抛异常，便于降级）。 */
function compileShader(
  gl: WebGLRenderingContext,
  type: number,
  source: string,
): WebGLShader | null {
  const shader = gl.createShader(type)
  if (!shader) return null
  gl.shaderSource(shader, source)
  gl.compileShader(shader)
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    console.error('[WindParticleWebGL] shader compile failed:', gl.getShaderInfoLog(shader))
    gl.deleteShader(shader)
    return null
  }
  return shader
}

/** 链接 vertex + fragment 为 program，失败返回 null。 */
function linkProgram(
  gl: WebGLRenderingContext,
  vertexSource: string,
  fragmentSource: string,
): WebGLProgram | null {
  const vs = compileShader(gl, gl.VERTEX_SHADER, vertexSource)
  const fs = compileShader(gl, gl.FRAGMENT_SHADER, fragmentSource)
  if (!vs || !fs) {
    if (vs) gl.deleteShader(vs)
    if (fs) gl.deleteShader(fs)
    return null
  }
  const program = gl.createProgram()
  if (!program) {
    gl.deleteShader(vs)
    gl.deleteShader(fs)
    return null
  }
  gl.attachShader(program, vs)
  gl.attachShader(program, fs)
  gl.linkProgram(program)
  // 链接成功后 detach 并释放 shader 对象，减少 GPU 内存占用
  gl.detachShader(program, vs)
  gl.detachShader(program, fs)
  gl.deleteShader(vs)
  gl.deleteShader(fs)
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    console.error('[WindParticleWebGL] program link failed:', gl.getProgramInfoLog(program))
    gl.deleteProgram(program)
    return null
  }
  return program
}

/** 与 GLSL encodeFloat 等价的 JS 单坐标编码（hi, lo 两个字节）。 */
function encodeFloatByte(v: number): [number, number] {
  const scaled = Math.max(0, Math.min(1, v)) * 255
  const hi = Math.floor(scaled)
  const lo = Math.floor((scaled - hi) * 255)
  return [hi, lo]
}

/** 与 GLSL encodePosition 等价：归一化 (nx, ny) → [R, G, B, A] 四字节。 */
export function encodePositionBytes(nx: number, ny: number): [number, number, number, number] {
  const ex = encodeFloatByte(nx)
  const ey = encodeFloatByte(ny)
  return [ex[0], ex[1], ey[0], ey[1]]
}

/** 与 GLSL decodePosition 等价：从 RGBA8 字节还原归一化 (nx, ny)（供单测验证往返）。 */
export function decodePositionBytes(r: number, g: number, b: number, a: number): [number, number] {
  const nx = r / 255 + g / (255 * 255)
  const ny = b / 255 + a / (255 * 255)
  return [nx, ny]
}

/** 从编码风场纹理最近邻取风速归一化 k∈[0,1]（供 CPU 绘制着色）。 */
export function sampleEncodedWindSpeedK(
  encoded: EncodedWindTexture,
  lon: number,
  lat: number,
): number {
  const { width, height, data, west, south, east, north } = encoded
  if (width <= 0 || height <= 0 || east === west || north === south) return 0
  const u = (lon - west) / (east - west)
  const v = (north - lat) / (north - south)
  if (u < 0 || u > 1 || v < 0 || v > 1) return 0
  const c = Math.min(width - 1, Math.max(0, Math.floor(u * width)))
  const r = Math.min(height - 1, Math.max(0, Math.floor(v * height)))
  return data[(r * width + c) * 4 + 2] / 255
}

/** 单帧最多绘制的世界副本数（防御病态矩阵；正常视野 ≤5） */
const MAX_WORLD_WRAP_DRAWS = 12

/**
 * 反子午线世界包裹偏移：计算屏幕 [-1,1] 实际可见的所有世界副本。
 *
 * matrix[0] 是一个世界宽度在裁剪空间（宽 2.0）中的尺寸，matrix[12] 是主世界
 * 的 x 平移。副本 k 的 clip 范围为 [tx + k·w, tx + (k+1)·w]，与屏幕相交即需绘制。
 * 即使 matrix[0] ≥ 2（单世界比屏幕宽），相机贴近反子午线时屏幕仍会露出相邻
 * 副本（跨幅临界），旧的「±1 启发式」会漏掉 → 表现为半球/半边区域无场。
 * 返回应用于 matrix[12]（x 平移）的偏移数组，恒含 0。抽离为纯函数以便单测。
 */
export function computeWorldWrapOffsets(matrix: ArrayLike<number>): number[] {
  const w = matrix[0]
  const tx = matrix[12]
  if (!Number.isFinite(w) || !Number.isFinite(tx) || w <= 0) return [0]
  // 最小 k：副本右缘 tx+(k+1)·w > -1；最大 k：副本左缘 tx+k·w < 1
  // （+0 把 Math.ceil 可能产生的 -0 归一化，避免偏移数组出现 -0）
  const kMin = Math.ceil((-1 - tx) / w - 1 + 1e-9) + 0
  const kMax = Math.ceil((1 - tx) / w - 1e-9) - 1 + 0
  if (kMax < kMin) return [0]
  const offsets: number[] = []
  const lo = Math.max(kMin, -MAX_WORLD_WRAP_DRAWS)
  const hi = Math.min(kMax, MAX_WORLD_WRAP_DRAWS)
  for (let k = lo; k <= hi; k += 1) offsets.push(k * w)
  return offsets.includes(0) ? offsets : [0]
}

/**
 * 从 MapLibre 5 CustomRenderMethodInput 取出「mercator [0,1]² → clip」矩阵。
 * 优先 `defaultProjectionData.mainMatrix`（官方 custom layer 示例）。
 *
 * 注意：`modelViewProjectionMatrix` 是像素世界坐标矩阵，与 `lngLatToMercatorNormalized`
 * 不兼容，会导致粒子投影到屏外。此处不再回退到它；调用方应通过 `refreshProjectionMatrix`
 * （走 `transform.getProjectionDataForCustomLayer`）获取矩阵。
 */
export function extractMercatorProjectionMatrix(
  options: CustomRenderMethodInput | ArrayLike<number> | null | undefined,
): ArrayLike<number> | null {
  if (!options) return null
  // 旧版签名：第二参直接是 Float32Array 矩阵
  if (
    typeof (options as ArrayLike<number>)[0] === 'number' &&
    (options as ArrayLike<number>).length >= 16
  ) {
    return options as ArrayLike<number>
  }
  const opts = options as CustomRenderMethodInput & {
    defaultProjectionData?: { mainMatrix?: ArrayLike<number>; projectionMatrix?: ArrayLike<number> }
  }
  const fromDefault =
    opts.defaultProjectionData?.mainMatrix ?? opts.defaultProjectionData?.projectionMatrix
  if (fromDefault && typeof fromDefault[0] === 'number') return fromDefault
  // 不再回退到 modelViewProjectionMatrix：该矩阵与 lngLatToMercator 不兼容，
  // 会导致粒子投影到屏外（只剩色底可见）。返回 null 让上层走 matrixMissFrames 失败检测。
  return null
}

export class WindParticleWebGLLayer {
  readonly id: string
  readonly type = 'custom' as const
  readonly renderingMode = '2d' as const

  private map: MaplibreMap | null = null
  private canvas: HTMLCanvasElement | null = null
  private gl: WebGLRenderingContext | null = null

  // B2 风场颜色场程序
  private fieldProgram: WebGLProgram | null = null
  private fieldAttribLngLat = -1
  private fieldUniformMatrix: WebGLUniformLocation | null = null
  private fieldUniformWindTexture: WebGLUniformLocation | null = null
  private fieldUniformWindBounds: WebGLUniformLocation | null = null
  private fieldUniformMaxWind: WebGLUniformLocation | null = null
  private fieldUniformOpacity: WebGLUniformLocation | null = null
  private fieldQuadBuffer: WebGLBuffer | null = null
  private windTexture: WebGLTexture | null = null

  // B3 粒子系统
  private updateProgram: WebGLProgram | null = null
  private updateAttribPos = -1
  private updateUniformParticleTexture: WebGLUniformLocation | null = null
  private updateUniformWindTexture: WebGLUniformLocation | null = null
  private updateUniformWindBounds: WebGLUniformLocation | null = null
  private updateUniformMaxWind: WebGLUniformLocation | null = null
  private updateUniformScaledSpeed: WebGLUniformLocation | null = null
  private updateUniformDt: WebGLUniformLocation | null = null
  private updateUniformFrameSeed: WebGLUniformLocation | null = null
  private updateUniformResetAll: WebGLUniformLocation | null = null
  private updateUniformPrevWindBounds: WebGLUniformLocation | null = null
  private updateUniformRemap: WebGLUniformLocation | null = null

  private drawProgram: WebGLProgram | null = null
  private drawAttribClipSpeed = -1
  private drawUniformPointSize: WebGLUniformLocation | null = null
  private drawUniformColor: WebGLUniformLocation | null = null

  private particleTextures: WebGLTexture[] = []
  private particleFBO: WebGLFramebuffer | null = null
  private currentParticleIndex = 0
  private particleVertexBuffer: WebGLBuffer | null = null
  /** 位置纹理边长（全量 72 / 核显 lite 48） */
  private readonly particleResolution: number
  /** readPixels 缓冲：RGBA8 位置纹理 */
  private readonly particlePosPixels: Uint8Array
  /** 当前帧各粒子 NDC（x,y,_）；Windy 风格只画点，靠 trail 连成丝 */
  private readonly particleClipData: Float32Array
  private particleDrawCount = 0
  private fullscreenQuadBuffer: WebGLBuffer | null = null
  private particleCount: number
  private particleSystemReady = false
  private particleResetAll = true
  private frameSeed = 0
  /** 最近一次上传的风场编码 */
  private lastEncodedWind: EncodedWindTexture | null = null
  private matrixMissFrames = 0
  private matrixReadyLogged = false

  // B4 拖尾系统（ping-pong trail FBO，尺寸 = canvas 设备像素）
  private fadeProgram: WebGLProgram | null = null
  private fadeAttribPos = -1
  private fadeUniformTexture: WebGLUniformLocation | null = null
  private fadeUniformFade: WebGLUniformLocation | null = null
  private screenProgram: WebGLProgram | null = null
  private screenAttribPos = -1
  private screenUniformTexture: WebGLUniformLocation | null = null
  private screenUniformOpacity: WebGLUniformLocation | null = null
  private trailTextures: WebGLTexture[] = []
  private trailFBO: WebGLFramebuffer | null = null
  private currentTrailIndex = 0
  private trailWidth = 0
  private trailHeight = 0
  private trailDirty = true

  /** 缓存的 modelViewProjectionMatrix（16 元素列主序），render() 时更新 */
  private matrix = new Float32Array(16)
  private hasMatrix = false
  private readonly lastDrawnMatrix = new Float32Array(16)
  private hasLastDrawnMatrix = false
  /** 世界包裹绘制时的临时矩阵（避免每帧分配） */
  private readonly tempMatrix = new Float32Array(16)

  private rafId: number | null = null
  private lastFrameTime = 0
  private mapMoving = false
  private lastMoveEndAt = 0
  private frameCounter = 0
  private visibilityHandler: (() => void) | null = null
  private moveStartHandler: (() => void) | null = null
  private moveEndHandler: (() => void) | null = null
  private zoomEndHandler: (() => void) | null = null
  /** onAdd / shader / VTF 失败时为 true；controller 可回退 Canvas */
  private initFailed = false
  private initFailReason: string | null = null
  private readonly frame = () => {
    this.rafId = requestAnimationFrame(this.frame)
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
      return
    }
    const now = performance.now()
    const idle =
      !this.mapMoving && this.lastMoveEndAt > 0 && now - this.lastMoveEndAt >= IDLE_AFTER_MOVE_MS
    const minFrameMs = idle ? MS_PER_30FPS_FRAME : MS_PER_60FPS_FRAME
    if (this.lastFrameTime > 0 && now - this.lastFrameTime < minFrameMs - 1) {
      return
    }
    const dt =
      this.lastFrameTime > 0
        ? Math.min((now - this.lastFrameTime) / MS_PER_60FPS_FRAME, MAX_DT_FRAMES)
        : 1
    this.lastFrameTime = now
    this.frameCounter += 1
    if (isPerfEnabled() && this.frameCounter % 30 === 0) {
      perfMark('wind.rafDt', { dt, idle, res: this.particleResolution })
    }
    this.drawFrame(dt)
    const matrixChanged = this.matrixNeedsRepaint()
    // 仅在矩阵变化或交互中请求 MapLibre repaint（transform API 可在无 repaint 时取矩阵）
    if (this.mapMoving || matrixChanged) {
      try {
        this.map?.triggerRepaint()
      } catch {
        /* map may be destroyed */
      }
    }
  }

  private resizeHandler: (() => void) | null = null

  private matrixNeedsRepaint(): boolean {
    if (!this.hasMatrix) return true
    if (!this.hasLastDrawnMatrix) {
      this.lastDrawnMatrix.set(this.matrix)
      this.hasLastDrawnMatrix = true
      return true
    }
    for (let i = 0; i < 16; i++) {
      if (Math.abs(this.matrix[i] - this.lastDrawnMatrix[i]) > 1e-7) {
        this.lastDrawnMatrix.set(this.matrix)
        return true
      }
    }
    return false
  }

  /** 层是否仍可作为 WebGL 粒子路径（未在 onAdd 中失败）。 */
  isUsable(): boolean {
    return !this.initFailed
  }

  getFailureReason(): string | null {
    return this.initFailReason
  }

  /** 风场纹理待上传标记与数据（setWindData 在 GL 就绪前可能被调用） */
  private pendingWindTexture: EncodedWindTexture | null = null
  private windBounds: { west: number; south: number; east: number; north: number } | null = null
  /** bbox 变化前的旧 bounds（remap 帧用；null 表示无历史） */
  private prevWindBounds: { west: number; south: number; east: number; north: number } | null = null
  /** 下一更新帧仅做归一化坐标重映射（不平流），保持轨迹/拖尾稳定 */
  private pendingRemap = false
  private hasWindData = false
  /** B5 调色板纹理（256×1 RGBA LUT）与待上传标记 */
  private paletteTexture: WebGLTexture | null = null
  private paletteDirty = false
  private paletteLUT: Uint8Array | null = null
  private particleColors: string[] = []

  constructor(id = 'wind-particle-webgl') {
    this.id = id
    this.particleResolution = resolveParticleResolution()
    this.particleCount = this.particleResolution * this.particleResolution
    this.particlePosPixels = new Uint8Array(this.particleCount * 4)
    this.particleClipData = new Float32Array(this.particleCount * 3)
  }

  // ── CustomLayerInterface 回调 ─────────────────────────────────────

  onAdd(map: MaplibreMap, _gl: WebGLRenderingContext): void {
    this.map = map
    this.initFailed = false
    this.initFailReason = null

    // 独立 overlay canvas（与 Canvas 粒子路径一致：挂在 map container 上）
    const canvas = document.createElement('canvas')
    canvas.className = 'wind-particle-webgl-canvas'
    canvas.style.position = 'absolute'
    canvas.style.top = '0'
    canvas.style.left = '0'
    canvas.style.width = '100%'
    canvas.style.height = '100%'
    canvas.style.pointerEvents = 'none'
    canvas.style.zIndex = '5'
    map.getContainer().appendChild(canvas)
    this.canvas = canvas

    const glAttrs = {
      alpha: true,
      antialias: false,
      preserveDrawingBuffer: false,
      premultipliedAlpha: false,
    } as const
    // 优先 WebGL2（FBO/readPixels 更稳）；再回退 WebGL1
    const gl = (canvas.getContext('webgl2', glAttrs) ||
      canvas.getContext('webgl', glAttrs) ||
      canvas.getContext('experimental-webgl', glAttrs)) as WebGLRenderingContext | null
    if (!gl) {
      this.failInit('WebGL context unavailable')
      if (canvas.parentNode) canvas.parentNode.removeChild(canvas)
      this.canvas = null
      return
    }
    this.gl = gl
    gl.disable(gl.DEPTH_TEST)

    // B2 风场颜色场
    this.fieldProgram = linkProgram(gl, WIND_FIELD_VERTEX_SHADER, WIND_FIELD_FRAGMENT_SHADER)
    if (this.fieldProgram) {
      this.fieldAttribLngLat = gl.getAttribLocation(this.fieldProgram, 'a_lnglat')
      this.fieldUniformMatrix = gl.getUniformLocation(this.fieldProgram, 'u_matrix')
      this.fieldUniformWindTexture = gl.getUniformLocation(this.fieldProgram, 'u_windTexture')
      this.fieldUniformWindBounds = gl.getUniformLocation(this.fieldProgram, 'u_windBounds')
      this.fieldUniformMaxWind = gl.getUniformLocation(this.fieldProgram, 'u_maxWind')
      this.fieldUniformOpacity = gl.getUniformLocation(this.fieldProgram, 'u_opacity')
    }
    this.fieldQuadBuffer = gl.createBuffer()
    this.windTexture = gl.createTexture()
    this.paletteTexture = gl.createTexture()
    // 默认调色板（透明→白），保证 setColors 之前 LUT 纹理有效
    this.paletteLUT = buildPaletteLUT([])
    this.paletteDirty = true

    // B3 粒子系统（program 与 buffer 在 onAdd 编译；纹理/FBO 在首个风场数据到达时创建）
    this.initParticlePrograms(gl)
    // B4 拖尾衰减/屏幕合成程序
    this.initTrailPrograms(gl)

    if (!this.updateProgram || !this.drawProgram) {
      this.failInit('particle shader program link failed')
      this.teardown()
      return
    }

    this.resizeCanvasToMap()
    this.resizeHandler = () => this.resizeCanvasToMap()
    map.on(MAP_EVENT_RESIZE, this.resizeHandler)

    this.moveStartHandler = () => {
      this.mapMoving = true
      // 交互期间拖尾（屏幕空间纹理）与底图错位：清空，交互中只画粒子点，
      // 结束后重新累积，避免旧位置残影与新位置粒子叠加的错乱感
      this.trailDirty = true
    }
    this.moveEndHandler = () => {
      this.mapMoving = false
      this.lastMoveEndAt = performance.now()
    }
    this.zoomEndHandler = () => {
      this.mapMoving = false
      this.lastMoveEndAt = performance.now()
      // 不再整列重撒：bbox 变化由 setWindData 的 remap/面积启发式处理
    }
    map.on('movestart', this.moveStartHandler)
    map.on('moveend', this.moveEndHandler)
    map.on('zoomstart', this.moveStartHandler)
    map.on('zoomend', this.zoomEndHandler)

    this.visibilityHandler = () => {
      if (document.visibilityState === 'visible') {
        this.lastFrameTime = 0
        this.start()
      } else {
        this.stop()
      }
    }
    document.addEventListener('visibilitychange', this.visibilityHandler)
  }

  /**
   * 缓存投影矩阵；绘制在自有 RAF / 自有 context 上完成。
   *
   * MapLibre 5：mercator [0,1]² → clip 应使用 `defaultProjectionData.mainMatrix`
   *（getProjectionDataForCustomLayer 已按 EXTENT 缩放）。`modelViewProjectionMatrix`
   * 是像素世界坐标，不能与 lngLatToMercator 混用。
   */
  render(_gl: WebGLRenderingContext, options: CustomRenderMethodInput): void {
    const matrix = extractMercatorProjectionMatrix(options)
    if (!matrix) return
    this.matrix.set(matrix)
    this.hasMatrix = true
  }

  /**
   * 每帧刷新投影矩阵：优先 transform.getProjectionDataForCustomLayer（不依赖
   * custom layer render 时序），其次沿用 render() 缓存。
   */
  private refreshProjectionMatrix(): boolean {
    const transform = (
      this.map as MaplibreMap & {
        transform?: {
          getProjectionDataForCustomLayer?: (applyGlobe?: boolean) => {
            mainMatrix?: ArrayLike<number>
          }
        }
      }
    )?.transform
    const fromTransform = transform?.getProjectionDataForCustomLayer?.(false)?.mainMatrix
    if (fromTransform && typeof fromTransform[0] === 'number') {
      this.matrix.set(fromTransform)
      this.hasMatrix = true
      return true
    }
    return this.hasMatrix
  }

  private failInit(reason: string): void {
    this.initFailed = true
    this.initFailReason = reason
    console.warn('[WindParticleWebGL]', reason)
  }

  onRemove(_map: MaplibreMap, _gl: WebGLRenderingContext): void {
    this.teardown()
  }

  // ── 公共 API（controller 调用）────────────────────────────────────

  start(): void {
    if (this.rafId !== null) return
    this.lastFrameTime = 0
    this.rafId = requestAnimationFrame(this.frame)
  }

  stop(): void {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId)
      this.rafId = null
    }
  }

  /** 喂入风场数据：构建网格 + 编码为纹理（实际上传延迟到 drawFrame，确保 GL 就绪） */
  setWindData(geojson: WindGeoJSON | null): void {
    if (!geojson) {
      this.hasWindData = false
      this.pendingWindTexture = null
      this.lastEncodedWind = null
      return
    }
    const grid = buildWindGridFromGeoJSON(geojson)
    if (!grid) {
      console.warn('[WindParticleWebGL] setWindData: 无法构建风场网格')
      this.hasWindData = false
      this.pendingWindTexture = null
      return
    }
    const encoded = encodeWindGridToRGBA(grid)
    const newBounds = {
      west: encoded.west,
      south: encoded.south,
      east: encoded.east,
      north: encoded.north,
    }
    const boundsChanged =
      !this.windBounds ||
      this.windBounds.west !== newBounds.west ||
      this.windBounds.east !== newBounds.east ||
      this.windBounds.south !== newBounds.south ||
      this.windBounds.north !== newBounds.north
    if (boundsChanged) {
      const old = this.windBounds
      if (!old) {
        // 首次数据：全量重撒
        this.particleResetAll = true
        this.trailDirty = true
      } else {
        // 面积显著增大（zoom-out 揭示更多区域）→ 全量重撒保证密度；
        // 否则 remap：粒子地理位置不变，轨迹与屏幕拖尾保持稳定，
        // 出界粒子在更新 shader 内于新 bbox 重撒（自动补足 zoom-in 密度）。
        const oldArea = (old.east - old.west) * (old.north - old.south)
        const newArea = (newBounds.east - newBounds.west) * (newBounds.north - newBounds.south)
        if (newArea > oldArea * 1.5) {
          this.particleResetAll = true
          this.trailDirty = true
        } else {
          this.prevWindBounds = { ...old }
          this.pendingRemap = true
        }
      }
    }
    this.pendingWindTexture = encoded
    this.windBounds = newBounds
    this.hasWindData = true
    this.lastEncodedWind = encoded
  }

  /** 更新调色板：构建 256×1 LUT（上传延迟到 drawFrame，确保 GL 就绪） */
  setColors(colors: string[]): void {
    if (colors.join(',') === this.particleColors.join(',')) return
    this.particleColors = colors
    this.paletteLUT = buildPaletteLUT(colors)
    this.paletteDirty = true
  }

  /** 清理 GL 资源与 DOM（幂等，可被 onRemove / destroy 重复调用） */
  dispose(): void {
    this.teardown()
  }

  // ── B3 粒子系统初始化 ─────────────────────────────────────────────

  private initParticlePrograms(gl: WebGLRenderingContext): void {
    this.updateProgram = linkProgram(
      gl,
      PARTICLE_UPDATE_VERTEX_SHADER,
      PARTICLE_UPDATE_FRAGMENT_SHADER,
    )
    if (this.updateProgram) {
      this.updateAttribPos = gl.getAttribLocation(this.updateProgram, 'a_pos')
      this.updateUniformParticleTexture = gl.getUniformLocation(
        this.updateProgram,
        'u_particleTexture',
      )
      this.updateUniformWindTexture = gl.getUniformLocation(this.updateProgram, 'u_windTexture')
      this.updateUniformWindBounds = gl.getUniformLocation(this.updateProgram, 'u_windBounds')
      this.updateUniformMaxWind = gl.getUniformLocation(this.updateProgram, 'u_maxWind')
      this.updateUniformScaledSpeed = gl.getUniformLocation(this.updateProgram, 'u_scaledSpeed')
      this.updateUniformDt = gl.getUniformLocation(this.updateProgram, 'u_dt')
      this.updateUniformFrameSeed = gl.getUniformLocation(this.updateProgram, 'u_frameSeed')
      this.updateUniformResetAll = gl.getUniformLocation(this.updateProgram, 'u_resetAll')
      this.updateUniformPrevWindBounds = gl.getUniformLocation(
        this.updateProgram,
        'u_prevWindBounds',
      )
      this.updateUniformRemap = gl.getUniformLocation(this.updateProgram, 'u_remap')
    }

    this.drawProgram = linkProgram(
      gl,
      PARTICLE_DRAW_CLIP_VERTEX_SHADER,
      PARTICLE_DRAW_SOFT_FRAGMENT_SHADER,
    )
    if (this.drawProgram) {
      this.drawAttribClipSpeed = gl.getAttribLocation(this.drawProgram, 'a_clipSpeed')
      this.drawUniformPointSize = gl.getUniformLocation(this.drawProgram, 'u_pointSize')
      this.drawUniformColor = gl.getUniformLocation(this.drawProgram, 'u_color')
    }

    // 粒子顶点缓冲：每粒子 clipX/clipY/_（每帧 DYNAMIC 回填）
    this.particleVertexBuffer = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, this.particleVertexBuffer)
    gl.bufferData(gl.ARRAY_BUFFER, this.particleClipData.byteLength, gl.DYNAMIC_DRAW)

    // 全屏 quad（更新 pass 用）：TRIANGLE_STRIP
    this.fullscreenQuadBuffer = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, this.fullscreenQuadBuffer)
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW)
  }

  /** 创建粒子位置纹理（NEAREST，RGBA8） */
  private createParticleTexture(data: Uint8Array): WebGLTexture | null {
    const gl = this.gl
    if (!gl) return null
    const tex = gl.createTexture()
    gl.bindTexture(gl.TEXTURE_2D, tex)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST)
    gl.texImage2D(
      gl.TEXTURE_2D,
      0,
      gl.RGBA,
      this.particleResolution,
      this.particleResolution,
      0,
      gl.RGBA,
      gl.UNSIGNED_BYTE,
      data,
    )
    return tex
  }

  /** 首个风场数据到达后，初始化 ping-pong 位置纹理 + FBO */
  private ensureParticleSystem(): void {
    if (this.particleSystemReady || !this.gl) return
    const gl = this.gl
    const initialData = this.buildInitialParticleData()
    const tex0 = this.createParticleTexture(initialData)
    const tex1 = this.createParticleTexture(initialData)
    if (!tex0 || !tex1) {
      if (tex0) gl.deleteTexture(tex0)
      if (tex1) gl.deleteTexture(tex1)
      console.warn('[WindParticleWebGL] 粒子位置纹理创建失败')
      return
    }
    this.particleTextures = [tex0, tex1]
    this.particleFBO = gl.createFramebuffer()
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.particleFBO)
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex1, 0)
    const complete = gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE
    gl.bindFramebuffer(gl.FRAMEBUFFER, null)
    if (!complete) {
      console.warn('[WindParticleWebGL] 粒子 FBO 不完整，粒子模拟禁用')
      return
    }
    this.particleSystemReady = this.updateProgram !== null && this.drawProgram !== null
    this.particleResetAll = true
  }

  private buildInitialParticleData(): Uint8Array {
    const res = this.particleResolution
    const data = new Uint8Array(res * res * 4)
    for (let i = 0; i < res * res; i++) {
      const [r, g, b, a] = encodePositionBytes(Math.random(), Math.random())
      data[i * 4] = r
      data[i * 4 + 1] = g
      data[i * 4 + 2] = b
      data[i * 4 + 3] = a
    }
    return data
  }

  // ── B4 拖尾系统 ──────────────────────────────────────────────────

  private initTrailPrograms(gl: WebGLRenderingContext): void {
    // 衰减 pass 与屏幕合成 pass 均复用全屏 quad 顶点着色器
    this.fadeProgram = linkProgram(gl, PARTICLE_UPDATE_VERTEX_SHADER, TRAIL_FADE_FRAGMENT_SHADER)
    if (this.fadeProgram) {
      this.fadeAttribPos = gl.getAttribLocation(this.fadeProgram, 'a_pos')
      this.fadeUniformTexture = gl.getUniformLocation(this.fadeProgram, 'u_texture')
      this.fadeUniformFade = gl.getUniformLocation(this.fadeProgram, 'u_fade')
    }
    this.screenProgram = linkProgram(
      gl,
      PARTICLE_UPDATE_VERTEX_SHADER,
      TRAIL_SCREEN_FRAGMENT_SHADER,
    )
    if (this.screenProgram) {
      this.screenAttribPos = gl.getAttribLocation(this.screenProgram, 'a_pos')
      this.screenUniformTexture = gl.getUniformLocation(this.screenProgram, 'u_texture')
      this.screenUniformOpacity = gl.getUniformLocation(this.screenProgram, 'u_opacity')
    }
  }

  private createTrailTexture(width: number, height: number): WebGLTexture | null {
    const gl = this.gl
    if (!gl) return null
    const tex = gl.createTexture()
    gl.bindTexture(gl.TEXTURE_2D, tex)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, null)
    return tex
  }

  /** 确保 trail 纹理与 canvas 尺寸一致（resize / bbox 变化时重建并清空） */
  private ensureTrailTextures(): void {
    const gl = this.gl
    if (!gl || !this.canvas) return
    const w = this.canvas.width
    const h = this.canvas.height
    if (w <= 0 || h <= 0) return
    const sizeMatch = w === this.trailWidth && h === this.trailHeight
    if (sizeMatch && !this.trailDirty && this.trailTextures.length === 2) return

    // 尺寸变化或需清空：删除旧纹理并重建
    for (const tex of this.trailTextures) gl.deleteTexture(tex)
    const t0 = this.createTrailTexture(w, h)
    const t1 = this.createTrailTexture(w, h)
    if (!t0 || !t1) {
      if (t0) gl.deleteTexture(t0)
      if (t1) gl.deleteTexture(t1)
      this.trailTextures = []
      return
    }
    this.trailTextures = [t0, t1]
    if (!this.trailFBO) {
      this.trailFBO = gl.createFramebuffer()
    }
    // 清空两张 trail 纹理
    for (const tex of this.trailTextures) {
      gl.bindFramebuffer(gl.FRAMEBUFFER, this.trailFBO)
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0)
      gl.clearColor(0, 0, 0, 0)
      gl.clear(gl.COLOR_BUFFER_BIT)
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, null)
    this.trailWidth = w
    this.trailHeight = h
    this.trailDirty = false
  }

  /** 绘制全屏 quad（供 fade / screen pass 复用） */
  private drawFullscreenQuad(attribPos: number): void {
    const gl = this.gl
    if (!gl) return
    gl.bindBuffer(gl.ARRAY_BUFFER, this.fullscreenQuadBuffer)
    gl.enableVertexAttribArray(attribPos)
    gl.vertexAttribPointer(attribPos, 2, gl.FLOAT, false, 0, 0)
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
  }

  // ── 帧渲染 ─────────────────────────────────────────────────────────

  /** 让 canvas 尺寸与地图 canvas 对齐（含 devicePixelRatio），保证矩阵 viewport 一致 */
  private resizeCanvasToMap(): void {
    if (!this.canvas || !this.map) return
    const mapCanvas = this.map.getCanvas()
    const w = mapCanvas.width
    const h = mapCanvas.height
    if (w > 0 && h > 0 && (this.canvas.width !== w || this.canvas.height !== h)) {
      this.canvas.width = w
      this.canvas.height = h
    }
    // CSS 尺寸：仅当 mapCanvas 已设置非空 style 时才同步，避免覆盖 onAdd 中的 '100%'
    const styleW = mapCanvas.style.width
    const styleH = mapCanvas.style.height
    if (styleW) this.canvas.style.width = styleW
    if (styleH) this.canvas.style.height = styleH
  }

  /** 上传待处理的风场纹理 + 重建场 quad（在 GL 就绪后由 drawFrame 调用） */
  private flushPendingWindTexture(): void {
    const gl = this.gl
    if (!gl || !this.pendingWindTexture || !this.windTexture) return
    const encoded = this.pendingWindTexture

    gl.bindTexture(gl.TEXTURE_2D, this.windTexture)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
    gl.texImage2D(
      gl.TEXTURE_2D,
      0,
      gl.RGBA,
      encoded.width,
      encoded.height,
      0,
      gl.RGBA,
      gl.UNSIGNED_BYTE,
      encoded.data,
    )

    // 场 quad：覆盖风场 bbox 的 4 角点（TRIANGLE_STRIP：NW, SW, NE, SE）
    if (this.windBounds && this.fieldQuadBuffer) {
      const { west, south, east, north } = this.windBounds
      const quad = new Float32Array([west, north, west, south, east, north, east, south])
      gl.bindBuffer(gl.ARRAY_BUFFER, this.fieldQuadBuffer)
      gl.bufferData(gl.ARRAY_BUFFER, quad, gl.STATIC_DRAW)
    }

    this.pendingWindTexture = null
  }

  /** 上传待处理的调色板 LUT 纹理（在 GL 就绪后由 drawFrame 调用） */
  private flushPaletteTexture(): void {
    const gl = this.gl
    if (!gl || !this.paletteDirty || !this.paletteLUT || !this.paletteTexture) return
    gl.bindTexture(gl.TEXTURE_2D, this.paletteTexture)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 256, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, this.paletteLUT)
    this.paletteDirty = false
  }

  private drawFrame(dt: number): void {
    const gl = this.gl
    if (!gl || !this.canvas) return

    if (!this.refreshProjectionMatrix()) {
      this.matrixMissFrames += 1
      if (this.matrixMissFrames >= MATRIX_MISS_FAIL_AFTER && !this.initFailed) {
        this.failInit('projection matrix unavailable (custom layer render / transform)')
      }
      return
    }
    this.matrixMissFrames = 0
    if (!this.matrixReadyLogged) {
      this.matrixReadyLogged = true
      console.log('[WindParticleWebGL] projection matrix ready, particles drawing')
    }

    this.flushPendingWindTexture()
    this.flushPaletteTexture()
    if (this.hasWindData) {
      this.ensureParticleSystem()
    }

    gl.viewport(0, 0, this.canvas.width, this.canvas.height)
    gl.clearColor(0, 0, 0, 0)
    gl.clear(gl.COLOR_BUFFER_BIT)

    // 优先粒子渲染（B3/B4）；风场颜色场 quad（B2）在粒子未就绪时作回退
    if (this.hasWindData && this.particleSystemReady && this.windBounds) {
      const zoom = this.map?.getZoom() ?? 4
      const zoomFactor = Math.min(Math.pow(2, Math.max(0, 4.2 - zoom)), 2.4)
      const advectDt = Math.min(dt, 2)
      const scaledSpeed = DEFAULT_SPEED_SCALE * zoomFactor * advectDt

      const brokeStreaks = this.particleResetAll
      this.updateParticles(scaledSpeed, dt)
      // updateParticles 会把 viewport 改成粒子纹理尺寸，绘制前必须恢复
      gl.viewport(0, 0, this.canvas.width, this.canvas.height)
      if (brokeStreaks) {
        this.trailDirty = true
      }

      // B4：拖尾系统就绪时用 ping-pong trail FBO；否则直接画点。
      // 交互（平移/缩放）期间不累积拖尾：拖尾是屏幕空间纹理，底图移动时
      // 旧轨迹会与新位置粒子错位叠加；交互只画点，结束后重新累积。
      const canTrail =
        !!(this.fadeProgram && this.screenProgram && this.trailFBO) && !this.mapMoving
      if (canTrail) {
        this.ensureTrailTextures()
      }
      if (canTrail && this.trailTextures.length >= 2) {
        this.renderTrails(dt)
      } else {
        gl.enable(gl.BLEND)
        gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA)
        this.drawParticles(gl)
      }
    } else if (this.hasWindData && this.fieldProgram && this.windBounds) {
      gl.enable(gl.BLEND)
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA)
      this.drawWindField(gl)
    }
    // hasWindData=false 时不绘制任何占位内容（原 B1 调试三角形已移除）
  }

  /** B3 更新 pass：ping-pong FBO 内做 RK2 平流（写原始位置数据，不做混合） */
  private updateParticles(scaledSpeed: number, dt: number): void {
    const gl = this.gl
    if (!gl || !this.updateProgram || !this.particleFBO || !this.windBounds) return
    const nextIndex = 1 - this.currentParticleIndex

    gl.bindFramebuffer(gl.FRAMEBUFFER, this.particleFBO)
    gl.framebufferTexture2D(
      gl.FRAMEBUFFER,
      gl.COLOR_ATTACHMENT0,
      gl.TEXTURE_2D,
      this.particleTextures[nextIndex],
      0,
    )
    gl.viewport(0, 0, this.particleResolution, this.particleResolution)
    gl.disable(gl.BLEND)

    gl.useProgram(this.updateProgram)
    gl.activeTexture(gl.TEXTURE0)
    gl.bindTexture(gl.TEXTURE_2D, this.particleTextures[this.currentParticleIndex])
    gl.uniform1i(this.updateUniformParticleTexture, 0)
    gl.activeTexture(gl.TEXTURE1)
    gl.bindTexture(gl.TEXTURE_2D, this.windTexture)
    gl.uniform1i(this.updateUniformWindTexture, 1)
    gl.uniform4f(
      this.updateUniformWindBounds,
      this.windBounds.west,
      this.windBounds.south,
      this.windBounds.east,
      this.windBounds.north,
    )
    gl.uniform1f(this.updateUniformMaxWind, WIND_TEXTURE_MAX_WIND)
    gl.uniform1f(this.updateUniformScaledSpeed, scaledSpeed)
    gl.uniform1f(this.updateUniformDt, dt)
    gl.uniform1f(this.updateUniformFrameSeed, this.frameSeed)
    gl.uniform1f(this.updateUniformResetAll, this.particleResetAll ? 1 : 0)
    const prev = this.prevWindBounds ?? this.windBounds
    gl.uniform4f(this.updateUniformPrevWindBounds, prev.west, prev.south, prev.east, prev.north)
    gl.uniform1f(this.updateUniformRemap, this.pendingRemap && !this.particleResetAll ? 1 : 0)

    gl.bindBuffer(gl.ARRAY_BUFFER, this.fullscreenQuadBuffer)
    gl.enableVertexAttribArray(this.updateAttribPos)
    gl.vertexAttribPointer(this.updateAttribPos, 2, gl.FLOAT, false, 0, 0)
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)

    gl.bindFramebuffer(gl.FRAMEBUFFER, null)
    this.currentParticleIndex = nextIndex
    this.particleResetAll = false
    this.pendingRemap = false
    this.frameSeed = (this.frameSeed + 1) % 1024
  }

  /** B4 拖尾渲染：衰减旧 trail → 叠加新粒子 → 合成到屏幕 */
  private renderTrails(dt: number): void {
    const gl = this.gl
    if (!gl || !this.canvas || !this.trailFBO) return
    if (this.trailTextures.length < 2) return
    const nextTrail = 1 - this.currentTrailIndex

    // 1. 衰减旧 trail 到 nextTrail FBO（覆盖写，不混合）
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.trailFBO)
    gl.framebufferTexture2D(
      gl.FRAMEBUFFER,
      gl.COLOR_ATTACHMENT0,
      gl.TEXTURE_2D,
      this.trailTextures[nextTrail],
      0,
    )
    gl.viewport(0, 0, this.trailWidth, this.trailHeight)
    gl.disable(gl.BLEND)
    gl.useProgram(this.fadeProgram)
    gl.activeTexture(gl.TEXTURE0)
    gl.bindTexture(gl.TEXTURE_2D, this.trailTextures[this.currentTrailIndex])
    gl.uniform1i(this.fadeUniformTexture, 0)
    // 对齐 Windy trailFade=0.96；dt 为相对 60fps 的帧数
    gl.uniform1f(this.fadeUniformFade, Math.pow(TRAIL_FADE, dt))
    this.drawFullscreenQuad(this.fadeAttribPos)

    // 2. 在同一 FBO 上叠加当前粒子（混合）
    gl.enable(gl.BLEND)
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA)
    this.drawParticles(gl)
    gl.bindFramebuffer(gl.FRAMEBUFFER, null)

    // 3. 合成 nextTrail 到屏幕
    gl.viewport(0, 0, this.canvas.width, this.canvas.height)
    gl.enable(gl.BLEND)
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA)
    gl.useProgram(this.screenProgram)
    gl.activeTexture(gl.TEXTURE0)
    gl.bindTexture(gl.TEXTURE_2D, this.trailTextures[nextTrail])
    gl.uniform1i(this.screenUniformTexture, 0)
    gl.uniform1f(this.screenUniformOpacity, 1.0)
    this.drawFullscreenQuad(this.screenAttribPos)

    this.currentTrailIndex = nextTrail
  }

  /**
   * 绘制 pass：Windy 风格实心点叠进 trail FBO。
   * 连续丝状观感来自「点大小覆盖帧间位移 + trailFade≈0.96 拖尾」。
   */
  private drawParticles(gl: WebGLRenderingContext): void {
    if (!this.drawProgram || !this.windBounds || !this.canvas || !this.particleFBO) return
    if (!this.uploadParticlePointBuffer(gl)) return

    gl.useProgram(this.drawProgram)
    gl.bindBuffer(gl.ARRAY_BUFFER, this.particleVertexBuffer)
    gl.enableVertexAttribArray(this.drawAttribClipSpeed)
    gl.vertexAttribPointer(this.drawAttribClipSpeed, 3, gl.FLOAT, false, 0, 0)
    gl.uniform4f(
      this.drawUniformColor,
      PARTICLE_COLOR[0],
      PARTICLE_COLOR[1],
      PARTICLE_COLOR[2],
      PARTICLE_COLOR[3],
    )
    // gl_PointSize 以 framebuffer 像素计；canvas 已是设备像素，与 Windy 同用固定尺寸
    gl.uniform1f(this.drawUniformPointSize, PARTICLE_POINT_SIZE)
    gl.drawArrays(gl.POINTS, 0, this.particleDrawCount)
  }

  /** readPixels → 投影到 NDC → 上传为 GL_POINTS 顶点 */
  private uploadParticlePointBuffer(gl: WebGLRenderingContext): boolean {
    if (!this.particleFBO || !this.windBounds) return false
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.particleFBO)
    gl.framebufferTexture2D(
      gl.FRAMEBUFFER,
      gl.COLOR_ATTACHMENT0,
      gl.TEXTURE_2D,
      this.particleTextures[this.currentParticleIndex],
      0,
    )
    gl.readPixels(
      0,
      0,
      this.particleResolution,
      this.particleResolution,
      gl.RGBA,
      gl.UNSIGNED_BYTE,
      this.particlePosPixels,
    )
    gl.bindFramebuffer(gl.FRAMEBUFFER, null)
    if (isPerfEnabled() && this.frameCounter % 30 === 0) {
      perfMark('wind.readPixels', { skipped: false, res: this.particleResolution })
    }

    const { west, south, east, north } = this.windBounds
    const m = this.matrix
    const pixels = this.particlePosPixels
    const out = this.particleClipData
    let write = 0

    for (let i = 0; i < this.particleCount; i++) {
      const p = i * 4
      const [nx, ny] = decodePositionBytes(pixels[p], pixels[p + 1], pixels[p + 2], pixels[p + 3])
      const lon = west + (east - west) * nx
      const lat = north + (south - north) * ny
      const [mercX, mercY] = lngLatToMercatorNormalized(lon, lat)
      const x = m[0] * mercX + m[4] * mercY + m[12]
      const y = m[1] * mercX + m[5] * mercY + m[13]
      const w = m[3] * mercX + m[7] * mercY + m[15]
      const invW = w !== 0 ? 1 / w : 0
      const o = write * 3
      out[o] = x * invW
      out[o + 1] = y * invW
      out[o + 2] = 0
      write += 1
    }

    this.particleDrawCount = write
    gl.bindBuffer(gl.ARRAY_BUFFER, this.particleVertexBuffer)
    gl.bufferData(gl.ARRAY_BUFFER, out.subarray(0, write * 3), gl.DYNAMIC_DRAW)
    return write > 0
  }

  private drawWindField(gl: WebGLRenderingContext): void {
    if (!this.fieldProgram || !this.windBounds || !this.windTexture) return
    gl.useProgram(this.fieldProgram)
    gl.bindBuffer(gl.ARRAY_BUFFER, this.fieldQuadBuffer)
    gl.enableVertexAttribArray(this.fieldAttribLngLat)
    gl.vertexAttribPointer(this.fieldAttribLngLat, 2, gl.FLOAT, false, 0, 0)
    gl.activeTexture(gl.TEXTURE0)
    gl.bindTexture(gl.TEXTURE_2D, this.windTexture)
    gl.uniform1i(this.fieldUniformWindTexture, 0)
    gl.uniform4f(
      this.fieldUniformWindBounds,
      this.windBounds.west,
      this.windBounds.south,
      this.windBounds.east,
      this.windBounds.north,
    )
    gl.uniform1f(this.fieldUniformMaxWind, WIND_TEXTURE_MAX_WIND)
    gl.uniform1f(this.fieldUniformOpacity, FIELD_OPACITY)
    // 世界包裹：屏幕可见的每个世界副本各画一次，消除反子午线附近的半球空白
    const offsets = computeWorldWrapOffsets(this.matrix)
    for (const offset of offsets) {
      this.tempMatrix.set(this.matrix)
      this.tempMatrix[12] += offset
      gl.uniformMatrix4fv(this.fieldUniformMatrix, false, this.tempMatrix)
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
    }
  }

  private teardown(): void {
    this.stop()
    if (this.map && this.resizeHandler) {
      this.map.off(MAP_EVENT_RESIZE, this.resizeHandler)
      this.resizeHandler = null
    }
    if (this.map && this.moveStartHandler) {
      this.map.off('movestart', this.moveStartHandler)
      this.map.off('zoomstart', this.moveStartHandler)
      this.moveStartHandler = null
    }
    if (this.map && this.moveEndHandler) {
      this.map.off('moveend', this.moveEndHandler)
      this.moveEndHandler = null
    }
    if (this.map && this.zoomEndHandler) {
      this.map.off('zoomend', this.zoomEndHandler)
      this.zoomEndHandler = null
    }
    if (this.visibilityHandler) {
      document.removeEventListener('visibilitychange', this.visibilityHandler)
      this.visibilityHandler = null
    }
    const gl = this.gl
    if (gl) {
      if (this.fieldQuadBuffer) gl.deleteBuffer(this.fieldQuadBuffer)
      if (this.fieldProgram) gl.deleteProgram(this.fieldProgram)
      if (this.windTexture) gl.deleteTexture(this.windTexture)
      if (this.paletteTexture) gl.deleteTexture(this.paletteTexture)
      if (this.updateProgram) gl.deleteProgram(this.updateProgram)
      if (this.drawProgram) gl.deleteProgram(this.drawProgram)
      if (this.particleVertexBuffer) gl.deleteBuffer(this.particleVertexBuffer)
      if (this.fullscreenQuadBuffer) gl.deleteBuffer(this.fullscreenQuadBuffer)
      for (const tex of this.particleTextures) gl.deleteTexture(tex)
      if (this.particleFBO) gl.deleteFramebuffer(this.particleFBO)
      for (const tex of this.trailTextures) gl.deleteTexture(tex)
      if (this.trailFBO) gl.deleteFramebuffer(this.trailFBO)
      if (this.fadeProgram) gl.deleteProgram(this.fadeProgram)
      if (this.screenProgram) gl.deleteProgram(this.screenProgram)
    }
    this.fieldQuadBuffer = null
    this.fieldProgram = null
    this.windTexture = null
    this.paletteTexture = null
    this.paletteLUT = null
    this.paletteDirty = false
    this.updateProgram = null
    this.drawProgram = null
    this.particleVertexBuffer = null
    this.fullscreenQuadBuffer = null
    this.particleTextures = []
    this.particleFBO = null
    this.particleSystemReady = false
    this.trailTextures = []
    this.trailFBO = null
    this.fadeProgram = null
    this.screenProgram = null
    this.trailWidth = 0
    this.trailHeight = 0
    this.trailDirty = true
    this.gl = null
    if (this.canvas && this.canvas.parentNode) {
      this.canvas.parentNode.removeChild(this.canvas)
    }
    this.canvas = null
    this.map = null
    this.hasMatrix = false
    this.hasWindData = false
    this.pendingWindTexture = null
    this.lastEncodedWind = null
    this.windBounds = null
    this.matrixMissFrames = 0
    this.matrixReadyLogged = false
    this.particleDrawCount = 0
    this.initFailed = this.initFailed || false
  }
}

/** @internal 测试辅助：探测浏览器是否具备粒子 WebGL 所需能力。 */
export function probeWindParticleWebGLSupport(doc: Document = document): {
  ok: boolean
  reason?: string
} {
  try {
    const canvas = doc.createElement('canvas')
    const gl = (canvas.getContext('webgl2', { alpha: true }) ||
      canvas.getContext('webgl', { alpha: true }) ||
      canvas.getContext('experimental-webgl', { alpha: true })) as WebGLRenderingContext | null
    if (!gl) return { ok: false, reason: 'no-webgl' }
    // 绘制已改为 readPixels + CPU 投影，不再依赖顶点纹理采样
    return { ok: true }
  } catch {
    return { ok: false, reason: 'probe-error' }
  }
}
