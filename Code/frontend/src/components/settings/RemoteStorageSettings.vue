<script setup lang="ts">
/**
 * RemoteStorageSettings — 「远程与存储」设置入口（顶栏双 tab）。
 *
 * tab 1「远程存储」：11 协议 Profile 管理（双路径/浏览/检索/凭据历史）。
 * tab 2「开放门户」：开放数据门户目录（凭据/测试/CMR 检索/地址覆盖/自定义门户）。
 */

import { ref } from 'vue'
import Tabs from '../ui/Tabs.vue'
import RemoteStoragePanel from './remote-storage/RemoteStoragePanel.vue'
import OpenPortalPanel from './portals/OpenPortalPanel.vue'
import { loadSettingsUiLocal, saveSettingsUiLocal } from '../../services/settings-local'

type SubTab = 'storage' | 'portals'

const TABS = [
  { value: 'storage', label: '远程存储' },
  { value: 'portals', label: '开放门户' },
]

const saved = loadSettingsUiLocal().remoteStorageTab as SubTab | undefined
const activeTab = ref<SubTab>(saved === 'portals' ? 'portals' : 'storage')

function onTabChange(tab: string) {
  activeTab.value = tab as SubTab
  saveSettingsUiLocal({ ...loadSettingsUiLocal(), remoteStorageTab: activeTab.value })
}
</script>

<template>
  <div class="remote-and-storage">
    <Tabs
      class="top-tabs"
      :items="TABS"
      :model-value="activeTab"
      variant="segmented"
      @update:model-value="onTabChange"
    />
    <RemoteStoragePanel v-if="activeTab === 'storage'" />
    <OpenPortalPanel v-else />
  </div>
</template>

<style scoped>
.remote-and-storage {
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
}
.top-tabs {
  align-self: flex-start;
}
</style>
