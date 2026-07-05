<script setup lang="ts">
import ControlPanel from './ControlPanel.vue'

defineProps<{
  panelLabel: string
  panelKey?: string
  controlWidth?: number
  contentWidth?: number
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
  resizable?: boolean
  handlePosition?: 'bottom-right' | 'bottom-left' | 'top-right'
  showResizeHandle?: boolean
}>()
</script>

<template>
  <ControlPanel
    :panel-label="panelLabel"
    :panel-key="panelKey"
    :draggable="draggable"
    :collapsible="collapsible"
    :default-collapsed="defaultCollapsed"
    :max-offset-x="maxOffsetX"
    :max-offset-y="maxOffsetY"
    :default-width="defaultWidth"
    :default-height="defaultHeight"
    :min-width="minWidth"
    :min-height="minHeight"
    :max-width="maxWidth"
    :max-height="maxHeight"
    :resizable="resizable"
    :handle-position="handlePosition"
    :show-resize-handle="showResizeHandle"
  >
    <slot />
  </ControlPanel>
</template>
