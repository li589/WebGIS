<script setup lang="ts">
/**
 * NsidcDownloadForm.vue
 *
 * download/nsidc_smap_download 节点专用参数表单。
 *
 * 字段：
 *   - start_date / end_date: YYYYMMDD
 *   - local_dir: 本地输出目录（须填写；相对 BACKEND_DATA_ROOT 或绝对路径）
 *   - version: 5 / 6
 *   - short_name: NSIDC 数据集短名（默认 SPL3SMP_E）
 */
import { computed, onMounted, reactive, watch } from 'vue'
import type { LGraphNodeClass } from '../litegraph-setup'
import {
  type FormErrors,
  isoToYyyymmdd,
  syncFormFromNode,
  validateDateRange,
  validateRequired,
  yyyymmddToIso,
} from './utils'
import {
  fillPathFieldsFromSystemSettings,
  loadSystemPathDefaults,
} from '../../../composables/system-settings-fill'
import { fieldMapForNodeType } from '../../../composables/node-form-system-settings-map'
import { WORKFLOW_COPY } from '../../../ui-copy/workflow'

const NODE_TYPE = 'download/nsidc_smap_download'
const PATH_FIELD_MAP = fieldMapForNodeType(NODE_TYPE)

const props = defineProps<{
  node: LGraphNodeClass | null
  readonly?: boolean
}>()

const emit = defineEmits<{
  'update-property': [key: string, value: unknown]
}>()

const DEFAULTS = {
  start_date: '',
  end_date: '',
  local_dir: '',
  version: 6,
  short_name: 'SPL3SMP_E',
}

const form = reactive<{ [k: string]: unknown }>({ ...DEFAULTS })

// 表单校验错误集合（实时更新）
const errors = reactive<FormErrors>({})
const errorCount = computed(() => Object.keys(errors).length)

/**
 * 实时校验：short_name / local_dir 非空 + 日期范围合法。
 * 结果写入 reactive errors，驱动模板中的字段错误提示与底部摘要。
 */
function validateForm() {
  const e: FormErrors = {}
  let r = validateRequired(form.short_name, '数据集短名')
  if (r) e.short_name = r
  r = validateRequired(form.local_dir, '本地目录')
  if (r) e.local_dir = r
  r = validateDateRange(String(form.start_date ?? ''), String(form.end_date ?? ''))
  if (r) e.date_range = r
  // 先清空再赋值，确保响应式触发
  for (const k of Object.keys(errors)) delete errors[k]
  Object.assign(errors, e)
}

function resync() {
  syncFormFromNode(form, props.node, DEFAULTS)
  // version 归一为 number
  const v = form.version
  if (v === '' || v === undefined || v === null) {
    form.version = DEFAULTS.version
  } else {
    const n = Number(v)
    form.version = Number.isFinite(n) ? n : DEFAULTS.version
  }
  validateForm()
}

watch(() => props.node, resync, { immediate: true })

onMounted(async () => {
  try {
    const defaults = await loadSystemPathDefaults()
    const filled = fillPathFieldsFromSystemSettings(form, defaults, PATH_FIELD_MAP, {
      onlyEmpty: true,
    })
    for (const key of filled) {
      emit('update-property', key, form[key])
    }
    validateForm()
  } catch {
    /* ignore settings fetch errors */
  }
})

async function applySystemSettings(overwrite = true) {
  const defaults = await loadSystemPathDefaults(true)
  const filled = fillPathFieldsFromSystemSettings(form, defaults, PATH_FIELD_MAP, { overwrite })
  for (const key of filled) {
    emit('update-property', key, form[key])
  }
  validateForm()
}

function update(key: string, value: unknown) {
  form[key] = value
  validateForm()
  emit('update-property', key, value)
}

function onVersionChange(event: Event) {
  const raw = (event.target as HTMLSelectElement).value
  update('version', Number(raw))
}
</script>

<template>
  <div class="node-form">
    <!-- 数据集短名 -->
    <div class="form-row">
      <label class="form-label">数据集 short_name</label>
      <input
        type="text"
        class="form-input"
        :value="String(form.short_name ?? '')"
        placeholder="SPL3SMP_E"
        :readonly="readonly"
        @input="update('short_name', ($event.target as HTMLInputElement).value)"
      />
      <span v-if="errors.short_name" class="field-error">{{ errors.short_name }}</span>
    </div>

    <!-- 版本 -->
    <div class="form-row">
      <label class="form-label">版本 version</label>
      <select
        class="form-input form-select"
        :value="String(form.version ?? '6')"
        :disabled="readonly"
        @change="onVersionChange"
      >
        <option value="5">5</option>
        <option value="6">6</option>
      </select>
    </div>

    <!-- 日期范围 -->
    <div class="form-row">
      <label class="form-label">起始日期 start_date</label>
      <input
        type="date"
        class="form-input"
        :value="yyyymmddToIso(form.start_date)"
        :readonly="readonly"
        @input="update('start_date', isoToYyyymmdd(($event.target as HTMLInputElement).value))"
      />
    </div>

    <div class="form-row">
      <label class="form-label">结束日期 end_date</label>
      <input
        type="date"
        class="form-input"
        :value="yyyymmddToIso(form.end_date)"
        :readonly="readonly"
        @input="update('end_date', isoToYyyymmdd(($event.target as HTMLInputElement).value))"
      />
      <span v-if="errors.date_range" class="field-error">{{ errors.date_range }}</span>
    </div>

    <!-- 本地输出目录 -->
    <div class="form-row">
      <label class="form-label">
        本地目录 local_dir
        <button
          v-if="!readonly"
          type="button"
          class="sys-fill-btn"
          :title="WORKFLOW_COPY.useSystemSettings"
          @click="applySystemSettings(true)"
        >
          {{ WORKFLOW_COPY.useSystemSettings }}
        </button>
      </label>
      <input
        type="text"
        class="form-input"
        :value="String(form.local_dir ?? '')"
        placeholder="请选择或输入本地目录"
        :readonly="readonly"
        @input="update('local_dir', ($event.target as HTMLInputElement).value)"
      />
      <span v-if="errors.local_dir" class="field-error">{{ errors.local_dir }}</span>
    </div>

    <!-- 校验状态摘要 -->
    <div class="form-summary" :class="{ valid: errorCount === 0, invalid: errorCount > 0 }">
      <template v-if="errorCount === 0">✓ 表单校验通过</template>
      <template v-else>⚠ 请修正 {{ errorCount }} 处错误</template>
    </div>
  </div>
</template>

<style scoped>
.node-form {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
  margin-bottom: 0.42rem;
}

.form-label {
  font-size: var(--font-size-caption);
  color: var(--text-faint);
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex-wrap: wrap;
}

.sys-fill-btn {
  margin-left: auto;
  padding: 0.12rem 0.36rem;
  border-radius: 0.28rem;
  border: 1px solid rgba(90, 213, 255, 0.35);
  background: rgba(90, 213, 255, 0.1);
  color: var(--accent);
  font-size: var(--font-size-caption);
  cursor: pointer;
}

.sys-fill-btn:hover {
  background: rgba(90, 213, 255, 0.2);
}

.form-input {
  width: 100%;
  padding: 0.32rem 0.42rem;
  border: 1px solid rgba(136, 192, 255, 0.14);
  border-radius: 0.36rem;
  background: var(--surface-raised);
  color: var(--text-primary);
  font: inherit;
  font-size: var(--font-size-caption);
  box-sizing: border-box;
}

.form-input:focus {
  outline: none;
  border-color: rgba(90, 213, 255, 0.4);
}

.form-input:read-only {
  background: rgba(4, 12, 23, 0.3);
  color: var(--text-faint);
  cursor: default;
}

.form-select {
  appearance: none;
  cursor: pointer;
  background-image:
    linear-gradient(45deg, transparent 50%, var(--text-faint) 50%),
    linear-gradient(135deg, var(--text-faint) 50%, transparent 50%);
  background-position:
    calc(100% - 0.8rem) center,
    calc(100% - 0.5rem) center;
  background-size:
    0.3rem 0.3rem,
    0.3rem 0.3rem;
  background-repeat: no-repeat;
  padding-right: 1.6rem;
}

.form-select:disabled {
  opacity: 0.6;
  cursor: default;
}

/* 字段错误提示 */
.field-error {
  font-size: var(--font-size-caption);
  color: #ff7b7b;
  margin-top: 0.06rem;
  line-height: 1.3;
}

/* 校验状态摘要 */
.form-summary {
  margin-top: 0.32rem;
  padding: 0.3rem 0.52rem;
  border-radius: 0.36rem;
  font-size: var(--font-size-caption);
  text-align: center;
  border: 1px solid transparent;
}

.form-summary.valid {
  background: rgba(114, 255, 207, 0.08);
  color: #72ffcf;
  border-color: rgba(114, 255, 207, 0.22);
}

.form-summary.invalid {
  background: rgba(255, 123, 123, 0.08);
  color: #ff7b7b;
  border-color: rgba(255, 123, 123, 0.22);
}
</style>
