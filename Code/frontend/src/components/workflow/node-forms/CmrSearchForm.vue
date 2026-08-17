<script setup lang="ts">
/**
 * CmrSearchForm.vue
 *
 * download/cmr_search 节点专用参数表单（公共只读检索，免凭据）。
 */
import { computed, reactive, watch } from 'vue'
import { Check, AlertTriangle } from '../../ui/icons'
import type { LGraphNodeClass } from '../litegraph-setup'
import {
  type FormErrors,
  isoToYyyymmdd,
  syncFormFromNode,
  validateDateRange,
  validateRequired,
  yyyymmddToIso,
} from './utils'

const props = defineProps<{
  node: LGraphNodeClass | null
  readonly?: boolean
}>()

const emit = defineEmits<{
  'update-property': [key: string, value: unknown]
}>()

const DEFAULTS = {
  short_name: '',
  version: '',
  start_date: '',
  end_date: '',
  bounding_box: '',
  link_filter: '',
  max_results: 5,
}

const form = reactive<{ [k: string]: unknown }>({ ...DEFAULTS })
const errors = reactive<FormErrors>({})
const errorCount = computed(() => Object.keys(errors).length)

function validateForm() {
  const e: FormErrors = {}
  let r = validateRequired(form.short_name, '产品短名')
  if (r) e.short_name = r
  r = validateRequired(form.start_date, '起始日期')
  if (r) e.start_date = r
  r = validateDateRange(String(form.start_date ?? ''), String(form.end_date ?? ''))
  if (r) e.date_range = r
  for (const k of Object.keys(errors)) delete errors[k]
  Object.assign(errors, e)
}

function resync() {
  syncFormFromNode(form, props.node, DEFAULTS)
  validateForm()
}

watch(() => props.node, resync, { immediate: true })

function update(key: string, value: unknown) {
  form[key] = value
  validateForm()
  emit('update-property', key, value)
}
</script>

<template>
  <div class="node-form">
    <p class="form-hint">公共只读检索，无需凭据；输出 URL 可接「门户数据下载」。</p>

    <div class="form-row">
      <label class="form-label">产品 short_name</label>
      <input
        type="text"
        class="form-input"
        :value="String(form.short_name ?? '')"
        placeholder="VNP13A1 / SPL3SMP_E / GLDAS_NOAH025_3H"
        :readonly="readonly"
        @input="update('short_name', ($event.target as HTMLInputElement).value)"
      />
      <span v-if="errors.short_name" class="field-error">{{ errors.short_name }}</span>
    </div>

    <div class="form-row">
      <label class="form-label">版本 version（可选）</label>
      <input
        type="text"
        class="form-input"
        :value="String(form.version ?? '')"
        placeholder="如 061"
        :readonly="readonly"
        @input="update('version', ($event.target as HTMLInputElement).value)"
      />
    </div>

    <div class="form-row">
      <label class="form-label">起始日期 start_date</label>
      <input
        type="date"
        class="form-input"
        :value="yyyymmddToIso(form.start_date)"
        :readonly="readonly"
        @input="update('start_date', isoToYyyymmdd(($event.target as HTMLInputElement).value))"
      />
      <span v-if="errors.start_date" class="field-error">{{ errors.start_date }}</span>
    </div>

    <div class="form-row">
      <label class="form-label">结束日期 end_date（默认同起始）</label>
      <input
        type="date"
        class="form-input"
        :value="yyyymmddToIso(form.end_date)"
        :readonly="readonly"
        @input="update('end_date', isoToYyyymmdd(($event.target as HTMLInputElement).value))"
      />
      <span v-if="errors.date_range" class="field-error">{{ errors.date_range }}</span>
    </div>

    <div class="form-row">
      <label class="form-label">范围 bounding_box（可选）</label>
      <input
        type="text"
        class="form-input"
        :value="String(form.bounding_box ?? '')"
        placeholder="西,南,东,北（如 70,15,140,55）"
        :readonly="readonly"
        @input="update('bounding_box', ($event.target as HTMLInputElement).value)"
      />
    </div>

    <div class="form-row">
      <label class="form-label">URL 过滤 link_filter（可选）</label>
      <input
        type="text"
        class="form-input"
        :value="String(form.link_filter ?? '')"
        placeholder="URL 子串（如 .h5）"
        :readonly="readonly"
        @input="update('link_filter', ($event.target as HTMLInputElement).value)"
      />
    </div>

    <div class="form-row">
      <label class="form-label">max_results（1~50）</label>
      <input
        type="number"
        class="form-input"
        min="1"
        max="50"
        :value="form.max_results == null ? '' : Number(form.max_results)"
        :readonly="readonly"
        @input="
          update(
            'max_results',
            ($event.target as HTMLInputElement).value
              ? Number(($event.target as HTMLInputElement).value)
              : 5,
          )
        "
      />
    </div>

    <div class="form-summary" :class="{ valid: errorCount === 0, invalid: errorCount > 0 }">
      <template v-if="errorCount === 0"
        ><Check :size="14" aria-hidden="true" /> 表单校验通过</template
      >
      <template v-else
        ><AlertTriangle :size="14" aria-hidden="true" /> 请修正 {{ errorCount }} 处错误</template
      >
    </div>
  </div>
</template>

<style scoped>
.node-form {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}

.form-hint {
  margin: 0 0 0.42rem;
  font-size: var(--font-size-caption);
  color: var(--text-faint);
  line-height: 1.4;
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
}

.form-input {
  width: 100%;
  padding: 0.32rem 0.42rem;
  border: 1px solid var(--border-default);
  border-radius: 0.36rem;
  background: var(--surface-raised);
  color: var(--text-primary);
  font: inherit;
  font-size: var(--font-size-caption);
  box-sizing: border-box;
}

.form-input:focus {
  outline: none;
  border-color: var(--border-strong);
}

.form-input:read-only {
  background: var(--surface-sunken);
  color: var(--text-faint);
  cursor: default;
}

.field-error {
  font-size: var(--font-size-caption);
  color: var(--danger);
  margin-top: 0.06rem;
  line-height: 1.3;
}

.form-summary {
  margin-top: 0.32rem;
  padding: 0.3rem 0.52rem;
  border-radius: 0.36rem;
  font-size: var(--font-size-caption);
  text-align: center;
  border: 1px solid transparent;
}

.form-summary.valid {
  background: var(--success-surface);
  color: var(--success);
  border-color: var(--success-border);
}

.form-summary.invalid {
  background: rgba(255, 123, 123, 0.08);
  color: var(--danger);
  border-color: rgba(255, 123, 123, 0.22);
}
</style>
