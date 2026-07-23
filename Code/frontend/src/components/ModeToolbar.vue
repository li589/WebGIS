<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { storeToRefs } from 'pinia'

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
import { useWeatherTileManager } from '../stores/weather-tile-manager'
import { useWeatherSyncStatusStore } from '../stores/weather-sync-status'
import { mergeWorkflowSummaryWithWeather } from '../utils/workflow-status-merge'
import WorkflowStatusButton from './workflow/WorkflowStatusButton.vue'
import DataImportMenu from './toolbar/DataImportMenu.vue'

const layersStore = useLayersStore()
const uiStore = useUiStore()
const logStore = useLogStore()
const settingsStore = useSettingsStore()
const weatherTileManager = useWeatherTileManager()
const weatherSyncStatus = useWeatherSyncStatusStore()
const { workflowSummary } = storeToRefs(layersStore)
const { activityVersion, statusVersion } = storeToRefs(weatherTileManager)
const { apiKeys } = storeToRefs(settingsStore)
const { syncInProgress } = storeToRefs(weatherSyncStatus)

onMounted(() => {
  if (apiKeys.value.length === 0) {
    void settingsStore.loadApiKeys().catch(() => {
      /* toolbar still works with free basemaps */
    })
  }
  void weatherSyncStatus.refreshOverview()
})

/** 合并业务 job + 天气瓦片合成态（含 data-empty → 失败/等待重试） */
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

const sourcesByStyle = computed(() => {
  const result: Array<{
    style: BasemapStyle
    label: string
    icon: string
    sources: TileSourceConfig[]
  }> = []
  const styleMeta: Record<BasemapStyle, { label: string; icon: string }> = {
    none: { label: '空图', icon: '◇' },
    satellite: { label: '影像', icon: '◆' },
    street: { label: '街道', icon: '▦' },
    dark: { label: '深色', icon: '◑' },
    terrain: { label: '地形', icon: '⛰' },
  }

  for (const [style, sources] of TILE_SOURCES_BY_STYLE) {
    const standard = sources.filter((s) => s.isStandard)
    // Keep key-locked sources visible but marked unusable so users know to configure keys
    if (standard.some((s) => s.isStandard)) {
      result.push({
        style,
        label: styleMeta[style]?.label ?? style,
        icon: styleMeta[style]?.icon ?? '▦',
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
  logStore.logOperation('settings-open', '打开系统设置')
}

function handleWorkflowEditor() {
  emit('openWorkflowEditor')
  logStore.logOperation('workflow-editor-open', '打开流配置编辑器')
}
</script>

<template>
  <header class="toolbar">
    <!-- 左侧：主工具栏 -->
    <div class="toolbar-primary">
      <div class="brand">
        <div class="brand-mark"></div>
        <div class="brand-copy">
          <p class="eyebrow">GeoFlow</p>
          <h1>综合地理态势</h1>
        </div>
      </div>

      <div class="primary-tools">
        <!-- 数据导入 -->
        <DataImportMenu />

        <!-- 移动 / 选择 模式 -->
        <div class="mode-group">
          <button
            class="mode-btn"
            :class="{ active: uiStore.interactionMode === 'move' }"
            type="button"
            title="移动模式（拖动平移地图）"
            @click="setInteractionMode('move')"
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
              <polyline points="5 9 2 12 5 15" />
              <polyline points="9 5 12 2 15 5" />
              <polyline points="15 19 12 22 9 19" />
              <polyline points="19 9 22 12 19 15" />
              <line x1="2" y1="12" x2="22" y2="12" />
              <line x1="12" y1="2" x2="12" y2="22" />
            </svg>
          </button>
          <button
            class="mode-btn"
            :class="{ active: uiStore.interactionMode === 'select' }"
            type="button"
            title="选择模式（点击查询点信息）"
            @click="setInteractionMode('select')"
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
              <path d="M3 3l7.07 16.97 2.51-7.39 7.39-2.51L3 3z" />
            </svg>
          </button>
          <button
            class="mode-btn"
            :class="{ active: uiStore.interactionMode === 'measure' }"
            type="button"
            title="测量模式（点击打点，双击完成，右键撤销）"
            @click="setInteractionMode('measure')"
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
              <path d="M21 3L3 21" />
              <circle cx="21" cy="3" r="2" fill="currentColor" />
              <circle cx="3" cy="21" r="2" fill="currentColor" />
            </svg>
          </button>
          <button
            v-if="uiStore.interactionMode === 'measure' && uiStore.measureState.points.length > 0"
            class="mode-btn clear-btn"
            type="button"
            title="清除测量路径"
            @click="clearMeasure"
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
              <path d="M3 6h18" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
              <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            </svg>
          </button>
        </div>

        <!-- 截图 -->
        <button class="tool-btn" type="button" title="导出截图" @click="handleScreenshot">
          <span class="btn-icon" aria-hidden="true">◫</span>
          <span class="btn-label">截图</span>
        </button>

        <!-- 流配置 -->
        <button
          class="tool-btn"
          type="button"
          title="工作流配置编辑器（含定时器）"
          @click="handleWorkflowEditor"
        >
          <span class="btn-icon" aria-hidden="true">⬡</span>
          <span class="btn-label">流配置</span>
        </button>

        <!-- 设置 -->
        <button class="tool-btn" type="button" title="系统设置" @click="handleSettings">
          <span class="btn-icon" aria-hidden="true">⚙</span>
          <span class="btn-label">设置</span>
        </button>

        <!-- 日志 -->
        <button class="tool-btn" type="button" title="系统日志" @click="emit('openLog')">
          <span class="btn-icon" aria-hidden="true">📋</span>
          <span class="btn-label">日志</span>
          <span v-if="logStore.entries.length > 0" class="log-badge">{{
            logStore.entries.length
          }}</span>
        </button>
      </div>
    </div>

    <!-- 右侧：保留元素 -->
    <div class="toolbar-main">
      <!-- Row 1: style tabs + workflow status + availability + 2D -->
      <div class="toolbar-strip">
        <div class="style-tabs" role="tablist" aria-label="底图风格">
          <button
            v-for="group in sourcesByStyle"
            :key="group.style"
            class="style-tab"
            :class="{ active: activeStyle === group.style }"
            role="tab"
            :aria-selected="activeStyle === group.style"
            @click="selectSource(group.sources.find((s) => sourceUsable(s)) ?? group.sources[0])"
          >
            <span class="style-icon" aria-hidden="true">{{ group.icon }}</span>
            <span>{{ group.label }}</span>
          </button>
        </div>

        <!-- Workflow status -->
        <WorkflowStatusButton
          :summary="mergedWorkflowSummary"
          @click="emit('openWorkflowStatus')"
        />

        <!-- Availability status chip -->
        <div
          v-if="activeLayerCount > 0"
          class="status-chip"
          :class="`availability-${activeLayer.availabilityState}`"
          :title="activeLayer.availabilityDescription"
        >
          {{ activeLayer.availabilityLabel }}
        </div>

        <!-- 2D/3D dimension indicator -->
        <div class="status-chip dim-mode">2D</div>
      </div>

      <!-- Row 2: source selector + time + layer info -->
      <div class="toolbar-strip">
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
                : `${source.label}（需配置 API Key：${source.secretRef?.key ?? ''}，点击打开设置）`
            "
            @click="selectSource(source)"
          >
            {{ source.provider[0] }}
          </button>
        </div>

        <div class="time-chip">{{ hourLabel }}</div>

        <div v-if="activeLayerCount > 0" class="status-chip">{{ activeLayer.name }}</div>
        <div v-else class="status-chip">无图层</div>
        <div v-if="activeLayerCount > 0" class="status-chip">{{ activeLayerCount }} 个图层</div>
        <div v-if="currentSourceLocked" class="status-chip warning">需配置底图 Key</div>
        <div v-else-if="currentTileConfig?.needsBackendTransform" class="status-chip warning">
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
    linear-gradient(180deg, rgba(8, 17, 31, 0.52), rgba(7, 15, 28, 0.44)), rgba(8, 18, 33, 0.42);
  backdrop-filter: blur(18px);
  box-shadow:
    0 18px 42px rgba(1, 8, 16, 0.22),
    inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

/* ── 左侧主工具栏 ─────────────────────────────────────────────────── */
.toolbar-primary {
  display: flex;
  align-items: center;
  gap: 0.62rem;
  min-width: 0;
}

.brand {
  display: flex;
  align-items: center;
  gap: 0.58rem;
  min-width: 0;
  flex: none;
}

.brand-mark {
  width: 1.9rem;
  height: 1.9rem;
  flex: none;
  border-radius: 0.72rem;
  background:
    radial-gradient(circle at 30% 30%, rgba(255, 255, 255, 0.32), transparent 42%),
    linear-gradient(135deg, #5ad5ff, #2f7eff 58%, #7d7dff);
  box-shadow:
    0 0 0 1px rgba(255, 255, 255, 0.06),
    0 12px 30px rgba(47, 126, 255, 0.28);
}

.brand-copy {
  min-width: 0;
}

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
  white-space: nowrap;
}

.primary-tools {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  padding-left: 0.62rem;
  border-left: 1px solid rgba(136, 192, 255, 0.1);
}

/* 统一工具按钮样式 */
.tool-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 0.24rem;
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: 0.5rem;
  padding: 0.3rem 0.46rem;
  background: rgba(4, 12, 23, 0.6);
  color: #9fb6cc;
  cursor: pointer;
  font: inherit;
  font-size: 0.62rem;
  font-weight: 500;
  white-space: nowrap;
  transition:
    border-color 0.18s ease,
    color 0.18s ease,
    background 0.18s ease;
}

.tool-btn:hover {
  border-color: rgba(90, 213, 255, 0.3);
  color: #5ad5ff;
  background: rgba(10, 132, 255, 0.12);
}

.tool-btn.active {
  border-color: rgba(90, 213, 255, 0.4);
  color: #5ad5ff;
  background: rgba(10, 132, 255, 0.2);
  box-shadow: inset 0 0 0 1px rgba(90, 213, 255, 0.16);
}

.btn-icon {
  font-size: 0.72rem;
  opacity: 0.9;
}
.btn-label {
  font-size: 0.6rem;
}

.log-badge {
  position: absolute;
  top: -0.36rem;
  right: -0.36rem;
  min-width: 0.82rem;
  height: 0.82rem;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 0.18rem;
  border-radius: 999px;
  background: rgba(10, 132, 255, 0.8);
  color: #fff;
  font-size: 0.48rem;
  font-weight: 700;
}

/* 移动 / 选择 模式按钮组 */
.mode-group {
  display: inline-flex;
  gap: 0.12rem;
  padding: 0.16rem;
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: 0.5rem;
  background: rgba(4, 12, 23, 0.6);
}

.mode-btn {
  width: 1.56rem;
  height: 1.56rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid transparent;
  border-radius: 0.36rem;
  background: transparent;
  color: #6e8ba0;
  cursor: pointer;
  transition:
    background 0.16s ease,
    color 0.16s ease,
    border-color 0.16s ease;
}

.mode-btn:hover {
  background: rgba(136, 192, 255, 0.1);
  color: #c8dff0;
}

.mode-btn.active {
  background: rgba(60, 120, 200, 0.32);
  border-color: rgba(136, 192, 255, 0.38);
  color: #f4fbff;
}

/* 清除测量路径按钮（仅在 measure 模式且有路径时显示） */
.mode-btn.clear-btn {
  background: rgba(180, 60, 60, 0.18);
  border-color: rgba(255, 120, 120, 0.32);
  color: #ff9a9a;
}

.mode-btn.clear-btn:hover {
  background: rgba(220, 80, 80, 0.28);
  color: #ffb0b0;
}

/* ── 右侧保留区 ───────────────────────────────────────────────────── */
.toolbar-main {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.38rem;
  flex: none;
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
  transition:
    background-color 0.2s ease,
    color 0.2s ease,
    transform 0.2s ease;
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
  transition:
    background 0.16s ease,
    color 0.16s ease,
    transform 0.16s ease;
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

.source-btn.locked {
  opacity: 0.42;
  color: #8a6a6a;
  text-decoration: line-through;
}

.source-btn.locked:hover {
  background: rgba(255, 140, 100, 0.12);
  color: #ffb090;
}

/* Status chips */
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

.availability-ready {
  color: #9ff8cf;
  border-color: rgba(114, 255, 207, 0.18);
  background: rgba(114, 255, 207, 0.1);
}
.availability-partial {
  color: #ffd38a;
  border-color: rgba(255, 196, 120, 0.18);
  background: rgba(255, 196, 120, 0.08);
}
.availability-empty {
  color: #d7c1ff;
  border-color: rgba(187, 137, 255, 0.2);
  background: rgba(187, 137, 255, 0.1);
}
.status-chip.warning {
  color: #ffc878;
  border-color: rgba(255, 180, 80, 0.2);
  background: rgba(255, 160, 60, 0.1);
}
.status-chip.dim-mode {
  color: #5ad5ff;
  border-color: rgba(90, 213, 255, 0.24);
  background: rgba(10, 132, 255, 0.12);
  font-weight: 600;
}

/* Time chip */
.time-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 3.2rem;
  padding: 0.24rem 0.56rem;
  border-radius: 999px;
  background: rgba(4, 12, 23, 0.42);
  border: 1px solid rgba(136, 192, 255, 0.12);
  color: #eff8ff;
  font-size: 0.66rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.04em;
  text-align: center;
  white-space: nowrap;
}

@media (max-width: 1100px) {
  .toolbar {
    flex-direction: column;
    align-items: stretch;
    gap: 0.48rem;
  }

  .toolbar-primary {
    flex-wrap: wrap;
    gap: 0.42rem;
  }
  .toolbar-main {
    align-items: stretch;
  }
  .toolbar-strip {
    justify-content: flex-start;
  }
  .style-tabs {
    align-self: flex-start;
    flex-wrap: wrap;
  }
}
</style>
