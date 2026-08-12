<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef, watch, type Component } from 'vue'
import {
  Settings,
  User,
  X,
  LayoutGrid,
  Key,
  Globe,
  CloudSun,
  CloudLightning,
  Server,
  Database,
  Info,
  Palette,
} from '../ui/icons'

import { useAuthStore } from '../../stores/auth'
import { useSettingsStore } from '../../stores/settings'
import { useUiLoadingStore } from '../../stores/ui-loading'
import { loadSettingsUiLocal, saveSettingsUiLocal } from '../../services/settings-local'
import GeneralSettings from './GeneralSettings.vue'
import AppearanceSettings from './AppearanceSettings.vue'
import ApiKeySettings from './ApiKeySettings.vue'
import GeeAccountSettings from './GeeAccountSettings.vue'
import WeatherProviderSettings from './WeatherProviderSettings.vue'
import OpenMeteoSyncSettings from './OpenMeteoSyncSettings.vue'
import DataSourceSettings from './DataSourceSettings.vue'
import RemoteStorageSettings from './RemoteStorageSettings.vue'
import AboutSettings from './AboutSettings.vue'
import UserAccountSettings from './UserAccountSettings.vue'
import { SETTINGS_COPY } from '../../ui-copy'

const emit = defineEmits<{
  close: []
}>()

const settingsStore = useSettingsStore()
const authStore = useAuthStore()

type SettingsTab =
  | 'general'
  | 'appearance'
  | 'accounts'
  | 'api-keys'
  | 'gee-accounts'
  | 'weather-providers'
  | 'open-meteo-sync'
  | 'remote-storage'
  | 'data-source'
  | 'about'

const TAB_IDS: SettingsTab[] = [
  'general',
  'appearance',
  'accounts',
  'api-keys',
  'gee-accounts',
  'weather-providers',
  'open-meteo-sync',
  'remote-storage',
  'data-source',
  'about',
]

const savedTabRaw = loadSettingsUiLocal().activeTab
/** Legacy `system-status` tab merged into about. */
const savedTab = (savedTabRaw === 'system-status' ? 'about' : savedTabRaw) as
  SettingsTab | undefined
const defaultTab = (): SettingsTab =>
  authStore.authRequired && authStore.isAuthenticated ? 'accounts' : 'general'
const activeTab = ref<SettingsTab>(savedTab && TAB_IDS.includes(savedTab) ? savedTab : defaultTab())

const tabComponents = shallowRef<Record<SettingsTab, Component>>({
  general: GeneralSettings,
  appearance: AppearanceSettings,
  accounts: UserAccountSettings,
  'api-keys': ApiKeySettings,
  'gee-accounts': GeeAccountSettings,
  'weather-providers': WeatherProviderSettings,
  'open-meteo-sync': OpenMeteoSyncSettings,
  'remote-storage': RemoteStorageSettings,
  'data-source': DataSourceSettings,
  about: AboutSettings,
})

const ALL_TABS: Array<{ id: SettingsTab; label: string; icon: Component }> = [
  { id: 'general', label: SETTINGS_COPY.tabGeneral, icon: LayoutGrid },
  { id: 'appearance', label: SETTINGS_COPY.tabAppearance, icon: Palette },
  { id: 'accounts', label: '账户', icon: User },
  { id: 'api-keys', label: SETTINGS_COPY.tabApiKeys, icon: Key },
  { id: 'gee-accounts', label: SETTINGS_COPY.tabGee, icon: Globe },
  { id: 'weather-providers', label: SETTINGS_COPY.tabWeather, icon: CloudSun },
  { id: 'open-meteo-sync', label: SETTINGS_COPY.tabOpenMeteo, icon: CloudLightning },
  { id: 'remote-storage', label: '远程存储', icon: Server },
  { id: 'data-source', label: SETTINGS_COPY.tabDataSource, icon: Database },
  { id: 'about', label: '系统与关于', icon: Info },
]

/** VITE_SETTINGS_TABS=comma ids 白名单；未配置则全开（兼容现网） */
function resolveVisibleSettingsTabs(): Array<{ id: SettingsTab; label: string; icon: Component }> {
  const raw = String((import.meta.env as Record<string, unknown>).VITE_SETTINGS_TABS ?? '').trim()
  if (!raw) return ALL_TABS
  const allowed = new Set(
    raw
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean),
  )
  const filtered = ALL_TABS.filter((t) => allowed.has(t.id))
  return filtered.length ? filtered : ALL_TABS
}

const tabs = computed(() => {
  const visible = resolveVisibleSettingsTabs()
  if (!authStore.authRequired) {
    return visible.filter((t) => t.id !== 'accounts')
  }
  return visible
})

const ROLE_LABEL: Record<string, string> = {
  admin: '管理员',
  operator: '操作员',
  viewer: '只读',
}

const sessionLabel = computed(() => {
  if (!authStore.authRequired || !authStore.user) return null
  const role = ROLE_LABEL[authStore.user.role] ?? authStore.user.role
  return `${authStore.user.username} · ${role}`
})

function openAccountsTab() {
  activeTab.value = 'accounts'
}
if (!tabs.value.some((t) => t.id === activeTab.value)) {
  activeTab.value = tabs.value[0]?.id ?? defaultTab()
}

onMounted(async () => {
  window.addEventListener('resize', onWindowResize)
  const loading = useUiLoadingStore()
  // 面板异步 chunk 已挂上：立刻关掉全屏 hero。
  // 配置拉取用面板内 spinner；否则 9 路 /config 全完（甚至重试）才关全屏，看起来像「设置已出来但还在转」。
  loading.hideImmediate()
  try {
    await settingsStore.loadAll({ quiet: Boolean(settingsStore.generalConfig) })
  } catch {
    /* loadAll 自行写入 error / partialError */
  }
})

watch(activeTab, (tab) => {
  // merge 写入：勿整表替换，否则会丢掉 mapDistributionChrome 等偏好
  saveSettingsUiLocal({ ...loadSettingsUiLocal(), activeTab: tab })
  if (tab === 'api-keys' && settingsStore.apiKeys.length === 0) {
    void settingsStore.loadApiKeys()
  } else if (tab === 'gee-accounts' && settingsStore.geeAccounts.length === 0) {
    void settingsStore.loadGeeAccounts()
  } else if (tab === 'weather-providers' && settingsStore.weatherProviders.length === 0) {
    void settingsStore.loadWeatherProviders()
  } else if (tab === 'remote-storage' && settingsStore.remoteStorageProfiles.length === 0) {
    void settingsStore.loadRemoteStorageProfiles()
  }
})

/** 设置侧栏：左缘拖动加宽（面板贴右，向左拖 = 变宽） */
const PANEL_WIDTH_DEFAULT_PX = Math.round(38 * 16)
const PANEL_WIDTH_MIN_PX = Math.round(32 * 16)
const PANEL_WIDTH_MAX_CAP_PX = Math.round(56 * 16)

function clampPanelWidth(px: number): number {
  const maxByViewport = Math.floor(window.innerWidth * 0.92)
  const max = Math.min(PANEL_WIDTH_MAX_CAP_PX, Math.max(PANEL_WIDTH_MIN_PX, maxByViewport))
  return Math.min(max, Math.max(PANEL_WIDTH_MIN_PX, Math.round(px)))
}

const savedWidth = loadSettingsUiLocal().panelWidthPx
const panelWidthPx = ref(
  clampPanelWidth(
    typeof savedWidth === 'number' && Number.isFinite(savedWidth)
      ? savedWidth
      : PANEL_WIDTH_DEFAULT_PX,
  ),
)
const panelStyle = computed(() => ({ width: `${panelWidthPx.value}px` }))

let resizeStartX = 0
let resizeStartWidth = 0
const isResizing = ref(false)

function onResizePointerMove(event: PointerEvent) {
  if (!isResizing.value) return
  // 向左拖 → clientX 变小 → 宽度增加
  const next = resizeStartWidth + (resizeStartX - event.clientX)
  panelWidthPx.value = clampPanelWidth(next)
}

function stopResize() {
  if (!isResizing.value) return
  isResizing.value = false
  window.removeEventListener('pointermove', onResizePointerMove)
  window.removeEventListener('pointerup', stopResize)
  window.removeEventListener('pointercancel', stopResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  saveSettingsUiLocal({ ...loadSettingsUiLocal(), panelWidthPx: panelWidthPx.value })
}

function onResizePointerDown(event: PointerEvent) {
  if (event.button !== 0) return
  event.preventDefault()
  isResizing.value = true
  resizeStartX = event.clientX
  resizeStartWidth = panelWidthPx.value
  document.body.style.cursor = 'ew-resize'
  document.body.style.userSelect = 'none'
  window.addEventListener('pointermove', onResizePointerMove)
  window.addEventListener('pointerup', stopResize)
  window.addEventListener('pointercancel', stopResize)
}

function onWindowResize() {
  panelWidthPx.value = clampPanelWidth(panelWidthPx.value)
}

onUnmounted(() => {
  stopResize()
  window.removeEventListener('resize', onWindowResize)
})
</script>

<template>
  <div class="settings-overlay" @click.self="emit('close')">
    <div class="settings-panel" :class="{ 'settings-panel--resizing': isResizing }" :style="panelStyle">
      <div
        class="settings-resize-handle"
        title="向左拖动加宽"
        role="separator"
        aria-orientation="vertical"
        aria-label="调整设置面板宽度"
        @pointerdown="onResizePointerDown"
      />
      <div class="settings-header">
        <Settings :size="18" class="header-icon" aria-hidden="true" />
        <span class="header-title">{{ SETTINGS_COPY.panelTitle }}</span>
        <button
          v-if="sessionLabel"
          type="button"
          class="session-chip"
          title="账户与登录"
          @click="openAccountsTab"
        >
          <User :size="14" class="session-avatar" aria-hidden="true" />
          <span class="session-text">{{ sessionLabel }}</span>
        </button>
        <button class="close-btn" title="关闭" @click="emit('close')">
          <X :size="14" aria-hidden="true" />
        </button>
      </div>

      <div class="settings-body">
        <nav class="settings-nav">
          <button
            v-for="tab in tabs"
            :key="tab.id"
            class="nav-item"
            :class="{ active: activeTab === tab.id }"
            @click="activeTab = tab.id"
          >
            <span class="nav-icon" aria-hidden="true"><component :is="tab.icon" :size="16" /></span>
            <span class="nav-label">{{ tab.label }}</span>
          </button>
        </nav>

        <div class="settings-content">
          <div v-if="settingsStore.loading" class="content-loading">
            <span class="loading-spinner"></span>
            <span>加载配置中...</span>
          </div>
          <div
            v-else-if="settingsStore.error && !settingsStore.generalConfig"
            class="content-error"
          >
            <span>{{ settingsStore.error }}</span>
            <button type="button" class="retry-btn" @click="settingsStore.loadAll()">重试</button>
          </div>
          <template v-else>
            <div v-if="settingsStore.partialError" class="content-partial-error">
              <span>{{ settingsStore.partialError }}</span>
              <button type="button" class="retry-btn" @click="settingsStore.loadAll()">
                重试失败项
              </button>
            </div>
            <component :is="tabComponents[activeTab]" @close="emit('close')" />
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-overlay {
  position: fixed;
  inset: 0;
  z-index: 998;
  display: flex;
  justify-content: flex-end;
  background: var(--surface-raised);
}

.settings-panel {
  position: relative;
  width: 38rem;
  max-width: 92vw;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--surface-2);
  border-left: 1px solid var(--border-default);
  box-shadow: -12px 0 36px rgba(1, 8, 16, 0.32);
}

.settings-panel--resizing {
  transition: none;
}

.settings-resize-handle {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 0.4rem;
  transform: translateX(-50%);
  cursor: ew-resize;
  z-index: 2;
  touch-action: none;
}

.settings-resize-handle::after {
  content: '';
  position: absolute;
  left: 50%;
  top: 50%;
  width: 0.18rem;
  height: 2.4rem;
  transform: translate(-50%, -50%);
  border-radius: 999px;
  background: var(--border-default);
  opacity: 0;
  transition: opacity 0.15s ease;
}

.settings-panel:hover .settings-resize-handle::after,
.settings-panel--resizing .settings-resize-handle::after {
  opacity: 0.9;
  background: var(--accent);
}

.settings-header {
  display: flex;
  align-items: center;
  gap: 0.38rem;
  padding: 0.72rem 0.82rem;
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
  flex: none;
}

.header-icon {
  font-size: 0.82rem;
  color: var(--accent);
}

.header-title {
  flex: 1;
  min-width: 0;
}

.session-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  max-width: 9rem;
  padding: 0.22rem 0.45rem;
  border: 1px solid var(--success-border);
  border-radius: 999px;
  background: var(--success-surface);
  color: var(--success);
  cursor: pointer;
  font: inherit;
  font-size: var(--font-size-caption);
}

.session-chip:hover {
  border-color: var(--success-border);
  background: var(--success-surface);
}

.session-avatar {
  font-size: var(--font-size-caption);
  line-height: 1;
}

.session-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.close-btn {
  width: 1.4rem;
  height: 1.4rem;
  border: none;
  border-radius: 0.5rem;
  background: transparent;
  color: var(--text-faint);
  cursor: pointer;
  font-size: var(--font-size-caption);
}

.close-btn:hover {
  background: var(--border-subtle);
  color: var(--text-primary);
}

.settings-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.settings-nav {
  width: 8.5rem;
  flex: none;
  display: flex;
  flex-direction: column;
  gap: 0.12rem;
  padding: 0.52rem 0.32rem;
  border-right: 1px solid var(--border-subtle);
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 0.36rem;
  padding: 0.42rem 0.52rem;
  border: 1px solid transparent;
  border-radius: 0.5rem;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font: inherit;
  font-size: var(--font-size-caption);
  text-align: left;
  transition: all 0.16s ease;
}

.nav-item:hover {
  background: var(--border-subtle);
  color: var(--text-primary);
}

.nav-item.active {
  border-color: var(--accent-border);
  background: var(--accent-surface);
  color: var(--accent);
  font-weight: 600;
}

.nav-icon {
  font-size: var(--font-size-caption);
  opacity: 0.8;
  flex: none;
}

.nav-item.active .nav-icon {
  opacity: 1;
}

.nav-label {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.settings-content {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  padding: 0.62rem 0.82rem;
}

.content-loading,
.content-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.62rem;
  padding: 3rem 1rem;
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
}

.content-partial-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
  margin-bottom: 0.55rem;
  padding: 0.42rem 0.55rem;
  border: 1px solid var(--warning-border);
  border-radius: 0.45rem;
  background: rgba(90, 60, 20, 0.28);
  color: var(--accent-warm);
  font-size: var(--font-size-caption);
  line-height: 1.4;
}

.loading-spinner {
  width: 1.6rem;
  height: 1.6rem;
  border: 2px solid var(--accent-border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.retry-btn {
  padding: 0.26rem 0.72rem;
  border: 1px solid var(--accent-border);
  border-radius: 0.4rem;
  background: var(--accent-surface);
  color: var(--accent);
  cursor: pointer;
  font: inherit;
  font-size: var(--font-size-caption);
}

.retry-btn:hover {
  background: var(--accent-border);
}

@media (max-width: 640px) {
  .settings-panel {
    width: 100vw !important;
    max-width: 100vw;
  }

  .settings-resize-handle {
    display: none;
  }

  .settings-body {
    flex-direction: column;
  }

  .settings-nav {
    width: 100%;
    flex-direction: row;
    border-right: none;
    border-bottom: 1px solid var(--border-subtle);
    overflow-x: auto;
    overflow-y: hidden;
    padding: 0.32rem;
    scrollbar-gutter: auto;
  }

  .nav-item {
    flex: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .loading-spinner {
    animation: none;
  }
}
</style>

<style>
@import './settings-scrollbar.css';
</style>
