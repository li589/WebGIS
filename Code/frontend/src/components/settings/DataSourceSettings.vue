<script setup lang="ts">
/**
 * DataSourceSettings — 「数据源」设置入口（顶栏双 tab）。
 *
 * tab 1「本地数据源」：细分路径配置 + 可用数据集注册表 + 存储只读信息。
 * tab 2「远程数据源」：按「远程与存储」中的存储源/开放门户动态分组，浏览/检索并注册可访问远程数据源。
 */

import { ref } from 'vue'
import Tabs from '../ui/Tabs.vue'
import LocalDataSourcePanel from './data-source/LocalDataSourcePanel.vue'
import RemoteDataSourcesPanel from './data-source/RemoteDataSourcesPanel.vue'
import { loadSettingsUiLocal, saveSettingsUiLocal } from '../../services/settings-local'

type SubTab = 'local' | 'remote'

const TABS = [
  { value: 'local', label: '本地数据源' },
  { value: 'remote', label: '远程数据源' },
]

const saved = loadSettingsUiLocal().dataSourceTab as SubTab | undefined
const activeTab = ref<SubTab>(saved === 'remote' ? 'remote' : 'local')

function onTabChange(tab: string) {
  activeTab.value = tab as SubTab
  saveSettingsUiLocal({ ...loadSettingsUiLocal(), dataSourceTab: activeTab.value })
}
</script>

<template>
  <div class="data-source-settings-root">
    <Tabs
      class="top-tabs"
      :items="TABS"
      :model-value="activeTab"
      variant="segmented"
      @update:model-value="onTabChange"
    />
    <LocalDataSourcePanel v-if="activeTab === 'local'" />
    <RemoteDataSourcesPanel v-else />
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
</style>
