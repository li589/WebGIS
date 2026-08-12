/** * InfoPanel 顶部 Tab 栏 + 阶段标签。 * * 从 InfoPanel.vue 模板抽取（原 1190-1228
行）。纯展示组件，不持有状态。 */
<script setup lang="ts">
import type { AnalysisTabId } from './analysis-tab-focus'

defineProps<{
  activeTab: AnalysisTabId
  stageLabel: string
}>()

const emit = defineEmits<{
  'update:activeTab': [tab: AnalysisTabId]
}>()

function setTab(tab: AnalysisTabId) {
  emit('update:activeTab', tab)
}
</script>

<template>
  <div class="panel-sticky-chrome">
    <div class="dashboard-nav-tabs">
      <button
        type="button"
        class="dash-tab"
        :class="{ active: activeTab === 'visual' }"
        @click="setTab('visual')"
      >
        图表
      </button>
      <button
        type="button"
        class="dash-tab"
        :class="{ active: activeTab === 'tools' }"
        @click="setTab('tools')"
      >
        工具
      </button>
      <button
        type="button"
        class="dash-tab"
        :class="{ active: activeTab === 'style' }"
        @click="setTab('style')"
      >
        样式
      </button>
      <button
        type="button"
        class="dash-tab"
        :class="{ active: activeTab === 'meta' }"
        @click="setTab('meta')"
      >
        元数据
      </button>
    </div>
    <div class="panel-stage-row">
      <span class="readiness readiness--inline" :title="stageLabel">{{ stageLabel }}</span>
    </div>
  </div>
</template>
