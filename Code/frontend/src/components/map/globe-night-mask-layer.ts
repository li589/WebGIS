/**
 * Globe「自然」档夜半球 — WebGL 球面网格层（替代 MapLibre image source）。
 *
 * 在 overlay canvas 上按真实 lat/lon 三角网格绘制；fragment 内算太阳高度角 h，
 * h < 0 硬边暗色。globe 投影下无世界副本、无 equirectangular 四角扭曲。
 */
import type { CustomRenderMethodInput, Map as MaplibreMap } from 'maplibre-gl'
import { subsolarDeclination, subsolarLongitude } from './globe-scene-utils'
import { lngLatToUnitSphere, NIGHT_MASK_RGBA } from './globe-night-mask'
import {
  buildGlobeNightMesh,
  GLOBE_NIGHT_MASK_FRAGMENT_SHADER,
  GLOBE_NIGHT_MASK_VERTEX_SHADER,
} from './globe-night-mask-shaders'
import { linkProgram } from './webgl-utils'
import { MAP_EVENT_RESIZE } from './types'
import { TILE_LAYER_ID } from './basemap-module'

const LAYER_ID = 'globe-night-mask-webgl'

export class GlobeNightMaskLayer {
  readonly id = LAYER_ID
  readonly type = 'custom' as const
  readonly renderingMode = '2d' as const

  private map: MaplibreMap | null = null
  private canvas: HTMLCanvasElement | null = null
  private gl: WebGLRenderingContext | null = null
  private initFailed = false

  private program: WebGLProgram | null = null
  private meshBuffer: WebGLBuffer | null = null
  private meshVertexCount = 0
  private attribLngLat = -1
  private uMatrix: WebGLUniformLocation | null = null
  private uSubsolarLon: WebGLUniformLocation | null = null
  private uDeclDeg: WebGLUniformLocation | null = null
  private uNightRgb: WebGLUniformLocation | null = null
  private uNightAlpha: WebGLUniformLocation | null = null

  private subsolarLon = 0
  private declDeg = 0
  private visible = false
  private needsRedraw = true

  private matrix = new Float32Array(16)
  private hasMatrix = false
  private readonly lastDrawnMatrix = new Float32Array(16)
  private hasLastDrawnMatrix = false

  private rafId: number | null = null
  private resizeHandler: (() => void) | null = null

  isUsable(): boolean {
    return !this.initFailed && this.gl !== null
  }

  setVisible(visible: boolean): void {
    if (this.visible !== visible) {
      this.visible = visible
      this.needsRedraw = true
    }
  }

  /** 更新太阳几何（本地时间 hour + 日期） */
  setSunState(hour: number, date?: Date, tzOffsetHours?: number): void {
    const nextLon = subsolarLongitude(hour, tzOffsetHours)
    const nextDecl = subsolarDeclination(date)
    if (nextLon !== this.subsolarLon || nextDecl !== this.declDeg) {
      this.subsolarLon = nextLon
      this.declDeg = nextDecl
      this.needsRedraw = true
    }
  }

  onAdd(map: MaplibreMap, _gl: WebGLRenderingContext): void {
    this.map = map
    this.initFailed = false
    const canvas = document.createElement('canvas')
    canvas.className = 'globe-night-mask-webgl-canvas'
    canvas.style.cssText =
      'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:3'
    map.getContainer().appendChild(canvas)
    this.canvas = canvas

    const gl =
      canvas.getContext('webgl', {
        alpha: true,
        antialias: false,
        premultipliedAlpha: true,
        preserveDrawingBuffer: false,
      }) ?? null
    if (!gl) {
      this.initFailed = true
      return
    }
    this.gl = gl

    try {
      this.program = linkProgram(gl, GLOBE_NIGHT_MASK_VERTEX_SHADER, GLOBE_NIGHT_MASK_FRAGMENT_SHADER)
      this.attribLngLat = gl.getAttribLocation(this.program, 'a_lnglat')
      this.uMatrix = gl.getUniformLocation(this.program, 'u_matrix')
      this.uSubsolarLon = gl.getUniformLocation(this.program, 'u_subsolarLon')
      this.uDeclDeg = gl.getUniformLocation(this.program, 'u_declDeg')
      this.uNightRgb = gl.getUniformLocation(this.program, 'u_nightRgb')
      this.uNightAlpha = gl.getUniformLocation(this.program, 'u_nightAlpha')
      this.uCamDir = gl.getUniformLocation(this.program, 'u_camDir')

      const mesh = buildGlobeNightMesh()
      this.meshVertexCount = mesh.length / 2
      this.meshBuffer = gl.createBuffer()
      gl.bindBuffer(gl.ARRAY_BUFFER, this.meshBuffer)
      gl.bufferData(gl.ARRAY_BUFFER, mesh, gl.STATIC_DRAW)
    } catch {
      this.initFailed = true
      return
    }

    this.resizeHandler = () => this.resizeCanvas()
    map.on(MAP_EVENT_RESIZE, this.resizeHandler)
    this.resizeCanvas()
    this.start()
    try {
      map.triggerRepaint()
    } catch {
      /* ignore */
    }
  }

  render(_gl: WebGLRenderingContext, _options: CustomRenderMethodInput): void {
    const transform = (
      this.map as unknown as {
        transform?: {
          getProjectionDataForCustomLayer?: (globe: boolean) => {
            mainMatrix?: number[]
            projectionTransition?: number
          }
        }
      }
    )?.transform
    const data = transform?.getProjectionDataForCustomLayer?.(true)
    // ⚠️ 3D 投影切换（globe↔mercator）期间的过渡矩阵是中间插值——
    // 用它绘制遮罩会错乱（首帧进 3D 时"无效果"，切档位重触发才恢复）。
    // 过渡未完成时标记矩阵未就绪，rAF 循环继续重试直到过渡完成。
    if (data && typeof data.projectionTransition === 'number' && data.projectionTransition < 0.999) {
      this.hasMatrix = false
      return
    }
    const fromTransform = data?.mainMatrix
    if (fromTransform && typeof fromTransform[0] === 'number') {
      for (let i = 0; i < 16; i++) this.matrix[i] = Number(fromTransform[i])
      this.hasMatrix = true
    }
  }

  onRemove(): void {
    this.stop()
    if (this.resizeHandler && this.map) {
      try {
        this.map.off(MAP_EVENT_RESIZE, this.resizeHandler)
      } catch {
        /* ignore */
      }
    }
    this.resizeHandler = null
    if (this.gl && this.meshBuffer) this.gl.deleteBuffer(this.meshBuffer)
    if (this.gl && this.program) this.gl.deleteProgram(this.program)
    this.meshBuffer = null
    this.program = null
    this.gl = null
    this.canvas?.remove()
    this.canvas = null
    this.map = null
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
      if (this.matrixChangedSinceDraw()) this.needsRedraw = true
      if (!this.needsRedraw) return
      if (!this.drawFrame()) return
      this.needsRedraw = false
      try {
        this.map?.triggerRepaint()
      } catch {
        /* ignore */
      }
    }
    this.rafId = requestAnimationFrame(tick)
  }

  private stop(): void {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId)
      this.rafId = null
    }
  }

  private matrixChangedSinceDraw(): boolean {
    if (!this.hasMatrix) return false
    if (!this.hasLastDrawnMatrix) return true
    for (let i = 0; i < 16; i++) {
      if (Math.abs(this.matrix[i] - this.lastDrawnMatrix[i]) > 1e-7) return true
    }
    return false
  }

  private drawFrame(): boolean {
    const gl = this.gl
    if (!gl || !this.program || !this.hasMatrix || !this.meshBuffer) return false

    gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight)
    gl.clearColor(0, 0, 0, 0)
    gl.clear(gl.COLOR_BUFFER_BIT)

    if (!this.visible) return true

    if (this.map) {
      const center = this.map.getCenter()
      this.camDir = lngLatToUnitSphere(center.lng, center.lat)
    }

    gl.disable(gl.CULL_FACE)
    gl.enable(gl.BLEND)
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA)
    gl.useProgram(this.program)
    gl.enableVertexAttribArray(this.attribLngLat)
    gl.bindBuffer(gl.ARRAY_BUFFER, this.meshBuffer)
    gl.vertexAttribPointer(this.attribLngLat, 2, gl.FLOAT, false, 0, 0)

    gl.uniformMatrix4fv(this.uMatrix, false, this.matrix)
    gl.uniform1f(this.uSubsolarLon, this.subsolarLon)
    gl.uniform1f(this.uDeclDeg, this.declDeg)
    gl.uniform3f(
      this.uNightRgb,
      NIGHT_MASK_RGBA.r / 255,
      NIGHT_MASK_RGBA.g / 255,
      NIGHT_MASK_RGBA.b / 255,
    )
    gl.uniform1f(this.uNightAlpha, NIGHT_MASK_RGBA.a / 255)
    gl.uniform3f(this.uCamDir, this.camDir[0], this.camDir[1], this.camDir[2])

    gl.drawArrays(gl.TRIANGLES, 0, this.meshVertexCount)

    for (let i = 0; i < 16; i++) this.lastDrawnMatrix[i] = this.matrix[i]
    this.hasLastDrawnMatrix = true
    return true
  }
}

let sharedGlobeNightMaskLayer: GlobeNightMaskLayer | null = null

export function getGlobeNightMaskLayer(): GlobeNightMaskLayer {
  if (!sharedGlobeNightMaskLayer) {
    sharedGlobeNightMaskLayer = new GlobeNightMaskLayer()
  }
  return sharedGlobeNightMaskLayer
}

export function ensureGlobeNightMaskLayerOnMap(
  map: MaplibreMap,
  onReady?: (layer: GlobeNightMaskLayer) => void,
): GlobeNightMaskLayer {
  const layer = getGlobeNightMaskLayer()
  if (map.getLayer(layer.id)) {
    onReady?.(layer)
    return layer
  }

  const finish = () => {
    if (!map.getLayer(layer.id)) return
    onReady?.(layer)
    try {
      map.triggerRepaint()
    } catch {
      /* ignore */
    }
  }

  const tryAdd = () => {
    if (map.getLayer(layer.id)) return
    try {
      const layers = map.getStyle()?.layers ?? []
      const tileIdx = layers.findIndex((l) => l.id === TILE_LAYER_ID)
      const before =
        tileIdx >= 0 && tileIdx + 1 < layers.length ? layers[tileIdx + 1].id : undefined
      map.addLayer(layer, before)
    } catch {
      /* style not ready */
    }
  }

  tryAdd()
  if (map.getLayer(layer.id)) {
    finish()
  } else {
    const onStyle = () => {
      tryAdd()
      finish()
      map.off('style.load', onStyle)
    }
    map.on('style.load', onStyle)
    // ⚠️ 兜底：style.load 事件可能已在 ensure 调用前触发过（basemap 先就绪），
    // 挂在 style.load 上的监听永远不会再触发 → 遮罩层永不添加（"每次进 3D
    // 都要切档位才显示"的根因）。延迟重试一次覆盖该竞态。
    setTimeout(onStyle, 600)
  }
  return layer
}

export function removeLegacyNightMaskRaster(map: MaplibreMap): void {
  const legacyLayerIds = [
    'globe-night-mask-raster',
    'globe-night-core-fill',
    'globe-night-transition-fill',
    'globe-terminator-line',
    'globe-night-hemisphere-fill',
    'globe-twilight-glow-fill',
  ]
  for (const id of legacyLayerIds) {
    if (map.getLayer(id)) {
      try {
        map.removeLayer(id)
      } catch {
        /* ignore */
      }
    }
  }
  for (const srcId of ['globe-night-mask', 'globe-night-hemisphere']) {
    if (map.getSource(srcId)) {
      try {
        map.removeSource(srcId)
      } catch {
        /* ignore */
      }
    }
  }
}
