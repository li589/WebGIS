/**
 * 风羽（Wind Barb）渲染层 — WebGL2。
 *
 * 在风场网格点上绘制标准气象风羽符号：
 *   - 短线 = 5 m/s
 *   - 长线 = 10 m/s
 *   - 三角旗 = 50 m/s
 *   - 杆方向 = 风吹来的方向（气象风向）
 *
 * 符号使用 gl.LINES 批量 GPU 渲染，仅在地图移动/缩放时重绘。
 */
import type { Map as MaplibreMap } from 'maplibre-gl'
import type { WindGeoJSON } from './types'
import { DEFAULT_HEIGHT_SUFFIX, MAP_EVENT_MOVE, MAP_EVENT_MOVEEND, MAP_EVENT_RESIZE } from './types'
import {
  WebGLCanvas,
  computeCanvasLayout,
  buildGeoToNdc,
  createProgram,
  createDynamicFloat32Buffer,
  updateBufferData,
  createPlaceholderTexture,
} from './webgl-utils'

// ── 渲染参数常量 ─────────────────────────────────────────

/** 风羽圆圈固定半径（像素，shader 中的缩放系数） */
const BARB_CIRCLE_RADIUS_PX = 2.0

/** 三角旗间距系数（相对于 barbSize） */
const FLAG_SPACING_RATIO = 0.25

/** 三角旗垂直边宽度（像素） */
const FLAG_PERP_WIDTH_PX = 6

/** 气象风速单位（m/s）：三角旗=50，长线=10，短横线=5 */
const BARB_FLAG_UNIT = 50
const BARB_LONG_BARB_UNIT = 10
const BARB_SHORT_BARB_UNIT = 5

/** 风羽线段最小长度（像素），过滤过短线段 */
const MIN_BARB_LINE_LENGTH_PX = 0.5

/** 长线沿杆位置增量系数（相对于 flagSpacing） */
const LONG_BARB_POS_INCREMENT_RATIO = 0.6

/** 短线长度比例（相对于长线） */
const SHORT_BARB_LENGTH_RATIO = 0.55

/** 风羽 LOD 目标间距（像素） */
const BARB_TARGET_SPACING_PX = 80

/** 风羽视口剔除边距（像素） */
const BARB_VIEWPORT_CULLING_MARGIN_PX = 60

/** LOD 最低可视 zoom */
const BARB_MIN_VISIBLE_ZOOM = 3

// ── 类型定义 ─────────────────────────────────────────────

interface WindBarbData {
  lat: number
  lon: number
  speed: number
  direction: number
  row: number
  col: number
}

// ── 着色器源码 ────────────────────────────────────────────

/**
 * 通用线段着色器。
 * 每顶点 layout: [x, y, dx, dy, r, g, b, a]  (dx/dy 为线段方向向量，
 * 用于在片段着色器中根据到线段的距离计算 alpha，实现抗锯齿)
 */
const LINE_VERT_SRC = `#version 300 es
precision highp float;
layout(location = 0) in vec2 a_pos;
layout(location = 1) in vec2 a_dir;
layout(location = 2) in vec4 a_color;
uniform mat3 u_geoToNdc;
out vec4 v_color;
void main() {
  vec3 ndc = u_geoToNdc * vec3(a_pos, 1.0);
  gl_Position = vec4(ndc.xy, 0.0, 1.0);
  v_color = a_color;
}`

const LINE_FRAG_SRC = `#version 300 es
precision highp float;
in vec4 v_color;
out vec4 fragColor;
void main() {
  fragColor = v_color;
}`

/**
 * 返回圆形三角扇顶点着色器源码。
 * 圆圈半径通过参数注入，使 TypeScript 能追踪常量引用。
 */
function makeCircleVertSrc(radiusPx: number): string {
  return `#version 300 es
precision highp float;
layout(location = 0) in vec2 a_center;   // 圆心 canvas 内坐标
layout(location = 1) in vec3 a_color;    // RGB
layout(location = 2) in vec2 a_offset;   // 相对于圆心的偏移（半径 = 1）
uniform mat3 u_geoToNdc;
out vec3 v_color;
void main() {
  vec2 worldPos = a_center + a_offset * ${radiusPx};
  vec3 ndc = u_geoToNdc * vec3(worldPos, 1.0);
  gl_Position = vec4(ndc.xy, 0.0, 1.0);
  v_color = a_color;
}`
}

const CIRCLE_FRAG_SRC = `#version 300 es
precision highp float;
in vec3 v_color;
out vec4 fragColor;
void main() {
  fragColor = vec4(v_color, 1.0);
}`

// ── 预计算圆的偏移（三角扇，16 段） ───────────────────────

const CIRCLE_SEGS = 16

// ── 顶点格式常量 ──────────────────────────────────────────

// LINE: 每顶点 8 float = [x, y, dx, dy, r, g, b, a]
const FLOATS_PER_LINE_VERT = 8

// CIRCLE: 每顶点 8 float = [cx, cy, r, g, b, offsetX, offsetY]
const FLOATS_PER_CIRCLE_VERT = 7

export class WindBarbLayer {
  private map: MaplibreMap
  private glCanvas: WebGLCanvas

  // 线条渲染
  private lineProg!: WebGLProgram
  private lineBuf!: WebGLBuffer
  // 圆形渲染
  private circleProg!: WebGLProgram
  private circleBuf!: WebGLBuffer
  private placeholderTex!: WebGLTexture
  private loc_u_geoToNdc!: WebGLUniformLocation

  private data: WindBarbData[] = []

  private moveHandler: () => void
  private resizeHandler: () => void
  private rafId: number | null = null
  private isVisible = true
  private barbSize: number
  private gridCols = 0

  // 线条颜色
  private readonly STEM_COLOR  = { r: 0.863, g: 0.941, b: 1.0,   a: 0.90 }
  private readonly CIRCLE_COLOR = { r: 0.706, g: 0.902, b: 1.0,   a: 0.80 }

  constructor(map: MaplibreMap, geojson: WindGeoJSON, options?: { barbSize?: number }) {
    this.map = map
    this.barbSize = options?.barbSize ?? 24

    this.glCanvas = new WebGLCanvas(map)
    this.glCanvas.canvas.style.zIndex = '6'
    this.glCanvas.canvas.className = 'wind-barb-webgl'

    this.initGL()
    this.loadData(geojson)
    this.updateLayout()

    this.moveHandler = () => {
      if (this.rafId !== null) return
      this.rafId = requestAnimationFrame(() => {
        this.rafId = null
        this.updateLayout()
        this.draw()
      })
    }
    this.resizeHandler = () => { this.updateLayout(); this.draw() }
    map.on(MAP_EVENT_MOVE, this.moveHandler)
    map.on(MAP_EVENT_MOVEEND, this.moveHandler)
    map.on(MAP_EVENT_RESIZE, this.resizeHandler)
  }

  private initGL(): void {
    const gl = this.glCanvas.gl

    gl.enable(gl.BLEND)
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA)

    // 线条 program
    this.lineProg = createProgram(gl, LINE_VERT_SRC, LINE_FRAG_SRC)
    this.lineBuf = createDynamicFloat32Buffer(gl)

    // 圆形 program
    this.circleProg = createProgram(gl, makeCircleVertSrc(BARB_CIRCLE_RADIUS_PX), CIRCLE_FRAG_SRC)
    this.circleBuf = createDynamicFloat32Buffer(gl)

    // 占位纹理
    this.placeholderTex = createPlaceholderTexture(gl)

    // 线条顶点属性
    const lPos = gl.getAttribLocation(this.lineProg, 'a_pos')
    const lDir = gl.getAttribLocation(this.lineProg, 'a_dir')
    const lCol = gl.getAttribLocation(this.lineProg, 'a_color')
    gl.useProgram(this.lineProg)
    gl.vertexAttribPointer(lPos, 2, gl.FLOAT, false, FLOATS_PER_LINE_VERT * 4, 0)
    gl.vertexAttribPointer(lDir, 2, gl.FLOAT, false, FLOATS_PER_LINE_VERT * 4, 2 * 4)
    gl.vertexAttribPointer(lCol, 4, gl.FLOAT, false, FLOATS_PER_LINE_VERT * 4, 4 * 4)
    gl.enableVertexAttribArray(lPos)
    gl.enableVertexAttribArray(lDir)
    gl.enableVertexAttribArray(lCol)

    // 圆形顶点属性: [cx, cy, r, g, b, offsetX, offsetY]
    const cCenter = gl.getAttribLocation(this.circleProg, 'a_center')
    const cCol    = gl.getAttribLocation(this.circleProg, 'a_color')
    const cOffset = gl.getAttribLocation(this.circleProg, 'a_offset')
    gl.useProgram(this.circleProg)
    gl.vertexAttribPointer(cCenter, 2, gl.FLOAT, false, FLOATS_PER_CIRCLE_VERT * 4, 0)
    gl.vertexAttribPointer(cCol,    3, gl.FLOAT, false, FLOATS_PER_CIRCLE_VERT * 4, 2 * 4)
    gl.vertexAttribPointer(cOffset, 2, gl.FLOAT, false, FLOATS_PER_CIRCLE_VERT * 4, 5 * 4)
    gl.enableVertexAttribArray(cCenter)
    gl.enableVertexAttribArray(cCol)
    gl.enableVertexAttribArray(cOffset)

    this.loc_u_geoToNdc = gl.getUniformLocation(this.lineProg, 'u_geoToNdc')!
  }

  private updateLayout(): void {
    const layout = computeCanvasLayout(
      this.map,
      -180, 180, -90, 90,  // 全局范围（风羽不一定有完整网格）
    )
    this.glCanvas.updateLayout(layout)
  }

  private loadData(geojson: WindGeoJSON): void {
    const features = geojson?.features || []
    this.data = []
    this.gridCols = 0
    const firstProps = features[0]?.properties || {}
    const heightSuffix = firstProps.height ?? DEFAULT_HEIGHT_SUFFIX
    const speedKey = `wind_speed_${heightSuffix}`
    const directionKey = `wind_direction_${heightSuffix}`
    for (const f of features) {
      if (f.geometry?.type !== 'Point') continue
      const coords = f.geometry.coordinates
      const props = f.properties || {}
      this.data.push({
        lat: coords[1],
        lon: coords[0],
        speed: (props[speedKey] ?? props.wind_speed_10m ?? 0) as number,
        direction: (props[directionKey] ?? props.wind_direction_10m ?? 0) as number,
        row: props.row ?? 0,
        col: props.col ?? 0,
      })
      this.gridCols = Math.max(this.gridCols, (props.col ?? 0) + 1)
    }
  }

  /** 计算单个风羽符号的所有线段顶点，打包为 Float32Array */
  private buildBarbGeometry(
    cx: number, cy: number,   // canvas 内中心坐标
    dirCos: number, dirSin: number,  // 杆方向单位向量（cos/sin）
    speed: number,
    color: { r: number; g: number; b: number; a: number },
  ): { lines: Float32Array; circleCenters: [number, number][]; lineCount: number; circleCount: number } {
    const size = this.barbSize
    // 垂直于杆的单位向量（逆时针 90°）
    const perpCos = dirCos   // 旋转 90°: (cos, sin) -> (-sin, cos)
    const perpSin = -dirSin

    const vertices: number[] = []
    const circleCenters: [number, number][] = []

    // 气象风向：风吹来的方向，杆从圆圈指向风吹来的方向
    // stem: 从 (cx, cy) 指向 (cx + stemDx, cy + stemDy)
    const stemDx = -dirSin * size  // 负 sin = cos(90°+θ)
    const stemDy =  dirCos * size  //  cos(90°+θ) = -sin(θ)

    // 圆圈
    circleCenters.push([cx, cy])

    // 三角旗参数
    const flagSpacing = size * FLAG_SPACING_RATIO
    const perpX = perpCos * FLAG_PERP_WIDTH_PX
    const perpY = perpSin * FLAG_PERP_WIDTH_PX

    // 风速分解
    let remaining = Math.round(speed)
    const flags50 = Math.floor(remaining / BARB_FLAG_UNIT); remaining -= flags50 * BARB_FLAG_UNIT
    const flags10 = Math.floor(remaining / BARB_LONG_BARB_UNIT); remaining -= flags10 * BARB_LONG_BARB_UNIT
    const flags5  = Math.floor(remaining / BARB_SHORT_BARB_UNIT)

    const addLine = (x1: number, y1: number, x2: number, y2: number) => {
      const dx = x2 - x1, dy = y2 - y1
      const len = Math.hypot(dx, dy)
      if (len < MIN_BARB_LINE_LENGTH_PX) return
      // 端点 + 反向端点（组成宽线）
      const nx = dx / len, ny = dy / len
      vertices.push(x1, y1, nx, ny, color.r, color.g, color.b, color.a)
      vertices.push(x2, y2, nx, ny, color.r, color.g, color.b, color.a)
    }

    // 杆（用两倍的宽度，画一个细矩形）
    addLine(cx, cy, cx + stemDx, cy + stemDy)

    let pos = 0

    // 三角旗（50 m/s）
    for (let i = 0; i < flags50; i++) {
      const fx = cx + stemDx - pos * (-stemDx / size) * flagSpacing
      const fy = cy + stemDy - pos * (-stemDy / size) * flagSpacing
      const ex = fx - perpX * 2
      const ey = fy - perpY * 2
      const bx = fx - (-stemDx / size) * flagSpacing
      const by = fy - (-stemDy / size) * flagSpacing
      addLine(fx, fy, ex, ey)
      addLine(ex, ey, bx, by)
      addLine(bx, by, fx, fy)
      pos += 1
    }

    // 长线（10 m/s）
    for (let i = 0; i < flags10; i++) {
      const fx = cx + stemDx - pos * (-stemDx / size) * flagSpacing
      const fy = cy + stemDy - pos * (-stemDy / size) * flagSpacing
      addLine(fx, fy, fx + perpX, fy + perpY)
      pos += LONG_BARB_POS_INCREMENT_RATIO
    }

    // 短线（5 m/s）— 短一半
    if (flags5 > 0) {
      const fx = cx + stemDx - pos * (-stemDx / size) * flagSpacing
      const fy = cy + stemDy - pos * (-stemDy / size) * flagSpacing
      addLine(fx, fy, fx + perpX * SHORT_BARB_LENGTH_RATIO, fy + perpY * SHORT_BARB_LENGTH_RATIO)
    }

    const lineCount = vertices.length / FLOATS_PER_LINE_VERT
    return {
      lines: new Float32Array(vertices),
      circleCenters,
      lineCount,
      circleCount: circleCenters.length,
    }
  }

  /** 批量计算所有风羽符号几何 */
  private buildAllBarbs(): { lineData: Float32Array; circleData: Float32Array; lineCount: number; circleCount: number } {
    const zoom = this.map.getZoom()
    if (zoom < BARB_MIN_VISIBLE_ZOOM || this.data.length === 0) {
      return { lineData: new Float32Array(0), circleData: new Float32Array(0), lineCount: 0, circleCount: 0 }
    }

    const { width: cw, height: ch, offsetX: ox, offsetY: oy } = this.glCanvas.layout
    if (cw < 1 || ch < 1) {
      return { lineData: new Float32Array(0), circleData: new Float32Array(0), lineCount: 0, circleCount: 0 }
    }

    // LOD：估算步长
    const targetSpacingPx = BARB_TARGET_SPACING_PX
    let gridPixelSize = 1
    if (this.data.length >= 2) {
      const p0 = this.map.project([this.data[0].lon, this.data[0].lat])
      const p1 = this.map.project([this.data[1].lon, this.data[1].lat])
      gridPixelSize = Math.hypot(p1.x - p0.x, p1.y - p0.y)
    }
    const step = Math.max(1, Math.round(targetSpacingPx / Math.max(gridPixelSize, 1)))

    const allLines: number[] = []
    const allCircles: number[] = []
    let lineCount = 0
    let circleCount = 0

    for (const d of this.data) {
      if (d.row % step !== 0 || d.col % step !== 0) continue
      const screen = this.map.project([d.lon, d.lat])
      const cx = screen.x - ox
      const cy = screen.y - oy
      // 视口裁剪
      if (cx < -BARB_VIEWPORT_CULLING_MARGIN_PX || cx > cw + BARB_VIEWPORT_CULLING_MARGIN_PX || cy < -BARB_VIEWPORT_CULLING_MARGIN_PX || cy > ch + BARB_VIEWPORT_CULLING_MARGIN_PX) continue

      const rad = (d.direction * Math.PI) / 180
      const dirCos = Math.cos(rad)
      const dirSin = Math.sin(rad)

      const { lines, circleCenters, lineCount: lc } =
        this.buildBarbGeometry(cx, cy, dirCos, dirSin, d.speed, this.STEM_COLOR)

      // 追加线条
      for (let i = 0; i < lines.length; i++) allLines.push(lines[i])
      lineCount += lc

      // 追加圆圈（每个圆: 中心顶点 + CIRCLE_SEGS+1 个扇形顶点）
      for (const [ccx, ccy] of circleCenters) {
        // 中心点
        allCircles.push(ccx, ccy, this.CIRCLE_COLOR.r, this.CIRCLE_COLOR.g, this.CIRCLE_COLOR.b, 0, 0)
        // 扇形端点
        for (let i = 0; i <= CIRCLE_SEGS; i++) {
          const angle = (i / CIRCLE_SEGS) * Math.PI * 2
          allCircles.push(
            ccx, ccy,
            this.CIRCLE_COLOR.r, this.CIRCLE_COLOR.g, this.CIRCLE_COLOR.b,
            Math.cos(angle), Math.sin(angle),
          )
        }
        circleCount += 1
      }
    }

    return {
      lineData: new Float32Array(allLines),
      circleData: new Float32Array(allCircles),
      lineCount,
      circleCount: circleCount * (CIRCLE_SEGS + 2),
    }
  }

  private draw(): void {
    if (!this.isVisible) return
    const zoom = this.map.getZoom()
    if (zoom < BARB_MIN_VISIBLE_ZOOM) return

    const gl = this.glCanvas.gl
    gl.clearColor(0, 0, 0, 0)
    gl.clear(gl.COLOR_BUFFER_BIT)

    const { width: cw, height: ch, offsetX: ox, offsetY: oy } = this.glCanvas.layout
    const geoToNdc = buildGeoToNdc(cw, ch, ox, oy)

    const { lineData, circleData, lineCount, circleCount } = this.buildAllBarbs()

    if (lineCount === 0 && circleCount === 0) return

    // 绘制线条
    if (lineCount > 0) {
      updateBufferData(gl, this.lineBuf, lineData, gl.DYNAMIC_DRAW)
      gl.useProgram(this.lineProg)
      gl.uniformMatrix3fv(this.loc_u_geoToNdc, false, geoToNdc.m)
      gl.drawArrays(gl.LINES, 0, lineCount)
    }

    // 绘制圆圈（三角扇）
    if (circleCount > 0) {
      updateBufferData(gl, this.circleBuf, circleData, gl.DYNAMIC_DRAW)
      gl.useProgram(this.circleProg)
      gl.uniformMatrix3fv(this.loc_u_geoToNdc, false, geoToNdc.m)
      gl.drawArrays(gl.TRIANGLE_FAN, 0, circleCount * (CIRCLE_SEGS + 2))
    }
  }

  setVisible(visible: boolean): void {
    this.isVisible = visible
    if (!visible) {
      const gl = this.glCanvas.gl
      gl.clearColor(0, 0, 0, 0)
      gl.clear(gl.COLOR_BUFFER_BIT)
    } else {
      this.draw()
    }
  }

  updateGeoJSON(geojson: WindGeoJSON): void {
    this.loadData(geojson)
    this.updateLayout()
    this.draw()
  }

  destroy(): void {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId)
      this.rafId = null
    }
    this.map.off(MAP_EVENT_MOVE, this.moveHandler)
    this.map.off(MAP_EVENT_MOVEEND, this.moveHandler)
    this.map.off(MAP_EVENT_RESIZE, this.resizeHandler)
    const gl = this.glCanvas.gl
    gl.deleteProgram(this.lineProg)
    gl.deleteProgram(this.circleProg)
    gl.deleteBuffer(this.lineBuf)
    gl.deleteBuffer(this.circleBuf)
    gl.deleteTexture(this.placeholderTex)
    this.glCanvas.destroy()
  }
}
