/** InfoPanel 顶部 Tab 栏。纯展示，样式自洽（不依赖父级 scoped CSS）。
 * 2026-08-25 用户反馈：原「图层名 · 阶段标签」指示行移到 panel-topline
 * 顶摘要行（右对齐）——此处只保留 Tabs。 */
<script setup lang="ts">
import Tabs from '../ui/Tabs.vue'
import type { AnalysisTabId } from './analysis-tab-focus'

defineProps<{
  activeTab: AnalysisTabId
}>()

const emit = defineEmits<{
  'update:activeTab': [tab: AnalysisTabId]
}>()

const tabItems = [
  { value: 'visual', label: '图表' },
  { value: 'tools', label: '工具' },
  { value: 'style', label: '样式' },
  { value: 'meta', label: '元数据' },
]

function onTabChange(value: string) {
  emit('update:activeTab', value as AnalysisTabId)
}
</script>

<template>
  <div class="panel-sticky-chrome">
    <Tabs
      class="panel-analysis-tabs"
      variant="segmented"
      compact
      :items="tabItems"
      :model-value="activeTab"
      @update:model-value="onTabChange"
    />
  </div>
</template>

<style scoped>
.panel-sticky-chrome {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-3) var(--space-2);
  border-bottom: 1px solid var(--border-default);
  background: var(--surface-2);
  backdrop-filter: blur(8px);
  z-index: 5;
  border-top-left-radius: var(--panel-radius, var(--radius-xl));
  border-top-right-radius: var(--panel-radius, var(--radius-xl));
}

.panel-analysis-tabs {
  width: 100%;
  display: flex;
}

.panel-analysis-tabs :deep(.tabs-item) {
  flex: 1 1 0;
  min-width: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  text-align: center;
}
</style>
