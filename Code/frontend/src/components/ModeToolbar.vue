<script setup lang="ts">
import { computed, onMounted, toRef, watch } from 'vue'
import {
  Settings,
  ScrollText,
  Camera,
  Workflow,
  Move,
  Crosshair,
  Ruler,
  Pen,
  Trash2,
  Satellite,
  Map,
  Moon,
  Mountain,
  Globe,
} from './ui/icons'
import AppButton from './ui/AppButton.vue'
import IconButton from './ui/IconButton.vue'
import Chip from './ui/Chip.vue'
import SegmentedControl from './ui/SegmentedControl.vue'
import Tooltip from './ui/Tooltip.vue'

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
import { useWorkflowRun } from '../stores/layers/selectors'
import { useUiStore } from '../stores/ui'
import { useLogStore } from '../stores/log'
import { useSettingsStore } from '../stores/settings'
import { useAuthStore } from '../stores/auth'
import { useWeatherTileManager } from '../stores/weather-tile-manager'
import { useWeatherSyncStatusStore } from '../stores/weather-sync-status'
import { useDrawSessionTransition } from '../composables/useDrawSessionTransition'
import { useBreakpoint } from '../composables/useBreakpoint'
import { mergeWorkflowSummaryWithWeather } from '../utils/workflow-status-merge'
import {
  BASEMAP_COPY,
  basemapStyleLabel,
  basemapProviderShort,
  WORKFLOW_COPY,
  SETTINGS_COPY,
} from '../ui-copy'
import WorkflowStatusButton from './workflow/WorkflowStatusButton.vue'
import DataImportMenu from '../data-manager/ui/DataImportMenu.vue'
import BrandMark from './brand/BrandMark.vue'

const uiStore = useUiStore()
const logStore = useLogStore()
const settingsStore = useSettingsStore()
const authStore = useAuthStore()
const brand = computed(() => authStore.resolvedBrand)
const weatherTileManager = useWeatherTileManager()
const weatherSyncStatus = useWeatherSyncStatusStore()
const { isMobile } = useBreakpoint()
const { workflowSummary } = useWorkflowRun()
const activityVersion = toRef(weatherTileManager, 'activityVersion')
const statusVersion = toRef(weatherTileManager, 'statusVersion')
const apiKeys = toRef(settingsStore, 'apiKeys')
const syncInProgress = toRef(weatherSyncStatus, 'syncInProgress')
const { requestInteractionMode } = useDrawSessionTransition()

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
  hourLabel: string
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

const styleOptions = computed(() =>
  sourcesByStyle.value.map((g) => ({ value: g.style, label: g.label, icon: g.icon })),
)

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

function onStyleChange(style: BasemapStyle) {
  const group = sourcesByStyle.value.find((g) => g.style === style)
  if (group) {
    selectSource(group.sources.find((s) => sourceUsable(s)) ?? group.sources[0])
  }
}

function onViewModeChange(value: string | number) {
  const next = value === '3d' ? '3d' : '2d'
  if (next !== uiStore.viewMode) {
    uiStore.setViewMode(next)
    logStore.logOperation('view-mode-switch', `切换到${next.toUpperCase()}视图`)
  }
}

async function setInteractionMode(mode: 'move' | 'select' | 'measure' | 'draw') {
  const ok = await requestInteractionMode(mode)
  if (!ok) return
  const label =
    mode === 'move' ? '移动' : mode === 'select' ? '选择' : mode === 'measure' ? '测量' : '绘制'
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
        <img
          v-if="brand.logoUrl"
          class="brand-logo-img"
          :src="brand.logoUrl"
          :alt="brand.abbr"
          width="30"
          height="30"
        />
        <BrandMark v-else :size="30" />
        <div class="brand-copy">
          <p class="brand-eyebrow">{{ brand.eyebrow }}</p>
          <h1 class="brand-name">{{ brand.shortName }}</h1>
        </div>
      </div>

      <div class="toolbar-divider" />

      <div class="toolbar-tools">
        <!-- 数据导入/导出 -->
        <DataImportMenu />

        <!-- 交互模式：移动/选择/测量 -->
        <div class="mode-group">
          <Tooltip text="移动" position="bottom">
            <IconButton
              size="sm"
              :active="uiStore.interactionMode === 'move'"
              label="移动模式（拖动平移地图）"
              @click="setInteractionMode('move')"
            >
              <template #icon><Move :size="14" /></template>
            </IconButton>
          </Tooltip>
          <Tooltip text="点查" position="bottom">
            <IconButton
              size="sm"
              :active="uiStore.interactionMode === 'select'"
              label="点查模式（点击查询）"
              @click="setInteractionMode('select')"
            >
              <template #icon><Crosshair :size="14" /></template>
            </IconButton>
          </Tooltip>
          <Tooltip text="测量" position="bottom">
            <IconButton
              size="sm"
              :active="uiStore.interactionMode === 'measure'"
              label="测量模式（点击打点，双击完成）"
              @click="setInteractionMode('measure')"
            >
              <template #icon><Ruler :size="14" /></template>
            </IconButton>
          </Tooltip>
          <Tooltip text="绘制" position="bottom">
            <IconButton
              size="sm"
              :active="uiStore.interactionMode === 'draw'"
              label="绘制模式（点击添加顶点，双击完成多边形）"
              @click="setInteractionMode('draw')"
            >
              <template #icon><Pen :size="14" /></template>
            </IconButton>
          </Tooltip>
          <Tooltip
            v-if="uiStore.interactionMode === 'measure' && uiStore.measureState.points.length > 0"
            text="清除测量"
            position="bottom"
          >
            <IconButton size="sm" variant="danger" label="清除测量路径" @click="clearMeasure">
              <template #icon><Trash2 :size="14" /></template>
            </IconButton>
          </Tooltip>
        </div>

        <!-- 截图 -->
        <Tooltip text="截图" position="bottom">
          <AppButton size="sm" variant="secondary" aria-label="导出截图" @click="handleScreenshot">
            <template #icon><Camera :size="14" /></template>
            <span v-if="!isMobile">截图</span>
          </AppButton>
        </Tooltip>

        <!-- 工作流编辑器 -->
        <Tooltip :text="WORKFLOW_COPY.entry" position="bottom">
          <AppButton
            size="sm"
            variant="secondary"
            :aria-label="WORKFLOW_COPY.entryTitle"
            @click="handleWorkflowEditor"
          >
            <template #icon><Workflow :size="14" /></template>
            <span v-if="!isMobile">{{ WORKFLOW_COPY.entry }}</span>
          </AppButton>
        </Tooltip>

        <!-- 设置 -->
        <Tooltip :text="SETTINGS_COPY.panelTitle" position="bottom">
          <AppButton
            size="sm"
            variant="secondary"
            :aria-label="SETTINGS_COPY.panelTitle"
            @click="handleSettings"
          >
            <template #icon><Settings :size="14" /></template>
            <span v-if="!isMobile">{{ SETTINGS_COPY.panelTitle }}</span>
          </AppButton>
        </Tooltip>

        <!-- 日志 -->
        <div class="log-btn-wrap">
          <Tooltip text="日志" position="bottom">
            <AppButton size="sm" variant="secondary" aria-label="系统日志" @click="emit('openLog')">
              <template #icon><ScrollText :size="14" /></template>
              <span v-if="!isMobile">日志</span>
            </AppButton>
          </Tooltip>
          <span
            v-if="logStore.errorCount > 0"
            class="log-badge"
            :title="`${logStore.errorCount} 个错误`"
          >
            {{ logStore.errorCount >= 100 ? '99+' : logStore.errorCount }}
          </span>
        </div>
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
        <SegmentedControl
          :model-value="activeStyle"
          :options="styleOptions"
          size="xs"
          @change="(val) => onStyleChange(val as BasemapStyle)"
        />

        <!-- 工作流状态 -->
        <WorkflowStatusButton
          :summary="mergedWorkflowSummary"
          @click="emit('openWorkflowStatus')"
        />

        <!-- 时间标签 -->
        <Chip class="time-chip">{{ hourLabel }}</Chip>

        <!-- 2D/3D 视图切换（分段控件，与底图风格选择器同一交互语言） -->
        <SegmentedControl
          class="dim-seg"
          :model-value="uiStore.viewMode"
          :options="[
            { value: '2d', label: '2D', icon: Map },
            { value: '3d', label: '3D', icon: Globe },
          ]"
          size="xs"
          @change="onViewModeChange"
        />

        <!-- API Key 锁定警告 -->
        <Chip v-if="currentSourceLocked" variant="warning">
          {{ BASEMAP_COPY.needApiKey }}
        </Chip>
      </div>
    </div>
  </header>
</template>

<style scoped src="./ModeToolbar.styles.css" />
