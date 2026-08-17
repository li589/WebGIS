<script setup lang="ts">
/**
 * CdsDownloadForm.vue
 *
 * download/cds_download 节点专用参数表单（CDS 再分析下载）。
 *
 * 字段：
 *   - dataset: CDS 数据集 ID（如 reanalysis-era5-single-levels）
 *   - request: CDS request JSON（textarea）
 *   - target_dir: 本地目标目录（默认 workspace/data_access/cds）
 *   - use: 下载路径 auto / cdsapi / legacy
 *   - filename / direct_url / force
 *
 * 凭据不经节点参数下发（防明文落库），统一走门户 ecmwf_cds /
 * BACKEND_CDS_API_KEY，表单内仅展示凭据状态提示。
 *
 * 附加能力：
 *   - ecmwf_cds 门户凭据状态提示
 *   - request JSON 语法校验
 *   - target_dir 从系统设置 dataRoot 预填
 */
import { computed, onMounted, reactive, watch } from 'vue'
import { Check, AlertTriangle } from '../../ui/icons'
import type { LGraphNodeClass } from '../litegraph-setup'
import { type FormErrors, syncFormFromNode, validateRequired } from './utils'
import {
  fillPathFieldsFromSystemSettings,
  loadSystemPathDefaults,
} from '../../../composables/system-settings-fill'
import { fieldMapForNodeType } from '../../../composables/node-form-system-settings-map'
import AppSelect from '../../ui/AppSelect.vue'
import PortalCredHint from './PortalCredHint.vue'

const NODE_TYPE = 'download/cds_download'
const PATH_FIELD_MAP = fieldMapForNodeType(NODE_TYPE)

const props = defineProps<{
  node: LGraphNodeClass | null
  readonly?: boolean
}>()

const emit = defineEmits<{
  'update-property': [key: string, value: unknown]
}>()

const DEFAULTS = {
  dataset: '',
  request: '',
  target_dir: '',
  use: 'auto',
  filename: '',
  direct_url: '',
  force: false,
}

const USE_OPTIONS = [
  { label: 'auto（cdsapi → legacy 回退）', value: 'auto' },
  { label: 'cdsapi（排队轮询）', value: 'cdsapi' },
  { label: 'legacy（静态直链）', value: 'legacy' },
]

const form = reactive<{ [k: string]: unknown }>({ ...DEFAULTS })
const errors = reactive<FormErrors>({})
const errorCount = computed(() => Object.keys(errors).length)

function validateForm() {
  const e: FormErrors = {}
  const use = String(form.use ?? 'auto')
  if (use !== 'legacy') {
    let r = validateRequired(form.dataset, '数据集 ID')
    if (r) e.dataset = r
    r = validateRequired(form.request, 'request JSON')
    if (r) e.request = r
    else {
      try {
        const parsed: unknown = JSON.parse(String(form.request))
        if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
          e.request = 'request 必须是 JSON 对象'
        }
      } catch {
        e.request = 'request 不是合法 JSON'
      }
    }
  } else {
    const r = validateRequired(form.direct_url, 'legacy 直链 URL')
    if (r) e.direct_url = r
  }
  for (const k of Object.keys(errors)) delete errors[k]
  Object.assign(errors, e)
}

function resync() {
  syncFormFromNode(form, props.node, DEFAULTS)
  if (typeof form.force !== 'boolean') form.force = Boolean(form.force)
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

function update(key: string, value: unknown) {
  form[key] = value
  validateForm()
  emit('update-property', key, value)
}
</script>

<template>
  <div class="node-form">
    <!-- 门户凭据状态 -->
    <div class="form-row">
      <label class="form-label">CDS 凭据</label>
      <PortalCredHint cred-key="ecmwf_cds" />
    </div>

    <!-- 下载路径 -->
    <div class="form-row">
      <label class="form-label">下载路径 use</label>
      <AppSelect
        :model-value="String(form.use ?? 'auto')"
        :disabled="readonly"
        :options="USE_OPTIONS"
        @change="(val: string) => update('use', val)"
      />
    </div>

    <!-- 数据集 -->
    <div class="form-row">
      <label class="form-label">数据集 dataset</label>
      <input
        type="text"
        class="form-input"
        :value="String(form.dataset ?? '')"
        placeholder="reanalysis-era5-single-levels"
        :readonly="readonly"
        @input="update('dataset', ($event.target as HTMLInputElement).value)"
      />
      <span v-if="errors.dataset" class="field-error">{{ errors.dataset }}</span>
    </div>

    <!-- request JSON -->
    <div class="form-row">
      <label class="form-label">request JSON</label>
      <textarea
        class="form-textarea"
        rows="5"
        :value="String(form.request ?? '')"
        placeholder='{"variable": ["2m_temperature"], "date": ["2026-08-01"], "time": ["00:00"], "data_format": "grib"}'
        :readonly="readonly"
        @input="update('request', ($event.target as HTMLTextAreaElement).value)"
      />
      <span v-if="errors.request" class="field-error">{{ errors.request }}</span>
      <span v-else class="field-hint">CDS API request 体（变量/日期/范围/格式）</span>
    </div>

    <!-- legacy 直链 -->
    <div class="form-row">
      <label class="form-label">legacy 直链 direct_url</label>
      <input
        type="text"
        class="form-input"
        :value="String(form.direct_url ?? '')"
        placeholder="https://…（use=legacy 时必填）"
        :readonly="readonly"
        @input="update('direct_url', ($event.target as HTMLInputElement).value)"
      />
      <span v-if="errors.direct_url" class="field-error">{{ errors.direct_url }}</span>
      <span v-else class="field-hint"
        >凭据走门户 ecmwf_cds / BACKEND_CDS_API_KEY，不在节点参数中填写</span
      >
    </div>

    <!-- 目标目录 + 文件名 -->
    <div class="form-row two-col">
      <div class="col">
        <label class="form-label">目标目录 target_dir</label>
        <input
          type="text"
          class="form-input"
          :value="String(form.target_dir ?? '')"
          placeholder="默认 workspace/data_access/cds"
          :readonly="readonly"
          @input="update('target_dir', ($event.target as HTMLInputElement).value)"
        />
      </div>
      <div class="col">
        <label class="form-label">文件名 filename（可选）</label>
        <input
          type="text"
          class="form-input"
          :value="String(form.filename ?? '')"
          placeholder="默认由数据集/请求推导"
          :readonly="readonly"
          @input="update('filename', ($event.target as HTMLInputElement).value)"
        />
      </div>
    </div>

    <!-- force -->
    <div class="form-row">
      <label class="checkbox-label">
        <input
          type="checkbox"
          :checked="Boolean(form.force)"
          :disabled="readonly"
          @change="update('force', ($event.target as HTMLInputElement).checked)"
        />
        忽略已有文件强制重下 force
      </label>
    </div>

    <!-- 校验状态摘要 -->
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

.form-row.two-col {
  flex-direction: row;
  gap: 0.42rem;
}

.form-row.two-col .col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
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

.form-textarea {
  width: 100%;
  padding: 0.32rem 0.42rem;
  border: 1px solid var(--border-default);
  border-radius: 0.36rem;
  background: var(--surface-raised);
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: var(--font-size-caption);
  box-sizing: border-box;
  resize: vertical;
}

.form-textarea:focus {
  outline: none;
  border-color: var(--border-strong);
}

.form-textarea:read-only {
  background: var(--surface-sunken);
  color: var(--text-faint);
}

.field-error {
  font-size: var(--font-size-caption);
  color: var(--danger);
  margin-top: 0.06rem;
  line-height: 1.3;
}

.field-hint {
  font-size: var(--font-size-caption);
  color: var(--text-faint);
  line-height: 1.4;
}

.checkbox-label {
  display: inline-flex;
  align-items: center;
  gap: 0.36rem;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
  cursor: pointer;
  padding: 0.32rem 0;
  user-select: none;
}

.checkbox-label input[type='checkbox'] {
  accent-color: var(--accent);
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
