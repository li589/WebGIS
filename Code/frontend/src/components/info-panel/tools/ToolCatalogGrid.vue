<script setup lang="ts">
/**
 * 工具目录网格：后端目录工具 + 本地交互工具（底图要素提取）统一入口。
 * 响应式网格（窄 1–2 列、宽 3–4 列），整块可收回。
 */
import { computed, ref, watch } from 'vue'
import { ChevronDown, ChevronUp } from '../../ui/icons'
import type { AnalysisToolDescriptor } from '../../../services/analysis-api'

export interface ToolGridEntry {
  id: string
  title: string
  description: string
  enabled: boolean
  disabledReason?: string | null
  /** 运行中/已完成等角标文案 */
  phaseBadge?: string
}

const props = defineProps<{
  tools: AnalysisToolDescriptor[]
  phaseBadges?: Record<string, string>
}>()

const emit = defineEmits<{
  select: [entryId: string]
}>()

const collapsed = ref(false)

const entries = computed<ToolGridEntry[]>(() => {
  const catalog: ToolGridEntry[] = props.tools.map((tool) => ({
    id: tool.tool_id,
    title: tool.title,
    description: tool.description,
    enabled: tool.enabled,
    disabledReason: tool.disabled_reason,
    phaseBadge: props.phaseBadges?.[tool.tool_id],
  }))
  return [
    ...catalog,
    {
      id: 'basemap-extract',
      title: '底图要素提取',
      description: '从底图提取行政区 / 道路要素并创建矢量图层。',
      enabled: true,
    },
  ]
})

// 图层切换后重置收回态，避免新图层工具被隐藏
watch(
  () => props.tools,
  () => {
    collapsed.value = false
  },
)
</script>

<template>
  <div class="tool-catalog">
    <button type="button" class="catalog-toggle" @click="collapsed = !collapsed">
      <component :is="collapsed ? ChevronDown : ChevronUp" :size="14" aria-hidden="true" />
      <span class="catalog-title">工具目录</span>
      <span class="catalog-count">{{ entries.length }} 项</span>
    </button>

    <div v-show="!collapsed" class="tool-grid">
      <button
        v-for="entry in entries"
        :key="entry.id"
        type="button"
        class="tool-cell"
        :class="{ 'tool-cell--disabled': !entry.enabled }"
        :title="entry.disabledReason || entry.description"
        :disabled="!entry.enabled"
        @click="emit('select', entry.id)"
      >
        <span class="tool-cell-title">
          {{ entry.title }}
          <em v-if="entry.phaseBadge" class="tool-cell-badge">{{ entry.phaseBadge }}</em>
        </span>
        <span class="tool-cell-desc">{{ entry.description }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.tool-catalog {
  margin-bottom: 0.55rem;
}

.catalog-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--font-size-caption);
  letter-spacing: 0.04em;
  cursor: pointer;
  padding: 0.15rem 0;
  margin-bottom: 0.35rem;
}

.catalog-title {
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.catalog-count {
  color: var(--text-muted);
}

.tool-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(8.5rem, 1fr));
  gap: 0.4rem;
}

.tool-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.2rem;
  padding: 0.45rem 0.5rem;
  border: 1px solid var(--border-default);
  border-radius: 0.5rem;
  background: var(--surface-raised);
  color: var(--text-primary);
  cursor: pointer;
  text-align: left;
  transition:
    border-color 0.15s ease,
    background 0.15s ease;
}

.tool-cell:hover:not(:disabled) {
  border-color: var(--accent, #3b82f6);
}

.tool-cell--disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.tool-cell-title {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-size: var(--font-size-body);
  font-weight: 600;
}

.tool-cell-badge {
  font-style: normal;
  font-size: var(--font-size-caption);
  font-weight: 400;
  color: var(--accent, #3b82f6);
}

.tool-cell-desc {
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
