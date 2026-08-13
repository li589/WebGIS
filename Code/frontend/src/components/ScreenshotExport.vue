<script setup lang="ts">
/**
 * Screenshot export panel.
 *
 * html2canvas / jspdf are **static** imports so Vite does not re-optimize deps
 * mid-click (that previously caused occasional full-page reloads). This panel
 * itself is loaded via defineAsyncComponent, so the cost is deferred until open.
 */
import { computed, onBeforeUnmount, ref } from 'vue'
import { Table2, X, ChevronDown } from './ui/icons'
import IconButton from './ui/IconButton.vue'
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
/** Manual download when browser blocks programmatic <a download> after async work */
const manualDownload = ref<{ href: string; filename: string } | null>(null)
/** 跟踪 captureMsg 自动清除定时器，组件卸载时统一清理避免访问已销毁的 ref */
let captureMsgTimer: ReturnType<typeof setTimeout> | null = null

onBeforeUnmount(() => {
  if (captureMsgTimer !== null) {
    clearTimeout(captureMsgTimer)
    captureMsgTimer = null
  }
  if (manualDownload.value?.href) {
    URL.revokeObjectURL(manualDownload.value.href)
    manualDownload.value = null
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

type SaveFilePickerHandle = {
  createWritable: () => Promise<{
    write: (data: Blob) => Promise<void>
    close: () => Promise<void>
  }>
}

async function pickSaveTarget(
  filename: string,
  format: ScreenshotFormat,
): Promise<SaveFilePickerHandle | null> {
  const w = window as Window & {
    showSaveFilePicker?: (opts: Record<string, unknown>) => Promise<SaveFilePickerHandle>
  }
  if (typeof w.showSaveFilePicker !== 'function') return null
  try {
    return await w.showSaveFilePicker({
      suggestedName: filename,
      types:
        format === 'png'
          ? [{ description: 'PNG image', accept: { 'image/png': ['.png'] } }]
          : [{ description: 'PDF document', accept: { 'application/pdf': ['.pdf'] } }],
    })
  } catch (err) {
    // AbortError = user cancelled — treat as cancel of whole export
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    return null
  }
}

async function persistBlob(
  blob: Blob,
  filename: string,
  fileHandle: SaveFilePickerHandle | null,
): Promise<'picker' | 'anchor' | 'manual'> {
  if (fileHandle) {
    const writable = await fileHandle.createWritable()
    await writable.write(blob)
    await writable.close()
    return 'picker'
  }
  // Programmatic download after awaits is often blocked; still try, then keep manual link.
  downloadBlob(blob, filename)
  if (manualDownload.value?.href) URL.revokeObjectURL(manualDownload.value.href)
  manualDownload.value = { href: URL.createObjectURL(blob), filename }
  return 'manual'
}

function scheduleMsgClear(ms = 4000) {
  if (captureMsgTimer !== null) clearTimeout(captureMsgTimer)
  captureMsgTimer = setTimeout(() => {
    // Keep manual download affordance; only clear transient status text
    if (!manualDownload.value) captureMsg.value = ''
    captureMsgTimer = null
  }, ms)
}

async function capture() {
  if (!props.mapStageEl || isCapturing.value) return

  const stage = props.mapStageEl
  const mode = selectedMode.value
  const format = selectedFormat.value
  const exportName =
    props.activeLayerName === LAYERS_COPY.emptyTitle ? '无数据图层' : props.activeLayerName
  const basename = `geoflow-${exportName}-${props.hourLabel.replace(':', '')}-${mode}`
  const filename = format === 'png' ? `${basename}.png` : `${basename}.pdf`

  // Acquire file handle WHILE user gesture is still valid (before long awaits).
  let fileHandle: SaveFilePickerHandle | null = null
  try {
    fileHandle = await pickSaveTarget(filename, format)
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      captureMsg.value = '已取消'
      scheduleMsgClear(1500)
      return
    }
  }

  isCapturing.value = true
  captureMsg.value = '正在捕获...'
  if (manualDownload.value?.href) {
    URL.revokeObjectURL(manualDownload.value.href)
    manualDownload.value = null
  }

  const captureEl = resolveCaptureElement(mode, {
    dashboardEl: props.dashboardEl,
    mapShellEl: props.mapShellEl,
    mapStageEl: props.mapStageEl,
  })
  if (!captureEl) {
    captureMsg.value = '截图失败：找不到捕获区域'
    isCapturing.value = false
    scheduleMsgClear()
    return
  }

  let restoreStamps: (() => void) | null = null
  props.setWindAnimationPaused?.(true)

  try {
    captureMsg.value = '正在渲染...'
    // Cap scale — shell@dpr*2 can OOM; 2 is enough for crisp export
    const scale = Math.min(2, Math.max(1, window.devicePixelRatio || 1))

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

    const snapshotTarget = mapCanvasEl ?? stage
    const mapSnapshot = mapDataUrl
      ? buildMapSnapshotLayout(snapshotTarget, captureEl, scale, mapDataUrl)
      : null

    restoreStamps = stampLayoutMeasurements(captureEl)
    const paintSnapshots = snapshotLivePaint(captureEl)
    const realToolbar = captureEl.querySelector('.toolbar') as HTMLElement | null
    const captureRect = captureEl.getBoundingClientRect()

    const runHtml2Canvas = () =>
      html2canvas(captureEl, {
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
          if (matchesAnySelector(el, MAP_CANVAS_SELECTORS)) return true
          if (el.matches('.screenshot-overlay') || !!el.closest('.screenshot-overlay')) return true
          if (mode === 'clean' && matchesAnySelector(el, CLEAN_IGNORE_SELECTORS)) return true
          if (mode === 'pure' && matchesAnySelector(el, PURE_IGNORE_SELECTORS)) return true
          return false
        },
      })

    let uiCanvas: HTMLCanvasElement
    let mapOnlyFallback = false
    try {
      uiCanvas = await Promise.race([
        runHtml2Canvas(),
        new Promise<never>((_, reject) => {
          window.setTimeout(() => reject(new Error('界面渲染超时（20s）')), 20_000)
        }),
      ])
    } catch (uiErr) {
      console.warn('[ScreenshotExport] html2canvas failed, exporting map snapshot only:', uiErr)
      if (!mapDataUrl) throw uiErr
      mapOnlyFallback = true
      const fallback = document.createElement('canvas')
      const mapW = mapCanvasEl?.width || Math.ceil(captureRect.width) || 800
      const mapH = mapCanvasEl?.height || Math.ceil(captureRect.height) || 600
      fallback.width = mapW
      fallback.height = mapH
      const ctx = fallback.getContext('2d')
      if (!ctx) throw uiErr
      // Canvas 2D 不支持 CSS 变量，需解析为字面量颜色值
      const bgColor =
        getComputedStyle(document.documentElement).getPropertyValue('--surface-1').trim() ||
        '#0b1a2a'
      ctx.fillStyle = bgColor
      ctx.fillRect(0, 0, mapW, mapH)
      const img = await new Promise<HTMLImageElement>((resolve, reject) => {
        const image = new Image()
        image.onload = () => resolve(image)
        image.onerror = () => reject(new Error('Failed to load map snapshot for fallback'))
        image.src = mapDataUrl!
      })
      ctx.drawImage(img, 0, 0, mapW, mapH)
      uiCanvas = fallback
    }

    let finalCanvas = uiCanvas
    if (!mapOnlyFallback) {
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
    }

    captureMsg.value = '正在保存...'
    let blob: Blob
    if (format === 'png') {
      blob = await canvasToPngBlob(finalCanvas)
    } else {
      const imgData = finalCanvas.toDataURL('image/png')
      const pdf = new jsPDF({
        orientation: finalCanvas.width > finalCanvas.height ? 'landscape' : 'portrait',
        unit: 'px',
        format: [finalCanvas.width, finalCanvas.height],
      })
      pdf.addImage(imgData, 'PNG', 0, 0, finalCanvas.width, finalCanvas.height)
      blob = pdf.output('blob')
    }

    const how = await persistBlob(blob, filename, fileHandle)
    captureMsg.value = mapOnlyFallback
      ? how === 'manual'
        ? '已生成（仅地图）— 请点下方下载'
        : '已保存（仅地图）'
      : how === 'manual'
        ? '已生成 — 若未自动下载请点下方链接'
        : '已保存'
    scheduleMsgClear(how === 'manual' ? 12_000 : 4000)
  } catch (err) {
    console.error('[ScreenshotExport] Capture failed:', err)
    const detail = err instanceof Error ? err.message : String(err)
    captureMsg.value = detail.includes('Abort') ? '已取消' : `截图失败：${detail.slice(0, 80)}`
    scheduleMsgClear(5000)
  } finally {
    restoreStamps?.()
    props.setWindAnimationPaused?.(false)
    isCapturing.value = false
  }
}
</script>

<template>
  <div class="screenshot-overlay" @click.self="emit('close')">
    <div class="screenshot-panel">
      <div class="panel-header">
        <Table2 :size="16" class="panel-icon" aria-hidden="true" />
        <span>导出截图</span>
        <IconButton size="sm" label="关闭" class="close-btn-slot" @click="emit('close')">
          <template #icon><X :size="14" /></template>
        </IconButton>
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
        <ChevronDown
          v-if="!isCapturing && !captureMsg"
          :size="16"
          class="btn-icon"
          aria-hidden="true"
        />
        <span v-else-if="isCapturing && !captureMsg" class="btn-icon spinning" aria-hidden="true"
          >↻</span
        >
        <span class="btn-text">{{ captureMsg || (isCapturing ? '处理中...' : '导出') }}</span>
      </button>

      <a
        v-if="manualDownload"
        class="manual-download"
        :href="manualDownload.href"
        :download="manualDownload.filename"
        rel="noopener"
      >
        ⬇ 点击下载 {{ manualDownload.filename }}
      </a>

      <p v-if="captureMsg.startsWith('已保存')" class="success-hint">
        文件已写入所选位置或下载目录
      </p>
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
  padding: 5.5rem var(--space-3) 0;
  background: var(--surface-raised);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
}

.screenshot-panel {
  width: 20rem;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-5);
  border-radius: var(--radius-xl);
  border: 1px solid var(--accent-surface);
  background: linear-gradient(165deg, var(--surface-2), var(--surface-2));
  backdrop-filter: blur(24px) saturate(1.1);
  -webkit-backdrop-filter: blur(24px) saturate(1.1);
  box-shadow:
    0 24px 60px rgba(1, 8, 16, 0.5),
    0 1px 0 rgba(136, 223, 255, 0.1) inset;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-strong);
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-semibold);
}

.panel-icon {
  font-size: var(--font-size-body);
  color: var(--accent);
  line-height: 1;
}

.close-btn-slot {
  margin-left: auto;
}

.section-label {
  color: var(--text-faint);
  font-size: var(--font-size-caption);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  font-weight: var(--font-weight-medium);
}

.mode-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-2);
}

.mode-btn {
  display: grid;
  grid-template-rows: auto auto auto;
  align-items: center;
  gap: 2px;
  padding: var(--space-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface-sunken);
  color: var(--text-muted);
  cursor: pointer;
  font-family: inherit;
  text-align: left;
  transition:
    border-color var(--motion-fast) var(--ease-soft),
    background-color var(--motion-fast) var(--ease-soft),
    color var(--motion-fast) var(--ease-soft);
}

.mode-btn:hover {
  border-color: var(--border-strong);
  background: var(--surface-hover);
  color: var(--text-primary);
}

.mode-btn.active {
  border-color: var(--border-accent);
  background: var(--accent-surface);
  color: var(--accent);
}

.mode-icon {
  font-size: var(--font-size-h3);
  color: inherit;
  line-height: 1.2;
}

.mode-label {
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-semibold);
}

.mode-desc {
  font-size: var(--font-size-caption);
  color: var(--text-faint);
  line-height: 1.3;
  opacity: 0.8;
}

.mode-btn.active .mode-desc {
  color: var(--text-muted);
  opacity: 1;
}

.format-row {
  display: flex;
  gap: var(--space-2);
}

.format-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface-sunken);
  color: var(--text-muted);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-medium);
  transition:
    border-color var(--motion-fast) var(--ease-soft),
    background-color var(--motion-fast) var(--ease-soft),
    color var(--motion-fast) var(--ease-soft);
}

.format-btn:hover {
  border-color: var(--border-strong);
  color: var(--text-primary);
  background: var(--surface-hover);
}

.format-btn.active {
  border-color: var(--border-accent);
  background: var(--accent-surface);
  color: var(--accent);
}

.capture-btn {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  width: 100%;
  padding: 0.75rem var(--space-3);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-lg);
  background: linear-gradient(180deg, var(--border-strong), var(--accent-border));
  color: var(--text-strong);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-semibold);
  letter-spacing: 0.02em;
  overflow: hidden;
  box-shadow:
    0 6px 20px var(--accent-border),
    inset 0 1px 0 rgba(136, 223, 255, 0.2);
  transition:
    background-color var(--motion-fast) var(--ease-soft),
    color var(--motion-fast) var(--ease-soft),
    transform var(--motion-fast) ease,
    box-shadow var(--motion-fast) var(--ease-soft),
    border-color var(--motion-fast) var(--ease-soft);
}

.capture-btn::before {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, var(--surface-hover), transparent);
  transition: left 0.5s ease;
}

.capture-btn:hover:not(:disabled) {
  background: linear-gradient(180deg, var(--border-strong), var(--border-strong));
  border-color: var(--border-strong);
  box-shadow:
    0 10px 32px rgba(10, 132, 255, 0.3),
    inset 0 1px 0 rgba(136, 223, 255, 0.25);
  transform: translateY(-1px);
}

.capture-btn:hover:not(:disabled)::before {
  left: 100%;
}

.capture-btn:active:not(:disabled) {
  transform: translateY(1px);
  box-shadow:
    0 3px 10px var(--accent-border),
    inset 0 1px 0 rgba(136, 223, 255, 0.1);
}

.capture-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
}

.capture-btn.capturing {
  border-color: var(--border-strong);
  background: linear-gradient(180deg, var(--accent-border), var(--accent-surface));
}

.btn-icon {
  font-size: var(--font-size-caption);
  line-height: 1;
}

.btn-text {
  line-height: 1;
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
  color: var(--success);
  font-size: var(--font-size-caption);
}

.manual-download {
  display: block;
  margin: var(--space-1) 0 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  border: 1px solid var(--border-accent);
  background: var(--accent-surface);
  color: var(--accent);
  font-size: var(--font-size-caption);
  text-align: center;
  text-decoration: none;
  word-break: break-all;
  transition:
    background-color var(--motion-fast) ease,
    border-color var(--motion-fast) ease;
}

.manual-download:hover {
  border-color: var(--accent);
  background: var(--accent-border);
}

@media (prefers-reduced-motion: reduce) {
  .spinning {
    animation: none;
  }
  .capture-btn,
  .mode-btn,
  .format-btn,
  .close-btn {
    transition: none;
  }
  .capture-btn::before {
    display: none;
  }
  .capture-btn:hover:not(:disabled) {
    transform: none;
  }
}

@media (max-width: 640px) {
  .screenshot-overlay {
    padding: 5rem var(--space-2) 0;
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
