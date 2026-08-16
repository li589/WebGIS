<script setup lang="ts">
/**
 * CdseDownloadForm.vue
 *
 * download/cdse_download 节点专用参数表单（CDSE 产品下载）。
 *
 * 字段：
 *   - product_ids: 产品 UUID 列表（逗号/换行分隔，textarea）
 *   - odata_filter: OData $filter（在线检索）
 *   - target_dir / use / legacy_urls
 *   - force / max_products
 *
 * 凭据不经节点参数下发（防明文落库），统一走门户 copernicus，
 * 表单内仅展示凭据状态提示。
 *
 * 附加能力：copernicus 门户凭据状态提示；下载源三选一校验。
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

const NODE_TYPE = 'download/cdse_download'
const PATH_FIELD_MAP = fieldMapForNodeType(NODE_TYPE)

const props = defineProps<{
  node: LGraphNodeClass | null
  readonly?: boolean
}>()

const emit = defineEmits<{
  'update-property': [key: string, value: unknown]
}>()

const DEFAULTS = {
  product_ids: '',
  odata_filter: '',
  target_dir: '',
  use: 'auto',
  legacy_urls: '',
  force: false,
  max_products: '',
}

const USE_OPTIONS = [
  { label: 'auto（cdse → legacy 回退）', value: 'auto' },
  { label: 'cdse（OData $value）', value: 'cdse' },
  { label: 'legacy（公共直链）', value: 'legacy' },
]

const form = reactive<{ [k: string]: unknown }>({ ...DEFAULTS })
const errors = reactive<FormErrors>({})
const errorCount = computed(() => Object.keys(errors).length)

function validateForm() {
  const e: FormErrors = {}
  const use = String(form.use ?? 'auto')
  const hasProductIds = String(form.product_ids ?? '').trim().length > 0
  const hasFilter = String(form.odata_filter ?? '').trim().length > 0
  if (use === 'legacy') {
    const r = validateRequired(form.legacy_urls, 'legacy 直链列表')
    if (r) e.legacy_urls = r
  } else if (!hasProductIds && !hasFilter) {
    e.product_ids = 'product_ids 与 odata_filter 至少填一项（或改用 legacy 直链）'
  }
  const mp = form.max_products
  if (String(mp ?? '').trim() !== '') {
    const n = Number(mp)
    if (!Number.isFinite(n) || n < 1) {
      e.max_products = 'max_products 须为正整数'
    }
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
      <label class="form-label">CDSE 凭据</label>
      <PortalCredHint cred-key="copernicus" />
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

    <!-- 产品 UUID -->
    <div class="form-row">
      <label class="form-label">产品 UUID product_ids（逗号/换行分隔）</label>
      <textarea
        class="form-textarea"
        rows="3"
        :value="String(form.product_ids ?? '')"
        placeholder="8a5dd53e-…)（可经上游检索节点注入 search_results）"
        :readonly="readonly"
        @input="update('product_ids', ($event.target as HTMLTextAreaElement).value)"
      />
      <span v-if="errors.product_ids" class="field-error">{{ errors.product_ids }}</span>
    </div>

    <!-- OData filter -->
    <div class="form-row">
      <label class="form-label">OData $filter（可选）</label>
      <textarea
        class="form-textarea"
        rows="3"
        :value="String(form.odata_filter ?? '')"
        placeholder="Collection/Name eq 'SENTINEL-2' and ContentDate/Start gt 2026-08-01T00:00:00.000Z"
        :readonly="readonly"
        @input="update('odata_filter', ($event.target as HTMLTextAreaElement).value)"
      />
      <span class="field-hint">在线检索产品；与 product_ids 并存时优先显式 UUID</span>
    </div>

    <!-- legacy 直链 -->
    <div class="form-row">
      <label class="form-label">legacy 直链列表 legacy_urls（use=legacy）</label>
      <textarea
        class="form-textarea"
        rows="2"
        :value="String(form.legacy_urls ?? '')"
        placeholder="https://…（逗号/换行分隔，公共数据免凭据）"
        :readonly="readonly"
        @input="update('legacy_urls', ($event.target as HTMLTextAreaElement).value)"
      />
      <span v-if="errors.legacy_urls" class="field-error">{{ errors.legacy_urls }}</span>
    </div>

    <!-- 目标目录 + max_products -->
    <div class="form-row two-col">
      <div class="col">
        <label class="form-label">目标目录 target_dir</label>
        <input
          type="text"
          class="form-input"
          :value="String(form.target_dir ?? '')"
          placeholder="默认 workspace/data_access/cdse"
          :readonly="readonly"
          @input="update('target_dir', ($event.target as HTMLInputElement).value)"
        />
      </div>
      <div class="col">
        <label class="form-label">最多下载数 max_products（可选）</label>
        <input
          type="number"
          class="form-input"
          min="1"
          step="1"
          :value="String(form.max_products ?? '')"
          placeholder="不限"
          :readonly="readonly"
          @input="update('max_products', ($event.target as HTMLInputElement).value)"
        />
        <span v-if="errors.max_products" class="field-error">{{ errors.max_products }}</span>
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
