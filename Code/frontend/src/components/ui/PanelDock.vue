<script setup lang="ts">
/**
 * PanelDock — 浮层面板壳（设计系统 §3.1，演进 ControlPanel）
 *
 * 玻璃 + elevation-2；统一标题栏/折叠/复位/隐藏三件套。
 * 用于左侧图层抽屉、右侧分析 dock 等浮层容器。
 *
 * 用法：
 *   <PanelDock title="图层" :collapsed.sync="collapsed" @close="...">
 *     ...内容...
 *   </PanelDock>
 */
import { computed, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    title: string
    /** 是否可折叠 */
    collapsible?: boolean
    /** 是否可关闭（显示 X 按钮） */
    closable?: boolean
    /** 是否可复位（显示复位按钮） */
    resettable?: boolean
    /** 初始折叠状态 */
    defaultCollapsed?: boolean
    /** 宽度（CSS 值，如 '320px'） */
    width?: string
    /** 位置 */
    position?: 'left' | 'right' | 'bottom' | 'float'
  }>(),
  {
    collapsible: true,
    closable: false,
    resettable: false,
    defaultCollapsed: false,
    width: '320px',
    position: 'left',
  },
)

const emit = defineEmits<{
  'update:collapsed': [value: boolean]
  close: []
  reset: []
}>()

const collapsed = ref(props.defaultCollapsed)

// 支持外部 v-model:collapsed 控制
watch(
  () => props.defaultCollapsed,
  (val) => {
    collapsed.value = val
  },
)

const cls = computed(() => [
  'panel-dock',
  `panel-dock--${props.position}`,
  { 'panel-dock--collapsed': collapsed.value },
])

function toggleCollapse() {
  collapsed.value = !collapsed.value
  emit('update:collapsed', collapsed.value)
}

function handleClose() {
  emit('close')
}

function handleReset() {
  emit('reset')
}
</script>

<template>
  <div :class="cls" :style="{ width }" data-ui="panel-dock">
    <header class="panel-dock__head">
      <div class="panel-dock__title-wrap">
        <button
          v-if="collapsible"
          class="panel-dock__collapse"
          type="button"
          :aria-expanded="!collapsed"
          :aria-label="collapsed ? '展开面板' : '折叠面板'"
          @click="toggleCollapse"
        >
          <svg
            class="panel-dock__chevron"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="m6 9 6 6 6-6" />
          </svg>
        </button>
        <h3 class="panel-dock__title">{{ title }}</h3>
      </div>
      <div class="panel-dock__actions">
        <button
          v-if="resettable"
          class="panel-dock__action"
          type="button"
          aria-label="复位"
          title="复位"
          @click="handleReset"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
            <path d="M3 3v5h5" />
          </svg>
        </button>
        <button
          v-if="closable"
          class="panel-dock__action"
          type="button"
          aria-label="关闭面板"
          title="关闭"
          @click="handleClose"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M18 6 6 18" />
            <path d="m6 6 12 12" />
          </svg>
        </button>
      </div>
    </header>

    <transition name="panel-body">
      <div v-show="!collapsed" class="panel-dock__body">
        <slot />
      </div>
    </transition>
  </div>
</template>

<style scoped>
.panel-dock {
  display: flex;
  flex-direction: column;
  border-radius: var(--radius-lg);
  background: var(--surface-2);
  border: 1px solid var(--border-default);
  box-shadow: var(--elevation-2);
  backdrop-filter: blur(var(--glass-blur));
  -webkit-backdrop-filter: blur(var(--glass-blur));
  overflow: hidden;
  min-width: 0;
  transition:
    width var(--motion-base) var(--ease-standard),
    box-shadow var(--motion-base) var(--ease-standard);
}

/* 位置修饰 */
.panel-dock--left {
  border-top-left-radius: 0;
  border-bottom-left-radius: 0;
}

.panel-dock--right {
  border-top-right-radius: 0;
  border-bottom-right-radius: 0;
}

.panel-dock--bottom {
  border-bottom-left-radius: 0;
  border-bottom-right-radius: 0;
  width: 100% !important;
}

.panel-dock--float {
  position: absolute;
  z-index: var(--z-panel);
}

/* 标题栏 */
.panel-dock__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border-subtle);
  flex: 0 0 auto;
  min-height: 44px;
}

.panel-dock__title-wrap {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.panel-dock__collapse {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    background-color var(--motion-fast) var(--ease-standard),
    color var(--motion-fast) var(--ease-standard),
    transform var(--motion-fast) var(--ease-standard);
}

.panel-dock__collapse:hover {
  background: var(--surface-sunken);
  color: var(--text-strong);
}

.panel-dock__collapse:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.panel-dock__chevron {
  transition: transform var(--motion-fast) var(--ease-standard);
}

.panel-dock--collapsed .panel-dock__chevron {
  transform: rotate(-90deg);
}

.panel-dock__title {
  margin: 0;
  font-size: var(--font-size-title);
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
  letter-spacing: 0.01em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.panel-dock__actions {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  flex: 0 0 auto;
}

.panel-dock__action {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    background-color var(--motion-fast) var(--ease-standard),
    color var(--motion-fast) var(--ease-standard);
}

.panel-dock__action:hover {
  background: var(--surface-sunken);
  color: var(--text-strong);
}

.panel-dock__action:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

/* 折叠态：仅显示头部 rail */
.panel-dock--collapsed {
  width: 48px !important;
}

.panel-dock--collapsed .panel-dock__title,
.panel-dock--collapsed .panel-dock__actions {
  display: none;
}

.panel-dock--collapsed .panel-dock__head {
  justify-content: center;
  padding: var(--space-3);
  border-bottom: none;
}

/* 内容区 */
.panel-dock__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-4);
}

/* 内容区过渡 */
.panel-body-enter-active,
.panel-body-leave-active {
  transition: opacity var(--motion-base) var(--ease-standard);
}

.panel-body-enter-from,
.panel-body-leave-to {
  opacity: 0;
}

@media (prefers-reduced-motion: reduce) {
  .panel-dock,
  .panel-dock__collapse,
  .panel-dock__chevron,
  .panel-body-enter-active,
  .panel-body-leave-active {
    transition: none;
  }
}
</style>
