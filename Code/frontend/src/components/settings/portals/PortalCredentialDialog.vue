<script setup lang="ts">
/**
 * PortalCredentialDialog — 门户凭据配置对话框。
 *
 * auth_type 决定字段集：bearer/token → token；basic → username+password；header → token+token_header。
 * 留空 = 保留已存值；「清除凭据」整体删除。use_for_nsidc/use_earthdata 仅 Earthdata/NSIDC 体系显示。
 * NSMC 系门户额外支持多账号轮换（限额场景）：保存时整表覆盖已存账号列表，留空不动。
 */

import { computed, reactive, ref, watch } from 'vue'
import type { PortalCatalogEntry } from '../../../types/api-reexports'
import {
  deletePortalCredential,
  fetchPortalCredentials,
  upsertPortalCredential,
} from '../../../services/settings-api'
import AppSelect from '../../ui/AppSelect.vue'

const props = defineProps<{
  visible: boolean
  portal: PortalCatalogEntry | null
}>()

const emit = defineEmits<{
  close: []
  saved: []
}>()

const form = reactive({
  enabled: true,
  auth_type: 'bearer',
  username: '',
  token: '',
  password: '',
  token_header: '',
  use_for_nsidc: false,
  use_earthdata: false,
})

interface AccountRow {
  username: string
  token: string
  password: string
}

const accountRows = ref<AccountRow[]>([])
/** 脏标记：用户编辑过账号表才随保存覆盖（未触碰保持已存列表）。 */
const accountRowsDirty = ref(false)
const storedAccountCount = ref(0)

const saving = ref(false)
const errMsg = ref('')
const okMsg = ref('')

/** 凭据键（credential_profile）与门户同键时显示共享提示。 */
const isEarthdataFamily = computed(
  () =>
    props.portal?.credential_profile === 'earthdata' ||
    props.portal?.credential_profile === 'nsidc',
)

/** NSMC 系门户：支持多账号轮换（单账号限流场景）。 */
const supportsMultiAccount = computed(
  () => props.portal?.credential_profile === 'nsmc' || props.portal?.portal_id === 'nsmc',
)

watch(
  () => props.visible,
  (v) => {
    if (!v || !props.portal) return
    okMsg.value = ''
    errMsg.value = ''
    form.enabled = true
    form.auth_type = props.portal.auth_type || 'bearer'
    form.username = ''
    form.token = ''
    form.password = ''
    form.token_header = props.portal.token_header || ''
    form.use_for_nsidc = false
    form.use_earthdata = false
    accountRows.value = []
    accountRowsDirty.value = false
    storedAccountCount.value = 0
    void prefillFromStored()
  },
)

/** 已存凭据回填非敏感字段（username/enabled/auth_type/共享开关），机密留空。 */
async function prefillFromStored() {
  const portal = props.portal
  if (!portal) return
  try {
    const res = await fetchPortalCredentials()
    // 凭据键 = credential_profile || portal_id（与后端 cred_key 一致）
    const key = portal.credential_profile || portal.portal_id
    const stored = (res.portal_credentials || {})[key]
    // source=none 是无凭据的占位默认（enabled=false），不作为已存配置回填
    if (!stored || !stored.source || stored.source === 'none') return
    if (portal !== props.portal) return
    form.enabled = stored.enabled
    if (stored.auth_type) form.auth_type = stored.auth_type
    if (stored.username) form.username = stored.username
    if (stored.use_for_nsidc != null) form.use_for_nsidc = stored.use_for_nsidc
    if (stored.use_earthdata != null) form.use_earthdata = stored.use_earthdata
    storedAccountCount.value = stored.account_count ?? 0
  } catch {
    // 预填失败不打断对话框，保持默认值
  }
}

function addAccountRow() {
  accountRows.value.push({ username: '', token: '', password: '' })
  accountRowsDirty.value = true
}

function removeAccountRow(i: number) {
  accountRows.value.splice(i, 1)
  accountRowsDirty.value = true
}

function markAccountDirty() {
  accountRowsDirty.value = true
}

/** 有效账号行：token 或（用户名+密码）至少其一；返回 null 表示存在无效行。 */
function validAccountRows(): AccountRow[] | null {
  const rows = accountRows.value.map((r) => ({
    username: r.username.trim(),
    token: r.token.trim(),
    password: r.password.trim(),
  }))
  if (rows.some((r) => !r.token && !(r.username && r.password))) return null
  return rows
}

async function save() {
  if (!props.portal) return
  errMsg.value = ''
  okMsg.value = ''
  const accounts = validAccountRows()
  if (accounts === null) {
    errMsg.value = '多账号行须至少填写 token 或「用户名+密码」其一'
    return
  }
  saving.value = true
  try {
    await upsertPortalCredential(props.portal.portal_id, {
      enabled: form.enabled,
      auth_type: form.auth_type,
      username: form.username.trim() || null,
      token: form.token.trim() || null,
      password: form.password.trim() || null,
      token_header: form.token_header.trim() || null,
      use_for_nsidc: isEarthdataFamily.value ? form.use_for_nsidc : null,
      use_earthdata: isEarthdataFamily.value ? form.use_earthdata : null,
      // 未触碰不动已存账号；编辑过则整表覆盖（显式删完=清空多账号）
      accounts: supportsMultiAccount.value && accountRowsDirty.value ? accounts : null,
    })
    okMsg.value = '凭据已保存（加密存储于后端）'
    emit('saved')
  } catch (e) {
    errMsg.value = (e as Error).message
  } finally {
    saving.value = false
  }
}

async function clearCredentials() {
  if (!props.portal) return
  if (!confirm(`确认清除「${props.portal.name}」的凭据？`)) return
  errMsg.value = ''
  okMsg.value = ''
  saving.value = true
  try {
    await deletePortalCredential(props.portal.portal_id)
    okMsg.value = '凭据已清除'
    emit('saved')
  } catch (e) {
    errMsg.value = (e as Error).message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="visible && portal" class="pc-overlay" @click.self="emit('close')">
      <div class="pc-dialog" role="dialog" aria-modal="true">
        <div class="pc-header">
          <span class="pc-title">配置凭据 · {{ portal.name }}</span>
          <button type="button" class="pc-close" aria-label="关闭" @click="emit('close')">×</button>
        </div>

        <div class="pc-body">
          <p v-if="portal.credentials_hint" class="pc-hint">{{ portal.credentials_hint }}</p>
          <div class="form-grid">
            <label class="checkbox span-2">
              <input v-model="form.enabled" type="checkbox" />
              <span>启用该凭据（关闭后下载/测试不再使用）</span>
            </label>
            <label>
              <span>认证方式</span>
              <AppSelect
                v-model="form.auth_type"
                :options="[
                  { label: 'Bearer Token', value: 'bearer' },
                  { label: 'Basic（用户名/密码）', value: 'basic' },
                  { label: '自定义 Header', value: 'header' },
                  { label: 'Token（含登录态）', value: 'token' },
                ]"
              />
            </label>
            <label>
              <span>Token Header（header 方式用）</span>
              <input v-model="form.token_header" placeholder="X-API-Token" />
            </label>
            <label v-if="form.auth_type === 'basic' || form.auth_type === 'token'">
              <span>用户名</span>
              <input v-model="form.username" autocomplete="off" />
            </label>
            <label v-if="form.auth_type === 'basic'">
              <span>密码</span>
              <input v-model="form.password" type="password" autocomplete="new-password" />
            </label>
            <label v-if="form.auth_type !== 'basic'" class="span-2">
              <span>Token / API Key</span>
              <input
                v-model="form.token"
                type="password"
                autocomplete="new-password"
                placeholder="留空保留已存值"
              />
            </label>
            <template v-if="isEarthdataFamily">
              <label class="checkbox">
                <input v-model="form.use_for_nsidc" type="checkbox" />
                <span>同时用于 NSIDC</span>
              </label>
              <label class="checkbox">
                <input v-model="form.use_earthdata" type="checkbox" />
                <span>Earthdata 共享凭据</span>
              </label>
            </template>
          </div>

          <div v-if="supportsMultiAccount" class="pc-accounts">
            <div class="pc-accounts-head">
              <span class="pc-accounts-title"> 多账号轮换（单账号下载限额时自动切换） </span>
              <button type="button" class="btn pc-add-acc" @click="addAccountRow">添加账号</button>
            </div>
            <p class="pc-accounts-hint">
              已存 {{ storedAccountCount }} 个账号。每行填 token 或「用户名+密码」其一；
              保存时整表覆盖（清空并删完全部行 = 移除多账号）。下载节点遇 401/403/429
              自动冷却该账号并切换下一个。
            </p>
            <div v-for="(row, i) in accountRows" :key="i" class="pc-account-row">
              <input
                v-model="row.username"
                class="acc-user"
                placeholder="用户名"
                autocomplete="off"
                @input="markAccountDirty"
              />
              <input
                v-model="row.password"
                class="acc-pass"
                type="password"
                placeholder="密码"
                autocomplete="new-password"
                @input="markAccountDirty"
              />
              <input
                v-model="row.token"
                class="acc-token"
                type="password"
                placeholder="Token（可选）"
                autocomplete="new-password"
                @input="markAccountDirty"
              />
              <button
                type="button"
                class="pc-acc-del"
                :aria-label="`删除账号 ${i + 1}`"
                @click="removeAccountRow(i)"
              >
                ×
              </button>
            </div>
            <p v-if="accountRows.length === 0" class="pc-accounts-empty">
              暂无新账号行——不添加则保持已存账号列表不变。
            </p>
          </div>

          <p v-if="okMsg" class="pc-ok">{{ okMsg }}</p>
          <p v-if="errMsg" class="form-error">{{ errMsg }}</p>
        </div>

        <div class="pc-footer">
          <button type="button" class="btn primary" :disabled="saving" @click="save">
            {{ saving ? '保存中…' : '保存' }}
          </button>
          <button type="button" class="btn danger" :disabled="saving" @click="clearCredentials">
            清除凭据
          </button>
          <button type="button" class="btn" @click="emit('close')">关闭</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped src="../settings-form.css"></style>
<style scoped>
.pc-overlay {
  position: fixed;
  inset: 0;
  z-index: 1100;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-raised);
}
.pc-dialog {
  width: min(32rem, 92vw);
  max-height: 86vh;
  display: flex;
  flex-direction: column;
  border-radius: 0.6rem;
  border: 1px solid var(--border-default);
  background: var(--surface-2);
  box-shadow: 0 18px 48px rgba(1, 8, 16, 0.4);
  overflow: hidden;
}
.pc-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.55rem 0.72rem;
  border-bottom: 1px solid var(--border-subtle);
}
.pc-title {
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
}
.pc-close {
  width: 1.5rem;
  height: 1.5rem;
  border: none;
  border-radius: 0.4rem;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 1rem;
}
.pc-close:hover {
  background: var(--border-subtle);
}
.pc-body {
  flex: 1;
  overflow-y: auto;
  padding: 0.6rem 0.72rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.pc-hint {
  margin: 0;
  padding: 0.4rem 0.5rem;
  border-radius: 0.36rem;
  background: var(--warning-surface);
  color: var(--accent-warm);
  font-size: var(--font-size-caption);
  line-height: 1.45;
}
.pc-ok {
  margin: 0;
  color: var(--success);
  font-size: var(--font-size-caption);
}
.pc-accounts {
  display: flex;
  flex-direction: column;
  gap: 0.36rem;
  padding: 0.45rem 0.5rem;
  border: 1px solid var(--border-subtle);
  border-radius: 0.4rem;
  background: var(--surface-sunken);
}
.pc-accounts-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.4rem;
}
.pc-accounts-title {
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
}
.pc-add-acc {
  padding: 0.18rem 0.5rem;
  font-size: var(--font-size-caption);
}
.pc-accounts-hint {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  line-height: 1.45;
}
.pc-account-row {
  display: grid;
  grid-template-columns: 1.1fr 1.2fr 1.2fr 1.5rem;
  gap: 0.32rem;
  align-items: center;
}
.pc-account-row input {
  min-width: 0;
  padding: 0.28rem 0.4rem;
  border: 1px solid var(--border-default);
  border-radius: 0.32rem;
  background: var(--surface-2);
  color: var(--text-primary);
  font-size: var(--font-size-caption);
}
.pc-acc-del {
  width: 1.4rem;
  height: 1.4rem;
  border: none;
  border-radius: 0.32rem;
  background: transparent;
  color: var(--danger);
  cursor: pointer;
  font-size: 0.95rem;
  line-height: 1;
}
.pc-acc-del:hover {
  background: var(--danger-surface);
}
.pc-accounts-empty {
  margin: 0;
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
}
.pc-footer {
  display: flex;
  gap: 0.4rem;
  padding: 0.5rem 0.72rem;
  border-top: 1px solid var(--border-subtle);
}
</style>
