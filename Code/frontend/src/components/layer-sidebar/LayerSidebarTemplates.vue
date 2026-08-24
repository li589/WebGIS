<script setup lang="ts">
/**
 * 课题组工作流模板区（图层平台子系统 P2-1）。
 *
 * 渲染 GET /workflows/templates 的模板卡片：名称 + 描述 + 引擎徽标 +
 * 一键运行按钮。运行提交与轮询链由父组件（LayerSidebar）承担：
 * POST /workflows/templates/{id}/runs → registerExternalWorkflowRun
 * 纳入既有 poller → auto_display 产物物化上图。
 */
import type { WorkflowTemplateSummary } from '../../services/runtime-api'

defineProps<{
  templates: WorkflowTemplateSummary[]
  /** 正在提交的 workflow_id 集合（按钮转 pending 态防重复提交） */
  submittingIds: Set<string>
}>()

const emit = defineEmits<{
  runTemplate: [workflowId: string]
}>()

const ENGINE_LABELS: Record<string, string> = {
  python_provider: '算法引擎',
  gee: 'GEE',
  weather: '天气',
  analysis: '分析',
}

function engineLabel(engine: string): string {
  return ENGINE_LABELS[engine] ?? engine
}
</script>

<template>
  <div v-if="templates.length > 0" class="template-section" data-testid="lab-template-section">
    <div class="template-section-header">
      <span class="template-section-icon">⚗</span>
      <span class="template-section-title">课题组模板</span>
      <span class="template-section-count">{{ templates.length }}</span>
    </div>
    <div
      v-for="tpl in templates"
      :key="tpl.workflow_id"
      class="template-card"
      :data-testid="`lab-template-${tpl.workflow_id}`"
    >
      <div class="template-card-main">
        <div class="template-card-title-row">
          <span class="template-card-name" :title="tpl.workflow_id">{{ tpl.name }}</span>
          <span class="template-card-engine" :title="`引擎：${tpl.engine}`">
            {{ engineLabel(tpl.engine) }}
          </span>
        </div>
        <p v-if="tpl.description" class="template-card-desc">{{ tpl.description }}</p>
        <div class="template-card-meta">
          <span
            v-if="tpl.linked_layer_id"
            class="template-card-linked"
            :title="`完成后自动上图：${tpl.linked_layer_id}`"
            >↦ {{ tpl.linked_layer_id }}</span
          >
          <span v-else class="template-card-linked none" title="仅运行，不上图">仅运行</span>
        </div>
      </div>
      <button
        class="template-run-btn"
        :disabled="submittingIds.has(tpl.workflow_id)"
        :title="
          submittingIds.has(tpl.workflow_id)
            ? '正在提交…'
            : `运行「${tpl.name}」${tpl.auto_display ? '（完成后自动上图）' : ''}`
        "
        @click.stop="emit('runTemplate', tpl.workflow_id)"
      >
        {{ submittingIds.has(tpl.workflow_id) ? '提交中…' : '▶ 运行' }}
      </button>
    </div>
  </div>
</template>
