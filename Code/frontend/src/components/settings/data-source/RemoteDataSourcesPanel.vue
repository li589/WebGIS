<script setup lang="ts">
/**
 * RemoteDataSourcesPanel — 远程数据源页（2026-08-25 融合对话框改版）。
 *
 * 动态分组：存储源（remoteStorageProfiles）+ 开放门户（portalCatalog）。
 * 单一入口「添加为可访问远程数据源」打开融合对话框
 * （RemoteSourceAddDialog：检索多选/目录浏览/仅注册三形态）——
 * 卡片上不再有独立的「浏览」「在线检索」按钮。
 * 底部为已注册「可访问远程数据源」表（remote-source registry）。
 */

import { computed, reactive, ref, toRef } from 'vue'
import { useSettingsStore } from '../../../stores/settings'
import type { PortalCatalogEntry, RemoteStorageProfile } from '../../../types/api-reexports'
import { PROTOCOL_META } from '../remote-storage/protocols'
import RemoteSourceCard, { type RemoteSourceCardData } from './RemoteSourceCard.vue'
import RemoteSourceAddDialog from './RemoteSourceAddDialog.vue'
import RegisteredRemoteSources from './RegisteredRemoteSources.vue'

const settingsStore = useSettingsStore()
const remoteStorageProfiles = toRef(settingsStore, 'remoteStorageProfiles')
const portalCatalog = toRef(settingsStore, 'portalCatalog')
const onlineTileSources = toRef(settingsStore, 'onlineTileSources')
const tileForm = reactive({
  sourceId: '',
  displayName: '',
  serviceType: 'xyz' as 'wmts' | 'xyz',
  urlTemplate: '',
  layer: '',
  style: 'default',
  tileMatrixSet: '',
  imageFormat: 'image/png',
  coordinateSystem: 'EPSG:3857',
})

async function removeOnlineTileSource(sourceId: string) {
  if (!window.confirm(`确定删除在线瓦片源「${sourceId}」？`)) return
  await settingsStore.removeOnlineTileSource(sourceId)
}

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

// ── 融合「添加数据源」对话框（2026-08-25 改版）─────────────────────────

const addDialog = ref<{
  visible: boolean
  source: RemoteSourceCardData | null
}>({
  visible: false,
  source: null,
})

function openAdd(s: RemoteSourceCardData) {
  addDialog.value = { visible: true, source: s }
}

/** 融合对话框所需的 portal/profile 对象 */
const addDialogPortal = computed<PortalCatalogEntry | null>(() => {
  const s = addDialog.value.source
  if (!s || s.kind !== 'portal') return null
  return portalCatalog.value.find((x) => x.portal_id === s.refId) ?? null
})

const addDialogProfile = computed<RemoteStorageProfile | null>(() => {
  const s = addDialog.value.source
  if (!s || s.kind !== 'storage_profile') return null
  return remoteStorageProfiles.value.find((x) => x.profile_id === s.refId) ?? null
})

async function onRegistered() {
  await settingsStore.loadRemoteSources()
}

async function onRegisteredAndAdded() {
  // P2：注册并添加到图层——刷新注册表；工作流状态面板将显示下载/处理进度
  await settingsStore.loadRemoteSources()
}

async function saveTileSource() {
  const sourceId = tileForm.sourceId.trim()
  if (!sourceId || !tileForm.displayName.trim() || !tileForm.urlTemplate.trim()) return
  await settingsStore.saveOnlineTileSource(sourceId, {
    display_name: tileForm.displayName.trim(),
    service_type: tileForm.serviceType,
    url_template: tileForm.urlTemplate.trim(),
    layer: tileForm.layer.trim(),
    style: tileForm.style.trim() || 'default',
    tile_matrix_set: tileForm.tileMatrixSet.trim(),
    image_format: tileForm.imageFormat.trim() || 'image/png',
    coordinate_system: tileForm.coordinateSystem.trim() || 'EPSG:3857',
    auth_ref: null,
    enabled: true,
  })
  tileForm.sourceId = ''
  tileForm.displayName = ''
  tileForm.urlTemplate = ''
  tileForm.layer = ''
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
        <RemoteSourceCard v-for="s in storageSources" :key="s.refId" :source="s" @add="openAdd" />
      </div>
    </template>

    <template v-if="chinaPortalSources.intl.length">
      <h4 class="group-title">国际组织门户（{{ chinaPortalSources.intl.length }}）</h4>
      <div class="card-grid">
        <RemoteSourceCard
          v-for="s in chinaPortalSources.intl"
          :key="s.refId"
          :source="s"
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
          @add="openAdd"
        />
      </div>
    </template>

    <section class="tile-source-section">
      <div class="tile-section-head">
        <div>
          <h4 class="group-title">添加在线 WMTS / XYZ 瓦片源</h4>
          <p class="section-hint">登记后可作为统一地图瓦片源使用，支持公开 HTTPS 模板。</p>
        </div>
        <span class="section-kicker">在线图层</span>
      </div>
      <div class="tile-form">
        <label class="tile-field">
          <span>源 ID</span>
          <input v-model="tileForm.sourceId" placeholder="如 nasa-xyz" />
        </label>
        <label class="tile-field">
          <span>显示名称</span>
          <input v-model="tileForm.displayName" placeholder="地图瓦片源名称" />
        </label>
        <label class="tile-field">
          <span>服务类型</span>
          <select v-model="tileForm.serviceType">
            <option value="xyz">XYZ</option>
            <option value="wmts">WMTS</option>
          </select>
        </label>
        <label class="tile-field tile-field--wide">
          <span>瓦片地址模板</span>
          <input v-model="tileForm.urlTemplate" placeholder="https://example.org/{z}/{x}/{y}.png" />
        </label>
        <label v-if="tileForm.serviceType === 'wmts'" class="tile-field">
          <span>WMTS 图层</span>
          <input v-model="tileForm.layer" placeholder="图层标识" />
        </label>
        <button type="button" class="primary-btn tile-submit" @click="saveTileSource">
          保存瓦片源
        </button>
      </div>
    </section>

    <RegisteredRemoteSources />

    <section v-if="onlineTileSources.length" class="tile-source-section">
      <h4 class="group-title">在线 WMTS / XYZ 瓦片源（{{ onlineTileSources.length }}）</h4>
      <div class="registered-list">
        <div v-for="source in onlineTileSources" :key="source.source_id" class="registered-row">
          <div>
            <strong>{{ source.display_name }}</strong>
            <span class="muted"
              >{{ source.service_type.toUpperCase() }} · {{ source.coordinate_system }} ·
              {{ source.config_status === 'configured' ? '已配置' : '配置无效' }}</span
            >
            <code>{{ source.url_template }}</code>
          </div>
          <button
            type="button"
            class="danger-btn"
            @click="removeOnlineTileSource(source.source_id)"
          >
            删除
          </button>
        </div>
      </div>
    </section>

    <!-- 融合式「添加数据源」对话框（检索多选/目录浏览/仅注册三形态） -->
    <RemoteSourceAddDialog
      :visible="addDialog.visible"
      :kind="addDialog.source?.kind === 'portal' ? 'portal' : 'storage'"
      :ref-id="addDialog.source?.refId ?? ''"
      :name="addDialog.source?.name ?? ''"
      :searchable="addDialog.source?.searchable ?? false"
      :browsable="addDialog.source?.browsable ?? false"
      :protocol="addDialog.source?.protocol ?? null"
      :portal="addDialogPortal"
      :profile="addDialogProfile"
      @close="addDialog.visible = false"
      @registered="onRegistered"
      @registered-and-added="onRegisteredAndAdded"
    />
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
.tile-source-section {
  margin-top: 0.65rem;
  padding: 0.85rem;
  border: 1px solid var(--border-subtle);
  border-radius: 0.62rem;
  background:
    linear-gradient(
      135deg,
      color-mix(in srgb, var(--accent-surface) 72%, transparent),
      transparent 58%
    ),
    var(--surface-2);
}
.tile-section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.7rem;
}
.section-kicker {
  flex: none;
  padding: 0.2rem 0.45rem;
  border: 1px solid var(--accent-border);
  border-radius: 999px;
  color: var(--accent-strong);
  background: var(--accent-surface);
  font-size: 0.68rem;
  font-weight: 600;
  letter-spacing: 0.04em;
}
.tile-form {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.55rem;
  align-items: end;
}
.tile-field {
  display: grid;
  gap: 0.25rem;
  min-width: 0;
}
.tile-field span {
  color: var(--text-secondary);
  font-size: var(--font-size-caption);
  font-weight: 600;
}
.tile-field--wide {
  grid-column: 1 / -1;
}
.tile-form input,
.tile-form select {
  min-width: 0;
  min-height: 2.15rem;
  border: 1px solid var(--border-default);
  border-radius: 0.38rem;
  padding: 0.42rem 0.55rem;
  background: var(--surface-sunken);
  color: var(--text-primary);
  font: inherit;
  font-size: var(--font-size-caption);
  transition:
    border-color 0.16s ease,
    box-shadow 0.16s ease;
}
.tile-form input:focus,
.tile-form select:focus {
  outline: none;
  border-color: var(--accent-border);
  box-shadow: 0 0 0 3px var(--accent-surface);
}
.primary-btn {
  min-height: 2.15rem;
  border: 1px solid var(--accent-border);
  color: var(--accent-strong);
  background: var(--accent-surface);
  border-radius: 0.38rem;
  padding: 0.42rem 0.75rem;
  font: inherit;
  font-size: var(--font-size-caption);
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition:
    background 0.16s ease,
    border-color 0.16s ease,
    transform 0.16s ease;
}
.primary-btn:hover {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent-surface) 72%, var(--accent) 28%);
  transform: translateY(-1px);
}
.primary-btn:active {
  transform: translateY(0);
}
.registered-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.6rem 0.7rem;
  border: 1px solid var(--border-subtle);
  border-radius: 0.4rem;
  background: var(--surface-sunken);
}
.registered-row > div {
  display: grid;
  gap: 0.15rem;
  min-width: 0;
}
.registered-row code {
  max-width: 48rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-muted);
}
.muted {
  color: var(--text-muted);
  font-size: var(--font-size-caption);
}

.danger-btn {
  flex: none;
  border: 1px solid var(--danger-border, var(--border-subtle));
  color: var(--danger, #e85d5d);
  background: transparent;
  border-radius: 0.3rem;
  padding: 0.25rem 0.5rem;
  cursor: pointer;
}
@media (max-width: 44rem) {
  .tile-form {
    grid-template-columns: 1fr;
  }
  .tile-field--wide {
    grid-column: auto;
  }
  .tile-submit {
    width: 100%;
  }
}
</style>
