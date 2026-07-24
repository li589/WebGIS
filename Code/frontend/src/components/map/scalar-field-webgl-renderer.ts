/**
 * 标量场 WebGL 层：独立 canvas + CustomLayer 借 MapLibre 投影矩阵。
 * 双纹理槽 + LUT + u_blend 支持时次交叉淡入。
 */
import type { Map as MaplibreMap, CustomRenderMethodInput } from 'maplibre-gl'
import { MAP_EVENT_RESIZE } from './types'
import {
  SCALAR_FIELD_FRAGMENT_SHADER,
  SCALAR_FIELD_VERTEX_SHADER,
  lngLatToMercatorNormalized,
} from './scalar-field-webgl-shaders'
import type { EncodedScalarTexture } from './scalar-field-webgl-texture'
import {
  computeWorldWrapOffsets,
  extractMercatorProjectionMatrix,
} from './wind-particle-webgl-renderer'

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
    console.warn('[ScalarFieldWebGL] shader compile failed', gl.getShaderInfoLog(shader))
    gl.deleteShader(shader)
    return null
  }
  return shader
}

function linkProgram(gl: WebGLRenderingContext, vsSrc: string, fsSrc: string): WebGLProgram | null {
  const vs = compileShader(gl, gl.VERTEX_SHADER, vsSrc)
  const fs = compileShader(gl, gl.FRAGMENT_SHADER, fsSrc)
  if (!vs || !fs) return null
  const prog = gl.createProgram()
  if (!prog) return null
  gl.attachShader(prog, vs)
  gl.attachShader(prog, fs)
  gl.linkProgram(prog)
  gl.deleteShader(vs)
  gl.deleteShader(fs)
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
    console.warn('[ScalarFieldWebGL] program link failed', gl.getProgramInfoLog(prog))
    gl.deleteProgram(prog)
    return null
  }
  return prog
}

function uploadRgbaTexture(
  gl: WebGLRenderingContext,
  tex: WebGLTexture,
  encoded: EncodedScalarTexture,
): void {
  gl.bindTexture(gl.TEXTURE_2D, tex)
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, 0)
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
}

export class ScalarFieldWebGLLayer {
  readonly id: string
  readonly type = 'custom' as const
  readonly renderingMode = '2d' as const

  private map: MaplibreMap | null = null
  private canvas: HTMLCanvasElement | null = null
  private gl: WebGLRenderingContext | null = null
  private initFailed = false

  private program: WebGLProgram | null = null
  private attribLngLat = -1
  private uMatrix: WebGLUniformLocation | null = null
  private uFieldA: WebGLUniformLocation | null = null
  private uFieldB: WebGLUniformLocation | null = null
  private uPalette: WebGLUniformLocation | null = null
  private uBounds: WebGLUniformLocation | null = null
  private uBlend: WebGLUniformLocation | null = null
  private uOpacity: WebGLUniformLocation | null = null
  private uPlaceholder: WebGLUniformLocation | null = null
  private quadBuffer: WebGLBuffer | null = null
  /** 灰底占位 quad（视口 bounds）：数据未到的区域淡灰打底，数据 quad 覆盖上色 */
  private viewportQuadBuffer: WebGLBuffer | null = null
  private viewportBounds: { west: number; south: number; east: number; north: number } | null = null

  private texA: WebGLTexture | null = null
  private texB: WebGLTexture | null = null
  private paletteTex: WebGLTexture | null = null
  /** 已上传到 texA / texB 的数据引用（去重，避免每次 flush 双纹理全量重传） */
  private uploadedA: EncodedScalarTexture | null = null
  private uploadedB: EncodedScalarTexture | null = null
  private bounds: { west: number; south: number; east: number; north: number } | null = null
  private blend = 0
  private opacity = 0.78
  private hasData = false
  private pendingA: EncodedScalarTexture | null = null
  private pendingB: EncodedScalarTexture | null = null
  private pendingLut: Uint8Array | null = null

  private matrix = new Float32Array(16)
  private hasMatrix = false
  /** 世界包裹绘制时的临时矩阵（避免每帧分配） */
  private readonly tempMatrix = new Float32Array(16)
  private readonly lastDrawnMatrix = new Float32Array(16)
  private hasLastDrawnMatrix = false
  /** 脏标记：仅在数据/调色板/透明度/矩阵变化或 blend 进行中时重绘 */
  private needsRedraw = true
  private rafId: number | null = null
  private resizeHandler: (() => void) | null = null

  private blendAnim: {
    from: number
    to: number
    startMs: number
    durationMs: number
    token: number
  } | null = null

  constructor(id = 'scalar-field-webgl') {
    this.id = id
  }

  isUsable(): boolean {
    return !this.initFailed && this.gl !== null
  }

  onAdd(map: MaplibreMap, _gl: WebGLRenderingContext): void {
    this.map = map
    this.initFailed = false
    const canvas = document.createElement('canvas')
    canvas.className = 'scalar-field-webgl-canvas'
    canvas.style.cssText =
      'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:4'
    map.getContainer().appendChild(canvas)
    this.canvas = canvas

    const gl = (canvas.getContext('webgl2', {
      alpha: true,
      antialias: false,
      premultipliedAlpha: false,
    }) ||
      canvas.getContext('webgl', {
        alpha: true,
        antialias: false,
        premultipliedAlpha: false,
      })) as WebGLRenderingContext | null
    if (!gl) {
      this.initFailed = true
      canvas.remove()
      this.canvas = null
      return
    }
    this.gl = gl
    gl.disable(gl.DEPTH_TEST)
    gl.enable(gl.BLEND)
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA)

    this.program = linkProgram(gl, SCALAR_FIELD_VERTEX_SHADER, SCALAR_FIELD_FRAGMENT_SHADER)
    if (!this.program) {
      this.initFailed = true
      return
    }
    this.attribLngLat = gl.getAttribLocation(this.program, 'a_lnglat')
    this.uMatrix = gl.getUniformLocation(this.program, 'u_matrix')
    this.uFieldA = gl.getUniformLocation(this.program, 'u_fieldA')
    this.uFieldB = gl.getUniformLocation(this.program, 'u_fieldB')
    this.uPalette = gl.getUniformLocation(this.program, 'u_palette')
    this.uBounds = gl.getUniformLocation(this.program, 'u_bounds')
    this.uBlend = gl.getUniformLocation(this.program, 'u_blend')
    this.uOpacity = gl.getUniformLocation(this.program, 'u_opacity')
    this.uPlaceholder = gl.getUniformLocation(this.program, 'u_placeholder')

    this.quadBuffer = gl.createBuffer()
    this.viewportQuadBuffer = gl.createBuffer()
    this.texA = gl.createTexture()
    this.texB = gl.createTexture()
    this.paletteTex = gl.createTexture()

    this.resizeHandler = () => this.resizeCanvas()
    map.on(MAP_EVENT_RESIZE, this.resizeHandler)
    this.resizeCanvas()
    this.flushPending()
    this.start()
  }

  onRemove(): void {
    this.teardown()
  }

  render(_gl: WebGLRenderingContext, options: CustomRenderMethodInput): void {
    const mat = extractMercatorProjectionMatrix(options)
    if (mat) {
      for (let i = 0; i < 16; i++) this.matrix[i] = Number(mat[i])
      this.hasMatrix = true
    } else {
      this.refreshProjectionMatrix()
    }
  }

  private refreshProjectionMatrix(): void {
    const transform = (
      this.map as unknown as {
        transform?: {
          getProjectionDataForCustomLayer?: (applyGlobe?: boolean) => {
            mainMatrix?: ArrayLike<number>
          }
        }
      }
    )?.transform
    const fromTransform = transform?.getProjectionDataForCustomLayer?.(false)?.mainMatrix
    if (fromTransform && typeof fromTransform[0] === 'number') {
      for (let i = 0; i < 16; i++) this.matrix[i] = Number(fromTransform[i])
      this.hasMatrix = true
    }
  }

  setOpacity(opacity: number): void {
    const next = Math.max(0.05, Math.min(1, opacity))
    if (next !== this.opacity) this.needsRedraw = true
    this.opacity = next
  }

  setPaletteLUT(lut: Uint8Array): void {
    this.pendingLut = lut
    this.needsRedraw = true
    if (this.gl) this.flushPending()
  }

  /**
   * 上传新时次纹理。
   * - 首次：写入 A，blend=0
   * - 其后：A←旧 B（或当前显示），B←新数据，启动 crossfade
   */
  setFieldData(
    encoded: EncodedScalarTexture,
    options?: { crossfadeMs?: number; token?: number },
  ): void {
    const crossfadeMs = options?.crossfadeMs ?? 0
    const token = options?.token ?? 0

    if (!this.hasData || !this.gl || crossfadeMs <= 0) {
      this.pendingA = encoded
      this.pendingB = encoded
      this.bounds = {
        west: encoded.west,
        south: encoded.south,
        east: encoded.east,
        north: encoded.north,
      }
      this.blend = 0
      this.blendAnim = null
      this.hasData = true
      this.needsRedraw = true
      if (this.gl) this.flushPending()
      this.updateQuad()
      return
    }

    // 将当前显示结果固定到 A：若 blend≈1 则 B 已是当前，交换语义用 pending
    this.pendingA = this.pendingB ?? this.pendingA ?? encoded
    this.pendingB = encoded
    this.bounds = {
      west: encoded.west,
      south: encoded.south,
      east: encoded.east,
      north: encoded.north,
    }
    this.needsRedraw = true
    this.flushPending()
    this.updateQuad()
    this.blend = 0
    this.blendAnim = {
      from: 0,
      to: 1,
      startMs: performance.now(),
      durationMs: crossfadeMs,
      token,
    }
  }

  /** 取消进行中的淡入（token 不匹配时由 controller 调用） */
  cancelBlend(exceptToken?: number): void {
    if (this.blendAnim && exceptToken !== undefined && this.blendAnim.token === exceptToken) return
    if (this.blendAnim) {
      this.blend = 1
      this.pendingA = this.pendingB
      this.blendAnim = null
      this.needsRedraw = true
    }
  }

  private flushPending(): void {
    const gl = this.gl
    if (!gl) return
    // A 待传数据已在 B 纹理中（crossfade / blend 完成）：交换纹理槽，省一次全量上传
    if (
      this.pendingA &&
      this.pendingA === this.uploadedB &&
      this.pendingA !== this.uploadedA &&
      this.texA &&
      this.texB
    ) {
      const tmpTex = this.texA
      this.texA = this.texB
      this.texB = tmpTex
      const tmpUp = this.uploadedA
      this.uploadedA = this.uploadedB
      this.uploadedB = tmpUp
    }
    // 引用去重：同一数据对象不重复 texImage2D
    if (this.pendingA && this.texA && this.pendingA !== this.uploadedA) {
      uploadRgbaTexture(gl, this.texA, this.pendingA)
      this.uploadedA = this.pendingA
    }
    if (this.pendingB && this.texB && this.pendingB !== this.uploadedB) {
      uploadRgbaTexture(gl, this.texB, this.pendingB)
      this.uploadedB = this.pendingB
    }
    if (this.pendingLut && this.paletteTex) {
      gl.bindTexture(gl.TEXTURE_2D, this.paletteTex)
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, 0)
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR)
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
      gl.texImage2D(
        gl.TEXTURE_2D,
        0,
        gl.RGBA,
        256,
        1,
        0,
        gl.RGBA,
        gl.UNSIGNED_BYTE,
        this.pendingLut,
      )
    }
  }

  private updateQuad(): void {
    const gl = this.gl
    if (!gl || !this.quadBuffer || !this.bounds) return
    const { west, south, east, north } = this.bounds
    const verts = new Float32Array([west, south, east, south, west, north, east, north])
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quadBuffer)
    gl.bufferData(gl.ARRAY_BUFFER, verts, gl.STATIC_DRAW)
  }

  /** 设置灰底占位的视口 bounds；null 清除占位 */
  setViewportBounds(
    bounds: { west: number; south: number; east: number; north: number } | null,
  ): void {
    const changed =
      bounds === null
        ? this.viewportBounds !== null
        : !this.viewportBounds ||
          this.viewportBounds.west !== bounds.west ||
          this.viewportBounds.east !== bounds.east ||
          this.viewportBounds.south !== bounds.south ||
          this.viewportBounds.north !== bounds.north
    if (!changed) return
    this.viewportBounds = bounds ? { ...bounds } : null
    const gl = this.gl
    if (gl && this.viewportQuadBuffer && bounds) {
      const { west, south, east, north } = bounds
      const verts = new Float32Array([west, south, east, south, west, north, east, north])
      gl.bindBuffer(gl.ARRAY_BUFFER, this.viewportQuadBuffer)
      gl.bufferData(gl.ARRAY_BUFFER, verts, gl.STATIC_DRAW)
    }
    this.needsRedraw = true
  }

  private resizeCanvas(): void {
    if (!this.canvas || !this.map) return
    const container = this.map.getContainer()
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const w = container.clientWidth
    const h = container.clientHeight
    this.canvas.width = Math.round(w * dpr)
    this.canvas.height = Math.round(h * dpr)
    this.canvas.style.width = `${w}px`
    this.canvas.style.height = `${h}px`
    this.gl?.viewport(0, 0, this.canvas.width, this.canvas.height)
    this.needsRedraw = true
  }

  private start(): void {
    if (this.rafId !== null) return
    const tick = () => {
      this.rafId = requestAnimationFrame(tick)
      // 矩阵每帧比对（廉价 16 float）：平移/缩放时变化 → 触发重绘。
      // 数据静止 + 相机静止时不重绘也不 triggerRepaint，MapLibre 得以休眠，
      // 避免强制底图全程 60fps 重绘拖慢整个浏览器。
      this.refreshProjectionMatrix()
      if (this.matrixChangedSinceDraw()) this.needsRedraw = true
      if (this.blendAnim) this.needsRedraw = true
      if (!this.needsRedraw) return
      if (!this.drawFrame()) return
      // blend 进行中持续重绘，否则一帧即可
      this.needsRedraw = this.blendAnim !== null
      try {
        this.map?.triggerRepaint()
      } catch {
        /* ignore */
      }
    }
    this.rafId = requestAnimationFrame(tick)
  }

  /** 与最近一次实际绘制的矩阵比对；尚未绘制过视为已变化 */
  private matrixChangedSinceDraw(): boolean {
    if (!this.hasMatrix) return false
    if (!this.hasLastDrawnMatrix) return true
    for (let i = 0; i < 16; i++) {
      if (Math.abs(this.matrix[i] - this.lastDrawnMatrix[i]) > 1e-7) return true
    }
    return false
  }

  private stop(): void {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId)
      this.rafId = null
    }
  }

  private drawFrame(): boolean {
    const gl = this.gl
    if (!gl || !this.program || !this.hasMatrix) return false
    if (!this.hasData && !this.viewportBounds) return false

    if (this.blendAnim) {
      const t = (performance.now() - this.blendAnim.startMs) / this.blendAnim.durationMs
      if (t >= 1) {
        this.blend = 1
        this.pendingA = this.pendingB
        this.blendAnim = null
        // A←B：经 flushPending 的纹理槽交换完成，零上传
        this.flushPending()
      } else {
        // ease-out cubic
        const e = 1 - (1 - t) ** 3
        this.blend = this.blendAnim.from + (this.blendAnim.to - this.blendAnim.from) * e
      }
    }

    gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight)
    gl.clearColor(0, 0, 0, 0)
    gl.clear(gl.COLOR_BUFFER_BIT)

    gl.useProgram(this.program)
    gl.enableVertexAttribArray(this.attribLngLat)
    gl.uniform1f(this.uOpacity, this.opacity)

    // 世界包裹：屏幕可见的每个世界副本各画一次（v_merc 由各片元自身插值得到，
    // 与绘制次数无关；副本仅需平移 matrix[12]），消除反子午线/低缩放下的半球空白
    const offsets = computeWorldWrapOffsets(this.matrix)

    // Pass 1：灰底占位（视口 bounds）——数据未到的区域淡灰打底
    if (this.viewportBounds && this.viewportQuadBuffer) {
      gl.uniform1f(this.uPlaceholder, 1)
      gl.uniform4f(
        this.uBounds,
        this.viewportBounds.west,
        this.viewportBounds.south,
        this.viewportBounds.east,
        this.viewportBounds.north,
      )
      gl.uniform1f(this.uBlend, 0)
      gl.bindBuffer(gl.ARRAY_BUFFER, this.viewportQuadBuffer)
      gl.vertexAttribPointer(this.attribLngLat, 2, gl.FLOAT, false, 0, 0)
      for (const offset of offsets) {
        this.tempMatrix.set(this.matrix)
        this.tempMatrix[12] += offset
        gl.uniformMatrix4fv(this.uMatrix, false, this.tempMatrix)
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
      }
    }

    // Pass 2：数据场（grid bounds）——覆盖灰底渐进上色；无数据片元 discard 透出灰底
    if (this.hasData && this.bounds && this.quadBuffer) {
      gl.uniform1f(this.uPlaceholder, 0)
      gl.activeTexture(gl.TEXTURE0)
      gl.bindTexture(gl.TEXTURE_2D, this.texA)
      gl.uniform1i(this.uFieldA, 0)
      gl.activeTexture(gl.TEXTURE1)
      gl.bindTexture(gl.TEXTURE_2D, this.texB)
      gl.uniform1i(this.uFieldB, 1)
      gl.activeTexture(gl.TEXTURE2)
      gl.bindTexture(gl.TEXTURE_2D, this.paletteTex)
      gl.uniform1i(this.uPalette, 2)
      gl.uniform4f(
        this.uBounds,
        this.bounds.west,
        this.bounds.south,
        this.bounds.east,
        this.bounds.north,
      )
      gl.uniform1f(this.uBlend, this.blend)
      gl.bindBuffer(gl.ARRAY_BUFFER, this.quadBuffer)
      gl.vertexAttribPointer(this.attribLngLat, 2, gl.FLOAT, false, 0, 0)
      for (const offset of offsets) {
        this.tempMatrix.set(this.matrix)
        this.tempMatrix[12] += offset
        gl.uniformMatrix4fv(this.uMatrix, false, this.tempMatrix)
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
      }
    }

    this.lastDrawnMatrix.set(this.matrix)
    this.hasLastDrawnMatrix = true
    return true
  }

  private teardown(): void {
    this.stop()
    if (this.map && this.resizeHandler) {
      this.map.off(MAP_EVENT_RESIZE, this.resizeHandler)
      this.resizeHandler = null
    }
    const gl = this.gl
    if (gl) {
      if (this.program) gl.deleteProgram(this.program)
      if (this.quadBuffer) gl.deleteBuffer(this.quadBuffer)
      if (this.viewportQuadBuffer) gl.deleteBuffer(this.viewportQuadBuffer)
      if (this.texA) gl.deleteTexture(this.texA)
      if (this.texB) gl.deleteTexture(this.texB)
      if (this.paletteTex) gl.deleteTexture(this.paletteTex)
    }
    this.program = null
    this.quadBuffer = null
    this.viewportQuadBuffer = null
    this.viewportBounds = null
    this.texA = null
    this.texB = null
    this.paletteTex = null
    this.gl = null
    this.canvas?.remove()
    this.canvas = null
    this.map = null
    this.hasData = false
    this.hasMatrix = false
  }

  destroy(): void {
    if (this.map && this.map.getLayer(this.id)) {
      try {
        this.map.removeLayer(this.id)
      } catch {
        this.teardown()
      }
    } else {
      this.teardown()
    }
  }
}

/** @internal */
export function probeScalarFieldWebGLSupport(doc: Document = document): {
  ok: boolean
  reason?: string
} {
  try {
    const canvas = doc.createElement('canvas')
    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl')
    if (!gl) return { ok: false, reason: 'no-webgl' }
    return { ok: true }
  } catch {
    return { ok: false, reason: 'probe-error' }
  }
}

/** 避免未使用导入被 tree-shake 误报（投影与 wind 共用） */
void lngLatToMercatorNormalized
