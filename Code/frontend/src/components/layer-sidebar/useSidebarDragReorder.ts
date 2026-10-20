import { computed, ref, type Ref } from 'vue'
import type { ActiveLayerDisplay, ActiveRunLayerGroup } from '../../stores/layers/types'
import type { SidebarDragDeps } from './sidebar-layers-deps'
import { LAYERS_COPY } from '../../ui-copy'

export type ActiveTocRow =
  | { kind: 'group'; groupId: string; key: string; collapsed: boolean }
  | {
      kind: 'layer'
      layer: ActiveLayerDisplay
      key: string
      indented: boolean
      /**
       * 2026-10-20：该行是否为所属组的最后一行。
       * 组头与成员在 DOM 里是平级的 `<li>`（没有包裹层），靠 CSS 边框拼接成
       * 一张卡片；加包裹层会牵连拖拽 / 折叠 / 右键三套逻辑，故改用标记位。
       */
      groupLast: boolean
    }

const EXPANDED_GROUPS_KEY = 'cgda.sidebar.expandedGroups'

/**
 * 组展开记忆（2026-10-19）：默认折叠，只记住用户手动展开过的组。
 * 存「展开集合」而非「折叠集合」，这样从没见过的组（新跑完的工作流）天然是收起的。
 * 写入时剔除已消失的 groupId，避免 localStorage 无限增长。
 */
function loadExpandedGroups(): Set<string> {
  try {
    const raw = window.localStorage.getItem(EXPANDED_GROUPS_KEY)
    if (!raw) return new Set()
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return new Set()
    return new Set(parsed.filter((v): v is string => typeof v === 'string'))
  } catch {
    // localStorage 不可用（隐私模式等）⇒ 退化为仅当前会话有效
    return new Set()
  }
}

/**
 * Extracts drag/drop reordering logic from LayerSidebar.vue.
 *
 * Manages drag state for both individual layers and run groups, computes the
 * flat TOC row list (group headers + indented members), and handles reorder
 * operations via the layers store.
 *
 * @param activeLayersDisplay - ComputedRef of the display-ordered active layers
 * @param runLayerGroups - ComputedRef of the active run layer groups
 * @param layersDeps - Narrow layers dependencies (see sidebar-layers-deps.ts)
 */
export function useSidebarDragReorder(
  activeLayersDisplay: Ref<ActiveLayerDisplay[]>,
  runLayerGroups: Ref<ActiveRunLayerGroup[]>,
  layersDeps: SidebarDragDeps,
) {
  const draggedInstanceId = ref<string | null>(null)
  const draggedGroupId = ref<string | null>(null)
  const dragOverInstanceId = ref<string | null>(null)
  const dragOverGroupId = ref<string | null>(null)

  /** 用户手动展开过的组（未命中的组一律按折叠渲染） */
  const expandedGroups = ref<Set<string>>(loadExpandedGroups())

  function isGroupExpanded(groupId: string): boolean {
    return expandedGroups.value.has(groupId)
  }

  function toggleGroupCollapsed(groupId: string) {
    const next = new Set(expandedGroups.value)
    if (next.has(groupId)) next.delete(groupId)
    else next.add(groupId)
    expandedGroups.value = next
    try {
      const alive = new Set(runLayerGroups.value.map((g) => g.groupId))
      window.localStorage.setItem(
        EXPANDED_GROUPS_KEY,
        JSON.stringify([...next].filter((id) => alive.has(id))),
      )
    } catch {
      // 写入失败不影响本次会话的展开状态
    }
  }

  /** 组头 + 缩进成员的 Active TOC 行 */
  const activeTocRows = computed<ActiveTocRow[]>(() => {
    const rows: ActiveTocRow[] = []
    const seen = new Set<string>()
    for (const layer of activeLayersDisplay.value) {
      if (layer.runGroupId) {
        const collapsed = !isGroupExpanded(layer.runGroupId)
        if (!seen.has(layer.runGroupId)) {
          seen.add(layer.runGroupId)
          rows.push({
            kind: 'group',
            groupId: layer.runGroupId,
            key: `g-${layer.runGroupId}`,
            collapsed,
          })
        }
        // 折叠组的成员行不渲染；activeLayersDisplay 本身不动，拖拽落点仍按完整列表计算
        if (collapsed) continue
      }
      rows.push({
        kind: 'layer',
        layer,
        key: layer.instanceId,
        indented: Boolean(layer.runGroupId),
        groupLast: false,
      })
    }
    // 2026-10-20：标注组内最后一个成员——组块卡片的下圆角与底边框只画在它身上。
    // 判据：下一行不存在 / 是组头 / 是不缩进的独立图层。
    for (let i = 0; i < rows.length; i += 1) {
      const row = rows[i]
      if (row.kind !== 'layer' || !row.indented) continue
      const next = rows[i + 1]
      row.groupLast = !next || next.kind === 'group' || (next.kind === 'layer' && !next.indented)
    }
    return rows
  })

  function runGroupOf(groupId: string) {
    return runLayerGroups.value.find((g) => g.groupId === groupId) ?? null
  }

  function groupStatusLabel(groupId: string): string {
    const g = runGroupOf(groupId)
    if (!g) return ''
    if (g.status === 'computing') {
      if (g.message) return g.message
      return LAYERS_COPY.computingGroupBusy
    }
    // 2026-10-15 用户要求：组头不再显示「可拆分」（ready 态本身无需提示）——
    // 返回空串，模板据此不渲染状态胶囊；computing / failed / cancelled 照旧。
    if (g.status === 'ready') return ''
    if (g.status === 'failed') return '失败'
    if (g.status === 'cancelled') return '已取消'
    return g.status
  }

  function onDragStart(instanceId: string) {
    draggedInstanceId.value = instanceId
    draggedGroupId.value = null
  }

  function onGroupDragStart(groupId: string, event: DragEvent) {
    event.stopPropagation()
    draggedGroupId.value = groupId
    draggedInstanceId.value = null
  }

  function onDragOver(instanceId: string, event: DragEvent) {
    event.preventDefault()
    dragOverInstanceId.value = instanceId
    dragOverGroupId.value = null
  }

  function onGroupDragOver(groupId: string, event: DragEvent) {
    event.preventDefault()
    dragOverGroupId.value = groupId
    dragOverInstanceId.value = null
  }

  function onDrop(targetInstanceId: string) {
    if (draggedGroupId.value) {
      const group = runGroupOf(draggedGroupId.value)
      const target = activeLayersDisplay.value.find((l) => l.instanceId === targetInstanceId)
      if (group && target && target.runGroupId !== draggedGroupId.value) {
        const sorted = activeLayersDisplay.value
        const groupMembers = new Set(group.memberInstanceIds)
        const firstMember = sorted.find((l) => groupMembers.has(l.instanceId))
        const targetIdx = sorted.findIndex((l) => l.instanceId === targetInstanceId)
        const firstIdx = firstMember
          ? sorted.findIndex((l) => l.instanceId === firstMember.instanceId)
          : -1
        // 2026-10-13：「已添加图层」显示顺序为 order 升序（列表越靠上 order 越小）。
        // 落点在组块上方（索引更小）时插到锚点之前，否则插到锚点之后。
        const placeAfter = firstIdx >= 0 ? targetIdx > firstIdx : false
        layersDeps.moveRunGroupBlock(draggedGroupId.value, targetInstanceId, placeAfter)
      }
      onDragEnd()
      return
    }
    if (!draggedInstanceId.value || draggedInstanceId.value === targetInstanceId) {
      onDragEnd()
      return
    }
    const sorted = activeLayersDisplay.value
    const fromIndex = sorted.findIndex((d) => d.instanceId === draggedInstanceId.value)
    const toIndex = sorted.findIndex((d) => d.instanceId === targetInstanceId)
    if (fromIndex === -1 || toIndex === -1) {
      onDragEnd()
      return
    }
    layersDeps.reorderLayers(fromIndex, toIndex)
    onDragEnd()
  }

  function onGroupDrop(groupId: string) {
    if (draggedGroupId.value && draggedGroupId.value !== groupId) {
      const targetGroup = runGroupOf(groupId)
      const anchor = targetGroup?.memberInstanceIds[0] ?? null
      if (anchor) {
        layersDeps.moveRunGroupBlock(draggedGroupId.value, anchor, false)
      }
    }
    onDragEnd()
  }

  function onDragEnd() {
    draggedInstanceId.value = null
    draggedGroupId.value = null
    dragOverInstanceId.value = null
    dragOverGroupId.value = null
  }

  return {
    draggedInstanceId,
    draggedGroupId,
    dragOverInstanceId,
    dragOverGroupId,
    activeTocRows,
    expandedGroups,
    isGroupExpanded,
    toggleGroupCollapsed,
    runGroupOf,
    groupStatusLabel,
    onDragStart,
    onGroupDragStart,
    onDragOver,
    onGroupDragOver,
    onDrop,
    onGroupDrop,
    onDragEnd,
  }
}
