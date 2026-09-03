<script setup lang="ts">
import { LAYERS_COPY, ONLINE_PLAN_COPY } from '../../ui-copy'
import { productTagDescription } from '../../utils/workflow-expected-outputs'
import type { DataStatusBadge } from '../../utils/layer-data-status'
import { CircleDot, Circle, X, Menu } from '../ui/icons'
import type { ActiveLayerDisplay, ActiveRunLayerGroup } from '../../stores/layers/types'
import type { ActiveTocRow } from './useSidebarDragReorder'
import type { ActiveLayerDisplayLike } from './useSidebarSymbology'

const props = defineProps<{
  activeLayersDisplay: ActiveLayerDisplay[]
  activeTocRows: ActiveTocRow[]
  selectedInstanceId: string | null
  dragOverInstanceId: string | null
  dragOverGroupId: string | null
  runGroupOf: (groupId: string) => ActiveRunLayerGroup | null
  groupStatusLabel: (groupId: string) => string
  hasColorSymbology: (layer: ActiveLayerDisplayLike) => boolean
  getColorRampStyle: (layer: ActiveLayerDisplayLike) => Record<string, string>
  getSymbologyUnit: (layer: ActiveLayerDisplayLike) => string
  getSymbologyVmin: (layer: ActiveLayerDisplayLike) => string
  getSymbologyVmax: (layer: ActiveLayerDisplayLike) => string
  availabilityClass: (state: string) => string
  getCategoryName: (categoryId: string) => string
  supportsOnlineTemporal: (catalogId: string) => boolean
  getSourceRouteBadge?: (catalogId: string) => { key: string; label: string; title: string } | null
  cycleSourceRoute?: (catalogId: string) => void
  /**
   * 统一数据状态徽标（2026-08-25 UX 简化）：归并 availability/lifecycle/job
   * 三源为单枚五态徽标（运行中/排队中/异常/完成/旧数据）+ 详情。
   * null = 不渲染。
   */
  getUnifiedDataStatus: (layer: ActiveLayerDisplay) => DataStatusBadge | null
  /** P2：在线计划会话待决策（只读，不改 job status） */
  isOnlinePlanPending?: (catalogId: string) => boolean
  openOnlinePlan?: () => void
}>()

function isComputingRunMember(layer: ActiveLayerDisplay): boolean {
  if (!layer.runGroupId) return false
  return props.runGroupOf(layer.runGroupId)?.status === 'computing'
}

const emit = defineEmits<{
  selectItem: [instanceId: string]
  zoomToItem: [instanceId: string]
  toggleVisibility: [instanceId: string, event: MouseEvent]
  removeItem: [instanceId: string, event: MouseEvent]
  openJobReport: [instanceId: string]
  showAllLayers: []
  hideAllLayers: []
  removeAllLayers: []
  openLibrary: []
  onDragStart: [instanceId: string]
  onGroupDragStart: [groupId: string, event: DragEvent]
  onDragOver: [instanceId: string, event: DragEvent]
  onGroupDragOver: [groupId: string, event: DragEvent]
  onDrop: [targetInstanceId: string]
  onGroupDrop: [groupId: string]
  onDragEnd: []
  onLayerContextMenu: [instanceId: string, event: MouseEvent]
  onGroupContextMenu: [groupId: string, event: MouseEvent]
}>()
</script>

<template>
  <!-- ── ACTIVE STATE ───────────────────────────────────────────────────── -->
  <div class="active-state">
    <div v-if="activeLayersDisplay.length === 0" class="no-layers">
      <p>{{ LAYERS_COPY.emptyActive }}</p>
      <button type="button" class="empty-cta" @click="emit('openLibrary')">
        {{ LAYERS_COPY.emptyActiveCta }}
      </button>
    </div>

    <template v-else>
      <!-- 批量操作工具栏 -->
      <div class="batch-toolbar">
        <button class="batch-btn" title="显示所有图层" @click="emit('showAllLayers')">
          <CircleDot :size="14" aria-hidden="true" /> 全部显示
        </button>
        <button class="batch-btn" title="隐藏所有图层" @click="emit('hideAllLayers')">
          <Circle :size="14" aria-hidden="true" /> 全部隐藏
        </button>
        <button
          class="batch-btn batch-btn-danger"
          title="移除所有图层"
          @click="emit('removeAllLayers')"
        >
          <X :size="14" aria-hidden="true" /> 全部移除
        </button>
      </div>

      <!-- 图层列表：组头 + 成员；按内容高度排列 -->
      <ul class="layer-list" role="listbox" aria-label="已添加图层">
        <template v-for="row in activeTocRows" :key="row.key">
          <li
            v-if="row.kind === 'group'"
            class="layer-group-header"
            :class="{
              'drag-over': row.groupId === dragOverGroupId,
              computing: runGroupOf(row.groupId)?.status === 'computing',
            }"
            @dragover="emit('onGroupDragOver', row.groupId, $event)"
            @drop="emit('onGroupDrop', row.groupId)"
            @dragend="emit('onDragEnd')"
            @contextmenu.prevent="emit('onGroupContextMenu', row.groupId, $event)"
          >
            <span
              class="drag-handle-wrap"
              draggable="true"
              @dragstart="emit('onGroupDragStart', row.groupId, $event)"
            >
              <Menu :size="14" class="drag-handle" title="拖动整组" />
            </span>
            <span class="group-accent" aria-hidden="true"></span>
            <strong class="group-title">{{
              runGroupOf(row.groupId)?.title || LAYERS_COPY.computingGroup
            }}</strong>
            <span
              class="group-status-chip"
              :class="`group-status-chip--${runGroupOf(row.groupId)?.status ?? 'computing'}`"
              >{{ groupStatusLabel(row.groupId) }}</span
            >
            <span
              v-if="typeof runGroupOf(row.groupId)?.progress === 'number'"
              class="group-progress-track"
              :title="`${runGroupOf(row.groupId)?.progress}%`"
            >
              <span
                class="group-progress-fill"
                :style="{
                  width: `${Math.max(0, Math.min(100, runGroupOf(row.groupId)?.progress ?? 0))}%`,
                }"
              ></span>
            </span>
            <span class="group-count"
              >{{ runGroupOf(row.groupId)?.memberInstanceIds.length ?? 0 }} 层</span
            >
          </li>
          <li
            v-else
            class="layer-item"
            :class="{
              active: row.layer.instanceId === selectedInstanceId,
              hidden: !row.layer.visible,
              'drag-over': row.layer.instanceId === dragOverInstanceId,
              'in-run-group': row.indented,
              'group-locked': row.layer.runGroupLocked,
            }"
            :style="{
              '--accent': row.layer.accentColor,
              '--glow': row.layer.accentGlow,
            }"
            role="option"
            :aria-selected="row.layer.instanceId === selectedInstanceId"
            @click="emit('selectItem', row.layer.instanceId)"
            @dblclick.stop="emit('zoomToItem', row.layer.instanceId)"
            @contextmenu="emit('onLayerContextMenu', row.layer.instanceId, $event)"
            @dragover="emit('onDragOver', row.layer.instanceId, $event)"
            @drop="emit('onDrop', row.layer.instanceId)"
            @dragend="emit('onDragEnd')"
          >
            <div class="layer-row-top">
              <span
                class="drag-handle-wrap"
                draggable="true"
                @dragstart="emit('onDragStart', row.layer.instanceId)"
              >
                <Menu
                  :size="14"
                  class="drag-handle"
                  :title="row.layer.runGroupLocked ? '仅可在组内排序' : '拖动排序'"
                />
              </span>
              <button
                class="vis-btn"
                :title="row.layer.visible ? '隐藏图层' : '显示图层'"
                :aria-label="row.layer.visible ? '隐藏图层' : '显示图层'"
                @click="emit('toggleVisibility', row.layer.instanceId, $event)"
              >
                <CircleDot v-if="row.layer.visible" :size="14" aria-hidden="true" />
                <Circle v-else :size="14" aria-hidden="true" />
              </button>
              <span
                class="layer-color-dot"
                :style="{ background: row.layer.accentColor }"
                aria-hidden="true"
              ></span>
              <strong
                class="layer-name"
                :title="
                  row.layer.runGroupProductTag
                    ? productTagDescription(row.layer.runGroupProductTag)
                    : undefined
                "
                >{{ row.layer.name }}</strong
              >
              <span
                v-if="!isComputingRunMember(row.layer)"
                class="layer-chip"
                :style="{ background: row.layer.chipTone }"
                >{{ getCategoryName(row.layer.category) }}</span
              >
              <button
                class="del-btn"
                title="移除图层"
                aria-label="移除图层"
                @click="emit('removeItem', row.layer.instanceId, $event)"
              >
                <X :size="14" aria-hidden="true" />
              </button>
            </div>

            <!-- 图例行（2026-08-25 UX 简化）：单位已挪入状态行；仅当有
                 vmin/vmax 刻度时渲染（无刻度时色带行无信息量，省一行高度）。 -->
            <div
              v-if="
                hasColorSymbology(row.layer) &&
                (getSymbologyVmin(row.layer) || getSymbologyVmax(row.layer))
              "
              class="layer-legend"
            >
              <div class="legend-ramp" :style="getColorRampStyle(row.layer)"></div>
              <div class="legend-labels">
                <span class="legend-min">{{ getSymbologyVmin(row.layer) }}</span>
                <span class="legend-max">{{ getSymbologyVmax(row.layer) }}</span>
              </div>
            </div>

            <div class="layer-row-bottom">
              <!-- 统一数据状态徽标（2026-08-25 UX 简化）：三源归并为
                   五态（运行中/排队中/异常/完成/旧数据）——去掉
                   「数据异常/资产陈旧/失败」堆叠与「资产」术语。 -->
              <span
                v-if="getUnifiedDataStatus(row.layer)"
                class="data-status-badge"
                :class="`data-status-${getUnifiedDataStatus(row.layer)!.state}`"
                :title="getUnifiedDataStatus(row.layer)!.title ?? undefined"
              >
                {{ getUnifiedDataStatus(row.layer)!.label }}
              </span>
              <button
                v-if="isOnlinePlanPending?.(row.layer.catalogId)"
                type="button"
                class="plan-pending-badge"
                :title="ONLINE_PLAN_COPY.pendingBadgeTitle"
                @click.stop="openOnlinePlan?.()"
              >
                {{ ONLINE_PLAN_COPY.pendingBadge }}
              </button>
              <button
                v-if="getSourceRouteBadge?.(row.layer.catalogId)"
                type="button"
                class="source-route-badge"
                :class="`source-route-${getSourceRouteBadge?.(row.layer.catalogId)?.key}`"
                :title="getSourceRouteBadge?.(row.layer.catalogId)?.title"
                @click.stop="cycleSourceRoute?.(row.layer.catalogId)"
              >
                {{ getSourceRouteBadge?.(row.layer.catalogId)?.label }}
              </button>
              <span
                v-if="
                  supportsOnlineTemporal(row.layer.catalogId) &&
                  !getSourceRouteBadge?.(row.layer.catalogId)
                "
                class="online-fetch-badge"
                title="此图层支持在线获取历史时间数据"
                >在线</span
              >
              <span v-if="row.layer.isAdminBoundary" class="admin-tip-inline">边界 · 静态矢量</span>
              <span v-else-if="row.layer.isImported" class="admin-tip-inline"
                >导入 · {{ row.layer.importedGeometryType }} ·
                {{ row.layer.importedFeatureCount }} 要素</span
              >
              <span v-else-if="row.layer.isImportedRaster" class="admin-tip-inline"
                >导入 · 栅格{{
                  row.layer.importedRasterTimeCount
                    ? ` · ${row.layer.importedRasterTimeCount} 块`
                    : ' · TIF'
                }}{{
                  row.layer.importedRasterEffectiveTime
                    ? ` · ${row.layer.importedRasterEffectiveTime}`
                    : ''
                }}</span
              >
              <span
                v-else-if="
                  row.layer.runGroupId &&
                  !row.layer.isImportedRaster &&
                  runGroupOf(row.layer.runGroupId)?.status !== 'computing'
                "
                class="admin-tip-inline"
                >计算占位{{
                  row.layer.runGroupProductTag ? ` · ${row.layer.runGroupProductTag}` : ''
                }}</span
              >
              <template v-if="row.layer.jobLayer">
                <button
                  v-if="row.layer.jobLayer.reportSummary"
                  class="job-report-hint"
                  type="button"
                  @click.stop="emit('openJobReport', row.layer.instanceId)"
                >
                  {{ LAYERS_COPY.viewReportInline }}
                </button>
              </template>
              <!-- 单位（2026-08-25 UX 简化）：从图例行挪入状态行，
                   相对整个图层条水平居中（绝对定位，不随左右内容挤压）。 -->
              <span
                v-if="getSymbologyUnit(row.layer) && !row.layer.runGroupLocked"
                class="layer-metric-unit"
                :title="`图层计量单位：${getSymbologyUnit(row.layer)}`"
                >{{ getSymbologyUnit(row.layer) }}</span
              >
              <span v-if="!row.layer.runGroupId && !row.layer.runGroupLocked" class="order-hint"
                >顺序
                {{
                  activeLayersDisplay.findIndex((l) => l.instanceId === row.layer.instanceId) + 1
                }}
                / {{ activeLayersDisplay.length }}</span
              >
            </div>
          </li>
        </template>
      </ul>
    </template>
  </div>
</template>

<style scoped src="./LayerSidebar.styles.css"></style>
