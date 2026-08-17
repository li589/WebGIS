/** InfoPanel 顶部 Tab 栏 + 阶段标签。纯展示，样式自洽（不依赖父级 scoped CSS）。 */
<script setup lang="ts">
import Tabs from '../ui/Tabs.vue'
import type { AnalysisTabId } from './analysis-tab-focus'

defineProps<{
  activeTab: AnalysisTabId
  stageLabel: string
  /** 选中图层名；与阶段短标签合成显示为「图层名 · 叠加图层」 */
  layerName?: string
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
    <div class="panel-stage-row">
      <span
        class="readiness readiness--inline"
        :title="layerName ? `${layerName} · ${stageLabel}` : stageLabel"
      >
        <template v-if="layerName">{{ layerName }} · </template>{{ stageLabel }}
      </span>
    </div>
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

.panel-stage-row {
  display: flex;
  justify-content: flex-end;
  padding: 0 var(--space-1);
}

.readiness--inline {
  flex: 0 1 auto;
  max-width: 100%;
  padding: 0.12rem 0.32rem;
  font-size: var(--font-size-caption);
  color: var(--text-muted);
  background: var(--surface-sunken);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
