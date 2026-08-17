<script setup lang="ts">
/**
 * OpenPortalPanel — 开放门户面板（「远程与存储」tab 之二）。
 *
 * 内置 + 自定义门户目录，按 国际组织 / 国内机构 分组；凭据配置 / 连通测试 / CMR 检索 /
 * 地址覆盖（builtin）或完整编辑（custom）/ 自定义门户增删。
 */

import { computed, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'
import type { PortalCatalogEntry, PortalUpsertRequest } from '../../../types/api-reexports'
import { useSettingsStore } from '../../../stores/settings'
import AppSelect from '../../ui/AppSelect.vue'
import PortalCard from './PortalCard.vue'
import PortalCredentialDialog from './PortalCredentialDialog.vue'
import PortalSearchDialog from './PortalSearchDialog.vue'

const settingsStore = useSettingsStore()
const { portalCatalog } = storeToRefs(settingsStore)

const credVisible = ref(false)
const credPortal = ref<PortalCatalogEntry | null>(null)

const searchVisible = ref(false)
const searchPortalEntry = ref<PortalCatalogEntry | null>(null)

const urlEditOpen = ref(false)
const urlEditPortal = ref<PortalCatalogEntry | null>(null)
const urlForm = reactive({ base_url: '', alt_url: '' })
const urlSaving = ref(false)
const urlErr = ref('')

const customOpen = ref(false)
const customForm = reactive({
  portal_id: '',
  name: '',
  organization: '',
  region: 'international',
  base_url: '',
  alt_url: '',
  website: '',
  description: '',
  requires_credentials: true,
  auth_type: 'token',
  token_header: '',
  credential_profile: '',
  credentials_hint: '',
})
const customSaving = ref(false)
const customErr = ref('')

const intlPortals = computed(() => portalCatalog.value.filter((p) => p.region !== 'china'))
const chinaPortals = computed(() => portalCatalog.value.filter((p) => p.region === 'china'))

function openCredentials(portal: PortalCatalogEntry) {
  credPortal.value = portal
  credVisible.value = true
}

function onCredSaved() {
  void settingsStore.loadAll({ quiet: true })
}

function openSearch(portal: PortalCatalogEntry) {
  searchPortalEntry.value = portal
  searchVisible.value = true
}

function openUrlEdit(portal: PortalCatalogEntry) {
  urlEditPortal.value = portal
  urlForm.base_url = portal.base_url_overridden ? portal.effective_base_url : ''
  urlForm.alt_url = portal.effective_alt_url || ''
  urlErr.value = ''
  urlEditOpen.value = true
}

async function saveUrlEdit() {
  if (!urlEditPortal.value) return
  if (urlForm.base_url.trim() && !/^https?:\/\/.+/i.test(urlForm.base_url.trim())) {
    urlErr.value = 'Base URL 须以 http:// 或 https:// 开头'
    return
  }
  urlSaving.value = true
  urlErr.value = ''
  try {
    const payload: PortalUpsertRequest = {
      base_url: urlForm.base_url.trim(),
      alt_url: urlForm.alt_url.trim(),
    }
    if (!urlEditPortal.value.builtin) {
      // 自定义门户是全字段 upsert：未传字段会回退默认，须显式带回原值
      payload.name = urlEditPortal.value.name
      payload.auth_type = urlEditPortal.value.auth_type || 'none'
      payload.region = urlEditPortal.value.region || 'international'
      payload.search_capability = urlEditPortal.value.search_capability || 'none'
      payload.token_header = urlEditPortal.value.token_header || null
      payload.credential_profile = urlEditPortal.value.credential_profile || null
      payload.requires_credentials = urlEditPortal.value.requires_credentials
      payload.organization = urlEditPortal.value.organization || null
      payload.website = urlEditPortal.value.website || null
      payload.description = urlEditPortal.value.description || null
    }
    await settingsStore.savePortal(urlEditPortal.value.portal_id, payload)
    urlEditOpen.value = false
  } catch (e) {
    urlErr.value = (e as Error).message
  } finally {
    urlSaving.value = false
  }
}

function resetCustom() {
  customForm.portal_id = ''
  customForm.name = ''
  customForm.organization = ''
  customForm.region = 'international'
  customForm.base_url = ''
  customForm.alt_url = ''
  customForm.website = ''
  customForm.description = ''
  customForm.requires_credentials = true
  customForm.auth_type = 'token'
  customForm.token_header = ''
  customForm.credential_profile = ''
  customForm.credentials_hint = ''
  customErr.value = ''
}

async function saveCustom() {
  const id = customForm.portal_id.trim()
  if (!id) {
    customErr.value = '请填写 Portal ID（小写字母/数字/下划线）'
    return
  }
  if (!/^[a-z0-9_]+$/.test(id)) {
    customErr.value = 'Portal ID 仅允许小写字母、数字与下划线'
    return
  }
  if (!customForm.name.trim() || !/^https?:\/\/.+/i.test(customForm.base_url.trim())) {
    customErr.value = '名称必填；Base URL 须以 http:// 或 https:// 开头'
    return
  }
  customSaving.value = true
  customErr.value = ''
  try {
    await settingsStore.savePortal(id, {
      name: customForm.name.trim(),
      organization: customForm.organization.trim() || null,
      region: customForm.region,
      base_url: customForm.base_url.trim(),
      alt_url: customForm.alt_url.trim() || null,
      website: customForm.website.trim() || null,
      description: customForm.description.trim() || null,
      requires_credentials: customForm.requires_credentials,
      auth_type: customForm.auth_type,
      token_header: customForm.token_header.trim() || null,
      credential_profile: customForm.credential_profile.trim() || null,
      credentials_hint: customForm.credentials_hint.trim() || null,
    })
    customOpen.value = false
    resetCustom()
  } catch (e) {
    customErr.value = (e as Error).message
  } finally {
    customSaving.value = false
  }
}

async function removeCustom(portal: PortalCatalogEntry) {
  if (!confirm(`确认删除自定义门户「${portal.name}」？凭据配置将一并失效。`)) return
  try {
    await settingsStore.removePortal(portal.portal_id)
  } catch (e) {
    alert(`删除失败: ${(e as Error).message}`)
  }
}
</script>

<template>
  <div class="open-portal-panel">
    <section class="settings-section">
      <div class="panel-head">
        <div>
          <h3 class="section-title">开放数据门户（{{ portalCatalog.length }}）</h3>
          <p class="section-hint">
            覆盖 NASA / NOAA / ESA / ECMWF / USGS / JAXA 等国际组织与国内权威数据中心。
            需凭据门户的凭据加密保存在后端；下载走工作流「门户数据下载」节点（cred_profile 引用门户
            ID）。
          </p>
        </div>
        <button type="button" class="btn primary" @click="customOpen = !customOpen">
          {{ customOpen ? '收起' : '添加自定义门户' }}
        </button>
      </div>

      <div v-if="customOpen" class="form-card custom-form">
        <div class="form-grid">
          <label>
            <span>Portal ID <em class="req">*</em></span>
            <input v-model="customForm.portal_id" placeholder="my_lab_portal" />
          </label>
          <label>
            <span>名称 <em class="req">*</em></span>
            <input v-model="customForm.name" placeholder="实验室数据门户" />
          </label>
          <label>
            <span>所属组织</span>
            <input v-model="customForm.organization" />
          </label>
          <label>
            <span>区域</span>
            <AppSelect
              v-model="customForm.region"
              :options="[
                { label: '国际', value: 'international' },
                { label: '国内', value: 'china' },
              ]"
            />
          </label>
          <label class="span-2">
            <span>Base URL <em class="req">*</em></span>
            <input v-model="customForm.base_url" placeholder="https://data.example.org/" />
          </label>
          <label>
            <span>备用 URL（隧道）</span>
            <input v-model="customForm.alt_url" placeholder="https://mirror.example.org/" />
          </label>
          <label>
            <span>官网</span>
            <input v-model="customForm.website" />
          </label>
          <label>
            <span>认证方式</span>
            <AppSelect
              v-model="customForm.auth_type"
              :options="[
                { label: '无需认证', value: 'none' },
                { label: 'Bearer Token', value: 'bearer' },
                { label: 'Basic（用户名/密码）', value: 'basic' },
                { label: '自定义 Header', value: 'header' },
                { label: 'Token', value: 'token' },
              ]"
            />
          </label>
          <label>
            <span>Token Header</span>
            <input v-model="customForm.token_header" placeholder="token" />
          </label>
          <label class="checkbox">
            <input v-model="customForm.requires_credentials" type="checkbox" />
            <span>需要凭据</span>
          </label>
          <label>
            <span>凭据键（留空 = 门户 ID）</span>
            <input v-model="customForm.credential_profile" placeholder="与其他门户共用时填写" />
          </label>
          <label class="span-2">
            <span>凭据提示</span>
            <input v-model="customForm.credentials_hint" placeholder="在何处获取 token" />
          </label>
          <label class="span-2">
            <span>描述</span>
            <textarea v-model="customForm.description" rows="2" />
          </label>
        </div>
        <p v-if="customErr" class="form-error">{{ customErr }}</p>
        <div class="form-actions">
          <button type="button" class="btn primary" :disabled="customSaving" @click="saveCustom">
            {{ customSaving ? '保存中…' : '创建门户' }}
          </button>
          <button type="button" class="btn" @click="resetCustom">清空</button>
        </div>
      </div>
    </section>

    <section class="settings-section">
      <h3 class="section-title">国际组织（{{ intlPortals.length }}）</h3>
      <div class="portal-grid">
        <div v-for="p in intlPortals" :key="p.portal_id" class="portal-cell">
          <PortalCard
            :portal="p"
            @configure="openCredentials"
            @search="openSearch"
            @edit-url="openUrlEdit"
          />
          <button
            v-if="!p.builtin"
            type="button"
            class="btn danger cell-del"
            @click="removeCustom(p)"
          >
            删除该门户
          </button>
        </div>
      </div>
    </section>

    <section class="settings-section">
      <h3 class="section-title">国内机构（{{ chinaPortals.length }}）</h3>
      <div class="portal-grid">
        <div v-for="p in chinaPortals" :key="p.portal_id" class="portal-cell">
          <PortalCard
            :portal="p"
            @configure="openCredentials"
            @search="openSearch"
            @edit-url="openUrlEdit"
          />
          <button
            v-if="!p.builtin"
            type="button"
            class="btn danger cell-del"
            @click="removeCustom(p)"
          >
            删除该门户
          </button>
        </div>
      </div>
    </section>

    <PortalCredentialDialog
      :visible="credVisible"
      :portal="credPortal"
      @close="credVisible = false"
      @saved="onCredSaved"
    />
    <PortalSearchDialog
      :visible="searchVisible"
      :portal="searchPortalEntry"
      @close="searchVisible = false"
      @added="() => {}"
    />

    <!-- 地址覆盖/编辑 -->
    <Teleport to="body">
      <div v-if="urlEditOpen && urlEditPortal" class="ue-overlay" @click.self="urlEditOpen = false">
        <div class="ue-dialog" role="dialog" aria-modal="true">
          <div class="ue-header">
            <span class="ue-title">
              {{ urlEditPortal.builtin ? '覆盖地址' : '编辑地址' }} · {{ urlEditPortal.name }}
            </span>
            <button type="button" class="ue-close" aria-label="关闭" @click="urlEditOpen = false">
              ×
            </button>
          </div>
          <div class="ue-body">
            <p v-if="urlEditPortal.builtin" class="ue-hint">
              内置门户仅可覆盖访问地址（留空恢复内置值）；下载节点经 effective 地址访问。
            </p>
            <div class="form-grid">
              <label class="span-2">
                <span>Base URL{{ urlEditPortal.builtin ? '（覆盖，留空恢复内置）' : '' }}</span>
                <input v-model="urlForm.base_url" :placeholder="urlEditPortal.base_url" />
              </label>
              <label class="span-2">
                <span>备用 URL（隧道，可选）</span>
                <input v-model="urlForm.alt_url" placeholder="https://mirror.example.org/" />
              </label>
            </div>
            <p v-if="urlErr" class="form-error">{{ urlErr }}</p>
          </div>
          <div class="ue-footer">
            <button type="button" class="btn primary" :disabled="urlSaving" @click="saveUrlEdit">
              {{ urlSaving ? '保存中…' : '保存' }}
            </button>
            <button type="button" class="btn" @click="urlEditOpen = false">取消</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped src="../settings-form.css"></style>
<style scoped>
.open-portal-panel {
  display: flex;
  flex-direction: column;
  gap: 1.2rem;
}
.settings-section {
  display: flex;
  flex-direction: column;
  gap: 0.52rem;
}
.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.6rem;
}
.panel-head > div:first-child {
  flex: 1;
  min-width: 0;
}
.portal-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(17.5rem, 1fr));
  gap: 0.55rem;
}
.portal-cell {
  display: flex;
  flex-direction: column;
  gap: 0.32rem;
}
.cell-del {
  align-self: flex-end;
}
.custom-form {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.req {
  color: var(--danger);
  font-style: normal;
}
.ue-overlay {
  position: fixed;
  inset: 0;
  z-index: 1100;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-raised);
}
.ue-dialog {
  width: min(30rem, 92vw);
  border-radius: 0.6rem;
  border: 1px solid var(--border-default);
  background: var(--surface-2);
  box-shadow: 0 18px 48px rgba(1, 8, 16, 0.4);
  overflow: hidden;
}
.ue-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.55rem 0.72rem;
  border-bottom: 1px solid var(--border-subtle);
}
.ue-title {
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
}
.ue-close {
  width: 1.5rem;
  height: 1.5rem;
  border: none;
  border-radius: 0.4rem;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 1rem;
}
.ue-close:hover {
  background: var(--border-subtle);
}
.ue-body {
  padding: 0.6rem 0.72rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.ue-hint {
  margin: 0;
  color: var(--accent-warm);
  font-size: var(--font-size-caption);
}
.ue-footer {
  display: flex;
  gap: 0.4rem;
  padding: 0.5rem 0.72rem;
  border-top: 1px solid var(--border-subtle);
}
</style>
