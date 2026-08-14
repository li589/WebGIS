<script setup lang="ts">
/**
 * GldasDownloadForm.vue
 *
 * download/gldas_download 节点专用参数表单。
 */
import { computed, onMounted, reactive, watch } from 'vue'
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
import {
  fillPathFieldsFromSystemSettings,
  loadSystemPathDefaults,
} from '../../../composables/system-settings-fill'
import { fieldMapForNodeType } from '../../../composables/node-form-system-settings-map'
import { WORKFLOW_COPY } from '../../../ui-copy/workflow'
import AppSelect from '../../ui/AppSelect.vue'

const NODE_TYPE = 'download/gldas_download'
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
  version: '2.1',
  short_name: 'GLDAS_NOAH025_3H',
  dry_run: false,
  max_files: '',
}

const form = reactive<{ [k: string]: unknown }>({ ...DEFAULTS })
const errors = reactive<FormErrors>({})
const errorCount = computed(() => Object.keys(errors).length)

function validateForm() {
  const e: FormErrors = {}
  let r = validateRequired(form.short_name, '数据集短名')
  if (r) e.short_name = r
  r = validateRequired(form.local_dir, '本地目录')
  if (r) e.local_dir = r
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
</script>

<template>
  <div class="node-form">
    <div class="form-row">
      <label class="form-label">数据集 short_name</label>
      <input
        type="text"
        class="form-input"
        :value="String(form.short_name ?? '')"
        placeholder="GLDAS_NOAH025_3H"
        :readonly="readonly"
        @input="update('short_name', ($event.target as HTMLInputElement).value)"
      />
      <span v-if="errors.short_name" class="field-error">{{ errors.short_name }}</span>
    </div>

    <div class="form-row">
      <label class="form-label">版本 version</label>
      <AppSelect
        :model-value="String(form.version ?? '2.1')"
        :disabled="readonly"
        :options="[{ label: '2.1', value: '2.1' }]"
        @change="(val: string) => update('version', val)"
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

    <div class="form-row">
      <label class="form-label">max_files（可选）</label>
      <input
        type="number"
        class="form-input"
        :value="form.max_files === '' || form.max_files == null ? '' : Number(form.max_files)"
        placeholder="联调节流"
        :readonly="readonly"
        @input="
          update(
            'max_files',
            ($event.target as HTMLInputElement).value
              ? Number(($event.target as HTMLInputElement).value)
              : null,
          )
        "
      />
    </div>

    <div class="form-row form-row-check">
      <label class="form-check">
        <input
          type="checkbox"
          :checked="Boolean(form.dry_run)"
          :disabled="readonly"
          @change="update('dry_run', ($event.target as HTMLInputElement).checked)"
        />
        dry_run（仅搜索不下载）
      </label>
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

.form-row {
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
  margin-bottom: 0.42rem;
}

.form-row-check {
  margin-top: 0.1rem;
}

.form-check {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: var(--font-size-caption);
  color: var(--text-primary);
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
