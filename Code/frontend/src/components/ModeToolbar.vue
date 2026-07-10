<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'

import {
  TILE_SOURCES,
  TILE_SOURCES_BY_STYLE,
  type BasemapStyle,
  type TileSourceConfig,
  type TileSourceId,
} from '../services/api-config'
import type { ActiveLayerDisplay } from '../stores/layers/types'
import { useLayersStore } from '../stores/layers'
import { useUiStore } from '../stores/ui'
import WorkflowStatusButton from './workflow/WorkflowStatusButton.vue'

const layersStore = useLayersStore()
const uiStore = useUiStore()
const { workflowSummary } = storeToRefs(layersStore)
const { interactionMode } = storeToRefs(uiStore)

const props = defineProps<{
  tileSourceId: TileSourceId
  activeLayer: ActiveLayerDisplay
  hourLabel: string
  activeLayerCount: number
}>()

const emit = defineEmits<{
  changeTileSource: [sourceId: TileSourceId]
  openScreenshot: []
  openWorkflowStatus: []
}>()

const activeStyle = computed<BasemapStyle>(() => {
  const cfg = TILE_SOURCES.find((s) => s.id === props.tileSourceId)
  return cfg?.style ?? 'street'
})

const sourcesByStyle = computed(() => {
  const result: Array<{ style: BasemapStyle; label: string; icon: string; sources: TileSourceConfig[] }> = []
  const styleMeta: Record<BasemapStyle, { label: string; icon: string }> = {
    none: { label: '空图', icon: '◇' },
    satellite: { label: '影像', icon: '◆' },
    street: { label: '街道', icon: '▦' },
    dark: { label: '深色', icon: '◑' },
    terrain: { label: '地形', icon: '⛰' },
  }

  // Only show standard sources in the picker (non-standard need backend transform)
  for (const [style, sources] of TILE_SOURCES_BY_STYLE) {
    if (sources.some((s) => s.isStandard)) {
      result.push({
        style,
        label: styleMeta[style]?.label ?? style,
        icon: styleMeta[style]?.icon ?? '▦',
        sources: sources.filter((s) => s.isStandard),
      })
    }
  }

  return result
})

const currentTileConfig = computed(() => TILE_SOURCES.find((s) => s.id === props.tileSourceId))
</script>

<template>
  <header class="toolbar">
    <!-- Brand -->
    <div class="brand">
      <div class="brand-mark"></div>
      <div class="brand-copy">
        <p class="eyebrow">GeoFlow</p>
        <h1>综合地理态势</h1>
        <p class="subtitle">2D 演示台</p>
      </div>
    </div>

    <!-- Interaction mode: 移动 / 选择 -->
    <div class="interaction-mode" role="group" aria-label="交互模式">
      <button
        class="mode-btn"
        :class="{ active: interactionMode === 'move' }"
        :aria-pressed="interactionMode === 'move'"
        title="移动模式：拖动地图视角"
        @click="uiStore.setInteractionMode('move')"
      >
        <span class="mode-icon" aria-hidden="true">✥</span>
        <span>移动</span>
      </button>
      <button
        class="mode-btn"
        :class="{ active: interactionMode === 'select' }"
        :aria-pressed="interactionMode === 'select'"
        title="选择模式：点击选择点或图层"
        @click="uiStore.setInteractionMode('select')"
      >
        <span class="mode-icon" aria-hidden="true">⌖</span>
        <span>选择</span>
      </button>
    </div>

    <!-- Main toolbar -->
    <div class="toolbar-main">
      <!-- Style tabs -->
      <div class="toolbar-strip">
        <div class="style-tabs" role="tablist" aria-label="底图风格">
          <button
            v-for="group in sourcesByStyle"
            :key="group.style"
            class="style-tab"
            :class="{ active: activeStyle === group.style }"
            role="tab"
            :aria-selected="activeStyle === group.style"
            @click="emit('changeTileSource', group.sources[0].id)"
          >
            <span class="style-icon" aria-hidden="true">{{ group.icon }}</span>
            <span>{{ group.label }}</span>
          </button>
        </div>

        <!-- Source selector (shows sources for current style) -->
        <div v-if="activeStyle !== 'none'" class="source-pill">
          <button
            v-for="source in sourcesByStyle.find(g => g.style === activeStyle)?.sources ?? []"
            :key="source.id"
            class="source-btn"
            :class="{ active: tileSourceId === source.id }"
            :title="`${source.provider} · ${source.label}`"
            @click="emit('changeTileSource', source.id)"
          >
            {{ source.provider[0] }}
          </button>
        </div>

        <!-- Screenshot export -->
        <button
          class="screenshot-btn"
          title="导出截图"
          @click="emit('openScreenshot')"
        >
          <span class="screenshot-icon" aria-hidden="true">◫</span>
          <span>截图</span>
        </button>

        <!-- Workflow status -->
        <WorkflowStatusButton
          :summary="workflowSummary"
          @click="emit('openWorkflowStatus')"
        />

        <!-- Quick stats -->
        <div class="quick-stats">
          <div class="stat-pill">
            <span class="label">时间</span>
            <strong>{{ hourLabel }}</strong>
          </div>
          <div class="stat-pill compact">
            <span class="label">状态</span>
            <strong>{{ activeLayer.availabilityLabel }}</strong>
          </div>
        </div>
      </div>

      <!-- Status row -->
      <div class="toolbar-strip">
        <div class="status-chip">2D-first</div>
        <div v-if="activeLayerCount > 0" class="status-chip">{{ activeLayer.name }}</div>
        <div v-else class="status-chip">无图层</div>
        <div v-if="activeLayerCount > 0" class="status-chip" :class="`availability-${activeLayer.availabilityState}`">
          {{ activeLayer.availabilityLabel }}
        </div>
        <div v-if="activeLayerCount > 0" class="status-chip">{{ activeLayerCount }} 个图层</div>
        <div v-if="currentTileConfig?.needsBackendTransform" class="status-chip warning">
          需坐标转换
        </div>
      </div>
    </div>
  </header>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  gap: 0.8rem;
  align-items: center;
  padding: 0.48rem 0.7rem;
  border: 1px solid rgba(145, 197, 255, 0.14);
  border-radius: 1rem;
  background:
    linear-gradient(180deg, rgba(8, 17, 31, 0.8), rgba(7, 15, 28, 0.72)),
    rgba(8, 18, 33, 0.72);
  backdrop-filter: blur(18px);
  box-shadow:
    0 18px 42px rgba(1, 8, 16, 0.32),
    inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

.brand {
  display: flex;
  align-items: center;
  gap: 0.58rem;
  min-width: 0;
}

.brand-mark {
  width: 1.9rem;
  height: 1.9rem;
  flex: none;
  border-radius: 0.72rem;
  background:
    radial-gradient(circle at 30% 30%, rgba(255, 255, 255, 0.32), transparent 42%),
    linear-gradient(135deg, #5ad5ff, #2f7eff 58%, #7d7dff);
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.06), 0 12px 30px rgba(47, 126, 255, 0.28);
}

.brand-copy { min-width: 0; }

.eyebrow {
  margin: 0 0 0.08rem;
  color: #88dfff;
  font-size: 0.62rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  font-size: clamp(0.9rem, 1.5vw, 1.18rem);
  color: #f5fbff;
}

.subtitle {
  margin: 0.1rem 0 0;
  color: #93a4b8;
  line-height: 1.35;
  font-size: 0.68rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 16rem;
}

/* Interaction mode (移动 / 选择) */
.interaction-mode {
  display: inline-flex;
  gap: 0.18rem;
  padding: 0.16rem;
  border: 1px solid rgba(136, 192, 255, 0.14);
  border-radius: 999px;
  background: rgba(4, 12, 23, 0.82);
}

.mode-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.26rem;
  border: none;
  border-radius: 999px;
  padding: 0.28rem 0.56rem;
  background: transparent;
  color: #8aa8bf;
  cursor: pointer;
  font: inherit;
  font-size: 0.64rem;
  transition: background-color 0.2s ease, color 0.2s ease, transform 0.2s ease;
  white-space: nowrap;
}

.mode-btn:hover {
  color: #f0f8ff;
  background: rgba(136, 192, 255, 0.1);
  transform: translateY(-1px);
}

.mode-btn.active {
  background: rgba(10, 132, 255, 0.5);
  color: #f0faff;
  font-weight: 600;
  box-shadow: inset 0 0 0 1px rgba(90, 213, 255, 0.2);
}

.mode-icon {
  font-size: 0.72rem;
  opacity: 0.7;
}

.mode-btn.active .mode-icon {
  opacity: 1;
}

.toolbar-main {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.38rem;
}

.toolbar-strip {
  display: flex;
  align-items: center;
  gap: 0.42rem;
  flex-wrap: wrap;
}

.toolbar-strip:last-child {
  flex-wrap: nowrap;
  overflow: hidden;
  min-width: 0;
}

/* Style tabs */
.style-tabs {
  display: inline-flex;
  gap: 0.18rem;
  padding: 0.16rem;
  border: 1px solid rgba(136, 192, 255, 0.14);
  border-radius: 999px;
  background: rgba(4, 12, 23, 0.82);
}

.style-tab {
  display: inline-flex;
  align-items: center;
  gap: 0.28rem;
  border: none;
  border-radius: 999px;
  padding: 0.26rem 0.52rem;
  background: transparent;
  color: #8aa8bf;
  cursor: pointer;
  font: inherit;
  font-size: 0.64rem;
  transition: background-color 0.2s ease, color 0.2s ease, transform 0.2s ease;
  white-space: nowrap;
}

.style-tab:hover {
  color: #f0f8ff;
  background: rgba(136, 192, 255, 0.1);
  transform: translateY(-1px);
}

.style-tab.active {
  background: rgba(10, 132, 255, 0.5);
  color: #f0faff;
  font-weight: 600;
  box-shadow: inset 0 0 0 1px rgba(90, 213, 255, 0.2);
}

.style-icon {
  font-size: 0.7rem;
  opacity: 0.7;
}

.style-tab.active .style-icon {
  opacity: 1;
}

/* Source buttons */
.source-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.14rem;
  padding: 0.16rem 0.22rem 0.16rem 0.3rem;
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: 999px;
  background: rgba(4, 12, 23, 0.6);
}

.source-pill::before {
  content: '源';
  color: #5a7080;
  font-size: 0.56rem;
  letter-spacing: 0.04em;
  margin-right: 0.12rem;
}

.source-btn {
  width: 1.38rem;
  height: 1.38rem;
  border: none;
  border-radius: 0.4rem;
  padding: 0;
  background: transparent;
  color: #6e8ba0;
  cursor: pointer;
  font: inherit;
  font-size: 0.58rem;
  font-weight: 600;
  letter-spacing: 0.01em;
  transition: background 0.16s ease, color 0.16s ease, transform 0.16s ease;
}

.source-btn:hover {
  background: rgba(136, 192, 255, 0.1);
  color: #c8dff0;
  transform: scale(1.06);
}

.source-btn.active {
  background: rgba(10, 132, 255, 0.22);
  color: #5ad5ff;
  box-shadow: inset 0 0 0 1px rgba(90, 213, 255, 0.3);
}

/* Admin overlay toggle */
.overlay-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.28rem;
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: 999px;
  padding: 0.26rem 0.52rem;
  background: rgba(4, 12, 23, 0.6);
  color: #6e8ba0;
  cursor: pointer;
  font: inherit;
  font-size: 0.62rem;
  font-weight: 500;
  transition: border-color 0.18s ease, color 0.18s ease, background 0.18s ease;
  white-space: nowrap;
}

.overlay-toggle:hover {
  border-color: rgba(136, 192, 255, 0.24);
  color: #c8dff0;
  background: rgba(136, 192, 255, 0.08);
}

.overlay-toggle.active {
  border-color: rgba(76, 136, 186, 0.4);
  color: #7fd0f8;
  background: rgba(60, 120, 170, 0.16);
}

.overlay-icon {
  font-size: 0.7rem;
  opacity: 0.8;
}

.overlay-toggle.active .overlay-icon {
  opacity: 1;
}

/* Screenshot button */
.screenshot-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.28rem;
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: 999px;
  padding: 0.26rem 0.52rem;
  background: rgba(4, 12, 23, 0.6);
  color: #6e8ba0;
  cursor: pointer;
  font: inherit;
  font-size: 0.62rem;
  font-weight: 500;
  transition: border-color 0.18s ease, color 0.18s ease, background 0.18s ease;
  white-space: nowrap;
}

.screenshot-btn:hover {
  border-color: rgba(90, 213, 255, 0.3);
  color: #5ad5ff;
  background: rgba(10, 132, 255, 0.12);
}

.screenshot-icon {
  font-size: 0.7rem;
  opacity: 0.8;
}

/* Stats */
.quick-stats {
  display: flex;
  gap: 0.28rem;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.stat-pill {
  display: grid;
  gap: 0.15rem;
  min-width: 4rem;
  padding: 0.24rem 0.44rem;
  border-radius: 0.68rem;
  background: rgba(4, 12, 23, 0.42);
  border: 1px solid rgba(136, 192, 255, 0.1);
}

.stat-pill.compact { min-width: 3rem; }

.label {
  color: #7f96ab;
  font-size: 0.52rem;
}

.stat-pill strong {
  color: #eff8ff;
  font-size: 0.62rem;
  font-weight: 600;
}

.status-chip {
  display: inline-flex;
  align-items: center;
  max-width: 8rem;
  padding: 0.24rem 0.46rem;
  border-radius: 999px;
  background: rgba(4, 12, 23, 0.42);
  border: 1px solid rgba(136, 192, 255, 0.1);
  color: #d8e6f5;
  font-size: 0.6rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.availability-ready { color: #9ff8cf; border-color: rgba(114, 255, 207, 0.18); background: rgba(114, 255, 207, 0.1); }
.availability-partial { color: #ffd38a; border-color: rgba(255, 196, 120, 0.18); background: rgba(255, 196, 120, 0.08); }
.availability-empty { color: #d7c1ff; border-color: rgba(187, 137, 255, 0.2); background: rgba(187, 137, 255, 0.1); }
.status-chip.warning { color: #ffc878; border-color: rgba(255, 180, 80, 0.2); background: rgba(255, 160, 60, 0.1); }

@media (max-width: 900px) {
  .toolbar {
    flex-direction: column;
    align-items: stretch;
    padding: 0.72rem;
  }

  .toolbar-main { align-items: stretch; }

  .toolbar-strip,
  .quick-stats {
    justify-content: flex-start;
  }

  .style-tabs {
    align-self: flex-start;
    flex-wrap: wrap;
  }
}
</style>
