<script setup lang="ts">
/**
 * Screenshot export panel.
 *
 * html2canvas / jspdf are **static** imports so Vite does not re-optimize deps
 * mid-click (that previously caused occasional full-page reloads). This panel
 * itself is loaded via defineAsyncComponent, so the cost is deferred until open.
 */
import { computed, onBeforeUnmount, ref } from 'vue'
import html2canvas from 'html2canvas'
import { jsPDF } from 'jspdf'
import { LAYERS_COPY } from '../ui-copy'
import {
  CLEAN_IGNORE_SELECTORS,
  PURE_IGNORE_SELECTORS,
  MAP_CANVAS_SELECTORS,
  type ScreenshotFormat,
  type ScreenshotMode,
  buildMapSnapshotLayout,
  canvasToPngBlob,
  compositeMapUnderUi,
  downloadBlob,
  matchesAnySelector,
  stampLayoutMeasurements,
  prepareCloneForCapture,
  resolveCaptureElement,
  snapshotLivePaint,
} from './screenshot-export'

export type { ScreenshotFormat, ScreenshotMode }

const props = defineProps<{
  dashboardEl: HTMLElement | null
  mapShellEl: HTMLElement | null
  mapStageEl: HTMLElement | null
  captureMapCanvas: (() => Promise<string | null> | string | null) | null
  setWindAnimationPaused?: ((paused: boolean) => void) | null
  activeLayerName: string
  hourLabel: string
}>()

const emit = defineEmits<{
  close: []
}>()

const isCapturing = ref(false)
const captureMsg = ref('')
/** 跟踪 captureMsg 自动清除定时器，组件卸载时统一清理避免访问已销毁的 ref */
let captureMsgTimer: ReturnType<typeof setTimeout> | null = null

onBeforeUnmount(() => {
  if (captureMsgTimer !== null) {
    clearTimeout(captureMsgTimer)
    captureMsgTimer = null
  }
})

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

async function capture() {
  if (!props.mapStageEl || isCapturing.value) return
  isCapturing.value = true
  captureMsg.value = '正在捕获...'

  const stage = props.mapStageEl
  const mode = selectedMode.value
  const format = selectedFormat.value

  const captureEl = resolveCaptureElement(mode, {
    dashboardEl: props.dashboardEl,
    mapShellEl: props.mapShellEl,
    mapStageEl: props.mapStageEl,
  })
  if (!captureEl) {
    captureMsg.value = '截图失败'
    isCapturing.value = false
    return
  }

  let restoreStamps: (() => void) | null = null
  props.setWindAnimationPaused?.(true)

  try {
    captureMsg.value = '正在渲染...'
    const scale = Math.max(2, window.devicePixelRatio || 1)

    // Step 1: Capture map WebGL FIRST — before any DOM measurements that could
    // trigger reflow and clear the GL framebuffer (preserveDrawingBuffer=false).
    const mapCanvasEl =
      (stage.querySelector('.maplibregl-canvas') as HTMLCanvasElement | null) ||
      (stage.querySelector('canvas') as HTMLCanvasElement | null)

    let mapDataUrl: string | null = null
    if (props.captureMapCanvas) {
      try {
        mapDataUrl = await Promise.resolve(props.captureMapCanvas())
      } catch (err) {
        console.warn('[ScreenshotExport] captureMapCanvas threw error:', err)
      }
    }
    if (!mapDataUrl && mapCanvasEl) {
      try {
        mapDataUrl = mapCanvasEl.toDataURL('image/png')
      } catch {
        mapDataUrl = null
      }
    }

    // Step 2: Build map snapshot layout using live rects.
    const snapshotTarget = mapCanvasEl ?? stage
    const mapSnapshot = mapDataUrl
      ? buildMapSnapshotLayout(snapshotTarget, captureEl, scale, mapDataUrl)
      : null

    // Step 3: Stamp layout measurements as data attributes (non-destructive to live DOM).
    restoreStamps = stampLayoutMeasurements(captureEl)

    // Step 4: Snapshot live paint (computed styles) before html2canvas clones.
    const paintSnapshots = snapshotLivePaint(captureEl)
    const realToolbar = captureEl.querySelector('.toolbar') as HTMLElement | null

    // Step 5: Run html2canvas — onclone callback does all layout pinning in the clone.
    const captureRect = captureEl.getBoundingClientRect()
    const uiCanvas = await html2canvas(captureEl, {
      useCORS: true,
      allowTaint: false,
      scale,
      backgroundColor: null,
      logging: false,
      scrollX: -window.scrollX,
      scrollY: -window.scrollY,
      windowWidth: Math.ceil(captureRect.width) || captureEl.clientWidth || window.innerWidth,
      windowHeight: Math.ceil(captureRect.height) || captureEl.clientHeight || window.innerHeight,
      onclone: (clonedDoc: Document) => {
        prepareCloneForCapture(clonedDoc, { mode, paintSnapshots, realToolbar })
      },
      ignoreElements: (el: Element) => {
        if (!(el instanceof HTMLElement)) return false

        if (matchesAnySelector(el, MAP_CANVAS_SELECTORS)) {
          return true
        }

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

    // Step 6: Composite map under UI.
    let finalCanvas = uiCanvas
    try {
      finalCanvas = await compositeMapUnderUi(uiCanvas, mapSnapshot)
    } catch (error) {
      console.warn('[ScreenshotExport] map composite failed, exporting UI only:', error)
    }

    if (!mapSnapshot) {
      console.warn(
        '[ScreenshotExport] map snapshot missing — basemap/overlays may be blank (tainted canvas or capture failure)',
      )
    }

    const exportName =
      props.activeLayerName === LAYERS_COPY.emptyTitle ? '无数据图层' : props.activeLayerName
    const filename = `geoflow-${exportName}-${props.hourLabel.replace(':', '')}-${mode}`

    if (format === 'png') {
      const blob = await canvasToPngBlob(finalCanvas)
      downloadBlob(blob, `${filename}.png`)
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
    }

    captureMsg.value = '已保存'
  } catch (err) {
    console.error('[ScreenshotExport] Capture failed:', err)
    captureMsg.value = '截图失败'
  } finally {
    restoreStamps?.()
    props.setWindAnimationPaused?.(false)
    isCapturing.value = false
    if (captureMsgTimer !== null) {
      clearTimeout(captureMsgTimer)
    }
    captureMsgTimer = setTimeout(() => {
      captureMsg.value = ''
      captureMsgTimer = null
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
        <button type="button" class="close-btn" @click.prevent="emit('close')" title="关闭">
          <span aria-hidden="true">✕</span>
        </button>
      </div>

      <!-- Mode selection -->
      <div class="section-label">截图模式</div>
      <div class="mode-grid">
        <button
          v-for="m in MODES"
          :key="m.id"
          type="button"
          class="mode-btn"
          :class="{ active: selectedMode === m.id }"
          @click.prevent="selectedMode = m.id"
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
          type="button"
          class="format-btn"
          :class="{ active: selectedFormat === f.id }"
          @click.prevent="selectedFormat = f.id"
        >
          <span aria-hidden="true">{{ f.icon }}</span>
          <span>{{ f.label }}</span>
        </button>
      </div>

      <!-- Capture button -->
      <button
        type="button"
        class="capture-btn"
        :class="{ capturing: isCapturing }"
        :disabled="!canCapture"
        @click.prevent="capture"
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
  transition:
    background 0.18s ease,
    color 0.18s ease;
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
  transition:
    border-color 0.18s ease,
    background 0.18s ease,
    color 0.18s ease;
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
  transition:
    border-color 0.18s ease,
    background 0.18s ease,
    color 0.18s ease;
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
  transition:
    background 0.2s ease,
    color 0.2s ease,
    transform 0.2s cubic-bezier(0.25, 0.46, 0.45, 0.94),
    box-shadow 0.2s ease;
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
  to {
    transform: rotate(360deg);
  }
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
