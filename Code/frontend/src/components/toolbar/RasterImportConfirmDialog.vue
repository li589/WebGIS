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
import { computed, ref, watch } from 'vue'
import { listCrs, transformBounds, type CRSDef } from '@/services/crs'

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

// CRS 下拉选项（13 项，按 category 顺序：geographic / encrypted / projected）
const crsOptions = ref<CRSDef[]>([])

function loadCrsOptions() {
  crsOptions.value = listCrs()
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
      loadCrsOptions()
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
</script>

<template>
  <div v-if="visible" class="csv-dialog-overlay" @click.self="!isBusy && handleCancel()">
    <div class="csv-dialog-panel">
      <div class="panel-header">
        <span class="panel-icon" aria-hidden="true">🗺️</span>
        <span>确认栅格数据坐标系 — {{ fileName }}</span>
        <button class="close-btn" :disabled="isBusy" @click="handleCancel" title="关闭">
          <span aria-hidden="true">✕</span>
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
          <span class="info-unit" v-if="detectionResult.source_crs"
            >（在 {{ detectionResult.source_crs }} 下）</span
          >
        </div>
      </div>

      <!-- 区块 2：用户校验 -->
      <div class="section-label">用户校验</div>
      <div class="col-row">
        <label class="col-field crs-field">
          <span class="col-label">源 CRS（栅格实际坐标系）</span>
          <select v-model="selectedCrs" class="col-select">
            <option v-for="opt in crsOptions" :key="opt.code" :value="opt.code">
              {{ opt.code }} — {{ opt.label }}
            </option>
          </select>
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
  background: rgba(8, 17, 31, 0.96);
  box-shadow: 0 24px 60px rgba(1, 8, 16, 0.48);
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
  width: 1.4rem;
  height: 1.4rem;
  border: none;
  border-radius: 0.5rem;
  background: transparent;
  color: #6e8ba0;
  cursor: pointer;
  font-size: 0.7rem;
}
.close-btn:hover:not(:disabled) {
  background: rgba(136, 192, 255, 0.1);
  color: #d8e6f5;
}
.close-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.section-label {
  color: #5a7080;
  font-size: 0.58rem;
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
  border: 1px solid rgba(136, 192, 255, 0.08);
  background: rgba(4, 12, 23, 0.5);
}

.info-line {
  display: flex;
  align-items: baseline;
  gap: 0.42rem;
  font-size: 0.6rem;
  flex-wrap: wrap;
}

.info-key {
  color: #6e8ba0;
  min-width: 5.6rem;
  flex-shrink: 0;
}

.info-value {
  color: #d8e6f5;
  word-break: break-all;
}

.info-value.notes {
  color: #9fb6cc;
  font-style: italic;
}
.info-value.mono {
  font-variant-numeric: tabular-nums;
  color: #5ad5ff;
}
.info-unit {
  color: #5a7080;
  font-size: 0.54rem;
}

.crs-badge {
  display: inline-block;
  padding: 0.12rem 0.42rem;
  border-radius: 0.32rem;
  background: rgba(90, 213, 255, 0.14);
  border: 1px solid rgba(90, 213, 255, 0.28);
  color: #5ad5ff;
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
  color: #8aa8bf;
  font-size: 0.56rem;
}

.col-select,
.col-input {
  padding: 0.32rem 0.42rem;
  border-radius: 0.42rem;
  border: 1px solid rgba(136, 192, 255, 0.16);
  background: rgba(4, 12, 23, 0.6);
  color: #d8e6f5;
  font: inherit;
  font-size: 0.62rem;
  cursor: pointer;
}

.col-input {
  cursor: text;
}

.col-select:focus,
.col-input:focus {
  outline: none;
  border-color: rgba(90, 213, 255, 0.36);
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
  color: #88dfff;
  font-size: 0.58rem;
  font-weight: 600;
  margin-bottom: 0.22rem;
  display: flex;
  align-items: center;
  gap: 0.42rem;
}

.preview-warn {
  color: #ffb070;
  font-weight: 400;
  font-size: 0.54rem;
}

.preview-value {
  color: #5ad5ff;
  font-size: 0.66rem;
  font-variant-numeric: tabular-nums;
  word-break: break-all;
}

.preview-hint {
  color: #5a7080;
  font-size: 0.54rem;
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
  border-top: 1px solid rgba(136, 192, 255, 0.08);
}

.cancel-btn,
.skip-btn,
.confirm-btn {
  padding: 0.42rem 0.72rem;
  border-radius: 0.5rem;
  font: inherit;
  font-size: 0.64rem;
  cursor: pointer;
}

.cancel-btn:disabled,
.skip-btn:disabled,
.confirm-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.cancel-btn {
  border: 1px solid rgba(136, 192, 255, 0.16);
  background: transparent;
  color: #9fb6cc;
}
.cancel-btn:hover:not(:disabled) {
  background: rgba(136, 192, 255, 0.08);
  color: #d8e6f5;
}

.skip-btn {
  border: 1px solid rgba(255, 200, 120, 0.22);
  background: rgba(255, 200, 120, 0.06);
  color: #ffc878;
}
.skip-btn:hover:not(:disabled) {
  background: rgba(255, 200, 120, 0.14);
  color: #ffe0a8;
}

.confirm-btn {
  border: 1px solid rgba(90, 213, 255, 0.3);
  background: rgba(10, 132, 255, 0.28);
  color: #a8e8ff;
  font-weight: 600;
}
.confirm-btn:hover:not(:disabled) {
  background: rgba(10, 132, 255, 0.48);
  color: #d0f0ff;
}
</style>
