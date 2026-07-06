/**
 * WebGL2 共享工具 — 着色器编译、缓冲区创建、纹理上传、矩阵计算。
 * 所有风场渲染层共享此模块。
 */
import type { Map as MaplibreMap } from 'maplibre-gl'

// ── 渲染参数常量 ─────────────────────────────────────────

/** 最大像素比（防止超高 DPI 屏幕性能问题） */
const MAX_PIXEL_RATIO = 2

/** Canvas 布局边距（像素），确保网格边缘不被裁剪 */
const CANVAS_LAYOUT_MARGIN_PX = 40

// ── 着色器编译 ────────────────────────────────────────────

export function compileShader(gl: WebGL2RenderingContext, type: number, src: string): WebGLShader {
  const shader = gl.createShader(type)!
  gl.shaderSource(shader, src)
  gl.compileShader(shader)
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(shader)
    gl.deleteShader(shader)
    throw new Error(`Shader compile error: ${log}`)
  }
  return shader
}

export function createProgram(
  gl: WebGL2RenderingContext,
  vertSrc: string,
  fragSrc: string,
): WebGLProgram {
  const vert = compileShader(gl, gl.VERTEX_SHADER, vertSrc)
  const frag = compileShader(gl, gl.FRAGMENT_SHADER, fragSrc)
  const prog = gl.createProgram()!
  gl.attachShader(prog, vert)
  gl.attachShader(prog, frag)
  gl.linkProgram(prog)
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
    const log = gl.getProgramInfoLog(prog)
    gl.deleteProgram(prog)
    throw new Error(`Program link error: ${log}`)
  }
  // 已链接，删除中间对象
  gl.deleteShader(vert)
  gl.deleteShader(frag)
  return prog
}

// ── 缓冲区工具 ────────────────────────────────────────────

export function createFloat32Buffer(gl: WebGL2RenderingContext, data: Float32Array): WebGLBuffer {
  const buf = gl.createBuffer()!
  gl.bindBuffer(gl.ARRAY_BUFFER, buf)
  gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW)
  return buf
}

export function createDynamicFloat32Buffer(gl: WebGL2RenderingContext): WebGLBuffer {
  const buf = gl.createBuffer()!
  gl.bindBuffer(gl.ARRAY_BUFFER, buf)
  gl.bufferData(gl.ARRAY_BUFFER, 0, gl.DYNAMIC_DRAW)
  return buf
}

export function updateBufferData(gl: WebGL2RenderingContext, buf: WebGLBuffer, data: Float32Array, usage = gl.DYNAMIC_DRAW): void {
  gl.bindBuffer(gl.ARRAY_BUFFER, buf)
  gl.bufferData(gl.ARRAY_BUFFER, data, usage)
}

// ── 纹理工具 ─────────────────────────────────────────────

/** 上传 1×1 纯透明纹理（用于满足需要的 sampler 绑定） */
export function createPlaceholderTexture(gl: WebGL2RenderingContext): WebGLTexture {
  const tex = gl.createTexture()!
  gl.bindTexture(gl.TEXTURE_2D, tex)
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([0, 0, 0, 0]))
  return tex
}

// ── 矩阵工具 ─────────────────────────────────────────────

/** 3×3 齐次变换矩阵（WebGL 列主序）：
 *  将经纬度 + 屏幕偏移映射到 NDC [-1,1]
 *  设 map 为 MaplibreMap，glCanvas 为 WebGL canvas，glCanvasSize 为 WebGL canvas 像素尺寸
 *
 *  变换链：
 *    (lon, lat) --map.project--> (screenX, screenY)
 *    (screenX, screenY) - offsetX/Y--> (cx, cy)  [canvas 内坐标]
 *    (cx, cy, cw, ch) ---> NDC (x_ndc, y_ndc)
 */
export interface Mat3 {
  /** 列主序 9 元素数组 */
  m: Float32Array
}

/** 创建平移矩阵（列主序） */
export function mat3Translate(tx: number, ty: number): Mat3 {
  return { m: new Float32Array([1, 0, 0, 0, 1, 0, tx, ty, 1]) }
}

/** 创建缩放矩阵（列主序） */
export function mat3Scale(sx: number, sy: number): Mat3 {
  return { m: new Float32Array([sx, 0, 0, 0, sy, 0, 0, 0, 1]) }
}

/** 矩阵乘法（列主序）：return a * b */
export function mat3Mul(a: Mat3, b: Mat3): Mat3 {
  const am = a.m, bm = b.m
  return {
    m: new Float32Array([
      am[0] * bm[0] + am[3] * bm[1] + am[6] * bm[2],
      am[1] * bm[0] + am[4] * bm[1] + am[7] * bm[2],
      am[2] * bm[0] + am[5] * bm[1] + am[8] * bm[2],
      am[0] * bm[3] + am[3] * bm[4] + am[6] * bm[5],
      am[1] * bm[3] + am[4] * bm[4] + am[7] * bm[5],
      am[2] * bm[3] + am[5] * bm[4] + am[8] * bm[5],
      am[0] * bm[6] + am[3] * bm[7] + am[6] * bm[8],
      am[1] * bm[6] + am[4] * bm[7] + am[7] * bm[8],
      am[2] * bm[6] + am[5] * bm[7] + am[8] * bm[8],
    ]),
  }
}

/** 构建经纬度→NDC 的完整变换矩阵
 *  map: MaplibreMap 实例
 *  glCanvasWidth/Height: WebGL canvas 的实际像素尺寸
 *  canvasOffsetX/Y: canvas 左上角相对于地图容器的像素偏移
 */
export function buildGeoToNdc(
  glCanvasWidth: number,
  glCanvasHeight: number,
  canvasOffsetX: number,
  canvasOffsetY: number,
): Mat3 {
  // 屏幕坐标转 NDC：NDC_x = 2*cx/cw - 1, NDC_y = 1 - 2*cy/ch
  // 合并：NDC = translate(-1,-1) * scale(2/cw, -2/ch) * translate(-ox, -oy)
  const cw = glCanvasWidth, ch = glCanvasHeight, ox = canvasOffsetX, oy = canvasOffsetY
  return mat3Mul(
    mat3Translate(-1, -1),
    mat3Mul(mat3Scale(2 / cw, -2 / ch), mat3Translate(-ox, -oy)),
  )
}

// ── Canvas 尺寸管理 ───────────────────────────────────────

export interface CanvasLayout {
  width: number
  height: number
  offsetX: number
  offsetY: number
}

/**
 * 根据地图投影的网格范围，计算 WebGL canvas 的最佳尺寸和偏移。
 * canvas 直接覆盖网格投影区域（非全屏），节省像素量。
 */
export function computeCanvasLayout(
  map: MaplibreMap,
  gridWest: number,
  gridEast: number,
  gridSouth: number,
  gridNorth: number,
  margin = CANVAS_LAYOUT_MARGIN_PX,
): CanvasLayout {
  const container = map.getContainer()
  const vw = container.clientWidth
  const vh = container.clientHeight

  // 投影网格四角到屏幕坐标
  const tl = map.project([gridWest, gridNorth])
  const tr = map.project([gridEast, gridNorth])
  const bl = map.project([gridWest, gridSouth])
  const br = map.project([gridEast, gridSouth])

  const gridMinX = Math.min(tl.x, tr.x, bl.x, br.x) - margin
  const gridMaxX = Math.max(tl.x, tr.x, bl.x, br.x) + margin
  const gridMinY = Math.min(tl.y, tr.y, bl.y, br.y) - margin
  const gridMaxY = Math.max(tl.y, tr.y, bl.y, br.y) + margin

  // 裁剪到视口范围
  const minX = Math.max(gridMinX, 0)
  const maxX = Math.min(gridMaxX, vw)
  const minY = Math.max(gridMinY, 0)
  const maxY = Math.min(gridMaxY, vh)

  const width = Math.max(1, Math.round(maxX - minX))
  const height = Math.max(1, Math.round(maxY - minY))

  return {
    width,
    height,
    offsetX: Math.round(minX),
    offsetY: Math.round(minY),
  }
}

// ── WebGL Canvas 包装器 ──────────────────────────────────

/**
 * 创建对齐到地图容器、拥有独立 WebGL2 上下文的 canvas。
 * 自动处理 DPI、尺寸更新、销毁清理。
 */
export class WebGLCanvas {
  private container: HTMLElement
  private _pixelRatio: number
  public canvas: HTMLCanvasElement
  public gl: WebGL2RenderingContext
  public layout: CanvasLayout

  constructor(map: MaplibreMap, pixelRatio = Math.min(window.devicePixelRatio, MAX_PIXEL_RATIO)) {
    this.container = map.getContainer()
    this._pixelRatio = pixelRatio
    this.canvas = document.createElement('canvas')
    this.canvas.style.position = 'absolute'
    this.canvas.style.top = '0'
    this.canvas.style.left = '0'
    this.canvas.style.pointerEvents = 'none'
    this.canvas.className = 'wind-webgl-canvas'
    this.container.appendChild(this.canvas)

    const gl = this.canvas.getContext('webgl2', {
      alpha: true,
      premultipliedAlpha: true,
      antialias: false,
      powerPreference: 'high-performance',
    })
    if (!gl) {
      throw new Error(
        'WebGL2 is not available in this browser. Please use a modern browser (Chrome 56+, Firefox 51+, Safari 15+) with hardware acceleration enabled.',
      )
    }
    this.gl = gl

    this.layout = { width: 0, height: 0, offsetX: 0, offsetY: 0 }
    this.resize()
  }

  resize(layout?: CanvasLayout): void {
    if (layout) {
      this.layout = layout
    }
    const { width, height, offsetX, offsetY } = this.layout
    const dpr = this._pixelRatio
    this.canvas.width = Math.round(width * dpr)
    this.canvas.height = Math.round(height * dpr)
    this.canvas.style.width = `${width}px`
    this.canvas.style.height = `${height}px`
    this.canvas.style.left = `${offsetX}px`
    this.canvas.style.top = `${offsetY}px`
    this.gl.viewport(0, 0, this.canvas.width, this.canvas.height)
  }

  /** 仅更新布局参数，不重新创建 canvas（性能优化） */
  updateLayout(layout: CanvasLayout): void {
    this.layout = layout
    const { width, height, offsetX, offsetY } = layout
    const dpr = this._pixelRatio
    this.canvas.width = Math.round(width * dpr)
    this.canvas.height = Math.round(height * dpr)
    this.canvas.style.width = `${width}px`
    this.canvas.style.height = `${height}px`
    this.canvas.style.left = `${offsetX}px`
    this.canvas.style.top = `${offsetY}px`
    this.gl.viewport(0, 0, this.canvas.width, this.canvas.height)
  }

  destroy(): void {
    if (this.canvas.parentNode) {
      this.canvas.parentNode.removeChild(this.canvas)
    }
  }
}
