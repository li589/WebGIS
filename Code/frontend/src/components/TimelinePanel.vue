<script setup lang="ts">
/**
 * TimelinePanel — 时间轴浮层面板（PanelDock 薄封装）
 *
 * 原 567 行独立实现已收敛至 PanelDock + usePanelDragResize composable。
 * 仅保留 timeline 专有的默认尺寸与 CSS 变量覆盖。
 */

import PanelDock from './ui/PanelDock.vue'

withDefaults(
  defineProps<{
    panelLabel: string
    panelKey?: string
    draggable?: boolean
    collapsible?: boolean
    defaultCollapsed?: boolean
    maxOffsetX?: number
    maxOffsetY?: number
    defaultWidth?: number
    defaultHeight?: number
    minWidth?: number
    minHeight?: number
    maxWidth?: number
    maxHeight?: number
  }>(),
  {
    draggable: true,
    collapsible: true,
    defaultCollapsed: false,
    maxOffsetX: 140,
    maxOffsetY: 70,
    defaultWidth: 720,
    defaultHeight: 205,
    minWidth: 500,
    minHeight: 195,
    maxWidth: 980,
    maxHeight: 260,
  },
)
</script>

<template>
  <PanelDock
    :panel-label="panelLabel"
    :panel-key="panelKey"
    position="bottom"
    :draggable="draggable"
    :collapsible="collapsible"
    :default-collapsed="defaultCollapsed"
    :resizable="false"
    :show-resize-handle="false"
    :max-offset-x="maxOffsetX"
    :max-offset-y="maxOffsetY"
    :default-width="defaultWidth"
    :default-height="defaultHeight"
    :min-width="minWidth"
    :min-height="minHeight"
    :max-width="maxWidth"
    :max-height="maxHeight"
    body-overflow="hidden"
  >
    <slot />
  </PanelDock>
</template>

<style scoped>
/* 覆盖 PanelDock 的 timeline 专有变量 */
:deep(.panel-anchor) {
  --panel-collapsed-height: 2.55rem;
  --panel-title-height: 2.3rem;
  --panel-body-padding: 0.18rem;
}
</style>
