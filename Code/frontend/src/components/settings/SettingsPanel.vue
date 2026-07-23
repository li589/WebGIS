<script setup lang="ts">
import { onMounted, ref, shallowRef, watch } from 'vue'

import { useSettingsStore } from '../../stores/settings'
import { useUiLoadingStore } from '../../stores/ui-loading'
import { loadSettingsUiLocal, saveSettingsUiLocal } from '../../services/settings-local'
import GeneralSettings from './GeneralSettings.vue'
import ApiKeySettings from './ApiKeySettings.vue'
import GeeAccountSettings from './GeeAccountSettings.vue'
import WeatherProviderSettings from './WeatherProviderSettings.vue'
import OpenMeteoSyncSettings from './OpenMeteoSyncSettings.vue'
import DataSourceSettings from './DataSourceSettings.vue'
import RemoteStorageSettings from './RemoteStorageSettings.vue'
import AboutSettings from './AboutSettings.vue'

const emit = defineEmits<{
  close: []
}>()

const settingsStore = useSettingsStore()

type SettingsTab =
  | 'general'
  | 'api-keys'
  | 'gee-accounts'
  | 'weather-providers'
  | 'open-meteo-sync'
  | 'remote-storage'
  | 'data-source'
  | 'about'

const savedTab = loadSettingsUiLocal().activeTab as SettingsTab | undefined
const activeTab = ref<SettingsTab>(
  savedTab &&
    [
      'general',
      'api-keys',
      'gee-accounts',
      'weather-providers',
      'open-meteo-sync',
      'remote-storage',
      'data-source',
      'about',
    ].includes(savedTab)
    ? savedTab
    : 'api-keys',
)

const tabComponents = shallowRef<Record<SettingsTab, typeof GeneralSettings>>({
  general: GeneralSettings,
  'api-keys': ApiKeySettings,
  'gee-accounts': GeeAccountSettings,
  'weather-providers': WeatherProviderSettings,
  'open-meteo-sync': OpenMeteoSyncSettings,
  'remote-storage': RemoteStorageSettings,
  'data-source': DataSourceSettings,
  about: AboutSettings,
})

const tabs: Array<{ id: SettingsTab; label: string; icon: string }> = [
  { id: 'general', label: '常规设置', icon: '▣' },
  { id: 'api-keys', label: 'API管理', icon: '🔑' },
  { id: 'gee-accounts', label: 'GEE账户', icon: '🌍' },
  { id: 'weather-providers', label: '天气源', icon: '🌦' },
  { id: 'open-meteo-sync', label: 'Open-Meteo', icon: '🌩' },
  { id: 'remote-storage', label: '远程存储', icon: '🖧' },
  { id: 'data-source', label: '数据源', icon: '⚱' },
  { id: 'about', label: '关于', icon: 'ⓘ' },
]

onMounted(async () => {
  const loading = useUiLoadingStore()
  try {
    await settingsStore.loadAll()
  } finally {
    // 对应 DashboardView 中 settingsOpen watch 的 showImmediate
    loading.hideImmediate()
  }
})

watch(activeTab, (tab) => {
  saveSettingsUiLocal({ activeTab: tab })
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
</script>

<template>
  <div class="settings-overlay" @click.self="emit('close')">
    <div class="settings-panel">
      <div class="settings-header">
        <span class="header-icon" aria-hidden="true">⚙</span>
        <span class="header-title">系统设置</span>
        <button class="close-btn" @click="emit('close')" title="关闭">
          <span aria-hidden="true">✕</span>
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
            <span class="nav-icon" aria-hidden="true">{{ tab.icon }}</span>
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
  background: rgba(4, 10, 18, 0.4);
}

.settings-panel {
  width: 38rem;
  max-width: 92vw;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: rgba(8, 17, 31, 0.98);
  border-left: 1px solid rgba(136, 192, 255, 0.14);
  box-shadow: -12px 0 36px rgba(1, 8, 16, 0.32);
}

.settings-header {
  display: flex;
  align-items: center;
  gap: 0.38rem;
  padding: 0.72rem 0.82rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.1);
  color: #e8f3fc;
  font-size: 0.74rem;
  font-weight: 600;
  flex: none;
}

.header-icon {
  font-size: 0.82rem;
  color: #5ad5ff;
}

.header-title {
  flex: 1;
}

.close-btn {
  width: 1.4rem;
  height: 1.4rem;
  border: none;
  border-radius: 0.5rem;
  background: transparent;
  color: #6e8ba0;
  cursor: pointer;
  font-size: 0.7rem;
}

.close-btn:hover {
  background: rgba(136, 192, 255, 0.1);
  color: #d8e6f5;
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
  border-right: 1px solid rgba(136, 192, 255, 0.08);
  overflow-y: auto;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 0.36rem;
  padding: 0.42rem 0.52rem;
  border: 1px solid transparent;
  border-radius: 0.5rem;
  background: transparent;
  color: #8aa8bf;
  cursor: pointer;
  font: inherit;
  font-size: 0.62rem;
  text-align: left;
  transition: all 0.16s ease;
}

.nav-item:hover {
  background: rgba(136, 192, 255, 0.06);
  color: #d8e6f5;
}

.nav-item.active {
  border-color: rgba(90, 213, 255, 0.3);
  background: rgba(10, 132, 255, 0.14);
  color: #5ad5ff;
  font-weight: 600;
}

.nav-icon {
  font-size: 0.68rem;
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
  color: #5a7080;
  font-size: 0.62rem;
}

.content-partial-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
  margin-bottom: 0.55rem;
  padding: 0.42rem 0.55rem;
  border: 1px solid rgba(255, 180, 90, 0.28);
  border-radius: 0.45rem;
  background: rgba(90, 60, 20, 0.28);
  color: #ffd9a8;
  font-size: 0.58rem;
  line-height: 1.4;
}

.loading-spinner {
  width: 1.6rem;
  height: 1.6rem;
  border: 2px solid rgba(90, 213, 255, 0.2);
  border-top-color: #5ad5ff;
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
  border: 1px solid rgba(90, 213, 255, 0.3);
  border-radius: 0.4rem;
  background: rgba(10, 132, 255, 0.12);
  color: #5ad5ff;
  cursor: pointer;
  font: inherit;
  font-size: 0.58rem;
}

.retry-btn:hover {
  background: rgba(10, 132, 255, 0.22);
}

@media (max-width: 600px) {
  .settings-panel {
    width: 100vw;
    max-width: 100vw;
  }

  .settings-body {
    flex-direction: column;
  }

  .settings-nav {
    width: 100%;
    flex-direction: row;
    border-right: none;
    border-bottom: 1px solid rgba(136, 192, 255, 0.08);
    overflow-x: auto;
    padding: 0.32rem;
  }

  .nav-item {
    flex: none;
  }
}
</style>
