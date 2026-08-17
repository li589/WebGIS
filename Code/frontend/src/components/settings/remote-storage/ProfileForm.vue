<script setup lang="ts">
/**
 * ProfileForm — 远程存储 Profile 新增/编辑表单（协议感知 + 双路径）。
 *
 * 语义约定：
 *  - 密码/私钥/SA JSON 留空 = 保留后端已存值（secret: null）
 *  - extra 始终整体重建，避免协议切换后残留旧协议的 extra 键
 *  - 双路径：主路径（内网）+ 备用路径（隧道），fallback_mode auto|manual|off
 */

import { computed, reactive, ref, watch } from 'vue'
import type {
  RemoteFallbackMode,
  RemoteStorageProfile,
  RemoteStorageProtocol,
  RemoteStorageUpsertRequest,
} from '../../../types/api-reexports'
import AppSelect from '../../ui/AppSelect.vue'
import { PROTOCOL_META, PROTOCOL_ORDER, protocolSupportsAlt } from './protocols'

const props = defineProps<{
  /** 编辑目标；null = 新建 */
  editing: RemoteStorageProfile | null
}>()

const emit = defineEmits<{
  saved: [profile: RemoteStorageProfile]
  /** 用户点击「切换为新建」：请求父组件清除 editing 状态 */
  switchNew: []
}>()

const protocols = PROTOCOL_ORDER.map((p) => ({ label: PROTOCOL_META[p].label, value: p }))

const form = reactive({
  profile_id: '',
  protocol: 'sftp' as RemoteStorageProtocol,
  host: '',
  port: '' as string | number,
  username: '',
  secret: '',
  private_key_pem: '',
  domain: '',
  default_share: '',
  host_key_policy: false,
  allow_plain_ftp: false,
  display_name: '',
  // 双路径
  alt_host: '',
  alt_port: '' as string | number,
  alt_url: '',
  fallback_mode: 'auto' as RemoteFallbackMode,
})

const saving = ref(false)
const formError = ref('')
const formHint = ref('')

const meta = computed(() => PROTOCOL_META[form.protocol])
const isEdit = computed(() => Boolean(props.editing))

watch(
  () => form.protocol,
  (proto) => {
    formHint.value = PROTOCOL_META[proto].hint
  },
  { immediate: true },
)

watch(
  () => props.editing,
  (p) => {
    // 草稿保护：同 profile 的对象引用变化（列表刷新后重新传入）不覆盖未保存草稿；
    // editing 置空（删除/切换为新建）则重置表单，避免残留已删 profile 继续可保存
    if (!p) {
      resetForm()
      return
    }
    if (p.profile_id === form.profile_id && form.profile_id) return
    fillFrom(p)
  },
  { immediate: true },
)

function fillFrom(p: RemoteStorageProfile) {
  const extra = (p.extra || {}) as Record<string, unknown>
  form.profile_id = p.profile_id
  form.protocol = (p.protocol as RemoteStorageProtocol) || 'sftp'
  form.host = p.host || ''
  form.port = p.port != null ? String(p.port) : ''
  form.username = p.username || ''
  form.secret = ''
  form.private_key_pem = ''
  form.domain = p.domain || ''
  form.default_share = String(extra.default_share || '')
  form.host_key_policy = String(extra.host_key_policy || '') === 'auto_add'
  form.allow_plain_ftp = String(extra.allow_plain_ftp || '') === 'true'
  form.display_name = p.display_name || ''
  // 备用路径已由后端展平为顶层便捷字段
  form.alt_host = p.alt_host || ''
  form.alt_port = p.alt_port != null ? String(p.alt_port) : ''
  form.alt_url = p.alt_url || ''
  form.fallback_mode = (p.fallback_mode as RemoteFallbackMode) || 'auto'
  formError.value = ''
}

function resetForm() {
  form.profile_id = ''
  form.protocol = 'sftp'
  form.host = ''
  form.port = ''
  form.username = ''
  form.secret = ''
  form.private_key_pem = ''
  form.domain = ''
  form.default_share = ''
  form.host_key_policy = false
  form.allow_plain_ftp = false
  form.display_name = ''
  form.alt_host = ''
  form.alt_port = ''
  form.alt_url = ''
  form.fallback_mode = 'auto'
  formError.value = ''
}

/** 切换为新建：丢弃编辑态（父组件清 editing → watch 重置表单）。 */
function switchToNew() {
  resetForm()
  emit('switchNew')
}

/** 每协议必填字段校验（对齐后端 upsert/探测约束）。 */
function validate(): string | null {
  if (!form.profile_id.trim()) return '请填写 Profile ID（唯一标识，如 lab-nas）'
  const host = form.host.trim()
  switch (form.protocol) {
    case 'smb':
      if (!host) return '请填写主机'
      if (!form.default_share.trim()) return 'SMB 需填写默认 Share（探测与 smb:// 解析依赖它）'
      return null
    case 'lan':
    case 'nfs':
      if (!host) return `请填写${meta.value.hostLabel}`
      return null
    case 'http':
    case 'https':
    case 'filebrowser':
      if (!/^https?:\/\/.+/i.test(host)) return 'Base URL 须以 http:// 或 https:// 开头'
      if (form.protocol === 'filebrowser' && !form.username.trim())
        return 'FileBrowser 需填写登录用户名'
      return null
    case 'gs':
      if (!host) return '请填写 Bucket 名'
      return null
    default:
      if (!host) return '请填写主机'
      return null
  }
}

/** 备用路径校验：url 类协议填 alt_url；host 类协议填 alt_host。 */
function validateAlt(): string | null {
  if (!protocolSupportsAlt(form.protocol)) return null
  const altHost = form.alt_host.trim()
  const altUrl = form.alt_url.trim()
  if (meta.value.usesUrl) {
    if (altHost) return 'URL 类协议的备用路径请填「备用 Base URL」，不要填主机'
    if (altUrl && !/^https?:\/\/.+/i.test(altUrl))
      return '备用 Base URL 须以 http:// 或 https:// 开头'
    if (altUrl && !form.host.trim()) return '填写备用路径前请先填写主路径'
    return null
  }
  if (altUrl) return '非 URL 协议的备用路径请填「备用主机/路径」'
  if (altHost && !form.host.trim()) return '填写备用路径前请先填写主路径'
  return null
}

function buildExtra(): Record<string, unknown> {
  const extra: Record<string, unknown> = {}
  if (form.protocol === 'smb' && form.default_share.trim()) {
    extra.default_share = form.default_share.trim()
  }
  if ((form.protocol === 'sftp' || form.protocol === 'ssh') && form.host_key_policy) {
    extra.host_key_policy = 'auto_add'
  }
  if (form.protocol === 'ftp' && form.allow_plain_ftp) {
    extra.allow_plain_ftp = 'true'
  }
  // URL 类协议把主 Base URL 同步进 extra.base_url（后端 effective target 优先读它）
  if (meta.value.usesUrl && form.host.trim()) {
    extra.base_url = form.host.trim()
  }
  return extra
}

async function save() {
  formError.value = ''
  const err = validate() || validateAlt()
  if (err) {
    formError.value = err
    return
  }
  const port = String(form.port).trim()
  const altPort = String(form.alt_port).trim()
  const request: RemoteStorageUpsertRequest = {
    protocol: form.protocol,
    host: form.host.trim(),
    port: port ? Number(port) : null,
    username: form.username.trim() || null,
    secret: form.secret.trim() || null,
    private_key_pem: form.private_key_pem.trim() || null,
    domain: form.domain.trim() || null,
    extra: buildExtra(),
    display_name: form.display_name.trim() || form.profile_id.trim(),
    enabled: props.editing?.enabled ?? true,
    // 双路径：host/url 空串 = 清除；port 空填 = 0（显式清除），null = 保留原值
    alt_host: protocolSupportsAlt(form.protocol) ? form.alt_host.trim() : '',
    alt_port: protocolSupportsAlt(form.protocol) ? (altPort ? Number(altPort) : 0) : null,
    alt_url: protocolSupportsAlt(form.protocol) ? form.alt_url.trim() : '',
    fallback_mode: form.fallback_mode,
  }
  saving.value = true
  try {
    const { upsertRemoteStorageProfile } = await import('../../../services/settings-api')
    const saved = await upsertRemoteStorageProfile(form.profile_id.trim(), request)
    form.secret = ''
    form.private_key_pem = ''
    emit('saved', saved)
  } catch (e) {
    formError.value = (e as Error).message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="profile-form form-card">
    <div class="form-head">
      <span class="form-title">{{
        isEdit ? `编辑 · ${editing?.profile_id}` : '新建远程存储源'
      }}</span>
      <button v-if="isEdit" type="button" class="btn" @click="switchToNew">切换为新建</button>
    </div>

    <div class="form-grid">
      <label>
        <span>Profile ID <em class="req">*</em></span>
        <input
          v-model="form.profile_id"
          :disabled="isEdit"
          placeholder="lab-nas"
          title="唯一标识：URI ?cred= 与工作流 cred_profile 引用它"
        />
      </label>
      <label>
        <span>协议</span>
        <AppSelect v-model="form.protocol" :options="protocols" />
      </label>
      <label>
        <span>{{ meta.hostLabel }} <em class="req">*</em></span>
        <input v-model="form.host" :placeholder="meta.hostPlaceholder" />
      </label>
      <label v-if="meta.defaultPort != null || String(form.port)">
        <span>端口</span>
        <input
          v-model="form.port"
          :placeholder="meta.defaultPort ? `默认 ${meta.defaultPort}` : '默认'"
        />
      </label>
      <label v-if="!meta.usesPath && form.protocol !== 'gs'">
        <span>用户名</span>
        <input v-model="form.username" autocomplete="off" />
      </label>
      <label v-if="form.protocol !== 'gs' && !meta.usesPath">
        <span>{{ form.protocol === 'filebrowser' ? '密码' : '密码 / Token' }}</span>
        <input
          v-model="form.secret"
          type="password"
          autocomplete="new-password"
          :placeholder="
            isEdit && (editing?.has_secret || editing?.has_private_key) ? '留空保留已存值' : ''
          "
        />
      </label>
      <label v-if="form.protocol === 'gs'" class="span-2">
        <span>Service Account JSON <em class="req">*</em></span>
        <textarea
          v-model="form.secret"
          rows="3"
          autocomplete="off"
          :placeholder="
            isEdit && editing?.has_secret
              ? '留空保留已存 JSON'
              : '{ &quot;type&quot;: &quot;service_account&quot;, ... }'
          "
        />
      </label>
      <label v-if="form.protocol === 'sftp' || form.protocol === 'ssh'" class="span-2">
        <span>SSH 私钥 PEM（可选，与密码二选一）</span>
        <textarea
          v-model="form.private_key_pem"
          rows="3"
          placeholder="粘贴完整 PEM 块（RSA / Ed25519 / ECDSA，含首尾标记行）"
        />
      </label>
      <label v-if="form.protocol === 'smb'">
        <span>域（可选）</span>
        <input v-model="form.domain" placeholder="WORKGROUP" />
      </label>
      <label v-if="form.protocol === 'smb'">
        <span>默认 Share <em class="req">*</em></span>
        <input v-model="form.default_share" placeholder="data" />
      </label>
      <label v-if="form.protocol === 'ftp'" class="checkbox">
        <input v-model="form.allow_plain_ftp" type="checkbox" />
        <span>允许明文 FTP（仅可信内网）</span>
      </label>
      <label v-if="form.protocol === 'sftp' || form.protocol === 'ssh'" class="checkbox">
        <input v-model="form.host_key_policy" type="checkbox" />
        <span>自动接受主机密钥（仅内网）</span>
      </label>
      <label class="span-2">
        <span>显示名</span>
        <input v-model="form.display_name" placeholder="实验室 NAS" />
      </label>
    </div>

    <!-- 双路径 -->
    <div v-if="protocolSupportsAlt(form.protocol)" class="dual-path">
      <div class="dual-path-head">
        <span class="dual-path-title">双路径访问（内网优先，异常自动切换）</span>
        <label class="fallback-select">
          <span>回退模式</span>
          <AppSelect
            v-model="form.fallback_mode"
            :options="[
              { label: '自动（推荐）', value: 'auto' },
              { label: '手动', value: 'manual' },
              { label: '关闭', value: 'off' },
            ]"
          />
        </label>
      </div>
      <div class="dual-grid">
        <div class="path-card primary">
          <span class="path-tag">主路径 · 内网</span>
          <p class="path-note">
            {{
              meta.usesUrl ? '即上方 Base URL' : meta.usesPath ? '即上方路径' : '即上方主机/端口'
            }}
          </p>
        </div>
        <div class="path-card alt">
          <span class="path-tag">备用路径 · 隧道</span>
          <div class="path-fields">
            <label v-if="!meta.usesUrl">
              <span>备用{{ meta.usesPath ? '路径' : '主机' }}</span>
              <input
                v-model="form.alt_host"
                :placeholder="meta.usesPath ? '/mnt/nas-tunnel' : 'tunnel.example.org'"
              />
            </label>
            <label v-if="!meta.usesUrl">
              <span>备用端口</span>
              <input v-model="form.alt_port" placeholder="默认同主端口" />
            </label>
            <label v-if="meta.usesUrl" class="span-2">
              <span>备用 Base URL</span>
              <input v-model="form.alt_url" placeholder="https://fb-tunnel.example.org" />
            </label>
          </div>
        </div>
      </div>
      <p class="dual-hint">
        auto：主路径网络类失败自动改走备用；认证失败不切换。手动切换在卡片「切主/切备」操作。
      </p>
    </div>

    <p v-if="formHint" class="proto-hint">{{ formHint }}</p>
    <p v-if="formError" class="form-error">{{ formError }}</p>
    <div class="form-actions">
      <button type="button" class="btn primary" :disabled="saving" @click="save">
        {{ saving ? '保存中…' : isEdit ? '保存修改' : '创建' }}
      </button>
      <button v-if="!isEdit" type="button" class="btn" @click="resetForm">清空</button>
    </div>
  </div>
</template>

<style scoped src="../settings-form.css"></style>
<style scoped>
.profile-form {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.form-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.4rem;
}
.form-title {
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
}
.proto-hint {
  margin: 0;
  color: var(--accent-warm);
  font-size: var(--font-size-caption);
  line-height: 1.45;
}
.req {
  color: var(--danger);
  font-style: normal;
}
.dual-path {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  padding: 0.5rem 0.6rem;
  border: 1px dashed var(--border-default);
  border-radius: 0.45rem;
}
.dual-path-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
  flex-wrap: wrap;
}
.dual-path-title {
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
}
.fallback-select {
  display: flex;
  align-items: center;
  gap: 0.36rem;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
}
.dual-grid {
  display: grid;
  grid-template-columns: 1fr 1.6fr;
  gap: 0.45rem;
  align-items: stretch;
}
.path-card {
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
  padding: 0.42rem 0.5rem;
  border-radius: 0.36rem;
  background: var(--surface-sunken);
  border: 1px solid var(--border-subtle);
}
.path-tag {
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
}
.path-note {
  margin: 0;
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
}
.path-fields {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.4rem;
}
.path-fields label {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
}
.path-fields label.span-2 {
  grid-column: span 2;
}
.path-fields input {
  border: 1px solid var(--border-default);
  border-radius: 0.36rem;
  background: var(--surface-1);
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  padding: 0.3rem 0.4rem;
}
.dual-hint {
  margin: 0;
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
  line-height: 1.4;
}
</style>
