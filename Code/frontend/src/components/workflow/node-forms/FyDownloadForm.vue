<script setup lang="ts">
/**
 * FyDownloadForm.vue
 *
 * download/fy_download 节点专用参数表单。
 * 风云卫星数据下载：支持 NSMC 门户、NAS SMB、auto 自动回退。
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

const NODE_TYPE = 'download/fy_download'
const PATH_FIELD_MAP = fieldMapForNodeType(NODE_TYPE)

const props = defineProps<{
  node: LGraphNodeClass | null
  readonly?: boolean
}>()

const emit = defineEmits<{
  'update-property': [key: string, value: unknown]
}>()

const DEFAULTS = {
  satellite: 'FY3D',
  data_source: 'auto',
  start_date: '',
  end_date: '',
  local_dir: '',
  band_ids: '1,2',
  orbit_mode: 'MWRID',
}

const form = reactive<{ [k: string]: unknown }>({ ...DEFAULTS })
const errors = reactive<FormErrors>({})
const errorCount = computed(() => Object.keys(errors).length)

function validateForm() {
  const e: FormErrors = {}
  let r = validateRequired(form.local_dir, '本地目录')
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
      <label class="form-label">卫星 satellite</label>
      <AppSelect
        :model-value="String(form.satellite ?? 'FY3D')"
        :disabled="readonly"
        :options="[
          { label: 'FY-3D', value: 'FY3D' },
          { label: 'FY-3B', value: 'FY3B' },
        ]"
        @change="(val: string) => update('satellite', val)"
      />
    </div>

    <div class="form-row">
      <label class="form-label">数据源 data_source</label>
      <AppSelect
        :model-value="String(form.data_source ?? 'auto')"
        :disabled="readonly"
        :options="[
          { label: 'auto（自动回退 NSMC→NAS）', value: 'auto' },
          { label: 'nsmc（NSMC 门户）', value: 'nsmc' },
          { label: 'nas（NAS 远程拉取）', value: 'nas' },
        ]"
        @change="(val: string) => update('data_source', val)"
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
      <label class="form-label">通道 ID band_ids</label>
      <input
        type="text"
        class="form-input"
        :value="String(form.band_ids ?? '1,2')"
        placeholder="1,2"
        :readonly="readonly"
        @input="update('band_ids', ($event.target as HTMLInputElement).value)"
      />
    </div>

    <div class="form-row">
      <label class="form-label">轨道模式 orbit_mode</label>
      <AppSelect
        :model-value="String(form.orbit_mode ?? 'MWRID')"
        :disabled="readonly"
        :options="[
          { label: 'MWRID', value: 'MWRID' },
          { label: 'MWRIA', value: 'MWRIA' },
          { label: 'Both', value: 'Both' },
        ]"
        @change="(val: string) => update('orbit_mode', val)"
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
