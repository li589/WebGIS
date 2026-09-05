<script setup lang="ts">
import { LayoutGrid } from '../ui/icons'
import Tooltip from '../ui/Tooltip.vue'
import AnimatedNumber from '../ui/AnimatedNumber.vue'

defineProps<{
  sidebarViewLabel: string
  sidebarView: string
  activeLayerCount: number
  canManageGroups?: boolean
}>()

const emit = defineEmits<{
  openLibrary: []
  openActive: []
  openGroupManager: []
}>()
</script>

<template>
  <!-- ── Header ─────────────────────────────────────────────────────────── -->
  <div class="panel-topline">
    <div class="panel-header">
      <div class="header-copy">
        <h2>{{ sidebarViewLabel }}</h2>
        <p v-if="sidebarView !== 'active'" class="panel-subtitle">
          {{ sidebarView === 'empty' ? '开始添加图层' : '从库中选择' }}
        </p>
      </div>
      <div class="header-actions">
        <Tooltip v-if="activeLayerCount > 0" text="已添加">
          <button
            class="badge"
            type="button"
            aria-label="查看已添加图层"
            @click="emit('openActive')"
          >
            <AnimatedNumber :value="activeLayerCount" />
          </button>
        </Tooltip>
        <div class="view-tabs" role="tablist">
          <Tooltip v-if="canManageGroups" text="分组">
            <button
              class="view-tab view-tab--icon"
              type="button"
              role="tab"
              aria-label="管理图层分组"
              @click="emit('openGroupManager')"
            >
              <LayoutGrid :size="14" :stroke-width="2" aria-hidden="true" />
            </button>
          </Tooltip>
          <Tooltip text="图层库">
            <button
              class="view-tab"
              :class="{ active: sidebarView === 'library' }"
              type="button"
              role="tab"
              aria-label="图层库"
              :aria-selected="sidebarView === 'library'"
              @click="emit('openLibrary')"
            >
              +
            </button>
          </Tooltip>
          <Tooltip text="已添加">
            <button
              class="view-tab"
              :class="{ active: sidebarView === 'active' }"
              type="button"
              role="tab"
              aria-label="已添加图层"
              :aria-selected="sidebarView === 'active'"
              @click="emit('openActive')"
            >
              ≡
            </button>
          </Tooltip>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped src="./LayerSidebar.styles.css"></style>
