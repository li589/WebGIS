<script setup lang="ts">
/**
 * RemoteDataSourcesPanel — 远程数据源页。
 *
 * 动态分组：存储源（remoteStorageProfiles）+ 开放门户（portalCatalog），
 * 数据实时来自「远程与存储」页的配置；能力（浏览/检索/仅下载）按协议与门户能力渲染。
 * 底部为已注册「可访问远程数据源」表（remote-source registry）。
 */

import { computed, reactive, ref, toRef } from 'vue'
import { useSettingsStore } from '../../../stores/settings'
import type { PortalCatalogEntry, RemoteStorageProfile } from '../../../types/api-reexports'
import { PROTOCOL_META } from '../remote-storage/protocols'
import ProfileBrowserDialog from '../remote-storage/ProfileBrowserDialog.vue'
import PortalSearchDialog from '../portals/PortalSearchDialog.vue'
import RemoteSourceCard, { type RemoteSourceCardData } from './RemoteSourceCard.vue'
import RegisteredRemoteSources from './RegisteredRemoteSources.vue'

const settingsStore = useSettingsStore()
const remoteStorageProfiles = toRef(settingsStore, 'remoteStorageProfiles')
const portalCatalog = toRef(settingsStore, 'portalCatalog')

// ── 分组数据 ───────────────────────────────────────────────────────────────

const storageSources = computed<RemoteSourceCardData[]>(() =>
  [...remoteStorageProfiles.value]
    .sort((a, b) => a.profile_id.localeCompare(b.profile_id))
    .map((p) => {
      const meta = PROTOCOL_META[p.protocol as keyof typeof PROTOCOL_META]
      const target = meta?.usesUrl ? p.host : `${p.host || ''}${p.port ? `:${p.port}` : ''}`
      return {
        kind: 'storage_profile' as const,
        refId: p.profile_id,
        name: p.display_name || p.profile_id,
        subtitle: `${p.protocol} · ${target}${p.alt_host || p.alt_url ? ' · 双路径' : ''}`,
        protocol: p.protocol,
        enabled: p.enabled !== false,
        statusBadge:
          p.last_test_status === 'ok'
            ? { text: '已验证', tone: 'ok' as const }
            : p.last_test_status === 'failed'
              ? { text: '测试失败', tone: 'fail' as const }
              : null,
        browsable: Boolean(meta?.browsable),
        searchable: Boolean(meta?.searchable),
        requiresCredentials: true,
        hasCredentials: Boolean(p.has_secret || p.has_private_key),
      }
    }),
)

const portalSources = computed<RemoteSourceCardData[]>(() =>
  [...portalCatalog.value]
    .sort((a, b) => a.portal_id.localeCompare(b.portal_id))
    .map((p) => ({
      kind: 'portal' as const,
      refId: p.portal_id,
      name: p.name,
      subtitle: `${p.organization || '自定义门户'} · ${p.effective_base_url || p.base_url}`,
      protocol: 'http',
      enabled: true,
      statusBadge: null,
      browsable: false,
      searchable: p.search_capability !== 'none',
      searchLabel: '在线检索',
      requiresCredentials: p.requires_credentials,
      hasCredentials: p.has_credentials,
    })),
)

const chinaPortalIds = computed(
  () => new Set(portalCatalog.value.filter((p) => p.region === 'china').map((p) => p.portal_id)),
)

const chinaPortalSources = computed(() => {
  const all = portalSources.value
  return {
    intl: all.filter((s) => !chinaPortalIds.value.has(s.refId)),
    china: all.filter((s) => chinaPortalIds.value.has(s.refId)),
  }
})

const emptyAll = computed(
  () => storageSources.value.length === 0 && portalSources.value.length === 0,
)

// ── 浏览 / 检索对话框 ─────────────────────────────────────────────────────

const browseProfile = ref<RemoteStorageProfile | null>(null)

const searchPortal = ref<PortalCatalogEntry | null>(null)

function onBrowse(s: RemoteSourceCardData) {
  const p = remoteStorageProfiles.value.find((x) => x.profile_id === s.refId)
  if (p) browseProfile.value = p
}

function onSearch(s: RemoteSourceCardData) {
  if (s.kind === 'portal') {
    const p = portalCatalog.value.find((x) => x.portal_id === s.refId)
    if (p) searchPortal.value = p
    return
  }
  onBrowse(s)
}

async function onSourceAdded() {
  await settingsStore.loadRemoteSources()
}

// ── 整源注册（别名） ──────────────────────────────────────────────────────

const addDialog = reactive({
  visible: false,
  kind: 'storage_profile' as 'storage_profile' | 'portal',
  refId: '',
  name: '',
  alias: '',
  remotePath: '',
})
const addBusy = ref(false)
const addErr = ref('')

function openAdd(s: RemoteSourceCardData) {
  addDialog.kind = s.kind
  addDialog.refId = s.refId
  addDialog.name = s.name
  addDialog.alias = s.refId
  addDialog.remotePath = ''
  addErr.value = ''
  addDialog.visible = true
}

async function confirmAdd() {
  const alias = addDialog.alias.trim()
  if (!alias) {
    addErr.value = '请填写别名 ID（唯一，供下载节点引用）'
    return
  }
  addBusy.value = true
  addErr.value = ''
  try {
    await settingsStore.saveRemoteSource(alias, {
      kind: addDialog.kind,
      ref_id: addDialog.refId,
      remote_path: addDialog.remotePath.trim(),
      display_name: addDialog.name,
      cache_policy: 'standard',
      access_mode: 'legacy',
      archived: false,
    })
    addDialog.visible = false
  } catch (e) {
    addErr.value = (e as Error).message
  } finally {
    addBusy.value = false
  }
}
</script>

<template>
  <div class="remote-panel">
    <p v-if="emptyAll" class="empty-guide">
      尚未配置任何远程源。请先到「设置 → 远程与存储」添加存储源或开放门户，本页将按其动态分组展示。
    </p>

    <template v-if="storageSources.length">
      <h4 class="group-title">远程存储源（{{ storageSources.length }}）</h4>
      <div class="card-grid">
        <RemoteSourceCard
          v-for="s in storageSources"
          :key="s.refId"
          :source="s"
          @browse="onBrowse"
          @search="onSearch"
          @add="openAdd"
        />
      </div>
    </template>

    <template v-if="chinaPortalSources.intl.length">
      <h4 class="group-title">国际组织门户（{{ chinaPortalSources.intl.length }}）</h4>
      <div class="card-grid">
        <RemoteSourceCard
          v-for="s in chinaPortalSources.intl"
          :key="s.refId"
          :source="s"
          @search="onSearch"
          @add="openAdd"
        />
      </div>
    </template>

    <template v-if="chinaPortalSources.china.length">
      <h4 class="group-title">国内机构门户（{{ chinaPortalSources.china.length }}）</h4>
      <div class="card-grid">
        <RemoteSourceCard
          v-for="s in chinaPortalSources.china"
          :key="s.refId"
          :source="s"
          @search="onSearch"
          @add="openAdd"
        />
      </div>
    </template>

    <RegisteredRemoteSources />

    <ProfileBrowserDialog
      :visible="Boolean(browseProfile)"
      :profile="browseProfile"
      @close="browseProfile = null"
      @added="onSourceAdded"
    />
    <PortalSearchDialog
      :visible="Boolean(searchPortal)"
      :portal="searchPortal"
      @close="searchPortal = null"
      @added="onSourceAdded"
    />

    <div v-if="addDialog.visible" class="dialog-mask" @click.self="addDialog.visible = false">
      <div class="dialog">
        <header class="dialog-head">
          <strong>注册「{{ addDialog.name }}」为可访问数据源</strong>
          <button type="button" class="btn" @click="addDialog.visible = false">关闭</button>
        </header>
        <div class="form-grid">
          <label>
            <span>别名 ID（唯一）<em class="req">*</em></span>
            <input v-model="addDialog.alias" placeholder="例如 nas-fy-2025" />
          </label>
          <label>
            <span>远端路径（可选）</span>
            <input
              v-model="addDialog.remotePath"
              placeholder="留空 = 整源；门户可填 preset 相对路径模板"
            />
          </label>
        </div>
        <p v-if="addErr" class="form-error">{{ addErr }}</p>
        <div class="form-actions">
          <button type="button" class="btn btn-primary" :disabled="addBusy" @click="confirmAdd">
            {{ addBusy ? '保存中…' : '注册' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped src="../settings-form.css"></style>
<style scoped>
.remote-panel {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.group-title {
  margin: 0.2rem 0 0;
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
}
.card-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.45rem;
}
.empty-guide {
  margin: 0;
  padding: 0.8rem 0.6rem;
  border: 1px dashed var(--border-default);
  border-radius: 0.5rem;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  line-height: 1.5;
}
.dialog-mask {
  position: fixed;
  inset: 0;
  background: rgb(0 0 0 / 0.42);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 60;
}
.dialog {
  width: min(30rem, 92vw);
  background: var(--surface-1);
  border: 1px solid var(--border-strong);
  border-radius: 0.6rem;
  padding: 0.8rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.dialog-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--text-strong);
  font-size: var(--font-size-body);
}
.req {
  color: var(--danger);
  font-style: normal;
}
</style>
