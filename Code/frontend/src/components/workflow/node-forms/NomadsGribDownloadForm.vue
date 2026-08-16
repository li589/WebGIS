<script setup lang="ts">
/**
 * NomadsGribDownloadForm.vue
 *
 * download/nomads_grib_download 节点专用参数表单（NOMADS GRIB2 下载）。
 *
 * 字段：
 *   - date: 起报日期 YYYYMMDD 或 latest
 *   - model: NOMADS 模型（gfs/gefs/gdas/nam/hrrr/rap，herbie 命名，可自定义）
 *   - product: 产品子路径（如 pgrb2.0p25）
 *   - fxx: 预报时效（小时，number）
 *   - search_string: GRIB 字段子集（herbie 语法）
 *   - members: 集合成员（逗号分隔，GEFS）
 *   - target_dir / use / legacy_url / overwrite
 *
 * 附加能力：target_dir 从系统设置 dataRoot 预填；开放数据无凭据提示。
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
import ParamCombobox from '../ParamCombobox.vue'
import AppSelect from '../../ui/AppSelect.vue'

const NODE_TYPE = 'download/nomads_grib_download'
const PATH_FIELD_MAP = fieldMapForNodeType(NODE_TYPE)

const props = defineProps<{
  node: LGraphNodeClass | null
  readonly?: boolean
}>()

const emit = defineEmits<{
  'update-property': [key: string, value: unknown]
}>()

const DEFAULTS = {
  date: '',
  model: 'gfs',
  product: '',
  fxx: 0,
  search_string: '',
  members: '',
  target_dir: '',
  use: 'auto',
  legacy_url: '',
  overwrite: false,
}

const MODEL_OPTIONS = ['gfs', 'gefs', 'gdas', 'nam', 'hrrr', 'rap']

const USE_OPTIONS = [
  { label: 'auto（herbie → legacy 回退）', value: 'auto' },
  { label: 'herbie（参数化检索/子集）', value: 'herbie' },
  { label: 'legacy（NOMADS 直连）', value: 'legacy' },
]

const form = reactive<{ [k: string]: unknown }>({ ...DEFAULTS })
const errors = reactive<FormErrors>({})
const errorCount = computed(() => Object.keys(errors).length)

function validateForm() {
  const e: FormErrors = {}
  const r = validateRequired(form.date, '起报日期')
  if (r) e.date = r
  else if (!/^\d{8}$|^latest$/i.test(String(form.date).trim())) {
    e.date = 'YYYYMMDD 八位日期或 latest'
  }
  const fxx = Number(form.fxx)
  if (form.fxx !== '' && form.fxx !== null && (!Number.isFinite(fxx) || fxx < 0)) {
    e.fxx = '预报时效须为非负整数（小时）'
  }
  for (const k of Object.keys(errors)) delete errors[k]
  Object.assign(errors, e)
}

function resync() {
  syncFormFromNode(form, props.node, DEFAULTS)
  if (typeof form.overwrite !== 'boolean') form.overwrite = Boolean(form.overwrite)
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
    <!-- 开放数据提示 -->
    <div class="form-row">
      <label class="form-label">数据源</label>
      <div class="portal-status">
        <span class="cred-dot ok"></span>
        <span>NCEP NOMADS 开放数据，无需凭据</span>
      </div>
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

    <!-- 日期 + 模型 -->
    <div class="form-row two-col">
      <div class="col">
        <label class="form-label">起报日期 date</label>
        <input
          type="text"
          class="form-input"
          :value="String(form.date ?? '')"
          placeholder="YYYYMMDD 或 latest"
          :readonly="readonly"
          @input="update('date', ($event.target as HTMLInputElement).value)"
        />
        <span v-if="errors.date" class="field-error">{{ errors.date }}</span>
      </div>
      <div class="col">
        <label class="form-label">模型 model</label>
        <ParamCombobox
          :model-value="String(form.model ?? 'gfs')"
          :options="MODEL_OPTIONS"
          :disabled="readonly"
          :allow-custom="true"
          placeholder="gfs"
          @update:model-value="(v: string) => update('model', v)"
        />
      </div>
    </div>

    <!-- 产品 + 时效 -->
    <div class="form-row two-col">
      <div class="col">
        <label class="form-label">产品 product（可选）</label>
        <input
          type="text"
          class="form-input"
          :value="String(form.product ?? '')"
          placeholder="pgrb2.0p25（空=模型默认）"
          :readonly="readonly"
          @input="update('product', ($event.target as HTMLInputElement).value)"
        />
      </div>
      <div class="col">
        <label class="form-label">预报时效 fxx（h）</label>
        <input
          type="number"
          class="form-input"
          min="0"
          step="1"
          :value="String(form.fxx ?? 0)"
          :readonly="readonly"
          @input="update('fxx', ($event.target as HTMLInputElement).value)"
        />
        <span v-if="errors.fxx" class="field-error">{{ errors.fxx }}</span>
      </div>
    </div>

    <!-- 字段子集 -->
    <div class="form-row">
      <label class="form-label">字段子集 search_string（可选）</label>
      <input
        type="text"
        class="form-input mono"
        :value="String(form.search_string ?? '')"
        placeholder=":TMP:2 m（herbie 语法；空=整场）"
        :readonly="readonly"
        @input="update('search_string', ($event.target as HTMLInputElement).value)"
      />
      <span class="field-hint">仅下载匹配的 GRIB 消息，显著减少体积</span>
    </div>

    <!-- 成员 + legacy URL -->
    <div class="form-row two-col">
      <div class="col">
        <label class="form-label">集合成员 members（可选）</label>
        <input
          type="text"
          class="form-input"
          :value="String(form.members ?? '')"
          placeholder="0,1,2（GEFS，逗号分隔）"
          :readonly="readonly"
          @input="update('members', ($event.target as HTMLInputElement).value)"
        />
      </div>
      <div class="col">
        <label class="form-label">legacy 直链 legacy_url（可选）</label>
        <input
          type="text"
          class="form-input"
          :value="String(form.legacy_url ?? '')"
          placeholder="https://nomads.ncep.noaa.gov/…"
          :readonly="readonly"
          @input="update('legacy_url', ($event.target as HTMLInputElement).value)"
        />
      </div>
    </div>

    <!-- 目标目录 -->
    <div class="form-row">
      <label class="form-label">目标目录 target_dir</label>
      <input
        type="text"
        class="form-input"
        :value="String(form.target_dir ?? '')"
        placeholder="默认 workspace/data_access/nomads"
        :readonly="readonly"
        @input="update('target_dir', ($event.target as HTMLInputElement).value)"
      />
    </div>

    <!-- overwrite -->
    <div class="form-row">
      <label class="checkbox-label">
        <input
          type="checkbox"
          :checked="Boolean(form.overwrite)"
          :disabled="readonly"
          @change="update('overwrite', ($event.target as HTMLInputElement).checked)"
        />
        覆盖已存在文件 overwrite
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

.form-input.mono {
  font-family: var(--font-mono);
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

.field-hint {
  font-size: var(--font-size-caption);
  color: var(--text-faint);
  line-height: 1.4;
}

.portal-status {
  display: flex;
  align-items: center;
  gap: 0.36rem;
  font-size: var(--font-size-caption);
  color: var(--text-muted);
  flex-wrap: wrap;
}

.cred-dot {
  flex: none;
  width: 0.56rem;
  height: 0.56rem;
  border-radius: 50%;
  border: 1px solid var(--surface-3);
  background: var(--success);
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
