<script setup lang="ts">
import { LAYERS_COPY, ONLINE_PLAN_COPY } from '../../ui-copy'
import { PRODUCT_TAG_LABELS, productTagDescription } from '../../utils/workflow-expected-outputs'
import { formatTimeKeyLabel } from '../../utils/time-key-format'
import { toLayerDisplayName } from '../../utils/layer-display-name'
import type { DataStatusBadge } from '../../utils/layer-data-status'
import { Check, ChevronDown, Info, Layers, MoreHorizontal, X } from '../ui/icons'
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

// 2026-10-09：唯一调用点是下方「本地导入」分类胶囊（已按需求注释掉），故此处暂时"未使用"。
// 恢复那段注释后，请把下面这行 eslint-disable 一并删掉。
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function isComputingRunMember(layer: ActiveLayerDisplay): boolean {
  if (!layer.runGroupId) return false
  return props.runGroupOf(layer.runGroupId)?.status === 'computing'
}

/**
 * 名称后的变量短码（2026-10-19）：对齐「土壤水分 SM / 植被光学厚度 VOD / ω」的读法。
 * 只对已知产物角色（PRODUCT_TAG_LABELS）显示，未知 tag 不猜；
 * 名称本身已含该短码时跳过，避免出现「VOD VOD」。
 */
function layerTagOf(layer: ActiveLayerDisplay): string {
  const tag = String(layer.runGroupProductTag ?? '')
    .trim()
    .toUpperCase()
  const short = PRODUCT_TAG_LABELS[tag]
  if (!short) return ''
  return toLayerDisplayName(layer.name).includes(short) ? '' : short
}

const emit = defineEmits<{
  selectItem: [instanceId: string]
  zoomToItem: [instanceId: string]
  toggleVisibility: [instanceId: string, event: MouseEvent]
  removeItem: [instanceId: string, event: MouseEvent]
  openJobReport: [instanceId: string]
  /** 2026-10-19：行尾 ⓘ（查看图层信息）——选中该层并打开右侧信息面板 */
  openLayerDetails: [instanceId: string]
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
  toggleGroup: [groupId: string]
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
          <span class="vis-check-box vis-check-box--sm is-on" aria-hidden="true">
            <Check :size="9" :stroke-width="3.5" />
          </span>
          全部显示
        </button>
        <button class="batch-btn" title="隐藏所有图层" @click="emit('hideAllLayers')">
          <span class="vis-check-box vis-check-box--sm" aria-hidden="true"></span>
          全部隐藏
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
        <template v-for="(row, index) in activeTocRows" :key="row.key">
          <li
            v-if="row.kind === 'group'"
            class="layer-group-header cgda-stagger-item"
            :class="{
              'drag-over': row.groupId === dragOverGroupId,
              computing: runGroupOf(row.groupId)?.status === 'computing',
              collapsed: row.collapsed,
            }"
            :style="{ '--stagger-i': index }"
            @click="emit('toggleGroup', row.groupId)"
            @dragover="emit('onGroupDragOver', row.groupId, $event)"
            @drop="emit('onGroupDrop', row.groupId)"
            @dragend="emit('onDragEnd')"
            @contextmenu.prevent="emit('onGroupContextMenu', row.groupId, $event)"
          >
            <button
              type="button"
              class="group-collapse-btn"
              :aria-expanded="!row.collapsed"
              :aria-label="row.collapsed ? '展开分组' : '收起分组'"
              :title="row.collapsed ? '展开分组' : '收起分组'"
              @click.stop="emit('toggleGroup', row.groupId)"
            >
              <ChevronDown :size="16" aria-hidden="true" />
            </button>
            <span class="group-accent" aria-hidden="true"></span>
            <span class="group-icon" aria-hidden="true">
              <Layers :size="13" :stroke-width="2" />
            </span>
            <strong class="group-title">{{
              toLayerDisplayName(runGroupOf(row.groupId)?.title) || LAYERS_COPY.computingGroup
            }}</strong>
            <span
              v-if="groupStatusLabel(row.groupId)"
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
            class="layer-item cgda-stagger-item"
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
              '--stagger-i': index,
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
              <button
                class="vis-btn"
                type="button"
                role="checkbox"
                :aria-checked="row.layer.visible"
                :title="row.layer.visible ? '隐藏图层' : '显示图层'"
                :aria-label="row.layer.name"
                @click="emit('toggleVisibility', row.layer.instanceId, $event)"
              >
                <span
                  class="vis-check-box"
                  :class="{ 'is-on': row.layer.visible }"
                  aria-hidden="true"
                >
                  <Check v-if="row.layer.visible" :size="10" :stroke-width="3.5" />
                </span>
              </button>
              <strong
                class="layer-name"
                :title="
                  row.layer.runGroupProductTag
                    ? productTagDescription(row.layer.runGroupProductTag)
                    : undefined
                "
                >{{ toLayerDisplayName(row.layer.name) }}</strong
              >
              <span v-if="layerTagOf(row.layer)" class="layer-tag" aria-hidden="true">{{
                layerTagOf(row.layer)
              }}</span>
              <!-- 2026-10-09 按要求隐藏「本地导入」分类胶囊（未删除，取消注释即可恢复）
              <span
                v-if="!isComputingRunMember(row.layer)"
                class="layer-chip"
                :style="{ background: row.layer.chipTone }"
                >{{ getCategoryName(row.layer.category) }}</span
              >
              -->
              <!-- 行尾操作（2026-10-19）：ⓘ 查看图层信息、⋯ 打开完整操作菜单。
                   移除图层收进 ⋯ 菜单（danger 分组已有「移除图层」），
                   行尾不再单独摆红叉，避免一行里出现两个同义入口。 -->
              <span class="layer-row-actions">
                <button
                  class="row-action-btn"
                  type="button"
                  title="查看图层信息"
                  aria-label="查看图层信息"
                  @click.stop="emit('openLayerDetails', row.layer.instanceId)"
                >
                  <Info :size="13" aria-hidden="true" />
                </button>
                <button
                  class="row-action-btn"
                  type="button"
                  title="更多操作"
                  aria-label="更多操作"
                  @click.stop="emit('onLayerContextMenu', row.layer.instanceId, $event)"
                >
                  <MoreHorizontal :size="14" aria-hidden="true" />
                </button>
              </span>
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
                <span class="legend-max">
                  {{ getSymbologyVmax(row.layer) }}
                  <!-- 2026-10-15 用户要求：colorbar 标注单位。SM（体积含水量）= m³/m³；
                       VOD / ω 为无量纲量 ⇒ 不显示单位（空串即不渲染）。
                      2026-10-16 用户要求：单位用括号括起来（如「0.5（m³/m³）」）。
                       单位来源见 useSidebarSymbology.getSymbologyUnit（按产物角色判定，
                       先排掉后端把变量标签写成 unit 的情况）。 -->
                  <span
                    v-if="getSymbologyVmax(row.layer) && getSymbologyUnit(row.layer)"
                    class="legend-unit"
                    :title="`单位：${getSymbologyUnit(row.layer)}`"
                    >（{{ getSymbologyUnit(row.layer) }}）</span
                  >
                </span>
              </div>
            </div>

            <div class="layer-row-bottom">
              <!-- 统一数据状态徽标（2026-08-25 UX 简化）：三源归并为
                   五态（运行中/排队中/异常/完成/旧数据）——去掉
                   「数据异常/资产陈旧/失败」堆叠与「资产」术语。 -->
              <!-- 2026-10-09 按要求只隐藏「完成」态徽标；运行中/排队中/异常/旧数据照常显示。
                   如需恢复显示「完成」：删掉 v-if 里 `&& getUnifiedDataStatus(row.layer)!.state !== 'done'` 即可。 -->
              <span
                v-if="
                  getUnifiedDataStatus(row.layer) &&
                  getUnifiedDataStatus(row.layer)!.state !== 'done'
                "
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
              <!-- 2026-10-09 按要求：只隐藏「导入 · 栅格 · N 块」这种技术前缀，日期单独保留（见下方 template）。
                   想完全恢复原样：把下面这段取消注释、并把紧邻的 template 段注释掉即可。
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
              -->
              <!-- 2026-10-09 栅格图层的「生效时间」单独显示；2026-10-15 起统一格式化为
                   `YYYY_MM_DD` / `YYYY_MM_DD~YYYY_MM_DD`（只改展示，不动时间键）。无日期时该分支不占位 -->
              <template v-else-if="row.layer.isImportedRaster">
                <span
                  v-if="row.layer.importedRasterEffectiveTime"
                  class="admin-tip-inline"
                  :title="`数据时间：${formatTimeKeyLabel(row.layer.importedRasterEffectiveTime)}`"
                  >{{ formatTimeKeyLabel(row.layer.importedRasterEffectiveTime) }}</span
                >
              </template>
              <span
                v-else-if="
                  row.layer.runGroupId &&
                  !row.layer.isImportedRaster &&
                  runGroupOf(row.layer.runGroupId)?.status !== 'computing'
                "
                class="admin-tip-inline"
                >计算占位{{
                  row.layer.runGroupProductTag
                    ? ` · ${toLayerDisplayName(row.layer.runGroupProductTag)}`
                    : ''
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
              <!-- 2026-10-09 按要求隐藏计量单位小字（本处会显示 OMEGA / VOD / SM 等变量角色）；未删除，取消注释即可恢复
              <span
                v-if="getSymbologyUnit(row.layer) && !row.layer.runGroupLocked"
                class="layer-metric-unit"
                :title="`图层计量单位：${getSymbologyUnit(row.layer)}`"
                >{{ getSymbologyUnit(row.layer) }}</span
              >
              -->
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
