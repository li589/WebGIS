<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { storeToRefs } from 'pinia'
import {
  Settings,
  ScrollText,
  Camera,
  Workflow,
  Move,
  Crosshair,
  Ruler,
  Trash2,
  Satellite,
  Map,
  Moon,
  Mountain,
  Globe,
} from 'lucide-vue-next'

import {
  TILE_SOURCES,
  TILE_SOURCES_BY_STYLE,
  getDefaultTileSource,
  isTileSourceUsable,
  tileSourceRequiresApiKey,
  type BasemapStyle,
  type TileSourceConfig,
  type TileSourceId,
} from '../services/api-config'
import type { ActiveLayerDisplay } from '../stores/layers/types'
import { useLayersStore } from '../stores/layers'
import { useUiStore } from '../stores/ui'
import { useLogStore } from '../stores/log'
import { useSettingsStore } from '../stores/settings'
import { useAuthStore } from '../stores/auth'
import { useWeatherTileManager } from '../stores/weather-tile-manager'
import { useWeatherSyncStatusStore } from '../stores/weather-sync-status'
import { mergeWorkflowSummaryWithWeather } from '../utils/workflow-status-merge'
import {
  BRAND,
  BASEMAP_COPY,
  basemapStyleLabel,
  basemapProviderShort,
  WORKFLOW_COPY,
  SETTINGS_COPY,
} from '../ui-copy'
import WorkflowStatusButton from './workflow/WorkflowStatusButton.vue'
import DataImportMenu from '../data-manager/ui/DataImportMenu.vue'

const layersStore = useLayersStore()
const uiStore = useUiStore()
const logStore = useLogStore()
const settingsStore = useSettingsStore()
const authStore = useAuthStore()
const weatherTileManager = useWeatherTileManager()
const weatherSyncStatus = useWeatherSyncStatusStore()
const { workflowSummary } = storeToRefs(layersStore)
const { activityVersion, statusVersion } = storeToRefs(weatherTileManager)
const { apiKeys } = storeToRefs(settingsStore)
const { syncInProgress } = storeToRefs(weatherSyncStatus)

onMounted(() => {
  if (authStore.isAuthenticated && apiKeys.value.length === 0) {
    void settingsStore.loadApiKeys().catch(() => {
      /* toolbar still works with free basemaps */
    })
  }
  void weatherSyncStatus.refreshOverview()
})

const mergedWorkflowSummary = computed(() => {
  void activityVersion.value
  void statusVersion.value
  void syncInProgress.value
  const contribution = weatherTileManager.deriveWeatherWorkflowContribution({
    syncInProgress: syncInProgress.value,
  })
  return mergeWorkflowSummaryWithWeather(workflowSummary.value, contribution)
})

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
  openLog: []
  openSettings: []
  openWorkflowEditor: []
}>()

function sourceUsable(source: TileSourceConfig): boolean {
  void apiKeys.value
  return isTileSourceUsable(source, (key) => settingsStore.isBasemapApiKeyAvailable(key))
}

const activeStyle = computed<BasemapStyle>(() => {
  const cfg = TILE_SOURCES.find((s) => s.id === props.tileSourceId)
  return cfg?.style ?? 'street'
})

const styleMeta: Record<BasemapStyle, { icon: typeof Map }> = {
  none: { icon: Globe },
  satellite: { icon: Satellite },
  street: { icon: Map },
  dark: { icon: Moon },
  terrain: { icon: Mountain },
}

const sourcesByStyle = computed(() => {
  const result: Array<{
    style: BasemapStyle
    label: string
    icon: typeof Map
    sources: TileSourceConfig[]
  }> = []
  for (const [style, sources] of TILE_SOURCES_BY_STYLE) {
    const standard = sources.filter((s) => s.isStandard)
    if (standard.some((s) => s.isStandard)) {
      result.push({
        style,
        label: basemapStyleLabel(style),
        icon: styleMeta[style]?.icon ?? Map,
        sources: standard,
      })
    }
  }
  return result
})

const currentTileConfig = computed(() => TILE_SOURCES.find((s) => s.id === props.tileSourceId))
const currentSourceLocked = computed(() => {
  const cfg = currentTileConfig.value
  if (!cfg) return false
  return tileSourceRequiresApiKey(cfg) && !sourceUsable(cfg)
})

watch(
  () => [props.tileSourceId, apiKeys.value] as const,
  () => {
    const cfg = TILE_SOURCES.find((s) => s.id === props.tileSourceId)
    if (cfg && !sourceUsable(cfg)) {
      emit('changeTileSource', getDefaultTileSource())
    }
  },
)

function selectSource(source: TileSourceConfig) {
  if (!sourceUsable(source)) {
    logStore.logOperation(
      'basemap-locked',
      `${source.label} 需要在设置中配置并启用 ${source.secretRef?.key ?? 'API Key'}`,
    )
    emit('openSettings')
    return
  }
  emit('changeTileSource', source.id)
}

function setInteractionMode(mode: 'move' | 'select' | 'measure') {
  uiStore.setInteractionMode(mode)
  const label = mode === 'move' ? '移动' : mode === 'select' ? '选择' : '测量'
  logStore.logOperation('mode-switch', `切换到${label}模式`)
}

function clearMeasure() {
  uiStore.clearMeasure()
  logStore.logOperation('measure-clear', '清除测量路径')
}

function handleScreenshot() {
  emit('openScreenshot')
  logStore.logOperation('screenshot', '打开截图导出')
}

function handleSettings() {
  emit('openSettings')
  logStore.logOperation('settings-open', SETTINGS_COPY.openLog)
}

function handleWorkflowEditor() {
  emit('openWorkflowEditor')
  logStore.logOperation('workflow-editor-open', WORKFLOW_COPY.openEditorLog)
}

function sourcePillLabel(source: TileSourceConfig): string {
  return basemapProviderShort(source.id, source.provider)
}
</script>

<template>
  <header class="mode-toolbar">
    <!-- 左侧：品牌 + 主工具 -->
    <div class="toolbar-left">
      <div class="brand">
        <div class="brand-mark" />
        <div class="brand-copy">
          <p class="brand-eyebrow">{{ BRAND.eyebrow }}</p>
          <h1 class="brand-name">{{ BRAND.shortName }}</h1>
        </div>
      </div>

      <div class="toolbar-divider" />

      <div class="toolbar-tools">
        <!-- 数据导入/导出 -->
        <DataImportMenu />

        <!-- 交互模式：移动/选择/测量 -->
        <div class="mode-group">
          <button
            class="mode-btn"
            :class="{ active: uiStore.interactionMode === 'move' }"
            type="button"
            title="移动模式（拖动平移地图）"
            aria-label="移动模式（拖动平移地图）"
            @click="setInteractionMode('move')"
          >
            <Move :size="14" />
          </button>
          <button
            class="mode-btn"
            :class="{ active: uiStore.interactionMode === 'select' }"
            type="button"
            title="点查模式（点击查询）"
            aria-label="点查模式（点击查询）"
            @click="setInteractionMode('select')"
          >
            <Crosshair :size="14" />
          </button>
          <button
            class="mode-btn"
            :class="{ active: uiStore.interactionMode === 'measure' }"
            type="button"
            title="测量模式（点击打点，双击完成）"
            aria-label="测量模式（点击打点，双击完成）"
            @click="setInteractionMode('measure')"
          >
            <Ruler :size="14" />
          </button>
          <button
            v-if="uiStore.interactionMode === 'measure' && uiStore.measureState.points.length > 0"
            class="mode-btn mode-btn--clear"
            type="button"
            title="清除测量路径"
            aria-label="清除测量路径"
            @click="clearMeasure"
          >
            <Trash2 :size="14" />
          </button>
        </div>

        <!-- 截图 -->
        <button class="tool-btn" type="button" title="导出截图" @click="handleScreenshot">
          <Camera :size="14" />
          <span class="tool-btn-label">截图</span>
        </button>

        <!-- 工作流编辑器 -->
        <button
          class="tool-btn"
          type="button"
          :title="WORKFLOW_COPY.entryTitle"
          @click="handleWorkflowEditor"
        >
          <Workflow :size="14" />
          <span class="tool-btn-label">{{ WORKFLOW_COPY.entry }}</span>
        </button>

        <!-- 设置 -->
        <button
          class="tool-btn"
          type="button"
          :title="SETTINGS_COPY.panelTitle"
          @click="handleSettings"
        >
          <Settings :size="14" />
          <span class="tool-btn-label">{{ SETTINGS_COPY.panelTitle }}</span>
        </button>

        <!-- 日志 -->
        <button class="tool-btn" type="button" title="系统日志" @click="emit('openLog')">
          <ScrollText :size="14" />
          <span class="tool-btn-label">日志</span>
          <span
            v-if="logStore.errorCount > 0"
            class="log-badge"
            :title="`${logStore.errorCount} 个错误`"
          >
            {{ logStore.errorCount >= 100 ? '99+' : logStore.errorCount }}
          </span>
        </button>
      </div>
    </div>

    <!-- 右侧：状态集群 -->
    <div class="toolbar-right">
      <div class="status-cluster">
        <!-- 来源选择器 -->
        <div v-if="activeStyle !== 'none'" class="source-pill">
          <button
            v-for="source in sourcesByStyle.find((g) => g.style === activeStyle)?.sources ?? []"
            :key="source.id"
            class="source-btn"
            :class="{
              active: tileSourceId === source.id,
              locked: !sourceUsable(source),
            }"
            :title="
              sourceUsable(source)
                ? `${source.provider} · ${source.label}`
                : `${source.label}（需配置 API Key，点击打开设置）`
            "
            @click="selectSource(source)"
          >
            {{ sourcePillLabel(source) }}
          </button>
        </div>

        <!-- 底图风格 -->
        <div class="style-group" role="tablist" aria-label="底图风格">
          <button
            v-for="group in sourcesByStyle"
            :key="group.style"
            class="style-btn"
            :class="{ active: activeStyle === group.style }"
            role="tab"
            :aria-selected="activeStyle === group.style"
            @click="selectSource(group.sources.find((s) => sourceUsable(s)) ?? group.sources[0])"
          >
            <component :is="group.icon" :size="12" class="style-icon" />
            <span>{{ group.label }}</span>
          </button>
        </div>

        <!-- 工作流状态 -->
        <WorkflowStatusButton
          :summary="mergedWorkflowSummary"
          @click="emit('openWorkflowStatus')"
        />

        <!-- 时间标签 -->
        <span class="chip time-chip">{{ hourLabel }}</span>

        <!-- 图层可用性 -->
        <span
          v-if="activeLayerCount > 0"
          class="chip"
          :class="`availability-${activeLayer.availabilityState}`"
          :title="activeLayer.availabilityDescription"
        >
          {{ activeLayer.availabilityLabel }}
        </span>

        <!-- 图层名 -->
        <span v-if="activeLayerCount > 0" class="chip chip--layer">
          {{ activeLayer.name }}
        </span>

        <!-- 图层计数 -->
        <span v-if="activeLayerCount > 0" class="chip chip--count"
          >{{ activeLayerCount }} 个图层</span
        >

        <!-- 2D/3D 视图切换 -->
        <button
          class="dim-toggle"
          :class="{ 'dim-toggle--3d': uiStore.viewMode === '3d' }"
          type="button"
          :title="uiStore.viewMode === '2d' ? '切换到3D地球视图' : '切换到2D平面视图'"
          @click="uiStore.toggleViewMode()"
        >
          <component :is="uiStore.viewMode === '2d' ? Map : Globe" :size="12" class="dim-icon" />
          <span>{{ uiStore.viewMode === '2d' ? '2D' : '3D' }}</span>
        </button>

        <!-- API Key 锁定警告 -->
        <span v-if="currentSourceLocked" class="chip chip--warning">{{
          BASEMAP_COPY.needApiKey
        }}</span>
      </div>
    </div>
  </header>
</template>

<style scoped>
.mode-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  background: rgba(8, 20, 36, 0.72);
  backdrop-filter: blur(var(--glass-blur));
  -webkit-backdrop-filter: blur(var(--glass-blur));
  box-shadow: var(--elevation-2);
  min-height: 48px;
}

/* 左侧 */
.toolbar-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: none;
}

.brand-mark {
  width: 32px;
  height: 32px;
  flex: none;
  border-radius: var(--radius-md);
  background:
    radial-gradient(circle at 30% 30%, rgba(255, 255, 255, 0.32), transparent 42%),
    linear-gradient(135deg, var(--accent), #2f7eff 58%, var(--accent-strong));
  box-shadow:
    0 0 0 1px rgba(255, 255, 255, 0.06),
    0 12px 30px rgba(47, 126, 255, 0.28);
}

.brand-copy {
  min-width: 0;
}

.brand-eyebrow {
  margin: 0 0 2px;
  color: var(--accent);
  font-size: var(--font-size-caption);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  line-height: 1;
}

.brand-name {
  margin: 0;
  font-size: clamp(0.9rem, 1.2vw, 1.1rem);
  font-weight: var(--font-weight-medium);
  color: var(--text-strong);
  white-space: nowrap;
}

.toolbar-divider {
  width: 1px;
  height: 24px;
  background: var(--border-subtle);
  flex: none;
}

.toolbar-tools {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

/* 统一工具按钮 */
.tool-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  height: 30px;
  padding: 0 var(--space-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-sunken);
  color: var(--text-secondary);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-medium);
  white-space: nowrap;
  transition:
    background-color var(--motion-fast) var(--ease-standard),
    border-color var(--motion-fast) var(--ease-standard),
    color var(--motion-fast) var(--ease-standard),
    box-shadow var(--motion-fast) var(--ease-standard);
}

.tool-btn:hover {
  background: var(--surface-hover);
  border-color: var(--border-strong);
  color: var(--accent);
  box-shadow: var(--elevation-1);
}

.tool-btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.tool-btn-label {
  font-size: var(--font-size-caption);
  line-height: 1;
}

/* 模式按钮组 */
.mode-group {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-sunken);
}

.mode-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition:
    background-color var(--motion-fast) var(--ease-standard),
    color var(--motion-fast) var(--ease-standard),
    border-color var(--motion-fast) var(--ease-standard);
}

.mode-btn:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.mode-btn.active {
  background: var(--accent-surface);
  border-color: var(--border-accent);
  color: var(--text-strong);
}

.mode-btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.mode-btn--clear {
  background: var(--danger-surface);
  border-color: var(--danger-border);
  color: var(--danger);
}

.mode-btn--clear:hover {
  background: var(--danger-surface);
  border-color: var(--danger);
  color: var(--danger);
}

/* 日志徽章 - 仅显示错误数，小字号，99+ 截断 */
.log-badge {
  position: absolute;
  top: -6px;
  right: -6px;
  min-width: 16px;
  height: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 4px;
  border-radius: var(--radius-pill);
  background: var(--danger);
  color: #fff;
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-bold);
  line-height: 1;
  font-variant-numeric: tabular-nums;
  box-shadow: 0 0 0 2px rgba(8, 20, 36, 0.9);
  border: 1px solid rgba(255, 255, 255, 0.15);
}

/* 右侧 */
.toolbar-right {
  display: flex;
  align-items: center;
  flex: none;
}

.status-cluster {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  justify-content: flex-end;
}

/* 底图风格组 */
.style-group {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  background: var(--surface-sunken);
}

.style-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  height: 26px;
  padding: 0 var(--space-3);
  border: none;
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-medium);
  white-space: nowrap;
  transition:
    background-color var(--motion-fast) var(--ease-standard),
    color var(--motion-fast) var(--ease-standard),
    box-shadow var(--motion-fast) var(--ease-standard);
}

.style-btn:hover {
  color: var(--text-primary);
  background: var(--surface-hover);
}

.style-btn.active {
  background: var(--accent-surface);
  color: var(--accent);
  box-shadow: inset 0 0 0 1px var(--border-accent);
}

.style-btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.style-icon {
  flex: none;
}

/* 来源选择器 */
.source-pill {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px 4px 2px 6px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  background: var(--surface-sunken);
}

.source-btn {
  min-width: 30px;
  height: 24px;
  border: none;
  border-radius: var(--radius-sm);
  padding: 0 var(--space-2);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-medium);
  letter-spacing: 0.01em;
  white-space: nowrap;
  transition:
    background-color var(--motion-fast) var(--ease-standard),
    color var(--motion-fast) var(--ease-standard);
}

.source-btn:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.source-btn.active {
  background: var(--accent-surface);
  color: var(--accent);
  box-shadow: inset 0 0 0 1px var(--border-accent);
}

.source-btn.locked {
  opacity: 0.42;
  color: var(--text-disabled);
  text-decoration: line-through;
}

.source-btn.locked:hover {
  background: var(--danger-surface);
  color: var(--danger);
}

.source-btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

/* 通用 Chip */
.chip {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 var(--space-3);
  border-radius: var(--radius-pill);
  background: var(--surface-sunken);
  border: 1px solid var(--border-subtle);
  color: var(--text-primary);
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-regular);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 120px;
}

.chip--layer {
  max-width: 140px;
}

.chip--count {
  background: var(--surface-2);
  border-color: var(--border-default);
  color: var(--text-secondary);
}

/* 2D/3D 切换按钮 */
.dim-toggle {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  height: 24px;
  padding: 0 var(--space-3);
  border-radius: var(--radius-pill);
  border: 1px solid var(--border-accent);
  background: var(--accent-surface);
  color: var(--accent);
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-medium);
  font-family: inherit;
  cursor: pointer;
  white-space: nowrap;
  transition:
    background-color var(--motion-fast) var(--ease-standard),
    border-color var(--motion-fast) var(--ease-standard),
    color var(--motion-fast) var(--ease-standard),
    box-shadow var(--motion-fast) var(--ease-standard);
}

.dim-toggle:hover {
  background: var(--accent);
  color: var(--surface-base);
  box-shadow: var(--elevation-1);
}

.dim-toggle:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.dim-toggle--3d {
  color: var(--accent-warm);
  border-color: rgba(255, 200, 120, 0.35);
  background: rgba(255, 200, 120, 0.12);
}

.dim-toggle--3d:hover {
  background: var(--accent-warm);
  color: var(--surface-base);
}

.dim-icon {
  flex: none;
  line-height: 1;
}

.chip--warning {
  color: var(--warning);
  border-color: var(--warning-border);
  background: var(--warning-surface);
}

.time-chip {
  min-width: 56px;
  justify-content: center;
  color: var(--text-strong);
  font-weight: var(--font-weight-medium);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.04em;
}

/* 可用性 */
.availability-ready {
  color: var(--success);
  border-color: var(--success-border);
  background: var(--success-surface);
}

.availability-partial {
  color: var(--warning);
  border-color: var(--warning-border);
  background: var(--warning-surface);
}

.availability-empty {
  color: var(--text-faint);
  border-color: var(--border-subtle);
  background: var(--surface-sunken);
}

/* 响应式 */
@media (max-width: 1024px) {
  .mode-toolbar {
    flex-direction: column;
    align-items: stretch;
    gap: var(--space-3);
  }
  .toolbar-left {
    flex-wrap: wrap;
  }
  .toolbar-right {
    width: 100%;
  }
  .status-cluster {
    justify-content: flex-start;
  }
}

@media (prefers-reduced-motion: reduce) {
  .tool-btn,
  .mode-btn,
  .style-btn,
  .source-btn,
  .dim-toggle {
    transition: none;
  }
}
</style>
