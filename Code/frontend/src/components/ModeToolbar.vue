<script setup lang="ts">
import { computed, onMounted, toRef } from 'vue'
import { Settings, ScrollText, Camera, Workflow, Map, Globe } from './ui/icons'
import AppButton from './ui/AppButton.vue'
import Chip from './ui/Chip.vue'
import SegmentedControl from './ui/SegmentedControl.vue'
import Tooltip from './ui/Tooltip.vue'

import {
  TILE_SOURCES,
  isTileSourceUsable,
  tileSourceRequiresApiKey,
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
import { useBreakpoint } from '../composables/useBreakpoint'
import { mergeWorkflowSummaryWithWeather } from '../utils/workflow-status-merge'
import { BASEMAP_COPY, WORKFLOW_COPY, SETTINGS_COPY } from '../ui-copy'
import WorkflowStatusButton from './workflow/WorkflowStatusButton.vue'
import DataImportMenu from '../data-manager/ui/DataImportMenu.vue'
import MapToolMenu from './toolbar/MapToolMenu.vue'
import BasemapMenu from './toolbar/BasemapMenu.vue'
import BrandMark from './brand/BrandMark.vue'

const uiStore = useUiStore()
const logStore = useLogStore()
const settingsStore = useSettingsStore()
const authStore = useAuthStore()
const brand = computed(() => authStore.resolvedBrand)
const weatherTileManager = useWeatherTileManager()
const weatherSyncStatus = useWeatherSyncStatusStore()
const { greaterOrEqual } = useBreakpoint()
/**
 * 按钮文字标签只在宽屏（≥1280px）显示。
 * 2026-09-30：原为「仅移动端隐藏」（!isMobile），在 1024~1280 这段单行排布里
 * 左右两簇都挤不下，文字会互相压住；改为窄屏自动收成纯图标（title/tooltip 仍在）。
 */
const showToolLabels = computed(() => greaterOrEqual('xl'))
const { workflowSummary } = useWorkflowRun()
const activityVersion = toRef(weatherTileManager, 'activityVersion')
const statusVersion = toRef(weatherTileManager, 'statusVersion')
const apiKeys = toRef(settingsStore, 'apiKeys')
const syncInProgress = toRef(weatherSyncStatus, 'syncInProgress')

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

const currentSourceLocked = computed(() => {
  const cfg = TILE_SOURCES.find((s) => s.id === props.tileSourceId)
  if (!cfg) return false
  return tileSourceRequiresApiKey(cfg) && !sourceUsable(cfg)
})

function onViewModeChange(value: string | number) {
  const next = value === '3d' ? '3d' : '2d'
  if (next !== uiStore.viewMode) {
    uiStore.setViewMode(next)
    logStore.logOperation('view-mode-switch', `切换到${next.toUpperCase()}视图`)
  }
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

        <!-- 地图工具：移动 / 点查 / 测量 / 绘制 收敛成一个下拉 -->
        <MapToolMenu />

        <!-- 底图：来源 + 风格 收敛成一个下拉 -->
        <BasemapMenu
          :tile-source-id="tileSourceId"
          @change-tile-source="emit('changeTileSource', $event)"
          @open-settings="emit('openSettings')"
        />

        <!-- 截图 -->
        <Tooltip text="截图" position="bottom">
          <AppButton size="sm" variant="secondary" aria-label="导出截图" @click="handleScreenshot">
            <template #icon><Camera :size="14" /></template>
            <span v-if="showToolLabels">截图</span>
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
            <span v-if="showToolLabels">{{ WORKFLOW_COPY.entry }}</span>
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
            <span v-if="showToolLabels">{{ SETTINGS_COPY.panelTitle }}</span>
          </AppButton>
        </Tooltip>

        <!-- 日志 -->
        <div class="log-btn-wrap">
          <Tooltip text="日志" position="bottom">
            <AppButton size="sm" variant="secondary" aria-label="系统日志" @click="emit('openLog')">
              <template #icon><ScrollText :size="14" /></template>
              <span v-if="showToolLabels">日志</span>
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
        <!-- 工作流运行状态（原「工作流」胶囊，改名「运行」避免与左侧编辑器按钮重名） -->
        <WorkflowStatusButton
          :summary="mergedWorkflowSummary"
          @click="emit('openWorkflowStatus')"
        />

        <!-- 2D/3D 视图切换（分段控件） -->
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
