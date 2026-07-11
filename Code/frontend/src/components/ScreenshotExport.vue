<script setup lang="ts">
import { computed, ref } from 'vue'

export type ScreenshotMode = 'shell' | 'bare' | 'clean' | 'pure'
export type ScreenshotFormat = 'png' | 'pdf'

const props = defineProps<{
  dashboardEl: HTMLElement | null
  mapShellEl: HTMLElement | null
  mapStageEl: HTMLElement | null
  captureMapCanvas: (() => string | null) | null
  activeLayerName: string
  hourLabel: string
}>()

const emit = defineEmits<{
  close: []
}>()

const isCapturing = ref(false)
const captureMsg = ref('')

const MODES: Array<{ id: ScreenshotMode; label: string; icon: string; desc: string }> = [
  { id: 'shell', label: '带外壳', icon: '▣', desc: '当前界面，含外层背景与全部模块' },
  { id: 'bare', label: '无外壳', icon: '▤', desc: '仅界面内部内容，保留面板与信息框' },
  { id: 'clean', label: '无控件', icon: '▥', desc: '移除全部控件，保留光影、主图和叠加层' },
  { id: 'pure', label: '纯净', icon: '◇', desc: '仅底图、比例尺和叠加层，无其他装饰' },
]

const FORMATS: Array<{ id: ScreenshotFormat; label: string; icon: string }> = [
  { id: 'png', label: 'PNG 图片', icon: '◫' },
  { id: 'pdf', label: 'PDF 文档', icon: '◰' },
]

const selectedMode = ref<ScreenshotMode>('bare')
const selectedFormat = ref<ScreenshotFormat>('png')

const canCapture = computed(() => !!props.mapStageEl && !isCapturing.value)

const CLEAN_IGNORE_SELECTORS = [
  '.overlay',
  '.map-overlay',
  '.map-note',
  '.tile-load-error',
  '.map-loading',
  '.map-skeleton',
  '.maplibregl-ctrl-bottom-right',
  '.maplibregl-ctrl-bottom-left',
]

const PURE_IGNORE_SELECTORS = [
  '.overlay',
  '.map-overlay',
  '.map-note',
  '.tile-load-error',
  '.map-loading',
  '.map-skeleton',
  '.maplibregl-ctrl-bottom-right',
  '.map-fog',
  '.time-sheen',
  '.time-band',
  '.weather-overlay',
  '.grid-overlay',
  '.basemap-transition-mask',
]

type MapSnapshot = {
  dataUrl: string
  dx: number
  dy: number
  dw: number
  dh: number
}

function buildMapSnapshot(stage: HTMLElement, captureEl: HTMLElement, scale: number): MapSnapshot | null {
  const mapCanvas = stage.querySelector('.maplibregl-canvas') as HTMLCanvasElement | null
  if (!mapCanvas) return null

  try {
    // preserveDrawingBuffer=false 下，必须通过 map.render() + 同步 toDataURL() 读取
    const dataUrl = props.captureMapCanvas
      ? props.captureMapCanvas()
      : mapCanvas.toDataURL('image/png')
    if (!dataUrl) return null
    const rect = mapCanvas.getBoundingClientRect()
    const parentRect = captureEl.getBoundingClientRect()

    return {
      dataUrl,
      dx: (rect.left - parentRect.left) * scale,
      dy: (rect.top - parentRect.top) * scale,
      dw: rect.width * scale,
      dh: rect.height * scale,
    }
  } catch (error) {
    console.warn('[ScreenshotExport] Failed to read map canvas:', error)
    return null
  }
}

function resolveCaptureElement(mode: ScreenshotMode): HTMLElement | null {
  if (!props.mapStageEl) return null

  if (mode === 'shell') {
    return props.dashboardEl?.ownerDocument.documentElement ?? props.dashboardEl ?? props.mapShellEl ?? props.mapStageEl
  }

  if (mode === 'bare' || mode === 'clean') {
    return props.mapShellEl ?? props.mapStageEl
  }

  return props.mapStageEl
}

function matchesAnySelector(el: HTMLElement, selectors: string[]) {
  return selectors.some((selector) => el.matches(selector) || !!el.closest(selector))
}

async function capture() {
  if (!props.mapStageEl || isCapturing.value) return
  isCapturing.value = true
  captureMsg.value = '正在捕获...'

  const stage = props.mapStageEl

  const mode = selectedMode.value
  const format = selectedFormat.value

  const captureEl = resolveCaptureElement(mode)
  if (!captureEl) {
    captureMsg.value = '截图失败'
    isCapturing.value = false
    return
  }

  let saved = false
  try {
    const { default: html2canvas } = await import('html2canvas')
    const { default: jsPDF } = await import('jspdf')

    captureMsg.value = '正在渲染...'
    const scale = window.devicePixelRatio * 2
    const mapSnapshot = buildMapSnapshot(stage, captureEl, scale)

    const canvas = await html2canvas(captureEl, {
      useCORS: true,
      allowTaint: true,
      scale,
      backgroundColor: null,
      logging: false,
      onclone: (clonedDoc: Document) => {
        const clonedStage = clonedDoc.querySelector('.map-stage') as HTMLElement | null
        if (clonedStage) {
          clonedStage.style.background = 'transparent'
          if (mode === 'pure') {
            clonedStage.style.border = 'none'
            clonedStage.style.borderRadius = '0'
            clonedStage.style.boxShadow = 'none'
          }
        }

        const clonedMapHost = clonedDoc.querySelector('.map-host') as HTMLElement | null
        if (clonedMapHost) {
          clonedMapHost.style.background = 'transparent'
        }

        clonedDoc.querySelectorAll('.maplibregl-canvas-container,.maplibregl-canvas').forEach((el: Element) => {
          ;(el as HTMLElement).style.visibility = 'hidden'
        })
      },
      ignoreElements: (el: Element) => {
        if (el instanceof HTMLElement && (el.matches('.maplibregl-canvas-container') || el.matches('.maplibregl-canvas'))) {
          return true
        }

        if (!(el instanceof HTMLElement)) return false

        if (el.matches('.screenshot-overlay') || !!el.closest('.screenshot-overlay')) {
          return true
        }

        if (mode === 'clean' && matchesAnySelector(el, CLEAN_IGNORE_SELECTORS)) {
          return true
        }

        if (mode === 'pure' && matchesAnySelector(el, PURE_IGNORE_SELECTORS)) {
          return true
        }

        return false
      },
    })

    let finalCanvas = canvas
    if (mapSnapshot) {
      const composedCanvas = document.createElement('canvas')
      composedCanvas.width = canvas.width
      composedCanvas.height = canvas.height
      const composedCtx = composedCanvas.getContext('2d')

      if (composedCtx) {
        const mapImage = new Image()
        mapImage.src = mapSnapshot.dataUrl
        await new Promise((resolve) => {
          mapImage.onload = () => {
            composedCtx.drawImage(mapImage, mapSnapshot.dx, mapSnapshot.dy, mapSnapshot.dw, mapSnapshot.dh)
            composedCtx.drawImage(canvas, 0, 0)
            finalCanvas = composedCanvas
            resolve(null)
          }
          mapImage.onerror = () => { finalCanvas = canvas; resolve(null) }
        })
      }
    }

    const exportName = props.activeLayerName === '无图层' ? '无数据图层' : props.activeLayerName
    const filename = `geoflow-${exportName}-${props.hourLabel.replace(':', '')}-${mode}`

    if (format === 'png') {
      const link = document.createElement('a')
      link.download = `${filename}.png`
      link.href = finalCanvas.toDataURL('image/png')
      link.click()
      saved = true
    } else {
      const imgData = finalCanvas.toDataURL('image/png')
      const pdfWidth = finalCanvas.width
      const pdfHeight = finalCanvas.height
      const pdf = new jsPDF({
        orientation: pdfWidth > pdfHeight ? 'landscape' : 'portrait',
        unit: 'px',
        format: [pdfWidth, pdfHeight],
      })
      pdf.addImage(imgData, 'PNG', 0, 0, pdfWidth, pdfHeight)
      pdf.save(`${filename}.pdf`)
      saved = true
    }

    captureMsg.value = saved ? '已保存' : '保存失败'
  } catch (err) {
    console.error('[ScreenshotExport] Capture failed:', err)
    captureMsg.value = '截图失败'
  } finally {
    isCapturing.value = false
    setTimeout(() => {
      captureMsg.value = ''
    }, 2000)
  }
}
</script>

<template>
  <div class="screenshot-overlay" @click.self="emit('close')">
    <div class="screenshot-panel">
      <div class="panel-header">
        <span class="panel-icon" aria-hidden="true">◫</span>
        <span>导出截图</span>
        <button class="close-btn" @click="emit('close')" title="关闭">
          <span aria-hidden="true">✕</span>
        </button>
      </div>

      <!-- Mode selection -->
      <div class="section-label">截图模式</div>
      <div class="mode-grid">
        <button
          v-for="m in MODES"
          :key="m.id"
          class="mode-btn"
          :class="{ active: selectedMode === m.id }"
          @click="selectedMode = m.id"
        >
          <span class="mode-icon" aria-hidden="true">{{ m.icon }}</span>
          <span class="mode-label">{{ m.label }}</span>
          <span class="mode-desc">{{ m.desc }}</span>
        </button>
      </div>

      <!-- Format selection -->
      <div class="section-label">保存格式</div>
      <div class="format-row">
        <button
          v-for="f in FORMATS"
          :key="f.id"
          class="format-btn"
          :class="{ active: selectedFormat === f.id }"
          @click="selectedFormat = f.id"
        >
          <span aria-hidden="true">{{ f.icon }}</span>
          <span>{{ f.label }}</span>
        </button>
      </div>

      <!-- Capture button -->
      <button
        class="capture-btn"
        :class="{ capturing: isCapturing }"
        :disabled="!canCapture"
        @click="capture"
      >
        <span v-if="!isCapturing && !captureMsg" class="btn-icon" aria-hidden="true">▼</span>
        <span v-else-if="captureMsg" class="btn-msg">{{ captureMsg }}</span>
        <span v-else class="btn-icon spinning" aria-hidden="true">↻</span>
        <span>{{ isCapturing ? captureMsg || '处理中...' : '导出' }}</span>
      </button>

      <p v-if="captureMsg === '已保存'" class="success-hint">文件已保存到下载目录</p>
    </div>
  </div>
</template>

<style scoped>
.screenshot-overlay {
  position: fixed;
  inset: 0;
  z-index: 999;
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  padding: 5.5rem 0.8rem 0;
  background: rgba(4, 10, 18, 0.52);
}

.screenshot-panel {
  width: 17rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  padding: 0.78rem 0.82rem;
  border-radius: 1rem;
  border: 1px solid rgba(136, 192, 255, 0.14);
  background: rgba(8, 17, 31, 0.96);
  box-shadow:
    0 24px 60px rgba(1, 8, 16, 0.48),
    inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 0.38rem;
  padding-bottom: 0.48rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.1);
  color: #e8f3fc;
  font-size: 0.72rem;
  font-weight: 600;
}

.panel-icon {
  font-size: 0.8rem;
  color: #5ad5ff;
}

.close-btn {
  margin-left: auto;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 1.4rem;
  height: 1.4rem;
  border: none;
  border-radius: 0.5rem;
  background: transparent;
  color: #6e8ba0;
  cursor: pointer;
  font-size: 0.7rem;
  transition: background 0.18s ease, color 0.18s ease;
}

.close-btn:hover {
  background: rgba(136, 192, 255, 0.1);
  color: #d8e6f5;
}

.section-label {
  color: #5a7080;
  font-size: 0.58rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.mode-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.38rem;
}

.mode-btn {
  display: grid;
  grid-template-rows: auto auto auto;
  align-items: center;
  gap: 0.1rem;
  padding: 0.48rem 0.42rem;
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: 0.68rem;
  background: rgba(4, 12, 23, 0.6);
  color: #8aa8bf;
  cursor: pointer;
  font: inherit;
  text-align: left;
  transition: border-color 0.18s ease, background 0.18s ease, color 0.18s ease;
}

.mode-btn:hover {
  border-color: rgba(136, 192, 255, 0.24);
  background: rgba(136, 192, 255, 0.08);
  color: #d8e6f5;
}

.mode-btn.active {
  border-color: rgba(90, 213, 255, 0.36);
  background: rgba(10, 132, 255, 0.14);
  color: #5ad5ff;
}

.mode-icon {
  font-size: 0.82rem;
  color: inherit;
}

.mode-label {
  font-size: 0.64rem;
  font-weight: 600;
}

.mode-desc {
  font-size: 0.52rem;
  color: #5a7080;
  line-height: 1.3;
}

.mode-btn.active .mode-desc {
  color: #4a8090;
}

.format-row {
  display: flex;
  gap: 0.38rem;
}

.format-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.32rem;
  padding: 0.44rem;
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: 0.68rem;
  background: rgba(4, 12, 23, 0.6);
  color: #8aa8bf;
  cursor: pointer;
  font: inherit;
  font-size: 0.64rem;
  font-weight: 500;
  transition: border-color 0.18s ease, background 0.18s ease, color 0.18s ease;
}

.format-btn:hover {
  border-color: rgba(136, 192, 255, 0.24);
  color: #d8e6f5;
  background: rgba(136, 192, 255, 0.08);
}

.format-btn.active {
  border-color: rgba(90, 213, 255, 0.36);
  background: rgba(10, 132, 255, 0.14);
  color: #5ad5ff;
}

.capture-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.42rem;
  width: 100%;
  padding: 0.54rem;
  border: 1px solid rgba(90, 213, 255, 0.3);
  border-radius: 0.8rem;
  background: rgba(10, 132, 255, 0.28);
  color: #a8e8ff;
  cursor: pointer;
  font: inherit;
  font-size: 0.7rem;
  font-weight: 600;
  box-shadow: 0 8px 24px rgba(10, 132, 255, 0.18);
  /* 性能优化：GPU 属性过渡 */
  transition: background 0.2s ease, color 0.2s ease, transform 0.2s cubic-bezier(0.25, 0.46, 0.45, 0.94), box-shadow 0.2s ease;
}

.capture-btn:hover:not(:disabled) {
  background: rgba(10, 132, 255, 0.48);
  color: #d0f0ff;
  transform: translateY(-1px);
  box-shadow: 0 10px 30px rgba(10, 132, 255, 0.28);
}

.capture-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.capture-btn.capturing {
  border-color: rgba(90, 213, 255, 0.2);
  background: rgba(10, 132, 255, 0.16);
}

.btn-icon {
  font-size: 0.72rem;
}

.spinning {
  display: inline-block;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.success-hint {
  margin: 0;
  text-align: center;
  color: #7ddfbb;
  font-size: 0.58rem;
}

@media (max-width: 600px) {
  .screenshot-overlay {
    padding: 5rem 0.5rem 0;
    align-items: flex-start;
  }

  .screenshot-panel {
    width: 100%;
  }

  .mode-grid {
    grid-template-columns: 1fr;
  }
}
</style>
