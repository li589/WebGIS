<script setup lang="ts">
/**
 * DataSourceSettings — 「数据源」设置入口（顶栏双 tab）。
 *
 * tab 1「本地数据源」：细分路径配置 + 可用数据集注册表 + 存储只读信息。
 * tab 2「远程数据源」：按「远程与存储」中的存储源/开放门户动态分组，浏览/检索并注册可访问远程数据源。
 * 顶部提示卡（admin 可见）：引导至「部署与数据源配置中心」（/deployment，真源 deployment.config.json）。
 */

import { ref } from 'vue'
import { RouterLink } from 'vue-router'
import Tabs from '../ui/Tabs.vue'
import LocalDataSourcePanel from './data-source/LocalDataSourcePanel.vue'
import RemoteDataSourcesPanel from './data-source/RemoteDataSourcesPanel.vue'
import DataInputPoliciesPanel from './data-source/DataInputPoliciesPanel.vue'
import { loadSettingsUiLocal, saveSettingsUiLocal } from '../../services/settings-local'
import { useAuthStore } from '../../stores/auth'

type SubTab = 'local' | 'remote' | 'policies'

const TABS = [
  { value: 'local', label: '本地数据源' },
  { value: 'remote', label: '远程数据源' },
  { value: 'policies', label: '调度策略' },
]

const authStore = useAuthStore()

const saved = loadSettingsUiLocal().dataSourceTab as SubTab | undefined
const activeTab = ref<SubTab>(saved === 'remote' || saved === 'policies' ? saved : 'local')

function onTabChange(tab: string) {
  activeTab.value = tab as SubTab
  saveSettingsUiLocal({ ...loadSettingsUiLocal(), dataSourceTab: activeTab.value })
}
</script>

<template>
  <div class="data-source-settings-root">
    <div v-if="authStore.isAdmin" class="deploy-guide">
      <span class="deploy-guide-text">
        数据盘路径、缓存、导入导出与 Docker
        等部署级配置已统一收敛到「部署配置中心」（deployment.config.json 真源）。
      </span>
      <RouterLink to="/deployment" class="deploy-guide-link">前往部署配置中心 →</RouterLink>
    </div>

    <Tabs
      class="top-tabs"
      :items="TABS"
      :model-value="activeTab"
      variant="segmented"
      @update:model-value="onTabChange"
    />
    <LocalDataSourcePanel v-if="activeTab === 'local'" />
    <RemoteDataSourcesPanel v-else-if="activeTab === 'remote'" />
    <DataInputPoliciesPanel v-else />
  </div>
</template>

<style scoped>
.data-source-settings-root {
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
}
.top-tabs {
  align-self: flex-start;
}
.deploy-guide {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
  padding: 0.5rem 0.65rem;
  border: 1px solid var(--border-subtle);
  border-radius: 0.42rem;
  background: var(--surface-sunken);
}
.deploy-guide-text {
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  line-height: 1.5;
  flex: 1;
  min-width: 12rem;
}
.deploy-guide-link {
  color: var(--accent-strong);
  font-size: var(--font-size-caption);
  text-decoration: none;
  white-space: nowrap;
}
.deploy-guide-link:hover {
  text-decoration: underline;
}
</style>
