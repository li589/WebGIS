<script setup lang="ts">
import type { LayerContextActionId, LayerContextMenuGroup } from './layer-context-menu'

defineProps<{
  contextMenu: { x: number; y: number; instanceId?: string; groupId?: string } | null
  contextMenuGroups: LayerContextMenuGroup[]
}>()

const emit = defineEmits<{
  handleContextAction: [action: LayerContextActionId]
}>()
</script>

<template>
  <!-- ── 右键上下文菜单（Teleport 到 body） ─────────────────────────────── -->
  <Teleport to="body">
    <div
      v-if="contextMenu"
      class="ctx-menu"
      :style="{ left: contextMenu.x + 'px', top: contextMenu.y + 'px' }"
      @click.stop
    >
      <template v-for="(group, gi) in contextMenuGroups" :key="group.id">
        <div v-if="gi > 0" class="ctx-sep" role="separator"></div>
        <button
          v-for="item in group.items"
          :key="item.id"
          class="ctx-item"
          :class="{ 'ctx-danger': item.danger }"
          type="button"
          :disabled="item.disabled"
          @click="emit('handleContextAction', item.id)"
        >
          <span class="ctx-icon" aria-hidden="true">{{ item.icon }}</span>
          <span>{{ item.label }}</span>
        </button>
      </template>
    </div>
  </Teleport>
</template>

<style scoped src="./LayerSidebar.styles.css"></style>
