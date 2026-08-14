<script setup lang="ts">
/**
 * HttpOpenDataForm.vue
 *
 * download/http_open_data 节点专用参数表单（门户数据下载）。
 *
 * 字段：
 *   - preset: 开放门户预设键（选项来自 GET /config/portals 目录，动态）
 *   - base_url: 自定义 base URL（优先于预设）
 *   - relative_path: 相对路径/对象键（必填）
 *   - query: 可选 query string
 *   - cred_profile: 门户凭据键（earthdata/nsidc/copernicus/…；随门户联动）
 *   - token_header / token_value: 覆盖 profile 的自定义鉴权头
 *   - force_refresh: 忽略缓存强制重下
 *   - accept: 可选 Accept 请求头
 *
 * 附加能力：
 *   - 门户凭据状态提示（requires_credentials / has_credentials / credentials_hint）
 *   - 最终 URL 预览（base_url 或 preset 的 effective_base_url + relative_path + query）
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Check, AlertTriangle } from '../../ui/icons'
import type { LGraphNodeClass } from '../litegraph-setup'
import { fetchPortalCatalog } from '../../../services/settings-api'
import type { PortalCatalogEntry } from '../../../types/api-reexports'
import ParamCombobox from '../ParamCombobox.vue'
import { type FormErrors, syncFormFromNode, validateRequired } from './utils'
import AppSelect from '../../ui/AppSelect.vue'

const props = defineProps<{
  node: LGraphNodeClass | null
  readonly?: boolean
}>()

const emit = defineEmits<{
  'update-property': [key: string, value: unknown]
}>()

const DEFAULTS = {
  preset: 'noaa_nomads',
  base_url: '',
  relative_path: '',
  query: '',
  cred_profile: '',
  token_header: '',
  token_value: '',
  force_refresh: false,
  accept: '',
}

const FALLBACK_PRESETS = [
  'noaa_nomads',
  'noaa_goes',
  'nasa_earthdata',
  'nasa_cmr',
  'nsidc_data',
  'nasa_ges_disc',
  'nasa_gldas',
  'esa_copernicus',
  'esa_download',
  'cma_nsmc',
  'cma_data',
]

const form = reactive<{ [k: string]: unknown }>({ ...DEFAULTS })
const errors = reactive<FormErrors>({})
const errorCount = computed(() => Object.keys(errors).length)

// ── 门户目录（动态 preset/凭据键） ────────────────────────────────────────────
const portals = ref<PortalCatalogEntry[]>([])
const portalsLoaded = ref(false)

const presetOptions = computed(() => {
  if (portals.value.length) {
    return portals.value.map((p) => ({ label: p.name || p.portal_id, value: p.portal_id }))
  }
  return FALLBACK_PRESETS.map((id) => ({ label: id, value: id }))
})

const selectedPortal = computed(
  () => portals.value.find((p) => p.portal_id === String(form.preset ?? '')) ?? null,
)

const credKeyOptions = computed(() => {
  const keys = new Set<string>()
  for (const p of portals.value) {
    const k = String(p.credential_profile || '').trim()
    if (k) keys.add(k)
  }
  if (!keys.size) return ['earthdata', 'nsidc', 'copernicus']
  return [...keys].sort()
})

async function loadPortals() {
  try {
    const data = await fetchPortalCatalog()
    portals.value = (data.portals ?? []).slice()
  } catch {
    portals.value = []
  } finally {
    portalsLoaded.value = true
  }
}

onMounted(loadPortals)

// ── 门户联动：preset 变化时自动补全凭据键 / 鉴权头（不覆盖已填值） ────────────
function applyPortalDefaults(preset: string) {
  const portal = portals.value.find((p) => p.portal_id === preset)
  if (!portal) return
  const updates: Array<[string, unknown]> = []
  const credKey = String(portal.credential_profile || '').trim()
  if (portal.requires_credentials && credKey && !String(form.cred_profile ?? '').trim()) {
    updates.push(['cred_profile', credKey])
  }
  const header = String(portal.token_header || '').trim()
  if (header && !String(form.token_header ?? '').trim()) {
    updates.push(['token_header', header])
  }
  for (const [key, value] of updates) {
    form[key] = value
    emit('update-property', key, value)
  }
}

function onPresetChange(value: string) {
  update('preset', value)
  applyPortalDefaults(value)
}

// ── URL 预览 ─────────────────────────────────────────────────────────────────
const urlPreview = computed(() => {
  const base = String(form.base_url ?? '').trim() || selectedPortal.value?.effective_base_url || ''
  const rel = String(form.relative_path ?? '').trim()
  const qs = String(form.query ?? '').trim()
  if (!base || !rel) return ''
  const joined = `${base.replace(/\/+$/, '')}/${rel.replace(/^\/+/, '')}`
  return qs ? `${joined}?${qs}` : joined
})

// ── 校验 ─────────────────────────────────────────────────────────────────────
function validateForm() {
  const e: FormErrors = {}
  let r = validateRequired(form.preset, '门户预设')
  if (r) e.preset = r
  if (!String(form.base_url ?? '').trim() && !selectedPortal.value && portalsLoaded.value) {
    e.preset = '未知门户预设（目录中不存在，请选择列表项或填写 base_url）'
  }
  r = validateRequired(form.relative_path, '相对路径')
  if (r) e.relative_path = r
  for (const k of Object.keys(errors)) delete errors[k]
  Object.assign(errors, e)
}

function resync() {
  syncFormFromNode(form, props.node, DEFAULTS)
  if (typeof form.force_refresh !== 'boolean') form.force_refresh = Boolean(form.force_refresh)
  validateForm()
}

watch(() => props.node, resync, { immediate: true })
watch(portalsLoaded, () => validateForm())

function update(key: string, value: unknown) {
  form[key] = value
  validateForm()
  emit('update-property', key, value)
}
</script>

<template>
  <div class="node-form">
    <!-- 门户预设 -->
    <div class="form-row">
      <label class="form-label">门户预设 preset</label>
      <AppSelect
        :model-value="String(form.preset ?? '')"
        :disabled="readonly"
        :options="presetOptions"
        @change="(val: string) => onPresetChange(val)"
      />
      <span v-if="errors.preset" class="field-error">{{ errors.preset }}</span>
      <span v-else-if="selectedPortal" class="field-hint">
        {{ selectedPortal.organization }} ·
        {{ selectedPortal.region === 'china' ? '国内' : '国际' }}
      </span>
    </div>

    <!-- 门户信息 + 凭据状态 -->
    <div v-if="selectedPortal" class="form-row">
      <label class="form-label">门户状态</label>
      <div class="portal-status">
        <template v-if="selectedPortal.requires_credentials">
          <span class="cred-dot" :class="{ ok: selectedPortal.has_credentials }"></span>
          <span :class="{ 'cred-missing': !selectedPortal.has_credentials }">
            {{
              selectedPortal.has_credentials
                ? '凭据已配置'
                : '未配置凭据 — 设置 → 远程与存储 → 开放门户'
            }}
          </span>
          <span
            v-if="selectedPortal.credentials_hint && !selectedPortal.has_credentials"
            class="cred-hint"
            :title="selectedPortal.credentials_hint"
          >
            {{ selectedPortal.credentials_hint }}
          </span>
        </template>
        <template v-else>
          <span class="cred-dot ok"></span>
          <span>开放数据，无需凭据</span>
        </template>
      </div>
    </div>

    <!-- base_url（可选覆盖） -->
    <div class="form-row">
      <label class="form-label">自定义 base_url（可选，优先于预设）</label>
      <input
        type="text"
        class="form-input"
        :value="String(form.base_url ?? '')"
        :placeholder="selectedPortal?.effective_base_url || 'https://example.org/data/'"
        :readonly="readonly"
        @input="update('base_url', ($event.target as HTMLInputElement).value)"
      />
    </div>

    <!-- 相对路径 -->
    <div class="form-row">
      <label class="form-label">相对路径 relative_path</label>
      <input
        type="text"
        class="form-input"
        :value="String(form.relative_path ?? '')"
        placeholder="GEOFLX0/2024/01/GEOFLX0.A2024015.V06A.B.hdf"
        :readonly="readonly"
        @input="update('relative_path', ($event.target as HTMLInputElement).value)"
      />
      <span v-if="errors.relative_path" class="field-error">{{ errors.relative_path }}</span>
    </div>

    <!-- query -->
    <div class="form-row">
      <label class="form-label">查询串 query（可选）</label>
      <input
        type="text"
        class="form-input"
        :value="String(form.query ?? '')"
        placeholder="key=value&lang=zh"
        :readonly="readonly"
        @input="update('query', ($event.target as HTMLInputElement).value)"
      />
    </div>

    <!-- URL 预览 -->
    <div v-if="urlPreview" class="form-row">
      <label class="form-label">最终 URL</label>
      <code class="url-preview" :title="urlPreview">{{ urlPreview }}</code>
    </div>

    <!-- 凭据 profile -->
    <div class="form-row">
      <label class="form-label">门户凭据 cred_profile</label>
      <ParamCombobox
        :model-value="String(form.cred_profile ?? '')"
        :options="credKeyOptions"
        :disabled="readonly"
        :allow-custom="true"
        placeholder="不使用凭据（可输入自定义键）"
        @update:model-value="(v: string) => update('cred_profile', v)"
      />
      <span class="field-hint">设置 → 远程与存储 → 开放门户 中配置的凭据键</span>
    </div>

    <!-- 鉴权头覆盖 -->
    <div class="form-row two-col">
      <div class="col">
        <label class="form-label">鉴权头名 token_header</label>
        <input
          type="text"
          class="form-input"
          :value="String(form.token_header ?? '')"
          placeholder="Authorization"
          :readonly="readonly"
          @input="update('token_header', ($event.target as HTMLInputElement).value)"
        />
      </div>
      <div class="col">
        <label class="form-label">鉴权头值 token_value</label>
        <input
          type="password"
          class="form-input"
          :value="String(form.token_value ?? '')"
          placeholder="Bearer …（留空走凭据库）"
          :readonly="readonly"
          @input="update('token_value', ($event.target as HTMLInputElement).value)"
        />
      </div>
    </div>

    <!-- force_refresh + accept -->
    <div class="form-row two-col">
      <div class="col checkbox-col">
        <label class="checkbox-label">
          <input
            type="checkbox"
            :checked="Boolean(form.force_refresh)"
            :disabled="readonly"
            @change="update('force_refresh', ($event.target as HTMLInputElement).checked)"
          />
          忽略缓存强制重下 force_refresh
        </label>
      </div>
      <div class="col">
        <label class="form-label">Accept 头（可选）</label>
        <input
          type="text"
          class="form-input"
          :value="String(form.accept ?? '')"
          placeholder="application/json"
          :readonly="readonly"
          @input="update('accept', ($event.target as HTMLInputElement).value)"
        />
      </div>
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

.checkbox-col {
  justify-content: flex-end;
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

.field-hint.ok {
  color: var(--success);
}

/* 门户状态行 */
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
  background: var(--danger);
}

.cred-dot.ok {
  background: var(--success);
}

.cred-missing {
  color: var(--danger);
}

.cred-hint {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-faint);
}

/* URL 预览 */
.url-preview {
  display: block;
  padding: 0.28rem 0.42rem;
  border: 1px solid var(--border-subtle);
  border-radius: 0.32rem;
  background: var(--surface-sunken);
  color: var(--accent);
  font-family: var(--font-mono);
  font-size: var(--font-size-caption);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 复选框 */
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
