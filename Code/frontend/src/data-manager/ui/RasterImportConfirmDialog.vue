<script setup lang="ts">
/**
 * 栅格导入坐标系确认弹窗。
 *
 * 当后端 `/import/raster` 返回 `needs_confirm=true`（即检测到的 CRS 非 WGS84 等价系）
 * 时弹出，让用户校验/覆盖源 CRS、设置 lng/lat 偏移，并实时预览转换后的 WGS84 bounds。
 *
 * 三区块：
 *  1. 检测信息只读（source_crs / detection_notes / 原始 bounds）
 *  2. 用户校验（源 CRS 下拉 13 项 + lng/lat offset 输入 + 实时预览 WGS84 bounds）
 *  3. 操作按钮（取消 / 跳过用建议值 / 确认转换）
 *
 * 样式复用 CsvImportDialog.vue 的暗色 BEM 命名（csv-dialog-* / panel-* / section-label /
 * col-row / col-field / col-select / action-row / cancel-btn / confirm-btn）。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { Map, X } from 'lucide-vue-next'
import { listCrs, transformBounds } from '@/services/crs'
import type { CRSOption } from '@/services/crs'
import { fetchCrsOptionsExpanded } from '@/services/data-import'
import AppSelect from '@/components/ui/AppSelect.vue'

interface DetectionResult {
  /** 后端 RasterImportResult 字段均为 optional，dialog 内部已做 fallback */
  source_crs?: string
  suggested_crs?: string
  needs_confirm?: boolean
  detection_notes?: string
  bounds?: [number, number, number, number]
}

const props = defineProps<{
  visible: boolean
  fileName: string
  detectionResult: DetectionResult
  /**
   * 后端重投影进行中（confirmRasterCrs / skipRasterConfirm 的 await 期间为 true）。
   * 此时取消/跳过/确认按钮均禁用，避免与正在进行的后端调用产生竞态
   * （cancel 删除后端文件 → confirm 的 await 返回 → 用 stale layerId 注册 overlay → 死链）。
   */
  importing?: boolean
}>()

const emit = defineEmits<{
  confirm: [payload: { sourceCrs: string; lngOffset: number; latOffset: number }]
  cancel: []
  skip: []
}>()

// CRS 下拉（优先后端 expanded，失败回退本地 13 项）
const crsOptions = ref<CRSOption[]>([])
const crsFilter = ref('')
const filteredCrsOptions = computed(() => {
  const q = crsFilter.value.trim().toLowerCase()
  if (!q) return crsOptions.value
  return crsOptions.value.filter(
    (c) =>
      c.code.toLowerCase().includes(q) ||
      String(c.label || '')
        .toLowerCase()
        .includes(q),
  )
})

async function loadCrsOptions() {
  try {
    const data = await fetchCrsOptionsExpanded()
    crsOptions.value = data.items || []
  } catch {
    crsOptions.value = listCrs().map((c) => ({
      code: c.code,
      label: c.label,
      category: c.category,
      area: c.area,
      deprecated: c.deprecated,
    }))
  }
}

// 用户校验输入
const selectedCrs = ref<string>('EPSG:4326')
const lngOffset = ref<number>(0)
const latOffset = ref<number>(0)

// 初始化：每次 visible 由 false → true 时重置为建议值
watch(
  () => props.visible,
  (v) => {
    if (v) {
      void loadCrsOptions()
      crsFilter.value = ''
      selectedCrs.value =
        props.detectionResult.suggested_crs || props.detectionResult.source_crs || 'EPSG:4326'
      lngOffset.value = 0
      latOffset.value = 0
    }
  },
  { immediate: true },
)

// 实时预览：原始 bounds（在 selectedCrs 下）→ WGS84 → 加偏移
const previewBounds = computed<[number, number, number, number] | null>(() => {
  const b = props.detectionResult.bounds
  if (!b || b.length !== 4 || b.some((v) => !Number.isFinite(v))) return null
  try {
    const wgs84 = transformBounds(b, selectedCrs.value, 'EPSG:4326')
    return [
      wgs84[0] + lngOffset.value,
      wgs84[1] + latOffset.value,
      wgs84[2] + lngOffset.value,
      wgs84[3] + latOffset.value,
    ]
  } catch (err) {
    console.warn('[RasterImportConfirm] transformBounds failed:', err)
    return null
  }
})

const previewValid = computed(() => {
  const b = previewBounds.value
  if (!b) return false
  const [w, s, e, n] = b
  return (
    Number.isFinite(w) &&
    Number.isFinite(s) &&
    Number.isFinite(e) &&
    Number.isFinite(n) &&
    w >= -180 &&
    w <= 180 &&
    e >= -180 &&
    e <= 180 &&
    s >= -90 &&
    s <= 90 &&
    n >= -90 &&
    n <= 90 &&
    w < e &&
    s < n
  )
})

/** 后端重投影进行中：所有可触发后端调用或关闭弹窗的按钮均禁用 */
const isBusy = computed(() => props.importing === true)

function formatNum(n: number, digits = 4): string {
  if (!Number.isFinite(n)) return '—'
  return n.toFixed(digits)
}

function formatBounds(b: [number, number, number, number] | null | undefined): string {
  if (!b) return '—'
  return `[${formatNum(b[0])}, ${formatNum(b[1])}, ${formatNum(b[2])}, ${formatNum(b[3])}]`
}

function handleConfirm() {
  if (!previewValid.value) return
  emit('confirm', {
    sourceCrs: selectedCrs.value,
    lngOffset: lngOffset.value,
    latOffset: latOffset.value,
  })
}

function handleCancel() {
  emit('cancel')
}

// ── 发布就绪修复（P1-11）：模态可访问性 ────────────────────────────────────
// role="dialog"/aria-modal/aria-label + ESC 关闭 + 焦点陷阱 + 关闭后焦点还原。
const panelRef = ref<HTMLElement | null>(null)
let previouslyFocused: HTMLElement | null = null

function onDialogKeydown(e: KeyboardEvent) {
  if (!props.visible) return
  if (e.key === 'Escape') {
    if (!isBusy.value) handleCancel()
    e.stopPropagation()
    return
  }
  if (e.key === 'Tab') {
    // 焦点陷阱：让 Tab / Shift+Tab 在弹窗内可聚焦元素间循环，不外溢到背景
    const panel = panelRef.value
    if (!panel) return
    const focusables = Array.from(
      panel.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((el) => !el.hasAttribute('disabled'))
    if (!focusables.length) return
    const first = focusables[0]
    const last = focusables[focusables.length - 1]
    const active = document.activeElement as HTMLElement | null
    if (e.shiftKey && active === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && active === last) {
      e.preventDefault()
      first.focus()
    }
  }
}

watch(
  () => props.visible,
  async (v) => {
    if (v) {
      previouslyFocused = document.activeElement as HTMLElement | null
      await nextTick()
      panelRef.value?.focus()
      window.addEventListener('keydown', onDialogKeydown, true)
    } else {
      window.removeEventListener('keydown', onDialogKeydown, true)
      previouslyFocused?.focus?.()
      previouslyFocused = null
    }
  },
)
</script>

<template>
  <div v-if="visible" class="csv-dialog-overlay" @click.self="!isBusy && handleCancel()">
    <div
      ref="panelRef"
      class="csv-dialog-panel"
      role="dialog"
      aria-modal="true"
      :aria-label="`确认栅格数据坐标系 — ${fileName}`"
      tabindex="-1"
    >
      <div class="panel-header">
        <Map :size="16" class="panel-icon" aria-hidden="true" />
        <span>确认栅格数据坐标系 — {{ fileName }}</span>
        <button class="close-btn" :disabled="isBusy" title="关闭" aria-label="关闭" @click="handleCancel">
          <X :size="14" aria-hidden="true" />
        </button>
      </div>

      <!-- 区块 1：检测信息（只读） -->
      <div class="section-label">检测信息（只读）</div>
      <div class="detection-info">
        <div class="info-line">
          <span class="info-key">检测到 CRS</span>
          <span class="info-value crs-badge">{{ detectionResult.source_crs || '—' }}</span>
        </div>
        <div class="info-line">
          <span class="info-key">建议 CRS</span>
          <span class="info-value">{{ detectionResult.suggested_crs || '—' }}</span>
        </div>
        <div class="info-line">
          <span class="info-key">检测备注</span>
          <span class="info-value notes">{{ detectionResult.detection_notes || '—' }}</span>
        </div>
        <div class="info-line">
          <span class="info-key">原始 bounds</span>
          <span class="info-value mono">{{ formatBounds(detectionResult.bounds) }}</span>
          <span v-if="detectionResult.source_crs" class="info-unit"
            >（在 {{ detectionResult.source_crs }} 下）</span
          >
        </div>
      </div>

      <!-- 区块 2：用户校验 -->
      <div class="section-label">用户校验</div>
      <div class="col-row">
        <label class="col-field crs-field">
          <span class="col-label">源 CRS（栅格实际坐标系）</span>
          <input
            v-model="crsFilter"
            type="search"
            class="col-input"
            placeholder="搜索 EPSG / 名称（全量 UTM/GK）"
            style="margin-bottom: 0.35rem"
          />
          <AppSelect
            v-model="selectedCrs"
            :options="filteredCrsOptions.map((opt) => ({ label: `${opt.code} — ${opt.label}`, value: opt.code }))"
          />
        </label>
      </div>
      <div class="col-row">
        <label class="col-field">
          <span class="col-label">经度偏移 lng_offset（度）</span>
          <input
            v-model.number="lngOffset"
            type="number"
            step="0.001"
            class="col-input"
            placeholder="0"
          />
        </label>
        <label class="col-field">
          <span class="col-label">纬度偏移 lat_offset（度）</span>
          <input
            v-model.number="latOffset"
            type="number"
            step="0.001"
            class="col-input"
            placeholder="0"
          />
        </label>
      </div>

      <!-- 实时预览 -->
      <div class="preview-block" :class="{ invalid: !previewValid }">
        <div class="preview-label">
          转换后 WGS84 bounds
          <span v-if="!previewValid" class="preview-warn">⚠ 转换失败或越界</span>
        </div>
        <div class="preview-value mono">{{ formatBounds(previewBounds) }}</div>
        <div class="preview-hint">
          路径：{{ selectedCrs }} → WGS84（transformBounds）→ +offset({{ formatNum(lngOffset, 3) }},
          {{ formatNum(latOffset, 3) }})
        </div>
      </div>

      <!-- 区块 3：操作按钮 -->
      <div class="action-row">
        <button class="cancel-btn" :disabled="isBusy" @click="handleCancel">取消</button>
        <button class="skip-btn" :disabled="isBusy" title="使用建议 CRS + 0 偏移">
          跳过（用建议值）
        </button>
        <button class="confirm-btn" :disabled="!previewValid || isBusy" @click="handleConfirm">
          确认转换
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.csv-dialog-overlay {
  position: fixed;
  inset: 0;
  z-index: 999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(4, 10, 18, 0.52);
}

.csv-dialog-panel {
  width: 34rem;
  max-width: 92vw;
  max-height: 86vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  padding: 0.82rem;
  border-radius: 1rem;
  border: 1px solid rgba(136, 192, 255, 0.14);
  background: var(--surface-1);
  box-shadow: 0 24px 60px rgba(1, 8, 16, 0.48);
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 0.38rem;
  padding-bottom: 0.48rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.1);
  color: #e8f3fc;
  font-size: var(--font-size-caption);
  font-weight: 600;
}

.panel-icon {
  font-size: 0.8rem;
  color: var(--accent);
}

.close-btn {
  margin-left: auto;
  width: 1.4rem;
  height: 1.4rem;
  border: none;
  border-radius: 0.5rem;
  background: transparent;
  color: var(--text-faint);
  cursor: pointer;
  font-size: var(--font-size-caption);
}
.close-btn:hover:not(:disabled) {
  background: rgba(136, 192, 255, 0.1);
  color: var(--text-primary);
}
.close-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.section-label {
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

/* 区块 1：检测信息 */
.detection-info {
  display: flex;
  flex-direction: column;
  gap: 0.32rem;
  padding: 0.52rem;
  border-radius: 0.5rem;
  border: 1px solid var(--border-subtle);
  background: var(--surface-sunken);
}

.info-line {
  display: flex;
  align-items: baseline;
  gap: 0.42rem;
  font-size: var(--font-size-caption);
  flex-wrap: wrap;
}

.info-key {
  color: var(--text-faint);
  min-width: 5.6rem;
  flex-shrink: 0;
}

.info-value {
  color: var(--text-primary);
  word-break: break-all;
}

.info-value.notes {
  color: var(--text-secondary);
  font-style: italic;
}
.info-value.mono {
  font-variant-numeric: tabular-nums;
  color: var(--accent);
}
.info-unit {
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
}

.crs-badge {
  display: inline-block;
  padding: 0.12rem 0.42rem;
  border-radius: 0.32rem;
  background: rgba(90, 213, 255, 0.14);
  border: 1px solid var(--border-accent);
  color: var(--accent);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

/* 区块 2：用户校验 */
.col-row {
  display: flex;
  gap: 0.52rem;
  flex-wrap: wrap;
}

.col-field {
  display: flex;
  flex-direction: column;
  gap: 0.22rem;
  flex: 1;
  min-width: 7rem;
}

.crs-field {
  flex: 1.4;
}

.col-label {
  color: var(--text-muted);
  font-size: var(--font-size-caption);
}

.col-select,
.col-input {
  padding: 0.32rem 0.42rem;
  border-radius: 0.42rem;
  border: 1px solid var(--border-default);
  background: var(--surface-raised);
  color: var(--text-primary);
  font: inherit;
  font-size: var(--font-size-caption);
  cursor: pointer;
}

.col-input {
  cursor: text;
}

.col-select:focus,
.col-input:focus {
  outline: none;
  border-color: var(--border-strong);
}

/* 实时预览块 */
.preview-block {
  padding: 0.52rem;
  border-radius: 0.5rem;
  border: 1px solid rgba(90, 213, 255, 0.18);
  background: rgba(10, 132, 255, 0.06);
}

.preview-block.invalid {
  border-color: rgba(255, 140, 100, 0.32);
  background: rgba(255, 100, 77, 0.06);
}

.preview-label {
  color: var(--accent-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
  margin-bottom: 0.22rem;
  display: flex;
  align-items: center;
  gap: 0.42rem;
}

.preview-warn {
  color: var(--warning);
  font-weight: 400;
  font-size: var(--font-size-caption);
}

.preview-value {
  color: var(--accent);
  font-size: var(--font-size-caption);
  font-variant-numeric: tabular-nums;
  word-break: break-all;
}

.preview-hint {
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
  margin-top: 0.22rem;
}

.mono {
  font-variant-numeric: tabular-nums;
}

/* 区块 3：操作按钮 */
.action-row {
  display: flex;
  gap: 0.52rem;
  justify-content: flex-end;
  padding-top: 0.32rem;
  border-top: 1px solid var(--border-subtle);
}

.cancel-btn,
.skip-btn,
.confirm-btn {
  padding: 0.42rem 0.72rem;
  border-radius: 0.5rem;
  font: inherit;
  font-size: var(--font-size-caption);
  cursor: pointer;
}

.cancel-btn:disabled,
.skip-btn:disabled,
.confirm-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.cancel-btn {
  border: 1px solid var(--border-default);
  background: transparent;
  color: var(--text-secondary);
}
.cancel-btn:hover:not(:disabled) {
  background: var(--border-subtle);
  color: var(--text-primary);
}

.skip-btn {
  border: 1px solid rgba(255, 200, 120, 0.22);
  background: rgba(255, 200, 120, 0.06);
  color: var(--accent-warm);
}
.skip-btn:hover:not(:disabled) {
  background: rgba(255, 200, 120, 0.14);
  color: #ffe0a8;
}

.confirm-btn {
  border: 1px solid var(--accent-border);
  background: rgba(10, 132, 255, 0.28);
  color: #a8e8ff;
  font-weight: 600;
}
.confirm-btn:hover:not(:disabled) {
  background: rgba(10, 132, 255, 0.48);
  color: #d0f0ff;
}
</style>
