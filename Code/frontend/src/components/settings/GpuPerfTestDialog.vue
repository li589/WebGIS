<script setup lang="ts">
/**
 * GPU 性能检测对话框：纯前端图形性能基准测试。
 *
 * 测试场景：
 * 1. WebGL Mandelbulb 光线追踪 — 片段着色器 ALU 压力
 * 2. WebGL 粒子系统 (20000) — 顶点吞吐 + 混合
 * 3. Canvas 2D 动画 (1500 渐变粒子) — 2D 栅格化压力
 * 4. GPU 信息详情 — WebGL renderer/vendor/参数
 *
 * 测试期间通过 CustomEvent 通知页面暂停地图渲染与动画，确保结果准确。
 * 结果仅显示在当前会话，不保存到后端。
 */
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()

// ── 类型 ──────────────────────────────────────────────────────────

type TestStatus = 'idle' | 'running' | 'done'
type ResultStatus = 'pass' | 'warn' | 'fail'

interface FrameStats {
  fps: number
  frameTimeMs: number
  minFps: number
  maxFps: number
  stability: number
  totalFrames: number
}

interface TestResult {
  name: string
  subtitle?: string
  value: string
  numericValue?: number
  detail: string
  stabilityScore?: number
  status: ResultStatus
}

// ── 常量 ──────────────────────────────────────────────────────────

const WARMUP_MS = 800
const MEASURE_MS = 2200
const CANVAS_SIZE = 512
const PARTICLE_COUNT = 20000
const CANVAS2D_PARTICLE_COUNT = 1500

// ── 着色器源码 ────────────────────────────────────────────────────

/** 全屏 quad 顶点着色器（通用） */
const QUAD_VS = `
attribute vec2 aPos;
void main() { gl_Position = vec4(aPos, 0.0, 1.0); }
`

/** Mandelbulb 光线追踪片段着色器 */
const MANDELBULB_FS = `
precision highp float;
uniform vec2 uResolution;
uniform float uTime;

float mandelbulbDE(vec3 pos) {
  vec3 z = pos;
  float dr = 1.0;
  float r = 0.0;
  for (int i = 0; i < 10; i++) {
    r = length(z);
    if (r > 2.0) break;
    float theta = acos(z.z / r);
    float phi = atan(z.y, z.x);
    dr = pow(r, 7.0) * 8.0 * dr + 1.0;
    float zr = pow(r, 8.0);
    theta *= 8.0;
    phi *= 8.0;
    z = zr * vec3(sin(theta) * cos(phi), sin(phi) * sin(theta), cos(theta));
    z += pos;
  }
  return 0.5 * log(r) * r / dr;
}

void main() {
  vec2 uv = (gl_FragCoord.xy - 0.5 * uResolution) / uResolution.y;
  vec3 ro = vec3(0.0, 0.0, 2.5);
  vec3 rd = normalize(vec3(uv, -1.5));
  float ca = cos(uTime * 0.3), sa = sin(uTime * 0.3);
  ro.xz = mat2(ca, -sa, sa, ca) * ro.xz;
  rd.xz = mat2(ca, -sa, sa, ca) * rd.xz;
  float t = 0.0;
  for (int i = 0; i < 64; i++) {
    vec3 p = ro + rd * t;
    float d = mandelbulbDE(p);
    if (d < 0.001) break;
    t += d;
    if (t > 10.0) break;
  }
  if (t > 10.0) {
    gl_FragColor = vec4(0.02, 0.02, 0.05, 1.0);
  } else {
    vec3 col = vec3(0.5 + 0.5 * sin(t * 0.8), 0.3 + 0.3 * sin(t * 1.2), 0.6 + 0.4 * sin(t * 0.5));
    gl_FragColor = vec4(col, 1.0);
  }
}
`

/** 粒子系统顶点着色器 */
const PARTICLE_VS = `
attribute vec2 aPosition;
attribute float aPhase;
uniform float uTime;
varying float vAlpha;
void main() {
  float t = uTime + aPhase;
  vec2 pos = aPosition;
  pos.x += sin(t * 2.0) * 0.15;
  pos.y += cos(t * 1.5 + aPhase) * 0.15;
  pos.y -= mod(t * 0.05, 2.0);
  pos = mod(pos + 1.0, 2.0) - 1.0;
  gl_Position = vec4(pos, 0.0, 1.0);
  gl_PointSize = 3.0;
  vAlpha = 0.5 + 0.5 * sin(t * 3.0);
}
`

/** 粒子系统片段着色器 */
const PARTICLE_FS = `
precision mediump float;
varying float vAlpha;
void main() {
  vec2 c = gl_PointCoord - 0.5;
  float d = length(c);
  if (d > 0.5) discard;
  float a = (1.0 - d * 2.0) * vAlpha;
  gl_FragColor = vec4(0.4, 0.7, 1.0, a);
}
`

// ── 响应式状态 ────────────────────────────────────────────────────

const testStatus = ref<TestStatus>('idle')
const results = ref<TestResult[]>([])
const progress = ref(0)
const currentTestName = ref('')
const currentPhase = ref('')
const previewContainer = ref<HTMLElement | null>(null)

// ── WebGL 工具函数 ────────────────────────────────────────────────

function createShader(gl: WebGLRenderingContext, type: number, source: string): WebGLShader | null {
  const shader = gl.createShader(type)
  if (!shader) return null
  gl.shaderSource(shader, source)
  gl.compileShader(shader)
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(shader)
    gl.deleteShader(shader)
    console.error('[GPU Perf] Shader compile error:', log)
    return null
  }
  return shader
}

function createProgram(
  gl: WebGLRenderingContext,
  vsSrc: string,
  fsSrc: string,
): WebGLProgram | null {
  const vs = createShader(gl, gl.VERTEX_SHADER, vsSrc)
  if (!vs) return null
  const fs = createShader(gl, gl.FRAGMENT_SHADER, fsSrc)
  if (!fs) {
    gl.deleteShader(vs)
    return null
  }
  const prog = gl.createProgram()
  if (!prog) {
    gl.deleteShader(vs)
    gl.deleteShader(fs)
    return null
  }
  gl.attachShader(prog, vs)
  gl.attachShader(prog, fs)
  gl.linkProgram(prog)
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
    const log = gl.getProgramInfoLog(prog)
    gl.deleteProgram(prog)
    gl.deleteShader(vs)
    gl.deleteShader(fs)
    console.error('[GPU Perf] Program link error:', log)
    return null
  }
  gl.deleteShader(vs)
  gl.deleteShader(fs)
  return prog
}

function createFullscreenQuad(
  gl: WebGLRenderingContext,
): { buffer: WebGLBuffer; loc: number } | null {
  const buf = gl.createBuffer()
  if (!buf) return null
  gl.bindBuffer(gl.ARRAY_BUFFER, buf)
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW)
  return { buffer: buf, loc: -1 }
}

// ── 统一测量框架 ──────────────────────────────────────────────────

async function measureAnimation(
  renderFrame: () => void,
  warmupMs = WARMUP_MS,
  measureMs = MEASURE_MS,
): Promise<FrameStats> {
  return new Promise<FrameStats>((resolve) => {
    const frameTimes: number[] = []
    let phase: 'warmup' | 'measure' = 'warmup'
    let phaseStart = performance.now()
    let lastTime = performance.now()

    function loop() {
      const now = performance.now()

      if (document.hidden) {
        phaseStart = now
        lastTime = now
        requestAnimationFrame(loop)
        return
      }

      const dt = now - lastTime
      lastTime = now
      renderFrame()

      if (phase === 'warmup') {
        if (now - phaseStart >= warmupMs) {
          phase = 'measure'
          phaseStart = now
          frameTimes.length = 0
        }
      } else {
        if (dt > 0 && dt < 1000) {
          frameTimes.push(dt)
        }
        if (now - phaseStart >= measureMs) {
          if (frameTimes.length === 0) {
            resolve({
              fps: 0,
              frameTimeMs: 0,
              minFps: 0,
              maxFps: 0,
              stability: 0,
              totalFrames: 0,
            })
            return
          }
          const avgFt = frameTimes.reduce((a, b) => a + b, 0) / frameTimes.length
          const minFt = Math.min(...frameTimes)
          const maxFt = Math.max(...frameTimes)
          const variance =
            frameTimes.reduce((s, ft) => s + (ft - avgFt) ** 2, 0) / frameTimes.length
          const stdDev = Math.sqrt(variance)
          const cv = avgFt > 0 ? stdDev / avgFt : 0
          const stability = Math.max(0, Math.min(100, 100 - cv * 200))

          resolve({
            fps: 1000 / avgFt,
            frameTimeMs: avgFt,
            minFps: 1000 / maxFt,
            maxFps: 1000 / minFt,
            stability,
            totalFrames: frameTimes.length,
          })
          return
        }
      }
      requestAnimationFrame(loop)
    }
    requestAnimationFrame(loop)
  })
}

function rateStatus(fps: number, passThreshold: number, warnThreshold: number): ResultStatus {
  if (fps >= passThreshold) return 'pass'
  if (fps >= warnThreshold) return 'warn'
  return 'fail'
}

function formatResult(
  name: string,
  subtitle: string,
  stats: FrameStats,
  passThreshold: number,
  warnThreshold: number,
): TestResult {
  const status = rateStatus(stats.fps, passThreshold, warnThreshold)
  return {
    name,
    subtitle,
    value: `${stats.fps.toFixed(1)} FPS`,
    numericValue: stats.fps,
    detail: `帧时间 ${stats.frameTimeMs.toFixed(1)}ms · 最低 ${stats.minFps.toFixed(0)} / 最高 ${stats.maxFps.toFixed(0)} FPS · ${stats.totalFrames} 帧`,
    stabilityScore: Math.round(stats.stability),
    status,
  }
}

// ── 测试实现 ──────────────────────────────────────────────────────

/** 测试 1：WebGL Mandelbulb 光线追踪 */
async function testWebglShaderStress(canvas: HTMLCanvasElement | null): Promise<TestResult> {
  if (!canvas)
    return { name: 'WebGL 着色器压力测试', value: '不可用', detail: '画布不可用', status: 'fail' }
  canvas.width = CANVAS_SIZE
  canvas.height = CANVAS_SIZE
  const gl = (canvas.getContext('webgl2', { antialias: false, preserveDrawingBuffer: false }) ??
    canvas.getContext('webgl', {
      antialias: false,
      preserveDrawingBuffer: false,
    })) as WebGLRenderingContext | null
  if (!gl) {
    return {
      name: 'WebGL 着色器压力测试',
      value: '不可用',
      detail: 'WebGL 不受支持',
      status: 'fail',
    }
  }

  // 检查 highp 精度
  const precFmt = gl.getShaderPrecisionFormat(gl.FRAGMENT_SHADER, gl.HIGH_FLOAT)
  const hasHighp = precFmt && precFmt.precision > 0

  const prog = createProgram(
    gl,
    QUAD_VS,
    hasHighp ? MANDELBULB_FS : MANDELBULB_FS.replace('highp', 'mediump'),
  )
  if (!prog) {
    return {
      name: 'WebGL 着色器压力测试',
      value: '编译失败',
      detail: '着色器编译失败',
      status: 'fail',
    }
  }

  const quad = createFullscreenQuad(gl)
  if (!quad) {
    gl.deleteProgram(prog)
    return {
      name: 'WebGL 着色器压力测试',
      value: '初始化失败',
      detail: '缓冲区创建失败',
      status: 'fail',
    }
  }

  gl.useProgram(prog)
  const posLoc = gl.getAttribLocation(prog, 'aPos')
  gl.bindBuffer(gl.ARRAY_BUFFER, quad.buffer)
  gl.enableVertexAttribArray(posLoc)
  gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 0, 0)

  const resLoc = gl.getUniformLocation(prog, 'uResolution')
  const timeLoc = gl.getUniformLocation(prog, 'uTime')
  gl.uniform2f(resLoc, CANVAS_SIZE, CANVAS_SIZE)

  gl.viewport(0, 0, CANVAS_SIZE, CANVAS_SIZE)

  let frame = 0
  const stats = await measureAnimation(() => {
    const t = frame * 0.016
    gl.uniform1f(timeLoc, t)
    gl.clearColor(0, 0, 0, 1)
    gl.clear(gl.COLOR_BUFFER_BIT)
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
    frame++
  })

  gl.deleteBuffer(quad.buffer)
  gl.deleteProgram(prog)

  return formatResult(
    'WebGL 着色器压力测试',
    `Mandelbulb 光线追踪 · ${CANVAS_SIZE}×${CANVAS_SIZE} · 64步/10迭代`,
    stats,
    30,
    15,
  )
}

/** 测试 2：WebGL 粒子系统 */
async function testWebglParticles(canvas: HTMLCanvasElement | null): Promise<TestResult> {
  if (!canvas)
    return { name: 'WebGL 粒子系统', value: '不可用', detail: '画布不可用', status: 'fail' }
  canvas.width = CANVAS_SIZE
  canvas.height = CANVAS_SIZE
  const gl = (canvas.getContext('webgl2', { antialias: false, preserveDrawingBuffer: false }) ??
    canvas.getContext('webgl', {
      antialias: false,
      preserveDrawingBuffer: false,
    })) as WebGLRenderingContext | null
  if (!gl) {
    return { name: 'WebGL 粒子系统', value: '不可用', detail: 'WebGL 不受支持', status: 'fail' }
  }

  const prog = createProgram(gl, PARTICLE_VS, PARTICLE_FS)
  if (!prog) {
    return { name: 'WebGL 粒子系统', value: '编译失败', detail: '着色器编译失败', status: 'fail' }
  }

  // 生成粒子数据：position(2F) + phase(1F)
  const particleData = new Float32Array(PARTICLE_COUNT * 3)
  for (let i = 0; i < PARTICLE_COUNT; i++) {
    particleData[i * 3] = Math.random() * 2 - 1
    particleData[i * 3 + 1] = Math.random() * 2 - 1
    particleData[i * 3 + 2] = Math.random() * Math.PI * 2
  }

  const buf = gl.createBuffer()
  if (!buf) {
    gl.deleteProgram(prog)
    return { name: 'WebGL 粒子系统', value: '初始化失败', detail: '缓冲区创建失败', status: 'fail' }
  }

  gl.useProgram(prog)
  gl.bindBuffer(gl.ARRAY_BUFFER, buf)
  gl.bufferData(gl.ARRAY_BUFFER, particleData, gl.STATIC_DRAW)

  const posLoc = gl.getAttribLocation(prog, 'aPosition')
  const phaseLoc = gl.getAttribLocation(prog, 'aPhase')
  gl.enableVertexAttribArray(posLoc)
  gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 12, 0)
  gl.enableVertexAttribArray(phaseLoc)
  gl.vertexAttribPointer(phaseLoc, 1, gl.FLOAT, false, 12, 8)

  const timeLoc = gl.getUniformLocation(prog, 'uTime')

  gl.viewport(0, 0, CANVAS_SIZE, CANVAS_SIZE)
  gl.enable(gl.BLEND)
  gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA)

  let frame = 0
  const stats = await measureAnimation(() => {
    const t = frame * 0.016
    gl.uniform1f(timeLoc, t)
    gl.clearColor(0.02, 0.02, 0.05, 1)
    gl.clear(gl.COLOR_BUFFER_BIT)
    gl.drawArrays(gl.POINTS, 0, PARTICLE_COUNT)
    frame++
  })

  gl.disable(gl.BLEND)
  gl.deleteBuffer(buf)
  gl.deleteProgram(prog)

  return formatResult(
    'WebGL 粒子系统',
    `${PARTICLE_COUNT.toLocaleString()} 粒子 · GL_POINTS · alpha 混合`,
    stats,
    45,
    30,
  )
}

/** 测试 3：Canvas 2D 动画 */
async function testCanvas2dAnimation(canvas: HTMLCanvasElement | null): Promise<TestResult> {
  if (!canvas)
    return { name: 'Canvas 2D 动画', value: '不可用', detail: '画布不可用', status: 'fail' }
  canvas.width = CANVAS_SIZE
  canvas.height = CANVAS_SIZE
  const ctx = canvas.getContext('2d')
  if (!ctx) {
    return { name: 'Canvas 2D 动画', value: '不可用', detail: 'Canvas 2D 不受支持', status: 'fail' }
  }

  interface Particle {
    x: number
    y: number
    vx: number
    vy: number
    r: number
    hue: number
  }

  const particles: Particle[] = Array.from({ length: CANVAS2D_PARTICLE_COUNT }, () => ({
    x: Math.random() * CANVAS_SIZE,
    y: Math.random() * CANVAS_SIZE,
    vx: (Math.random() - 0.5) * 5,
    vy: (Math.random() - 0.5) * 5,
    r: 3 + Math.random() * 8,
    hue: Math.random() * 360,
  }))

  const stats = await measureAnimation(() => {
    // 半透明背景擦除 — 拖尾效果
    ctx.fillStyle = 'rgba(0, 0, 0, 0.1)'
    ctx.fillRect(0, 0, CANVAS_SIZE, CANVAS_SIZE)

    for (const p of particles) {
      p.x += p.vx
      p.y += p.vy
      if (p.x < 0 || p.x > CANVAS_SIZE) p.vx *= -1
      if (p.y < 0 || p.y > CANVAS_SIZE) p.vy *= -1

      const grad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r)
      grad.addColorStop(0, `hsla(${p.hue}, 80%, 60%, 0.9)`)
      grad.addColorStop(1, `hsla(${p.hue}, 80%, 40%, 0)`)
      ctx.fillStyle = grad
      ctx.beginPath()
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2)
      ctx.fill()
    }
  })

  return formatResult(
    'Canvas 2D 动画',
    `${CANVAS2D_PARTICLE_COUNT} 渐变粒子 · createRadialGradient · 拖尾`,
    stats,
    45,
    30,
  )
}

/** 测试 4：GPU 信息详情（保留原有实现） */
async function testGpuInfo(): Promise<TestResult> {
  const canvas = document.createElement('canvas')
  canvas.width = 1
  canvas.height = 1
  const gl = (canvas.getContext('webgl2') ??
    canvas.getContext('webgl')) as WebGLRenderingContext | null
  if (!gl) {
    return { name: 'GPU 信息详情', value: '不可用', detail: 'WebGL 不受支持', status: 'fail' }
  }
  const debugInfo = gl.getExtension('WEBGL_debug_renderer_info')
  const renderer = debugInfo
    ? String(gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL))
    : String(gl.getParameter(gl.RENDERER))
  const vendor = debugInfo
    ? String(gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL))
    : String(gl.getParameter(gl.VENDOR))
  const maxTexSize = gl.getParameter(gl.MAX_TEXTURE_SIZE)
  const extensions = gl.getSupportedExtensions()?.length ?? 0
  const webglVersion = String(gl.getParameter(gl.VERSION))

  return {
    name: 'GPU 信息详情',
    value: renderer,
    detail: `${vendor} · WebGL ${webglVersion} · 最大纹理 ${maxTexSize}px · ${extensions} 个扩展`,
    status: 'pass',
  }
}

// ── 测试编排 ──────────────────────────────────────────────────────

type TestFn = (canvas: HTMLCanvasElement | null) => Promise<TestResult>

const TESTS: { id: string; name: string; needsCanvas: boolean; run: TestFn }[] = [
  { id: 'shader', name: 'WebGL 着色器压力测试', needsCanvas: true, run: testWebglShaderStress },
  { id: 'particle', name: 'WebGL 粒子系统', needsCanvas: true, run: testWebglParticles },
  { id: 'canvas2d', name: 'Canvas 2D 动画', needsCanvas: true, run: testCanvas2dAnimation },
  { id: 'gpuinfo', name: 'GPU 信息详情', needsCanvas: false, run: testGpuInfo },
]

async function runAllTests() {
  testStatus.value = 'running'
  results.value = []
  progress.value = 0
  window.dispatchEvent(new CustomEvent('cgda:perf-test-start'))

  try {
    for (let i = 0; i < TESTS.length; i++) {
      const test = TESTS[i]
      currentTestName.value = test.name
      currentPhase.value = '预热…'

      // 等待 Vue 渲染 v-if 条件容器后再访问 ref
      await nextTick()

      // 为需要画布的测试创建新 canvas
      let canvas: HTMLCanvasElement | null = null
      if (test.needsCanvas && previewContainer.value) {
        canvas = document.createElement('canvas')
        canvas.className = 'gpu-preview-canvas'
        canvas.width = CANVAS_SIZE
        canvas.height = CANVAS_SIZE
        previewContainer.value.innerHTML = ''
        previewContainer.value.appendChild(canvas)
      }

      // 更新阶段提示
      if (test.needsCanvas) {
        setTimeout(() => {
          currentPhase.value = '测量中…'
        }, WARMUP_MS)
      }

      try {
        const result = await test.run(canvas)
        results.value.push(result)
      } catch (e) {
        results.value.push({
          name: test.name,
          value: '失败',
          detail: e instanceof Error ? e.message : String(e),
          status: 'fail',
        })
      }

      progress.value = Math.round(((i + 1) / TESTS.length) * 100)
      await new Promise((r) => setTimeout(r, 100))
    }
  } finally {
    window.dispatchEvent(new CustomEvent('cgda:perf-test-end'))
    currentTestName.value = ''
    currentPhase.value = ''
  }
  testStatus.value = 'done'
}

// ── 总体评价 ──────────────────────────────────────────────────────

const overallRating = computed(() => {
  if (testStatus.value !== 'done' || results.value.length < 3) return null
  const testResults = results.value.slice(0, 3)
  const validResults = testResults.filter((r) => r.numericValue !== undefined)
  if (validResults.length === 0) return null
  const avgFps =
    validResults.reduce((sum, r) => sum + (r.numericValue ?? 0), 0) / validResults.length

  if (avgFps >= 45) return { label: '高性能', status: 'pass' as ResultStatus, avgFps }
  if (avgFps >= 30) return { label: '中等', status: 'pass' as ResultStatus, avgFps }
  if (avgFps >= 15) return { label: '基础', status: 'warn' as ResultStatus, avgFps }
  return { label: '不足', status: 'fail' as ResultStatus, avgFps }
})

// ── UI 处理 ───────────────────────────────────────────────────────

function reset() {
  testStatus.value = 'idle'
  results.value = []
  progress.value = 0
  currentTestName.value = ''
  currentPhase.value = ''
  if (previewContainer.value) {
    previewContainer.value.innerHTML = ''
  }
}

function handleClose() {
  emit('close')
  setTimeout(reset, 300)
}

onBeforeUnmount(() => {
  reset()
})
</script>

<template>
  <Teleport to="body">
    <div v-if="props.open" class="gpu-modal-mask" @click.self="handleClose">
      <div class="gpu-modal" role="dialog" aria-label="GPU 性能检测">
        <div class="gpu-header">
          <span class="gpu-title">GPU 性能检测</span>
          <button class="gpu-close" type="button" aria-label="关闭" @click="handleClose">×</button>
        </div>

        <div class="gpu-intro">
          <p class="gpu-intro-text">
            通过真实渲染场景（Mandelbulb 光线追踪、粒子系统、Canvas 2D 动画）测量 GPU
            性能。测试期间将暂停地图渲染与动画，结果仅显示在当前会话。
          </p>
          <button
            class="gpu-run-btn"
            type="button"
            :disabled="testStatus === 'running'"
            @click="runAllTests"
          >
            {{ testStatus === 'running' ? `检测中… ${progress}%` : '开始检测' }}
          </button>
        </div>

        <!-- 预览画面 -->
        <div v-if="testStatus === 'running' && currentTestName" class="gpu-preview">
          <div ref="previewContainer" class="gpu-preview-container"></div>
          <div class="gpu-preview-label">
            <span class="gpu-preview-test">{{ currentTestName }}</span>
            <span class="gpu-preview-phase">{{ currentPhase }}</span>
          </div>
        </div>

        <!-- 进度条 -->
        <div v-if="testStatus === 'running'" class="gpu-progress">
          <div class="gpu-progress-bar" :style="{ width: `${progress}%` }"></div>
        </div>

        <!-- 结果列表 -->
        <div v-if="results.length > 0" class="gpu-results">
          <div v-for="r in results" :key="r.name" class="gpu-result-item">
            <div class="gpu-result-header">
              <span class="gpu-result-name">{{ r.name }}</span>
              <span class="gpu-result-value" :class="`gpu-result--${r.status}`">{{ r.value }}</span>
            </div>
            <div v-if="r.subtitle" class="gpu-result-subtitle">{{ r.subtitle }}</div>
            <div class="gpu-result-detail">{{ r.detail }}</div>
            <div v-if="r.stabilityScore !== undefined" class="gpu-stability-row">
              <span class="gpu-stability-label">稳定性</span>
              <div class="gpu-stability-track">
                <div
                  class="gpu-stability-fill"
                  :class="`gpu-stability--${r.status}`"
                  :style="{ width: `${r.stabilityScore}%` }"
                ></div>
              </div>
              <span class="gpu-stability-pct">{{ r.stabilityScore }}%</span>
            </div>
          </div>
        </div>

        <!-- 总体评价 -->
        <div
          v-if="overallRating"
          class="gpu-summary"
          :class="`gpu-summary--${overallRating.status}`"
        >
          <span class="gpu-summary-label">总体评价</span>
          <span class="gpu-summary-value">{{ overallRating.label }}</span>
          <span class="gpu-summary-detail">平均 {{ overallRating.avgFps.toFixed(1) }} FPS</span>
        </div>

        <!-- 空状态 -->
        <div v-if="testStatus === 'idle' && results.length === 0" class="gpu-empty">
          点击"开始检测"运行性能测试
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.gpu-modal-mask {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
}

.gpu-modal {
  width: 480px;
  max-width: 90vw;
  max-height: 85vh;
  overflow-y: auto;
  padding: 1.2rem 1.4rem;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  background: var(--surface-2);
  backdrop-filter: blur(18px);
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.4);
}

.gpu-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.8rem;
}

.gpu-title {
  font-size: var(--font-size-body);
  font-weight: 600;
  color: var(--text-strong);
}

.gpu-close {
  width: 1.4rem;
  height: 1.4rem;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 1.1rem;
  line-height: 1;
  transition: background var(--motion-fast) var(--ease-soft);
}

.gpu-close:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.gpu-intro {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  margin-bottom: 0.8rem;
}

.gpu-intro-text {
  margin: 0;
  font-size: var(--font-size-caption);
  line-height: 1.5;
  color: var(--text-secondary);
}

.gpu-run-btn {
  align-self: flex-start;
  padding: 0.38rem 0.9rem;
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-md);
  background: var(--accent-surface);
  color: var(--accent-strong);
  font: inherit;
  font-size: var(--font-size-caption);
  font-weight: 500;
  cursor: pointer;
  transition:
    background var(--motion-fast) var(--ease-soft),
    opacity var(--motion-fast) var(--ease-soft);
}

.gpu-run-btn:hover:not(:disabled) {
  background: var(--surface-hover);
}

.gpu-run-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* ── 预览画面 ── */
.gpu-preview {
  margin-bottom: 0.8rem;
}

.gpu-preview-container {
  width: 100%;
  aspect-ratio: 1 / 1;
  max-height: 260px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-subtle);
  background: #000;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

.gpu-preview-canvas {
  width: 100%;
  height: 100%;
  display: block;
}

.gpu-preview-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 0.35rem;
  font-size: var(--font-size-caption);
}

.gpu-preview-test {
  color: var(--text-secondary);
  font-weight: 500;
}

.gpu-preview-phase {
  color: var(--text-muted);
}

/* ── 进度条 ── */
.gpu-progress {
  height: 4px;
  margin-bottom: 0.8rem;
  border-radius: var(--radius-pill);
  background: var(--surface-sunken);
  overflow: hidden;
}

.gpu-progress-bar {
  height: 100%;
  border-radius: var(--radius-pill);
  background: var(--accent);
  transition: width 0.2s var(--ease-standard);
}

/* ── 结果列表 ── */
.gpu-results {
  display: grid;
  gap: 0.5rem;
}

.gpu-result-item {
  padding: 0.5rem 0.6rem;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-sunken);
}

.gpu-result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.gpu-result-name {
  font-size: var(--font-size-caption);
  font-weight: 500;
  color: var(--text-secondary);
}

.gpu-result-value {
  font-size: var(--font-size-body);
  font-weight: 600;
}

.gpu-result--pass {
  color: var(--success);
}

.gpu-result--warn {
  color: var(--accent-warm);
}

.gpu-result--fail {
  color: var(--danger);
}

.gpu-result-subtitle {
  margin-top: 0.1rem;
  font-size: 0.7rem;
  color: var(--text-muted);
}

.gpu-result-detail {
  margin-top: 0.15rem;
  font-size: var(--font-size-caption);
  color: var(--text-muted);
  line-height: 1.4;
}

/* ── 稳定性进度条 ── */
.gpu-stability-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.3rem;
}

.gpu-stability-label {
  font-size: 0.7rem;
  color: var(--text-muted);
  flex-shrink: 0;
}

.gpu-stability-track {
  flex: 1;
  height: 4px;
  border-radius: var(--radius-pill);
  background: var(--surface-sunken);
  overflow: hidden;
}

.gpu-stability-fill {
  height: 100%;
  border-radius: var(--radius-pill);
  transition: width 0.4s var(--ease-standard);
}

.gpu-stability--pass {
  background: var(--success);
}

.gpu-stability--warn {
  background: var(--accent-warm);
}

.gpu-stability--fail {
  background: var(--danger);
}

.gpu-stability-pct {
  font-size: 0.7rem;
  color: var(--text-muted);
  flex-shrink: 0;
  min-width: 2rem;
  text-align: right;
}

/* ── 总体评价 ── */
.gpu-summary {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-top: 0.6rem;
  padding: 0.5rem 0.7rem;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-subtle);
}

.gpu-summary--pass {
  background: color-mix(in srgb, var(--success) 12%, transparent);
}

.gpu-summary--warn {
  background: color-mix(in srgb, var(--accent-warm) 12%, transparent);
}

.gpu-summary--fail {
  background: color-mix(in srgb, var(--danger) 12%, transparent);
}

.gpu-summary-label {
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}

.gpu-summary-value {
  font-size: var(--font-size-body);
  font-weight: 700;
}

.gpu-summary--pass .gpu-summary-value {
  color: var(--success);
}

.gpu-summary--warn .gpu-summary-value {
  color: var(--accent-warm);
}

.gpu-summary--fail .gpu-summary-value {
  color: var(--danger);
}

.gpu-summary-detail {
  margin-left: auto;
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}

/* ── 空状态 ── */
.gpu-empty {
  padding: 1.6rem 0;
  text-align: center;
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}
</style>
