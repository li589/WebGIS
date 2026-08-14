<script setup lang="ts">
defineProps<{
  sidebarViewLabel: string
  sidebarView: string
  activeLayerCount: number
}>()

const emit = defineEmits<{
  openLibrary: []
  openActive: []
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
        <button
          v-if="activeLayerCount > 0"
          class="badge"
          type="button"
          title="查看已添加图层"
          @click="emit('openActive')"
        >
          {{ activeLayerCount }}
        </button>
        <div class="view-tabs" role="tablist">
          <button
            class="view-tab"
            :class="{ active: sidebarView === 'library' }"
            role="tab"
            title="图层库"
            @click="emit('openLibrary')"
          >
            +
          </button>
          <button
            class="view-tab"
            :class="{ active: sidebarView === 'active' }"
            role="tab"
            :aria-selected="sidebarView === 'active'"
            title="已添加图层"
            @click="emit('openActive')"
          >
            ≡
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped src="./LayerSidebar.styles.css"></style>
