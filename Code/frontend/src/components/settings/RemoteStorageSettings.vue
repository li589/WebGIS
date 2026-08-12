<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useSettingsStore } from '../../stores/settings'
import type { RemoteStorageProtocol, RemoteStorageUpsertRequest } from '../../services/settings-api'
import AppSelect from '../ui/AppSelect.vue'

const settingsStore = useSettingsStore()
const { remoteStorageProfiles, remoteStorageHistory } = storeToRefs(settingsStore)

const protocols: RemoteStorageProtocol[] = ['sftp', 'smb', 'ftp', 'ftps', 'gs']

const form = reactive({
  profile_id: '',
  protocol: 'sftp' as RemoteStorageProtocol,
  host: '',
  port: '' as string,
  username: '',
  secret: '',
  private_key_pem: '',
  domain: '',
  default_share: '',
  host_key_policy: false,
  display_name: '',
  allow_plain_ftp: false,
})

const saving = ref(false)
const testing = ref<Set<string>>(new Set())
const testResults = reactive<Record<string, { success: boolean; message: string }>>({})
/** Optional object URI for per-profile test (stat that path instead of share root). */
const testUris = reactive<Record<string, string>>({})
const historyOpen = reactive<Record<string, boolean>>({})
const historyLoading = reactive<Record<string, boolean>>({})
const formError = ref('')

const sortedProfiles = computed(() =>
  [...remoteStorageProfiles.value].sort((a, b) => a.profile_id.localeCompare(b.profile_id)),
)

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
  form.display_name = ''
  form.allow_plain_ftp = false
  formError.value = ''
}

function fillFormFrom(profileId: string) {
  const p = remoteStorageProfiles.value.find((x) => x.profile_id === profileId)
  if (!p) return
  form.profile_id = p.profile_id
  form.protocol = (p.protocol as RemoteStorageProtocol) || 'sftp'
  form.host = p.host || ''
  form.port = p.port != null ? String(p.port) : ''
  form.username = p.username || ''
  form.secret = ''
  form.private_key_pem = ''
  form.domain = p.domain || ''
  form.default_share = String((p.extra || {}).default_share || '')
  form.host_key_policy = String((p.extra || {}).host_key_policy || '') === 'auto_add'
  form.display_name = p.display_name || ''
  form.allow_plain_ftp = String((p.extra || {}).allow_plain_ftp || '') === 'true'
  formError.value = ''
}

function buildRequest(): RemoteStorageUpsertRequest {
  const existing = remoteStorageProfiles.value.find((x) => x.profile_id === form.profile_id.trim())
  const extra: Record<string, unknown> = {}
  if (form.protocol === 'smb' && form.default_share.trim()) {
    extra.default_share = form.default_share.trim()
  }
  if (form.protocol === 'sftp' && form.host_key_policy) {
    extra.host_key_policy = 'auto_add'
  }
  if (form.protocol === 'ftp' && form.allow_plain_ftp) {
    extra.allow_plain_ftp = 'true'
  }
  const port = form.port.trim() ? Number(form.port) : null
  return {
    protocol: form.protocol,
    host: form.host.trim(),
    port: Number.isFinite(port as number) ? port : null,
    username: form.username.trim() || null,
    // null preserves existing secret / private key when left blank
    secret: form.secret.trim() || null,
    private_key_pem: form.private_key_pem.trim() || null,
    domain: form.domain.trim() || null,
    // Always send reconstructed extra so protocol-specific keys don't linger across edits
    extra,
    display_name: form.display_name.trim() || form.profile_id.trim(),
    // Preserve disabled state on edit-save
    enabled: existing?.enabled ?? true,
  }
}

async function saveProfile() {
  formError.value = ''
  const id = form.profile_id.trim()
  if (!id) {
    formError.value = '请填写 profile_id'
    return
  }
  if (!form.host.trim() && form.protocol !== 'gs') {
    formError.value = '请填写主机 / bucket'
    return
  }
  if (form.protocol === 'smb' && !form.default_share.trim()) {
    formError.value = 'SMB 需填写默认 Share（连通性测试与 smb://host/share/... 解析依赖它）'
    return
  }
  saving.value = true
  try {
    await settingsStore.saveRemoteStorageProfile(id, buildRequest())
    form.secret = ''
    form.private_key_pem = ''
  } catch (e) {
    formError.value = (e as Error).message
  } finally {
    saving.value = false
  }
}

async function runTest(profileId: string) {
  testing.value.add(profileId)
  try {
    const uri = (testUris[profileId] || '').trim() || null
    const result = await settingsStore.runRemoteStorageTest(profileId, uri)
    testResults[profileId] = { success: result.success, message: result.message }
  } catch (e) {
    testResults[profileId] = { success: false, message: (e as Error).message }
  } finally {
    testing.value.delete(profileId)
  }
}

async function toggle(profileId: string, enabled: boolean) {
  try {
    await settingsStore.toggleRemoteStorageProfileEnabled(profileId, enabled)
  } catch (e) {
    alert(`切换失败: ${(e as Error).message}`)
  }
}

async function remove(profileId: string) {
  if (!confirm(`确认删除远程存储配置「${profileId}」？`)) return
  try {
    await settingsStore.removeRemoteStorageProfile(profileId)
  } catch (e) {
    alert(`删除失败: ${(e as Error).message}`)
  }
}

async function toggleHistory(profileId: string) {
  const open = !historyOpen[profileId]
  historyOpen[profileId] = open
  if (!open) return
  historyLoading[profileId] = true
  try {
    await settingsStore.loadRemoteStorageHistory(profileId)
  } catch (e) {
    alert(`加载历史失败: ${(e as Error).message}`)
  } finally {
    historyLoading[profileId] = false
  }
}

async function restoreHistory(profileId: string, historyId: number) {
  try {
    await settingsStore.restoreRemoteStorageFromHistory(profileId, historyId)
  } catch (e) {
    alert(`恢复失败: ${(e as Error).message}`)
  }
}

async function deleteHistory(profileId: string, historyId: number) {
  if (!confirm(`删除历史 #${historyId}？`)) return
  try {
    await settingsStore.removeRemoteStorageHistoryEntry(profileId, historyId)
  } catch (e) {
    alert(`删除失败: ${(e as Error).message}`)
  }
}
</script>

<template>
  <div class="remote-storage-settings">
    <section class="settings-section">
      <h3 class="section-title">远程存储凭证</h3>
      <p class="section-hint">
        支持 sftp / smb / ftp(s) / gs。URI 形如
        <code>smb://host/share/path/file.h5?cred=profile_id</code>
        或
        <code>sftp://host/path?cred=profile_id</code>。 工作流「远程拉取」节点也可填
        <code>cred_profile</code> 参数引用本页 profile。
        算法取数与下载链共用；凭证落在本机加密库，多机需同步 DB +
        <code>BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY</code>。
      </p>

      <div class="form-card">
        <div class="form-grid">
          <label>
            <span>Profile ID</span>
            <input v-model="form.profile_id" placeholder="nas-lab" />
          </label>
          <label>
            <span>协议</span>
            <AppSelect
              v-model="form.protocol"
              :options="protocols.map((p) => ({ label: p, value: p }))"
            />
          </label>
          <label>
            <span>{{ form.protocol === 'gs' ? 'Bucket' : '主机' }}</span>
            <input v-model="form.host" placeholder="192.168.1.10" />
          </label>
          <label>
            <span>端口</span>
            <input v-model="form.port" placeholder="默认" />
          </label>
          <label>
            <span>用户名</span>
            <input v-model="form.username" autocomplete="off" />
          </label>
          <label>
            <span>密码 / SA JSON</span>
            <input v-model="form.secret" type="password" autocomplete="new-password" />
          </label>
          <label v-if="form.protocol === 'sftp'" class="span-2">
            <span>SSH 私钥 PEM（可选）</span>
            <textarea v-model="form.private_key_pem" rows="3" placeholder="-----BEGIN ..." />
          </label>
          <label v-if="form.protocol === 'sftp'" class="checkbox span-2">
            <input v-model="form.host_key_policy" type="checkbox" />
            <span>自动接受主机密钥（仅内网）</span>
          </label>
          <label v-if="form.protocol === 'smb'">
            <span>域</span>
            <input v-model="form.domain" />
          </label>
          <label v-if="form.protocol === 'smb'">
            <span>默认 Share（必填）</span>
            <input v-model="form.default_share" placeholder="data" />
          </label>
          <label v-if="form.protocol === 'ftp'" class="checkbox">
            <input v-model="form.allow_plain_ftp" type="checkbox" />
            <span>允许明文 FTP</span>
          </label>
          <label class="span-2">
            <span>显示名</span>
            <input v-model="form.display_name" />
          </label>
        </div>
        <p v-if="formError" class="form-error">{{ formError }}</p>
        <div class="form-actions">
          <button type="button" class="btn primary" :disabled="saving" @click="saveProfile">
            {{ saving ? '保存中…' : '保存 / 更新' }}
          </button>
          <button type="button" class="btn" @click="resetForm">新建空白</button>
        </div>
      </div>
    </section>

    <section class="settings-section">
      <h3 class="section-title">已配置 Profile</h3>
      <div v-if="sortedProfiles.length === 0" class="empty">暂无远程存储配置</div>
      <div v-else class="key-card-list">
        <div
          v-for="item in sortedProfiles"
          :key="item.profile_id"
          class="key-card"
          :class="{ disabled: !item.enabled }"
        >
          <div class="key-card-header">
            <span class="key-name">{{ item.display_name || item.profile_id }}</span>
            <div class="key-badges">
              <span class="key-badge">{{ item.protocol }}</span>
              <span v-if="item.last_test_status === 'ok'" class="key-badge badge-ok">已验证</span>
              <span v-else-if="item.last_test_status === 'failed'" class="key-badge badge-fail"
                >失败</span
              >
            </div>
          </div>
          <p class="key-desc">
            {{ item.profile_id }} · {{ item.host || '(no host)' }}
            <template v-if="item.port">:{{ item.port }}</template>
            · {{ item.has_secret || item.has_private_key ? '已配置密钥' : '未配置密钥' }}
            <template v-if="item.protocol === 'smb' && (item.extra || {}).default_share">
              · share={{ (item.extra || {}).default_share }}
            </template>
          </p>
          <label class="test-uri">
            <span>测试对象 URI（可选，留空则只测连通性）</span>
            <input
              v-model="testUris[item.profile_id]"
              :placeholder="
                item.protocol === 'smb'
                  ? 'smb://host/share/path/file.h5?cred=' + item.profile_id
                  : 'sftp://host/path/file.h5?cred=' + item.profile_id
              "
            />
          </label>
          <p
            v-if="testResults[item.profile_id]"
            class="test-msg"
            :class="{ ok: testResults[item.profile_id].success }"
          >
            {{ testResults[item.profile_id].message }}
          </p>
          <div class="actions">
            <button type="button" class="btn" @click="fillFormFrom(item.profile_id)">编辑</button>
            <button
              type="button"
              class="btn"
              :disabled="testing.has(item.profile_id)"
              @click="runTest(item.profile_id)"
            >
              {{ testing.has(item.profile_id) ? '测试中…' : '测试' }}
            </button>
            <button type="button" class="btn" @click="toggleHistory(item.profile_id)">
              {{ historyOpen[item.profile_id] ? '收起历史' : '历史' }}
            </button>
            <button type="button" class="btn" @click="toggle(item.profile_id, !item.enabled)">
              {{ item.enabled ? '禁用' : '启用' }}
            </button>
            <button type="button" class="btn danger" @click="remove(item.profile_id)">删除</button>
          </div>
          <div v-if="historyOpen[item.profile_id]" class="history-panel">
            <p v-if="historyLoading[item.profile_id]" class="history-empty">加载中…</p>
            <p
              v-else-if="!(remoteStorageHistory[item.profile_id] || []).length"
              class="history-empty"
            >
              暂无密钥历史（更新密码/私钥时会自动归档）
            </p>
            <ul v-else class="history-list">
              <li
                v-for="row in remoteStorageHistory[item.profile_id]"
                :key="row.id"
                class="history-row"
              >
                <span>
                  <code>{{ row.masked_secret || '****' }}</code>
                  · {{ row.has_private_key ? '含私钥' : '无私钥' }} · {{ row.superseded_at }}
                </span>
                <span class="history-actions">
                  <button
                    type="button"
                    class="btn"
                    @click="restoreHistory(item.profile_id, row.id)"
                  >
                    恢复
                  </button>
                  <button
                    type="button"
                    class="btn danger"
                    @click="deleteHistory(item.profile_id, row.id)"
                  >
                    删除
                  </button>
                </span>
              </li>
            </ul>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.remote-storage-settings {
  display: flex;
  flex-direction: column;
  gap: 1.2rem;
}
.settings-section {
  display: flex;
  flex-direction: column;
  gap: 0.52rem;
}
.section-title {
  margin: 0 0 0.32rem;
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
}
.section-hint {
  margin: 0;
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
  line-height: 1.5;
}
.section-hint code {
  color: var(--accent-strong);
}
.form-card,
.key-card {
  padding: 0.62rem 0.72rem;
  border-radius: 0.52rem;
  background: var(--surface-sunken);
  border: 1px solid var(--border-subtle);
}
.key-card.disabled {
  opacity: 0.55;
}
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.48rem;
}
.form-grid label {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
}
.form-grid label.span-2 {
  grid-column: span 2;
}
.form-grid label.checkbox {
  flex-direction: row;
  align-items: center;
  gap: 0.4rem;
}
.form-grid input,
.form-grid select,
.form-grid textarea,
.test-uri input {
  border: 1px solid var(--border-default);
  border-radius: 0.36rem;
  background: var(--surface-1);
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  padding: 0.32rem 0.42rem;
}
.test-uri {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  margin-top: 0.4rem;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
}
.form-error {
  color: var(--danger);
  font-size: var(--font-size-caption);
  margin: 0.4rem 0 0;
}
.form-actions,
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.36rem;
  margin-top: 0.48rem;
}
.btn {
  border: 1px solid var(--border-strong);
  background: var(--surface-2);
  color: var(--text-primary);
  border-radius: 0.32rem;
  font-size: var(--font-size-caption);
  padding: 0.28rem 0.52rem;
  cursor: pointer;
}
.btn.primary {
  background: rgba(56, 120, 196, 0.45);
}
.btn.danger {
  border-color: rgba(255, 120, 120, 0.35);
  color: var(--danger);
}
.btn:disabled {
  opacity: 0.5;
  cursor: default;
}
.key-card-list {
  display: flex;
  flex-direction: column;
  gap: 0.52rem;
}
.key-card-header {
  display: flex;
  justify-content: space-between;
  gap: 0.4rem;
}
.key-name {
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
}
.key-badges {
  display: flex;
  gap: 0.32rem;
}
.key-badge {
  padding: 0.1rem 0.36rem;
  border-radius: 0.26rem;
  font-size: var(--font-size-caption);
  background: var(--border-default);
  color: var(--accent-strong);
}
.badge-ok {
  background: var(--success-surface);
  color: var(--success);
}
.badge-fail {
  background: var(--danger-surface);
  color: var(--danger);
}
.key-desc {
  margin: 0.28rem 0 0;
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
}
.test-msg {
  margin: 0.28rem 0 0;
  color: var(--danger);
  font-size: var(--font-size-caption);
}
.test-msg.ok {
  color: var(--success);
}
.empty {
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
}
.history-panel {
  margin-top: 0.45rem;
  padding-top: 0.4rem;
  border-top: 1px solid var(--border-subtle);
}
.history-empty {
  margin: 0;
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
}
.history-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.32rem;
}
.history-row {
  display: flex;
  justify-content: space-between;
  gap: 0.4rem;
  align-items: center;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
}
.history-row code {
  color: var(--text-primary);
}
.history-actions {
  display: flex;
  gap: 0.28rem;
}
</style>
