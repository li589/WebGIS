<script setup lang="ts">
/**
 * WorkflowLeftSidebar.vue
 *
 * 工作流编辑器左侧面板：收起/展开按钮 + 工作流列表。
 * 从 WorkflowEditorPanel.vue 拆分，降低主面板代码复杂度。
 */
import WorkflowList from './WorkflowList.vue'

const props = defineProps<{
  collapsed: boolean
}>()

const emit = defineEmits<{
  'update:collapsed': [value: boolean]
  select: [workflowId: string]
  create: []
}>()

function toggleCollapsed() {
  emit('update:collapsed', !props.collapsed)
}
</script>

<template>
  <aside class="editor-sidebar left" :class="{ collapsed }">
    <WorkflowList v-show="!collapsed" @select="emit('select', $event)" @create="emit('create')" />
    <button
      class="sidebar-toggle left-toggle"
      type="button"
      :title="collapsed ? '展开左侧面板' : '收起左侧面板'"
      @click="toggleCollapsed"
    >
      <span aria-hidden="true">{{ collapsed ? '▶' : '◀' }}</span>
    </button>
  </aside>
</template>

<style scoped>
.editor-sidebar {
  display: flex;
  flex-direction: column;
  flex: none;
  border-right: 1px solid rgba(136, 192, 255, 0.1);
  position: relative;
  transition: width 0.22s ease;
}

.editor-sidebar.left {
  width: 16rem;
}

.editor-sidebar.left.collapsed {
  width: 1.6rem;
}

.sidebar-toggle {
  position: absolute;
  top: 0.42rem;
  z-index: 10;
  width: 1.2rem;
  height: 1.6rem;
  border: 1px solid rgba(136, 192, 255, 0.16);
  border-radius: 0.32rem;
  background: rgba(12, 24, 42, 0.88);
  color: #8aa8bf;
  font-size: 0.5rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition:
    color 0.16s ease,
    border-color 0.16s ease,
    background 0.16s ease;
}

.sidebar-toggle:hover {
  color: #ffd38a;
  border-color: rgba(255, 184, 77, 0.36);
  background: rgba(20, 34, 56, 0.92);
}

.left-toggle {
  right: 0.3rem;
}

.editor-sidebar.collapsed .sidebar-toggle {
  top: 50%;
  transform: translateY(-50%);
}

/* 展开状态下为子组件头部留出 toggle 按钮空间，避免重叠 */
.editor-sidebar.left:not(.collapsed) :deep(.list-header) {
  padding-right: 2rem;
}

@media (max-width: 1100px) {
  .editor-sidebar.left {
    width: 12rem;
  }
}

@media (max-width: 800px) {
  .editor-sidebar.left {
    width: 100%;
    height: 12rem;
    border-right: none;
    border-bottom: 1px solid rgba(136, 192, 255, 0.1);
  }
  .editor-sidebar.left.collapsed {
    width: 100%;
    height: 1.6rem;
  }
}
</style>
