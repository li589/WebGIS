import { computed, ref, type Ref } from 'vue'
import type { ActiveLayerDisplay, ActiveRunLayerGroup } from '../../stores/layers/types'
import type { SidebarDragDeps } from './sidebar-layers-deps'
import { LAYERS_COPY } from '../../ui-copy'

export type ActiveTocRow =
  | { kind: 'group'; groupId: string; key: string }
  | {
      kind: 'layer'
      layer: ActiveLayerDisplay
      key: string
      indented: boolean
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

  /** 组头 + 缩进成员的 Active TOC 行 */
  const activeTocRows = computed<ActiveTocRow[]>(() => {
    const rows: ActiveTocRow[] = []
    const seen = new Set<string>()
    for (const layer of activeLayersDisplay.value) {
      if (layer.runGroupId && !seen.has(layer.runGroupId)) {
        seen.add(layer.runGroupId)
        rows.push({ kind: 'group', groupId: layer.runGroupId, key: `g-${layer.runGroupId}` })
      }
      rows.push({
        kind: 'layer',
        layer,
        key: layer.instanceId,
        indented: Boolean(layer.runGroupId),
      })
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
    if (g.status === 'ready') return LAYERS_COPY.computingGroupReady
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
        const placeAfter = firstIdx >= 0 ? targetIdx < firstIdx : true
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
