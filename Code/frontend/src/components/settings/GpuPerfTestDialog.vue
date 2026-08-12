<script setup lang="ts">
/**
 * GPU 性能检测对话框：纯前端图形性能基准测试。
 * 测试期间通过 CustomEvent 通知页面暂停地图渲染与动画，确保结果准确。
 * 结果仅显示在当前会话，不保存到后端。
 */
import { ref, onBeforeUnmount } from 'vue'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()

type TestStatus = 'idle' | 'running' | 'done'
type ResultStatus = 'pass' | 'warn' | 'fail'

interface TestResult {
  name: string
  value: string
  detail?: string
  status: ResultStatus
}

const testStatus = ref<TestStatus>('idle')
const results = ref<TestResult[]>([])
const progress = ref(0)

// ── 测试实现 ──────────────────────────────────────────────────────

/** WebGL 渲染速度：创建离屏 canvas，绘制 1000 帧三角形，测量平均帧耗时 */
async function testWebglRender(): Promise<TestResult> {
  const canvas = document.createElement('canvas')
  canvas.width = 512
  canvas.height = 512
  const gl = canvas.getContext('webgl2') ?? canvas.getContext('webgl')
  if (!gl) {
    return { name: 'WebGL 渲染速度', value: '不可用', detail: 'WebGL 不受支持', status: 'fail' }
  }
  const glCtx = gl as WebGLRenderingContext

  const vs = glCtx.createShader(glCtx.VERTEX_SHADER)!
  glCtx.shaderSource(vs, 'attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.;}')
  glCtx.compileShader(vs)
  const fs = glCtx.createShader(glCtx.FRAGMENT_SHADER)!
  glCtx.shaderSource(fs, 'precision mediump float;void main(){gl_FragColor=vec4(0.5,0.7,1.,1.;}')
  glCtx.compileShader(fs)
  const prog = glCtx.createProgram()!
  glCtx.attachShader(prog, vs)
  glCtx.attachShader(prog, fs)
  glCtx.linkProgram(prog)
  glCtx.useProgram(prog)

  const buf = glCtx.createBuffer()
  glCtx.bindBuffer(glCtx.ARRAY_BUFFER, buf)
  glCtx.bufferData(
    glCtx.ARRAY_BUFFER,
    new Float32Array([0, 0.5, -0.5, -0.5, 0.5, -0.5]),
    glCtx.STATIC_DRAW,
  )
  const loc = glCtx.getAttribLocation(prog, 'p')
  glCtx.enableVertexAttribArray(loc)
  glCtx.vertexAttribPointer(loc, 2, glCtx.FLOAT, false, 0, 0)

  const frames = 1000
  const t0 = performance.now()
  for (let i = 0; i < frames; i++) {
    glCtx.viewport(0, 0, 512, 512)
    glCtx.clearColor(0, 0, 0, 1)
    glCtx.clear(glCtx.COLOR_BUFFER_BIT)
    glCtx.drawArrays(glCtx.TRIANGLES, 0, 3)
    glCtx.finish()
  }
  const elapsed = performance.now() - t0
  const avgMs = elapsed / frames
  const fps = 1000 / avgMs

  glCtx.deleteProgram(prog)
  glCtx.deleteShader(vs)
  glCtx.deleteShader(fs)
  glCtx.deleteBuffer(buf)

  const status: ResultStatus = fps >= 55 ? 'pass' : fps >= 30 ? 'warn' : 'fail'
  return {
    name: 'WebGL 渲染速度',
    value: `${fps.toFixed(0)} FPS`,
    detail: `平均 ${avgMs.toFixed(2)} ms/帧（${frames} 帧）`,
    status,
  }
}

/** Canvas 2D 填充速率：连续 fillRect 10000 次 */
async function testCanvasFill(): Promise<TestResult> {
  const canvas = document.createElement('canvas')
  canvas.width = 1024
  canvas.height = 1024
  const ctx = canvas.getContext('2d')
  if (!ctx) {
    return {
      name: 'Canvas 2D 填充速率',
      value: '不可用',
      detail: 'Canvas 2D 不受支持',
      status: 'fail',
    }
  }
  const ops = 10000
  const t0 = performance.now()
  for (let i = 0; i < ops; i++) {
    ctx.fillStyle = `rgb(${(i * 7) % 255},${(i * 13) % 255},${(i * 17) % 255})`
    ctx.fillRect((i * 37) % 1024, (i * 53) % 1024, ((i * 11) % 100) + 10, ((i * 23) % 100) + 10)
  }
  const elapsed = performance.now() - t0
  const opsPerSec = ops / (elapsed / 1000)
  const status: ResultStatus = opsPerSec >= 50000 ? 'pass' : opsPerSec >= 20000 ? 'warn' : 'fail'
  return {
    name: 'Canvas 2D 填充速率',
    value: `${(opsPerSec / 1000).toFixed(0)}K ops/s`,
    detail: `${ops} 次 fillRect，耗时 ${elapsed.toFixed(1)} ms`,
    status,
  }
}

/** 动画帧率：requestAnimationFrame 循环 3 秒 */
async function testAnimationFps(): Promise<TestResult> {
  return new Promise<TestResult>((resolve) => {
    const duration = 3000
    let frames = 0
    const t0 = performance.now()
    function loop() {
      frames++
      if (performance.now() - t0 < duration) {
        requestAnimationFrame(loop)
      } else {
        const elapsed = performance.now() - t0
        const fps = (frames / elapsed) * 1000
        const status: ResultStatus = fps >= 55 ? 'pass' : fps >= 30 ? 'warn' : 'fail'
        resolve({
          name: '动画帧率 (RAF FPS)',
          value: `${fps.toFixed(1)} FPS`,
          detail: `${frames} 帧 / ${(elapsed / 1000).toFixed(1)}s`,
          status,
        })
      }
    }
    requestAnimationFrame(loop)
  })
}

/** GPU 信息详情：WebGL renderer/vendor/参数 */
async function testGpuInfo(): Promise<TestResult> {
  const canvas = document.createElement('canvas')
  canvas.width = 1
  canvas.height = 1
  const gl = canvas.getContext('webgl2') ?? canvas.getContext('webgl')
  if (!gl) {
    return { name: 'GPU 信息详情', value: '不可用', status: 'fail' }
  }
  const glCtx = gl as WebGLRenderingContext
  const debugInfo = glCtx.getExtension('WEBGL_debug_renderer_info')
  const renderer = debugInfo
    ? glCtx.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL)
    : glCtx.getParameter(glCtx.RENDERER)
  const vendor = debugInfo
    ? glCtx.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL)
    : glCtx.getParameter(glCtx.VENDOR)
  const maxTexSize = glCtx.getParameter(glCtx.MAX_TEXTURE_SIZE)
  const extensions = glCtx.getSupportedExtensions()?.length ?? 0
  const webglVersion = glCtx.getParameter(glCtx.VERSION)

  return {
    name: 'GPU 信息详情',
    value: String(renderer ?? '未知'),
    detail: `${vendor ?? '未知'} · WebGL ${webglVersion} · 最大纹理 ${maxTexSize}px · ${extensions} 个扩展`,
    status: 'pass',
  }
}

const TESTS = [
  { id: 'webgl', name: 'WebGL 渲染速度', run: testWebglRender },
  { id: 'canvas', name: 'Canvas 2D 填充速率', run: testCanvasFill },
  { id: 'fps', name: '动画帧率 (RAF FPS)', run: testAnimationFps },
  { id: 'gpu', name: 'GPU 信息详情', run: testGpuInfo },
] as const

async function runAllTests() {
  testStatus.value = 'running'
  results.value = []
  progress.value = 0
  // 通知页面暂停性能消耗项
  window.dispatchEvent(new CustomEvent('cgda:perf-test-start'))
  try {
    for (let i = 0; i < TESTS.length; i++) {
      try {
        const result = await TESTS[i].run()
        results.value.push(result)
      } catch (e) {
        results.value.push({
          name: TESTS[i].name,
          value: '失败',
          detail: e instanceof Error ? e.message : String(e),
          status: 'fail',
        })
      }
      progress.value = Math.round(((i + 1) / TESTS.length) * 100)
      // 让 UI 有时间更新
      await new Promise((r) => setTimeout(r, 50))
    }
  } finally {
    window.dispatchEvent(new CustomEvent('cgda:perf-test-end'))
  }
  testStatus.value = 'done'
}

function reset() {
  testStatus.value = 'idle'
  results.value = []
  progress.value = 0
}

function handleClose() {
  emit('close')
  // 延迟重置，让关闭动画完成
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
            检测浏览器图形渲染能力。测试期间将暂停地图渲染与动画，确保结果准确。结果仅显示在当前会话，不保存到后端。
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

        <div v-if="testStatus === 'running'" class="gpu-progress">
          <div class="gpu-progress-bar" :style="{ width: `${progress}%` }"></div>
        </div>

        <div v-if="results.length > 0" class="gpu-results">
          <div v-for="r in results" :key="r.name" class="gpu-result-item">
            <span class="gpu-result-name">{{ r.name }}</span>
            <span class="gpu-result-value" :class="`gpu-result--${r.status}`">{{ r.value }}</span>
            <span v-if="r.detail" class="gpu-result-detail">{{ r.detail }}</span>
          </div>
        </div>

        <div v-else-if="testStatus === 'idle'" class="gpu-empty">点击"开始检测"运行性能测试</div>
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
  max-height: 80vh;
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
  transition: background var(--motion-fast) var(--ease-standard);
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
    background var(--motion-fast) var(--ease-standard),
    opacity var(--motion-fast) var(--ease-standard);
}

.gpu-run-btn:hover:not(:disabled) {
  background: var(--surface-hover);
}

.gpu-run-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

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

.gpu-results {
  display: grid;
  gap: 0.5rem;
}

.gpu-result-item {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 0.15rem 0.6rem;
  padding: 0.5rem 0.6rem;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-sunken);
}

.gpu-result-name {
  font-size: var(--font-size-caption);
  font-weight: 500;
  color: var(--text-secondary);
}

.gpu-result-value {
  font-size: var(--font-size-body);
  font-weight: 600;
  text-align: right;
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

.gpu-result-detail {
  grid-column: 1 / -1;
  font-size: var(--font-size-caption);
  color: var(--text-muted);
  line-height: 1.4;
}

.gpu-empty {
  padding: 1.6rem 0;
  text-align: center;
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}
</style>
