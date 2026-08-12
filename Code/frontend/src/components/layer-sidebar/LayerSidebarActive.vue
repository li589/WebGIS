<script setup lang="ts">
import { LAYERS_COPY } from '../../ui-copy'
import { productTagDescription } from '../../utils/workflow-expected-outputs'
import { CircleDot, Circle, X, Menu } from 'lucide-vue-next'

defineProps<{
  activeLayersDisplay: any[]
  activeTocRows: any[]
  selectedInstanceId: string | null
  dragOverInstanceId: string | null
  dragOverGroupId: string | null
  runGroupOf: (groupId: string) => any
  groupStatusLabel: (groupId: string) => string
  hasColorSymbology: (layer: any) => boolean
  getColorRampStyle: (layer: any) => Record<string, string>
  getSymbologyUnit: (layer: any) => string
  getSymbologyVmin: (layer: any) => string
  getSymbologyVmax: (layer: any) => string
  availabilityClass: (state: string) => string
  getCategoryName: (categoryId: string) => string
}>()

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
            draggable="true"
            @dragstart="emit('onGroupDragStart', row.groupId, $event)"
            @dragover="emit('onGroupDragOver', row.groupId, $event)"
            @drop="emit('onGroupDrop', row.groupId)"
            @dragend="emit('onDragEnd')"
            @contextmenu.prevent="emit('onGroupContextMenu', row.groupId, $event)"
          >
            <Menu :size="14" class="drag-handle" title="拖动整组" />
            <span class="group-accent" aria-hidden="true"></span>
            <strong class="group-title">{{
              runGroupOf(row.groupId)?.title || LAYERS_COPY.computingGroup
            }}</strong>
            <span class="group-status-chip">{{ groupStatusLabel(row.groupId) }}</span>
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
            :draggable="true"
            role="option"
            :aria-selected="row.layer.instanceId === selectedInstanceId"
            @click="emit('selectItem', row.layer.instanceId)"
            @dblclick.stop="emit('zoomToItem', row.layer.instanceId)"
            @contextmenu="emit('onLayerContextMenu', row.layer.instanceId, $event)"
            @dragstart="emit('onDragStart', row.layer.instanceId)"
            @dragover="emit('onDragOver', row.layer.instanceId, $event)"
            @drop="emit('onDrop', row.layer.instanceId)"
            @dragend="emit('onDragEnd')"
          >
            <div class="layer-row-top">
              <Menu
                :size="14"
                class="drag-handle"
                :title="row.layer.runGroupLocked ? '仅可在组内排序' : '拖动排序'"
              />
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
              <span class="layer-chip" :style="{ background: row.layer.chipTone }">{{
                getCategoryName(row.layer.category)
              }}</span>
              <button
                class="del-btn"
                title="移除图层"
                aria-label="移除图层"
                @click="emit('removeItem', row.layer.instanceId, $event)"
              >
                <X :size="14" aria-hidden="true" />
              </button>
            </div>

            <div v-if="hasColorSymbology(row.layer)" class="layer-legend">
              <div class="legend-ramp" :style="getColorRampStyle(row.layer)"></div>
              <div class="legend-labels">
                <span class="legend-min">{{ getSymbologyVmin(row.layer) }}</span>
                <span class="legend-unit">{{ getSymbologyUnit(row.layer) }}</span>
                <span class="legend-max">{{ getSymbologyVmax(row.layer) }}</span>
              </div>
            </div>

            <div class="layer-row-bottom">
              <span
                class="availability-chip"
                :class="availabilityClass(row.layer.availabilityState)"
              >
                {{ row.layer.availabilityLabel }}
              </span>
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
                v-else-if="row.layer.runGroupId && !row.layer.isImportedRaster"
                class="admin-tip-inline"
                >计算占位{{
                  row.layer.runGroupProductTag ? ` · ${row.layer.runGroupProductTag}` : ''
                }}</span
              >
              <template v-if="row.layer.jobLayer">
                <span class="job-status-badge" :class="`job-${row.layer.jobLayer.status}`">
                  {{
                    row.layer.jobLayer.status === 'running'
                      ? row.layer.jobLayer.message
                        ? row.layer.jobLayer.message
                        : `运行中 ${row.layer.jobLayer.progress}%`
                      : row.layer.jobLayer.status === 'queued'
                        ? '排队中'
                        : row.layer.jobLayer.status === 'retry_pending'
                          ? '等待重试'
                          : row.layer.jobLayer.status === 'succeeded'
                            ? '已完成'
                            : row.layer.jobLayer.status === 'failed'
                              ? '失败'
                              : row.layer.jobLayer.status === 'cancelled'
                                ? '已取消'
                                : row.layer.jobLayer.status
                  }}
                </span>
                <button
                  v-if="row.layer.jobLayer.reportSummary"
                  class="job-report-hint"
                  type="button"
                  @click.stop="emit('openJobReport', row.layer.instanceId)"
                >
                  查看报告
                </button>
              </template>
              <span class="order-hint"
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
