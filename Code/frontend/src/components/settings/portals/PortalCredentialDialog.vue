<script setup lang="ts">
/**
 * PortalCredentialDialog — 门户凭据配置对话框。
 *
 * auth_type 决定字段集：bearer/token → token；basic → username+password；header → token+token_header。
 * 留空 = 保留已存值；「清除凭据」整体删除。use_for_nsidc/use_earthdata 仅 Earthdata/NSIDC 体系显示。
 */

import { computed, reactive, ref, watch } from 'vue'
import type { PortalCatalogEntry } from '../../../types/api-reexports'
import { deletePortalCredential, upsertPortalCredential } from '../../../services/settings-api'
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

const saving = ref(false)
const errMsg = ref('')
const okMsg = ref('')

/** 凭据键（credential_profile）与门户同键时显示共享提示。 */
const isEarthdataFamily = computed(
  () =>
    props.portal?.credential_profile === 'earthdata' ||
    props.portal?.credential_profile === 'nsidc',
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
  },
)

async function save() {
  if (!props.portal) return
  errMsg.value = ''
  okMsg.value = ''
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
.pc-footer {
  display: flex;
  gap: 0.4rem;
  padding: 0.5rem 0.72rem;
  border-top: 1px solid var(--border-subtle);
}
</style>
