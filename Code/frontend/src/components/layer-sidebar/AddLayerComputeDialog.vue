<script setup lang="ts">
/**
 * AddLayerComputeDialog — 「添加图层」的时间范围选择框（2026-10-16 建，2026-10-17 改）。
 *
 * ## 为什么需要
 * 从图层库点「添加」时，原先会自动重跑工作流，而重跑的时间窗＝**时间轴当前那一帧**
 * （常停在无数据的日子）。对动态散射这类 8 天块产品更苛刻：`omega_sf.py` 要求窗口内
 * 每个像元至少有 2 次有效观测（`kmin=2`），只喂 8 天原料实测仅出 385 个像元，喂 31 天
 * 则出 6875 个（约 18 倍）⇒「添加」几乎必然失败，用户被迫绕进工作流页手填日期。
 *
 * ## 2026-10-17 改版（用户要求：不管有没有产物，点「添加」都弹）
 * - **无条件弹出**（仅"不支持时间"的静态图层除外）；
 * - 盘上已有产物时，默认日期＝**产物覆盖区间**，按钮显示「直接添加」⇒ 一次确认即可挂图；
 * - 用户改日期后超出现有范围则按钮变「开始计算」，按新窗口提交；
 * - **单次计算最长 31 天**（直接使用已有数据不受此限，因为它不消耗算力）。
 *
 * ## 契约
 * - 点主按钮：`emit('confirm', { start, end, within })`（日期均 `YYYYMMDD`；
 *   `within=true` 表示所选范围落在盘上已有数据范围内）；
 * - 取消 / 点遮罩 / Esc 一律 `emit('cancel')`，调用方据此不提交任何任务。
 */
import { computed, ref, watch } from 'vue'

import AppButton from '../ui/AppButton.vue'
import AppModal from '../ui/AppModal.vue'
import DateInputField from '../workflow/DateInputField.vue'

/** 单次计算允许的最长跨度（自然月上限）。 */
const MAX_COMPUTE_DAYS = 31

const props = withDefaults(
  defineProps<{
    open: boolean
    /** 图层显示名（说明文案用） */
    layerName?: string
    /** 默认开始日 YYYYMMDD */
    defaultStart?: string
    /** 默认结束日 YYYYMMDD */
    defaultEnd?: string
    /** 8 天块型产品（动态散射）：最少 8 天，且提示建议更长 */
    blockMode?: boolean
    /** 提交中（禁用交互） */
    busy?: boolean
    /** 盘上已有数据的起始日 YYYYMMDD（无产物留空） */
    availableStart?: string
    /** 盘上已有数据的结束日 YYYYMMDD（无产物留空） */
    availableEnd?: string
    /** 盘上已有帧数 */
    availableFrames?: number
    /** 该图层已在侧栏列表中（此时只能按新范围重算，不重复添加） */
    alreadyAdded?: boolean
  }>(),
  {
    layerName: '',
    defaultStart: '',
    defaultEnd: '',
    blockMode: false,
    busy: false,
    availableStart: '',
    availableEnd: '',
    availableFrames: 0,
    alreadyAdded: false,
  },
)

const emit = defineEmits<{
  confirm: [payload: { start: string; end: string; within: boolean }]
  cancel: []
}>()

const start = ref('')
const end = ref('')
const error = ref('')

// 每次打开都重置为调用方给的默认值，避免沿用上一次的选择
watch(
  () => props.open,
  (open) => {
    if (!open) return
    start.value = props.defaultStart
    end.value = props.defaultEnd
    error.value = ''
  },
  { immediate: true },
)

const minDays = computed(() => (props.blockMode ? 8 : 1))

/** 盘上是否已有可用产物。 */
const hasAvailable = computed(() => Boolean(props.availableStart && props.availableEnd))

/** 当前所选范围是否完全落在盘上已有数据范围内。 */
const withinAvailable = computed(() => {
  if (!hasAvailable.value) return false
  const s = String(start.value || '').trim()
  const e = String(end.value || '').trim()
  if (!/^\d{8}$/.test(s) || !/^\d{8}$/.test(e)) return false
  return s >= props.availableStart && e <= props.availableEnd
})

/** 本次是否需要真正计算（已添加的图层一律计算；否则看是否超出现有范围）。 */
const willCompute = computed(() => props.alreadyAdded || !withinAvailable.value)

/** 主按钮文案：跟着"要不要算"自动切换，用户不需要理解两套动作。 */
const primaryLabel = computed(() => {
  if (props.alreadyAdded) return '按此范围计算'
  if (withinAvailable.value) return '直接添加'
  return '开始计算'
})

function utcMs(yyyymmdd: string): number {
  return Date.UTC(
    Number(yyyymmdd.slice(0, 4)),
    Number(yyyymmdd.slice(4, 6)) - 1,
    Number(yyyymmdd.slice(6, 8)),
  )
}

/** YYYYMMDD → YYYY/MM/DD（展示用）。 */
function pretty(yyyymmdd: string): string {
  if (!/^\d{8}$/.test(yyyymmdd)) return yyyymmdd
  return `${yyyymmdd.slice(0, 4)}/${yyyymmdd.slice(4, 6)}/${yyyymmdd.slice(6, 8)}`
}

const availableLabel = computed(() =>
  hasAvailable.value ? `${pretty(props.availableStart)} ~ ${pretty(props.availableEnd)}` : '',
)

function onConfirm() {
  const s = String(start.value || '').trim()
  const e = String(end.value || '').trim()
  if (!/^\d{8}$/.test(s) || !/^\d{8}$/.test(e)) {
    error.value = '请选择完整的开始与结束日期'
    return
  }
  if (s > e) {
    error.value = '开始日期不能晚于结束日期'
    return
  }
  // 「直接使用已有数据」不消耗算力，不做跨度限制；只有真要计算时才校验上下限。
  if (willCompute.value) {
    const days = Math.round((utcMs(e) - utcMs(s)) / 86_400_000) + 1
    if (days < minDays.value) {
      error.value = `该产品按 ${minDays.value} 天为一块，时间范围至少需要 ${minDays.value} 天（当前 ${days} 天）`
      return
    }
    if (days > MAX_COMPUTE_DAYS) {
      error.value = `单次计算最长 ${MAX_COMPUTE_DAYS} 天（当前 ${days} 天），请缩短时间范围`
      return
    }
  }
  error.value = ''
  emit('confirm', { start: s, end: e, within: withinAvailable.value })
}

function onCancel() {
  if (props.busy) return
  emit('cancel')
}
</script>

<template>
  <AppModal
    :open="open"
    aria-label="选择计算时间范围"
    :close-on-backdrop="!busy"
    :close-on-escape="!busy"
    max-width="min(520px, 92vw)"
    @close="onCancel"
  >
    <header class="alc-head">
      <h3 class="alc-title">
        {{ alreadyAdded ? '按时间范围重新计算' : '添加图层' }}
      </h3>
      <p v-if="layerName" class="alc-sub">{{ layerName }}</p>
    </header>

    <div class="alc-body">
      <!-- 盘上已有数据 -->
      <div v-if="hasAvailable" class="alc-avail">
        <span class="alc-avail-dot" aria-hidden="true"></span>
        <div class="alc-avail-text">
          <strong>盘上已有数据</strong>
          <span class="alc-avail-range">{{ availableLabel }}</span>
          <span class="alc-avail-meta">共 {{ availableFrames }} 帧</span>
        </div>
      </div>

      <p class="alc-desc">
        <template v-if="alreadyAdded">
          该图层已在列表中。可直接按下面的时间范围重新计算：
        </template>
        <template v-else-if="hasAvailable">
          默认已填好现有数据的时间段，直接确认即可显示；修改日期后超出该范围将提交新计算。
        </template>
        <template v-else> 盘上暂无该图层的可用数据，将按下面的时间范围提交一次计算： </template>
      </p>

      <div class="alc-fields">
        <label class="alc-field">
          <span class="alc-label">开始日期</span>
          <DateInputField v-model="start" :error="!!error" />
        </label>
        <label class="alc-field">
          <span class="alc-label">结束日期</span>
          <DateInputField v-model="end" :error="!!error" />
        </label>
      </div>

      <p class="alc-hint">
        <template v-if="willCompute">
          <template v-if="blockMode">
            动态散射按 8 天一片落盘，单次计算最长
            {{ MAX_COMPUTE_DAYS }} 天；范围越大观测越多、出图越完整。
          </template>
          <template v-else>
            单次计算最长 {{ MAX_COMPUTE_DAYS }} 天；范围越大需要下载与计算的原始数据越多。
          </template>
        </template>
        <template v-else>该范围已有数据，将直接加载，不消耗计算资源。</template>
      </p>

      <p v-if="error" class="alc-error" role="alert">{{ error }}</p>
    </div>

    <footer class="alc-foot">
      <AppButton variant="ghost" :disabled="busy" @click="onCancel">取消</AppButton>
      <AppButton variant="primary" :loading="busy" @click="onConfirm">{{ primaryLabel }}</AppButton>
    </footer>
  </AppModal>
</template>

<style scoped>
.alc-head {
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--border-subtle);
}

.alc-title {
  margin: 0;
  font-size: var(--font-size-title);
  font-weight: var(--font-weight-semibold);
  color: var(--text-strong);
}

.alc-sub {
  margin: var(--space-2) 0 0;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
  word-break: break-all;
}

.alc-avail {
  display: flex;
  gap: var(--space-3);
  align-items: flex-start;
  padding: var(--space-3) var(--space-4);
  background: var(--surface-sunken, var(--surface-2, rgba(127, 127, 127, 0.08)));
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md, 8px);
}

.alc-avail-dot {
  flex: none;
  width: 8px;
  height: 8px;
  margin-top: 6px;
  background: var(--success, #2e9e5b);
  border-radius: 50%;
}

.alc-avail-text {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: baseline;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}

.alc-avail-range {
  font-weight: var(--font-weight-semibold);
  color: var(--text-strong);
}

.alc-avail-meta {
  color: var(--text-muted);
}

.alc-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-5);
  overflow: auto;
}

.alc-desc {
  margin: 0;
  font-size: var(--font-size-body);
  line-height: 1.5;
  color: var(--text-secondary);
}

.alc-fields {
  display: flex;
  gap: var(--space-4);
}

.alc-field {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: var(--space-2);
  min-width: 0;
}

.alc-label {
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-medium);
  color: var(--text-secondary);
}

.alc-hint {
  margin: 0;
  font-size: var(--font-size-caption);
  line-height: 1.5;
  color: var(--text-muted);
}

.alc-error {
  margin: 0;
  font-size: var(--font-size-caption);
  color: var(--danger);
}

.alc-foot {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  border-top: 1px solid var(--border-subtle);
}
</style>
