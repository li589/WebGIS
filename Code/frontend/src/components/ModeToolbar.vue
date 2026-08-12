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
} from './ui/icons'
import AppButton from './ui/AppButton.vue'
import IconButton from './ui/IconButton.vue'
import Chip from './ui/Chip.vue'
import SegmentedControl from './ui/SegmentedControl.vue'

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
import { useWorkflowRun } from '../stores/layers/selectors'
import { useUiStore } from '../stores/ui'
import { useLogStore } from '../stores/log'
import { useSettingsStore } from '../stores/settings'
import { useAuthStore } from '../stores/auth'
import { useWeatherTileManager } from '../stores/weather-tile-manager'
import { useWeatherSyncStatusStore } from '../stores/weather-sync-status'
import { useBreakpoint } from '../composables/useBreakpoint'
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

const uiStore = useUiStore()
const logStore = useLogStore()
const settingsStore = useSettingsStore()
const authStore = useAuthStore()
const weatherTileManager = useWeatherTileManager()
const weatherSyncStatus = useWeatherSyncStatusStore()
const { isMobile } = useBreakpoint()
const { workflowSummary } = useWorkflowRun()
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

const styleOptions = computed(() =>
  sourcesByStyle.value.map((g) => ({ value: g.style, label: g.label, icon: g.icon })),
)

const currentTileConfig = computed(() => TILE_SOURCES.find((s) => s.id === props.tileSourceId))
const currentSourceLocked = computed(() => {
  const cfg = currentTileConfig.value
  if (!cfg) return false
  return tileSourceRequiresApiKey(cfg) && !sourceUsable(cfg)
})

const availabilityVariant = computed<'success' | 'warning' | 'muted'>(() => {
  const state = props.activeLayer.availabilityState
  if (state === 'ready') return 'success'
  if (state === 'partial') return 'warning'
  return 'muted'
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
          <IconButton
            size="sm"
            :active="uiStore.interactionMode === 'move'"
            label="移动模式（拖动平移地图）"
            @click="setInteractionMode('move')"
          >
            <template #icon><Move :size="14" /></template>
          </IconButton>
          <IconButton
            size="sm"
            :active="uiStore.interactionMode === 'select'"
            label="点查模式（点击查询）"
            @click="setInteractionMode('select')"
          >
            <template #icon><Crosshair :size="14" /></template>
          </IconButton>
          <IconButton
            size="sm"
            :active="uiStore.interactionMode === 'measure'"
            label="测量模式（点击打点，双击完成）"
            @click="setInteractionMode('measure')"
          >
            <template #icon><Ruler :size="14" /></template>
          </IconButton>
          <IconButton
            v-if="uiStore.interactionMode === 'measure' && uiStore.measureState.points.length > 0"
            size="sm"
            variant="danger"
            label="清除测量路径"
            @click="clearMeasure"
          >
            <template #icon><Trash2 :size="14" /></template>
          </IconButton>
        </div>

        <!-- 截图 -->
        <AppButton size="sm" variant="secondary" aria-label="导出截图" @click="handleScreenshot">
          <template #icon><Camera :size="14" /></template>
          <span v-if="!isMobile">截图</span>
        </AppButton>

        <!-- 工作流编辑器 -->
        <AppButton
          size="sm"
          variant="secondary"
          :aria-label="WORKFLOW_COPY.entryTitle"
          @click="handleWorkflowEditor"
        >
          <template #icon><Workflow :size="14" /></template>
          <span v-if="!isMobile">{{ WORKFLOW_COPY.entry }}</span>
        </AppButton>

        <!-- 设置 -->
        <AppButton
          size="sm"
          variant="secondary"
          :aria-label="SETTINGS_COPY.panelTitle"
          @click="handleSettings"
        >
          <template #icon><Settings :size="14" /></template>
          <span v-if="!isMobile">{{ SETTINGS_COPY.panelTitle }}</span>
        </AppButton>

        <!-- 日志 -->
        <div class="log-btn-wrap">
          <AppButton size="sm" variant="secondary" aria-label="系统日志" @click="emit('openLog')">
            <template #icon><ScrollText :size="14" /></template>
            <span v-if="!isMobile">日志</span>
          </AppButton>
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

        <!-- 图层可用性 -->
        <Chip
          v-if="activeLayerCount > 0"
          :variant="availabilityVariant"
          :title="activeLayer.availabilityDescription"
        >
          {{ activeLayer.availabilityLabel }}
        </Chip>

        <!-- 图层名 -->
        <Chip v-if="activeLayerCount > 0" class="chip--layer">
          {{ activeLayer.name }}
        </Chip>

        <!-- 图层计数 -->
        <Chip v-if="activeLayerCount > 0" class="chip--count"> {{ activeLayerCount }} 个图层 </Chip>

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
        <Chip v-if="currentSourceLocked" variant="warning">
          {{ BASEMAP_COPY.needApiKey }}
        </Chip>
      </div>
    </div>
  </header>
</template>

<style scoped src="./ModeToolbar.styles.css" />
