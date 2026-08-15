<script setup lang="ts">
/**
 * SshSyncForm.vue
 *
 * download/ssh_sync 节点专用参数表单。
 *
 * 字段：
 *   - server_type: hpc / win11 / nas 遗留内置 + 「远程与存储」profile（ssh/sftp/filebrowser，动态注入）
 *   - remote_path: 远程路径（带"浏览"按钮 → RemoteDirBrowser；profile 走双路径回退浏览）
 *   - local_path:  本地路径（须填写；相对 BACKEND_DATA_ROOT 或绝对路径）
 *   - start_date / end_date: YYYYMMDD
 *   - file_filter: 多选扩展名标签 (.mat/.h5/.nc/.tif/.txt)
 *   - 连接状态指示器（POST /config/remote-storage/{id}/test，仅 profile；admin-only，403 时提示）
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Check, AlertTriangle } from '../../ui/icons'
import type { LGraphNodeClass } from '../litegraph-setup'
import {
  fetchRemoteSources,
  fetchRemoteStorageProfiles,
  testRemoteStorageProfile,
} from '../../../services/settings-api'
import type { RemoteSourceEntry, RemoteStorageProfile } from '../../../types/api-reexports'
import RemoteDirBrowser from './RemoteDirBrowser.vue'
import ParamCombobox from '../ParamCombobox.vue'
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

const NODE_TYPE = 'download/ssh_sync'
const PATH_FIELD_MAP = fieldMapForNodeType(NODE_TYPE)

/** 与后端 _SSH_SYNC_PROFILE_PROTOCOLS 对齐：可直接执行同步的远程存储协议。 */
const SYNC_PROFILE_PROTOCOLS = new Set(['ssh', 'sftp', 'filebrowser'])
const LEGACY_SERVERS = ['hpc', 'win11', 'nas']

const props = defineProps<{
  node: LGraphNodeClass | null
  readonly?: boolean
}>()

const emit = defineEmits<{
  'update-property': [key: string, value: unknown]
}>()

const DEFAULTS = {
  server_type: 'hpc',
  remote_path: '/',
  local_path: '',
  start_date: '',
  end_date: '',
  file_filter: [] as string[],
}

const form = reactive<{ [k: string]: unknown }>({ ...DEFAULTS })

// 表单校验错误集合（实时更新）
const errors = reactive<FormErrors>({})
const errorCount = computed(() => Object.keys(errors).length)

const FILE_FILTER_OPTIONS = ['.mat', '.h5', '.nc', '.tif', '.txt']

/**
 * 实时校验：server_type / remote_path / local_path 非空 + 日期范围合法。
 * 结果写入 reactive errors，驱动模板中的字段错误提示与底部摘要。
 */
function validateForm() {
  const e: FormErrors = {}
  let r = validateRequired(form.server_type, '服务器类型')
  if (r) e.server_type = r
  r = validateRequired(form.remote_path, '远程路径')
  if (r) e.remote_path = r
  r = validateRequired(form.local_path, '本地路径')
  if (r) e.local_path = r
  r = validateDateRange(String(form.start_date ?? ''), String(form.end_date ?? ''))
  if (r) e.date_range = r
  // 先清空再赋值，确保响应式触发
  for (const k of Object.keys(errors)) delete errors[k]
  Object.assign(errors, e)
}

function resync() {
  syncFormFromNode(form, props.node, DEFAULTS)
  // 保证 file_filter 为数组
  if (!Array.isArray(form.file_filter)) form.file_filter = []
  connState.value = { status: 'idle' }
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
  loadSyncProfiles()
  loadRegisteredSources()
})

// ── 动态服务器选项：遗留内置 + 可同步的远程存储 profile ─────────────────────
const syncProfiles = ref<RemoteStorageProfile[]>([])

async function loadSyncProfiles() {
  try {
    // 仅启用中的 profile；凭据细节不出仓库
    const profiles = await fetchRemoteStorageProfiles(false)
    syncProfiles.value = profiles.filter(
      (p) => p.enabled && SYNC_PROFILE_PROTOCOLS.has(String(p.protocol || '').toLowerCase()),
    )
  } catch {
    syncProfiles.value = []
  }
}

// ── 已注册远程数据源（settings → 远程存储「添加为数据源」的别名注册表）──────
const registeredSources = ref<RemoteSourceEntry[]>([])
const selectedSourceId = ref('')

async function loadRegisteredSources() {
  try {
    const entries = await fetchRemoteSources()
    registeredSources.value = entries.filter(
      (s) =>
        s.kind === 'storage_profile' &&
        s.ref_exists &&
        s.ref?.enabled !== false &&
        SYNC_PROFILE_PROTOCOLS.has(String(s.ref?.protocol || '').toLowerCase()),
    )
  } catch {
    registeredSources.value = []
  }
}

/** 选中已注册数据源：快捷填充 server_type（引用的 profile）+ remote_path。 */
function applyRegisteredSource() {
  const entry = registeredSources.value.find((s) => s.remote_source_id === selectedSourceId.value)
  if (!entry || props.readonly) return
  update('server_type', entry.ref_id)
  update('remote_path', entry.remote_path || '/')
}

const serverOptions = computed(() => [
  ...LEGACY_SERVERS,
  ...syncProfiles.value.map((p) => p.profile_id),
])

/** 当前 server_type 是否为远程存储 profile（legacy 内置不支持 UI 浏览/测试）。 */
const isProfileServer = computed(() => {
  const v = String(form.server_type ?? '').trim()
  return !!v && !LEGACY_SERVERS.includes(v)
})

const serverHint = computed(() => {
  const v = String(form.server_type ?? '').trim()
  if (!v) return ''
  const profile = syncProfiles.value.find((p) => p.profile_id === v)
  if (profile) {
    const via = String(profile.failover_state?.['active'] || '') === 'alt' ? '备用路径' : '主路径'
    const cred = profile.has_secret || profile.has_private_key ? '凭据已存' : '缺凭据'
    return `${profile.display_name || profile.profile_id} · ${profile.protocol} · ${via} · ${cred}`
  }
  if (v === 'hpc') return 'hpc — 遗留内置 SFTP（环境变量配置）'
  if (v === 'win11') return 'win11 — 遗留内置 FileBrowser（环境变量配置）'
  if (v === 'nas') return 'nas — 遗留内置 FileBrowser（环境变量配置）'
  return '未识别的 server（不在目录中，运行时按远程存储 profile 解析）'
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

// ── 远程目录浏览 ────────────────────────────────────────────────────────────
const browserVisible = ref(false)

function openBrowser() {
  if (props.readonly) return
  if (!isProfileServer.value) return
  browserVisible.value = true
}

function onBrowserSelect(path: string) {
  update('remote_path', path)
}

// ── 连接状态测试 ────────────────────────────────────────────────────────────
interface ConnState {
  status: 'idle' | 'testing' | 'ok' | 'fail'
  message?: string
  error?: string
}
const connState = ref<ConnState>({ status: 'idle' })

async function testConnection() {
  const server = String(form.server_type ?? '')
  if (!server || props.readonly) return
  if (!isProfileServer.value) {
    connState.value = {
      status: 'fail',
      error: '遗留内置服务器（hpc/win11/nas）不支持 UI 连接测试',
    }
    return
  }
  connState.value = { status: 'testing' }
  try {
    const data = await testRemoteStorageProfile(server)
    if (data.success) {
      connState.value = { status: 'ok', message: data.message || '已连接' }
    } else {
      connState.value = { status: 'fail', error: data.message || '连接失败' }
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    if (msg.startsWith('Settings API failed: 403')) {
      connState.value = {
        status: 'fail',
        error: '仅管理员可测试连接（当前角色无 config 管理权限）',
      }
    } else {
      connState.value = { status: 'fail', error: msg }
    }
  }
}

// 切换服务器时重置连接状态
watch(
  () => form.server_type,
  () => {
    connState.value = { status: 'idle' }
  },
)

// ── file_filter 多选 ────────────────────────────────────────────────────────
function isFilterActive(ext: string): boolean {
  return Array.isArray(form.file_filter) && (form.file_filter as string[]).includes(ext)
}

function toggleFilter(ext: string) {
  if (props.readonly) return
  const arr = Array.isArray(form.file_filter) ? [...(form.file_filter as string[])] : []
  const idx = arr.indexOf(ext)
  if (idx >= 0) arr.splice(idx, 1)
  else arr.push(ext)
  update('file_filter', arr)
}
</script>

<template>
  <div class="node-form">
    <!-- 服务器类型 -->
    <div class="form-row">
      <label class="form-label">服务器 server_type</label>
      <ParamCombobox
        :model-value="String(form.server_type ?? 'hpc')"
        :options="serverOptions"
        :disabled="readonly"
        :allow-custom="true"
        placeholder="hpc / win11 / nas 或远程存储 profile id"
        @update:model-value="(v: string) => update('server_type', v)"
      />
      <span v-if="errors.server_type" class="field-error">{{ errors.server_type }}</span>
      <span v-else-if="serverHint" class="field-hint">{{ serverHint }}</span>
    </div>

    <!-- 已注册远程数据源快捷填充 -->
    <div v-if="registeredSources.length" class="form-row">
      <label class="form-label">快捷填充：已注册数据源</label>
      <div class="input-with-btn">
        <select v-model="selectedSourceId" class="form-input form-select" :disabled="readonly">
          <option value="">选择已注册数据源…</option>
          <option
            v-for="src in registeredSources"
            :key="src.remote_source_id"
            :value="src.remote_source_id"
          >
            {{ src.remote_source_id }}（{{ src.ref?.protocol }} · {{ src.remote_path }}）
          </option>
        </select>
        <button
          type="button"
          class="browse-btn"
          :disabled="readonly || !selectedSourceId"
          title="按注册条目填充服务器与远程路径"
          @click="applyRegisteredSource"
        >
          填充
        </button>
      </div>
    </div>

    <!-- 连接状态 -->
    <div class="form-row">
      <label class="form-label">连接状态</label>
      <div class="conn-row">
        <span
          class="conn-dot"
          :class="{
            ok: connState.status === 'ok',
            fail: connState.status === 'fail',
            testing: connState.status === 'testing',
            idle: connState.status === 'idle',
          }"
        ></span>
        <span class="conn-text">
          <template v-if="connState.status === 'idle'">未测试</template>
          <template v-else-if="connState.status === 'testing'">测试中…</template>
          <template v-else-if="connState.status === 'ok'">
            {{ connState.message || '已连接' }}
          </template>
          <template v-else>{{ connState.error || '连接失败' }}</template>
        </span>
        <button
          type="button"
          class="mini-btn"
          :disabled="readonly || connState.status === 'testing' || !form.server_type"
          :title="
            isProfileServer
              ? '测试远程存储 profile 连通性（admin-only）'
              : '遗留内置服务器不支持 UI 连接测试'
          "
          @click="testConnection"
        >
          测试连接
        </button>
      </div>
    </div>

    <!-- 远程路径 -->
    <div class="form-row">
      <label class="form-label">远程路径 remote_path</label>
      <div class="input-with-btn">
        <input
          type="text"
          class="form-input"
          :value="String(form.remote_path ?? '/')"
          placeholder="/public/shared_data"
          :readonly="readonly"
          @input="update('remote_path', ($event.target as HTMLInputElement).value)"
        />
        <button
          type="button"
          class="browse-btn"
          :disabled="readonly || !isProfileServer"
          :title="
            isProfileServer
              ? '浏览远程存储 profile 目录'
              : '遗留内置服务器不支持目录浏览，请改用远程存储 profile'
          "
          @click="openBrowser"
        >
          浏览
        </button>
      </div>
      <span v-if="errors.remote_path" class="field-error">{{ errors.remote_path }}</span>
    </div>

    <!-- 本地路径 -->
    <div class="form-row">
      <label class="form-label">
        本地路径 local_path
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
        :value="String(form.local_path ?? '')"
        placeholder="请选择或输入本地目录"
        :readonly="readonly"
        @input="update('local_path', ($event.target as HTMLInputElement).value)"
      />
      <span v-if="errors.local_path" class="field-error">{{ errors.local_path }}</span>
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

    <!-- 文件过滤 -->
    <div class="form-row">
      <label class="form-label">文件过滤 file_filter</label>
      <div class="filter-tags">
        <button
          v-for="ext in FILE_FILTER_OPTIONS"
          :key="ext"
          type="button"
          class="filter-tag"
          :class="{ active: isFilterActive(ext) }"
          :disabled="readonly"
          @click="toggleFilter(ext)"
        >
          {{ ext }}
        </button>
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

    <!-- 远程目录浏览对话框 -->
    <RemoteDirBrowser
      :visible="browserVisible"
      :profile-id="String(form.server_type ?? '')"
      :initial-path="String(form.remote_path ?? '/')"
      @close="browserVisible = false"
      @select="onBrowserSelect"
    />
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
  border: 1px solid var(--border-strong);
  background: var(--accent-surface);
  color: var(--accent);
  font-size: var(--font-size-caption);
  cursor: pointer;
}

.sys-fill-btn:hover {
  background: var(--accent-border);
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

.input-with-btn {
  display: flex;
  gap: 0.32rem;
}

.input-with-btn .form-input {
  flex: 1;
}

.browse-btn,
.mini-btn {
  flex: none;
  padding: 0.3rem 0.52rem;
  border: 1px solid var(--border-strong);
  border-radius: 0.32rem;
  background: var(--accent-surface);
  color: var(--accent);
  font: inherit;
  font-size: var(--font-size-caption);
  cursor: pointer;
  transition: all 0.16s ease;
  white-space: nowrap;
}

.browse-btn:hover:not(:disabled),
.mini-btn:hover:not(:disabled) {
  background: var(--accent-border);
  color: var(--success);
}

.browse-btn:disabled,
.mini-btn:disabled {
  opacity: 0.4;
  cursor: default;
}

/* 连接状态 */
.conn-row {
  display: flex;
  align-items: center;
  gap: 0.36rem;
}

.conn-dot {
  flex: none;
  width: 0.56rem;
  height: 0.56rem;
  border-radius: 50%;
  border: 1px solid var(--surface-3);
}

.conn-dot.idle {
  background: var(--surface-sunken);
}

.conn-dot.testing {
  background: var(--accent-warm);
  animation: pulse 1s ease-in-out infinite;
}

.conn-dot.ok {
  background: var(--success);
}

.conn-dot.fail {
  background: var(--danger);
}

@keyframes pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.4;
  }
}

.conn-text {
  flex: 1;
  font-size: var(--font-size-caption);
  color: var(--text-muted);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 文件过滤标签 */
.filter-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.28rem;
}

.filter-tag {
  padding: 0.18rem 0.48rem;
  border: 1px solid var(--border-default);
  border-radius: 0.28rem;
  background: var(--surface-sunken);
  color: var(--text-muted);
  font: inherit;
  font-size: var(--font-size-caption);
  font-family: var(--font-mono);
  cursor: pointer;
  user-select: none;
  transition: all 0.14s ease;
}

.filter-tag:hover:not(:disabled) {
  border-color: var(--border-strong);
  color: var(--text-secondary);
}

.filter-tag.active {
  background: var(--accent-border);
  border-color: var(--border-strong);
  color: var(--accent);
}

.filter-tag:disabled {
  opacity: 0.5;
  cursor: default;
}

/* 字段错误提示 */
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
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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

@media (prefers-reduced-motion: reduce) {
  .conn-dot.testing {
    animation: none;
  }
}
</style>
