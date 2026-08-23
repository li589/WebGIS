import { ref, computed, onMounted, onUnmounted, type Ref } from 'vue'
import { useUiStore } from '../../stores/ui'
import { useLogStore } from '../../stores/log'
import { useOverlaySymbologyStore } from '../../stores/overlay-symbology'
import type { ActiveLayerDisplay, ActiveRunLayerGroup } from '../../stores/layers/types'
import type { SidebarLayersDeps } from './sidebar-layers-deps'
import { LAYERS_COPY } from '../../ui-copy'
import {
  openDataWorkspace,
  openDatedExportForLayer,
  showToast,
} from '../../data-manager/core/workspace-store'
import { exportLayer } from '../../data-manager/adapters/export'
import {
  buildLayerContextMenu,
  buildGroupContextMenu,
  type LayerContextActionId,
} from './layer-context-menu'

export interface ContextMenuState {
  instanceId?: string
  groupId?: string
  x: number
  y: number
}

/**
 * Extracts context menu logic from LayerSidebar.vue.
 *
 * Manages the right-click context menu state for both individual layers and
 * run groups, builds menu items based on layer type, and dispatches menu
 * actions (zoom, toggle visibility, export, rename, run workflow, etc.).
 * Also registers global click/keydown listeners to dismiss the menu.
 *
 * @param activeLayersDisplay - ComputedRef of the display-ordered active layers
 * @param runLayerGroups - ComputedRef of the active run layer groups
 * @param layersDeps - Narrow layers dependencies (see sidebar-layers-deps.ts)
 * @param uiStore - The UI store instance (analysis focus requests)
 * @param logStore - The log store instance (operation logging)
 * @param overlaySymbologyStore - The overlay symbology store (metadata prefetch)
 * @param emit - Component emit function
 * @param selectItem - Select a layer by instanceId
 * @param zoomToItem - Zoom to a layer by instanceId
 * @param removeItem - Remove a layer by instanceId
 * @param runGroupOf - Lookup a run group by groupId
 */
export function useSidebarContextMenu(
  activeLayersDisplay: Ref<ActiveLayerDisplay[]>,
  _runLayerGroups: Ref<ActiveRunLayerGroup[]>,
  layersDeps: SidebarLayersDeps,
  uiStore: ReturnType<typeof useUiStore>,
  logStore: ReturnType<typeof useLogStore>,
  overlaySymbologyStore: ReturnType<typeof useOverlaySymbologyStore>,
  _emit: (event: string, ...args: unknown[]) => void,
  selectItem: (instanceId: string) => void,
  zoomToItem: (instanceId: string) => void,
  removeItem: (instanceId: string, event: MouseEvent) => void,
  runGroupOf: (groupId: string) => ActiveRunLayerGroup | null,
) {
  // ── 右键菜单 ─────────────────────────────────────────────────────────────────

  const contextMenu = ref<ContextMenuState | null>(null)

  const contextMenuLayer = computed(() => {
    if (!contextMenu.value?.instanceId) return null
    return (
      activeLayersDisplay.value.find((l) => l.instanceId === contextMenu.value!.instanceId) ?? null
    )
  })

  /** 右键图层条目时弹出上下文菜单 */
  function onLayerContextMenu(instanceId: string, event: MouseEvent) {
    event.preventDefault()
    const MENU_W = 200
    const MENU_H = 360
    const vw = window.innerWidth
    const vh = window.innerHeight
    const x = Math.min(event.clientX, vw - MENU_W - 8)
    const y = Math.min(event.clientY, vh - MENU_H - 8)
    contextMenu.value = { instanceId, x: Math.max(8, x), y: Math.max(8, y) }
  }

  function onGroupContextMenu(groupId: string, event: MouseEvent) {
    event.preventDefault()
    event.stopPropagation()
    const MENU_W = 200
    const MENU_H = 200
    const vw = window.innerWidth
    const vh = window.innerHeight
    const x = Math.min(event.clientX, vw - MENU_W - 8)
    const y = Math.min(event.clientY, vh - MENU_H - 8)
    contextMenu.value = { groupId, x: Math.max(8, x), y: Math.max(8, y) }
  }

  function closeContextMenu() {
    contextMenu.value = null
  }

  const contextMenuGroups = computed(() => {
    if (contextMenu.value?.groupId) {
      const g = runGroupOf(contextMenu.value.groupId)
      if (!g) return []
      const members = g.memberInstanceIds
        .map((id) => layersDeps.activeLayers.value.find((l) => l.instanceId === id))
        .filter(Boolean)
      return buildGroupContextMenu({
        dissolvable: g.dissolvable,
        computing: g.status === 'computing',
        anyVisible: members.some((m) => m?.visible),
      })
    }
    const layer = contextMenuLayer.value
    if (!layer) return []
    const canRun =
      !layer.isImported &&
      !layer.isImportedRaster &&
      !layer.isAdminBoundary &&
      layersDeps.canRunCatalog(layer.catalogId)
    const raw = layersDeps.activeLayers.value.find((l) => l.instanceId === layer.instanceId)
    const isExportPending = Boolean(
      raw?.runGroupId &&
      !raw.importedRaster?.overlayLayerId &&
      !raw.importedVector?.backendLayerId &&
      !layer.isImported &&
      !layer.isImportedRaster,
    )
    return buildLayerContextMenu({
      visible: layer.visible,
      isAdminBoundary: layer.isAdminBoundary,
      isImported: layer.isImported,
      isImportedRaster: layer.isImportedRaster,
      isExportPending,
      hasJobReport: Boolean(layer.jobLayer?.reportSummary),
      canRunWorkflow: canRun,
      canDissolveGroup: Boolean(
        layer.runGroupId && layersDeps.findRunGroupById(layer.runGroupId)?.dissolvable,
      ),
    })
  })

  /** 右键「样式…」→ 分析面板样式 Tab（符号/透明度/配色等统一入口） */
  function openStyleInAnalysis() {
    if (!contextMenu.value?.instanceId) return
    const id = contextMenu.value.instanceId
    const layer = activeLayersDisplay.value.find((l) => l.instanceId === id)
    uiStore.requestAnalysisFocus(['layer-style'])
    selectItem(id)
    if (
      layer &&
      !layer.isImported &&
      !layer.isImportedRaster &&
      !layer.isAdminBoundary &&
      !layer.renderHint
    ) {
      void overlaySymbologyStore.ensureMeta(layer.catalogId)
    }
    closeContextMenu()
  }

  function openExportPanelForActive() {
    if (!contextMenu.value?.instanceId) return
    const active = layersDeps.activeLayers.value.find(
      (l) => l.instanceId === contextMenu.value?.instanceId,
    )
    if (!active) {
      closeContextMenu()
      return
    }
    const times = active.importedRaster?.timeList ?? []
    let time: string | null = null
    if (times.length) {
      const eff = active.importedRaster?.effectiveTimeLabel
      time =
        (eff && times.find((t) => eff === t || eff.startsWith(t))) ||
        times[times.length - 1] ||
        null
    }
    openDatedExportForLayer(active.instanceId, time)
    closeContextMenu()
  }

  async function exportActiveFromMenu(
    format: 'geojson' | 'csv' | 'shp-zip' | 'png' | 'tif' | 'nc' | 'mat',
  ) {
    if (!contextMenu.value) return
    const active = layersDeps.activeLayers.value.find(
      (l) => l.instanceId === contextMenu.value?.instanceId,
    )
    if (!active) {
      closeContextMenu()
      return
    }
    // 栅格：打开导出面板（时刻 / 裁剪 / CRS）；矢量直接导出
    if (
      active.importedRaster &&
      (format === 'tif' || format === 'png' || format === 'nc' || format === 'mat')
    ) {
      openExportPanelForActive()
      return
    }
    // 未保存的绘制草稿：前置提示而非事后报错
    if (active.catalogId.startsWith('draw-draft-')) {
      showToast('该绘制图层尚未保存：请先在绘制工具栏点击「保存」后再导出', true)
      closeContextMenu()
      return
    }
    try {
      await exportLayer(active, format)
      logStore.logOperation(`export-${format}`, `导出 ${format.toUpperCase()}「${active.name}」`)
    } catch (e) {
      logStore.logOperation(
        'export-fail',
        `导出 ${format.toUpperCase()} 失败: ${active.name}`,
        e instanceof Error ? e.message : String(e),
      )
    }
    closeContextMenu()
  }

  function renameLayerFromMenu() {
    if (!contextMenu.value?.instanceId) return
    const id = contextMenu.value.instanceId
    const layer = activeLayersDisplay.value.find((l) => l.instanceId === id)
    const next = window.prompt(LAYERS_COPY.renamePrompt, layer?.name ?? '')
    if (next == null) {
      closeContextMenu()
      return
    }
    const trimmed = next.trim()
    if (!trimmed) {
      closeContextMenu()
      return
    }
    layersDeps.setLayerDisplayName(id, trimmed)
    logStore.logOperation('layer-rename', `重命名图层「${trimmed}」`)
    closeContextMenu()
  }

  function zoomToLayerFromMenu() {
    if (!contextMenu.value?.instanceId) return
    const id = contextMenu.value.instanceId
    zoomToItem(id)
    closeContextMenu()
  }

  function openJobReport(instanceId: string) {
    // 先请求滚动目标，再选中图层，避免 InfoPanel 默认滚到「当前对象」盖住报告区
    uiStore.requestAnalysisFocus(['report-section', 'result-section', 'scheduler-status'])
    selectItem(instanceId)
  }

  function handleContextAction(action: LayerContextActionId) {
    if (action === 'exportPending') {
      closeContextMenu()
      return
    }
    if (!contextMenu.value) return
    const groupId = contextMenu.value.groupId
    if (groupId) {
      const g = runGroupOf(groupId)
      switch (action) {
        case 'toggleGroupVisible': {
          const members = g?.memberInstanceIds ?? []
          const anyVisible = members.some(
            (id) => layersDeps.activeLayers.value.find((l) => l.instanceId === id)?.visible,
          )
          for (const id of members) {
            const layer = layersDeps.activeLayers.value.find((l) => l.instanceId === id)
            if (!layer) continue
            if (layer.visible === anyVisible) {
              layersDeps.toggleLayerVisibility(id)
            }
          }
          closeContextMenu()
          return
        }
        case 'dissolveGroup':
          if (g?.dissolvable) {
            layersDeps.dissolveRunGroup(groupId)
            logStore.logOperation('layer-dissolve-group', `拆分计算组 ${groupId}`)
          }
          closeContextMenu()
          return
        case 'removeGroup': {
          const members = [...(g?.memberInstanceIds ?? [])]
          for (const id of members) {
            layersDeps.removeLayer(id)
          }
          logStore.logOperation('layer-remove-group', `移除计算组 ${groupId}`)
          closeContextMenu()
          return
        }
        default:
          closeContextMenu()
          return
      }
    }
    const id = contextMenu.value.instanceId
    if (!id) return
    switch (action) {
      case 'zoom':
        zoomToLayerFromMenu()
        return
      case 'toggleVisible':
        layersDeps.toggleLayerVisibility(id)
        closeContextMenu()
        return
      case 'viewDetails':
        selectItem(id)
        closeContextMenu()
        return
      case 'bringToFront':
        layersDeps.bringLayerToFront(id)
        closeContextMenu()
        return
      case 'sendToBack':
        layersDeps.sendLayerToBack(id)
        closeContextMenu()
        return
      case 'rename':
        renameLayerFromMenu()
        return
      case 'openAttributes':
        selectItem(id)
        openDataWorkspace({ tab: 'attributes', layerInstanceId: id })
        closeContextMenu()
        return
      case 'openDetails':
        selectItem(id)
        openDataWorkspace({ tab: 'details', layerInstanceId: id })
        closeContextMenu()
        return
      case 'openStyle':
        openStyleInAnalysis()
        return
      case 'exportGeoJson':
        void exportActiveFromMenu('geojson')
        return
      case 'exportCsv':
        void exportActiveFromMenu('csv')
        return
      case 'exportShp':
        void exportActiveFromMenu('shp-zip')
        return
      case 'exportPng':
        void exportActiveFromMenu('png')
        return
      case 'exportTif':
        void exportActiveFromMenu('tif')
        return
      case 'exportNc':
        void exportActiveFromMenu('nc')
        return
      case 'exportMat':
        void exportActiveFromMenu('mat')
        return
      case 'openExportPanel':
        openExportPanelForActive()
        return
      case 'viewReport':
        openJobReport(id)
        closeContextMenu()
        return
      case 'runWorkflow': {
        const layer = activeLayersDisplay.value.find((l) => l.instanceId === id)
        if (layer) {
          void layersDeps.runWorkflowForCatalog(layer.catalogId)
        }
        closeContextMenu()
        return
      }
      case 'runWorkflowNoCache': {
        // 不使用节点缓存：全量重算，规避复用旧输出目录带来的时间片污染
        const layer = activeLayersDisplay.value.find((l) => l.instanceId === id)
        if (layer) {
          void layersDeps.runWorkflowForCatalog(layer.catalogId, { reuseBlockCache: false })
        }
        closeContextMenu()
        return
      }
      case 'dissolveGroup': {
        const layer = activeLayersDisplay.value.find((l) => l.instanceId === id)
        if (layer?.runGroupId) {
          layersDeps.dissolveRunGroup(layer.runGroupId)
          logStore.logOperation('layer-dissolve-group', `拆分计算组 ${layer.runGroupId}`)
        }
        closeContextMenu()
        return
      }
      case 'remove':
        removeItem(id, new MouseEvent('click'))
        closeContextMenu()
        return
    }
  }

  /** 点击页面空白处关闭菜单 */
  function onGlobalClick(event: MouseEvent) {
    const target = event.target as HTMLElement
    if (contextMenu.value && !target.closest('.ctx-menu')) {
      closeContextMenu()
    }
  }

  /** ESC 关闭菜单 */
  function onGlobalKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      closeContextMenu()
    }
  }

  onMounted(() => {
    document.addEventListener('click', onGlobalClick)
    document.addEventListener('keydown', onGlobalKeydown)
  })

  onUnmounted(() => {
    document.removeEventListener('click', onGlobalClick)
    document.removeEventListener('keydown', onGlobalKeydown)
  })

  return {
    contextMenu,
    contextMenuLayer,
    contextMenuGroups,
    onLayerContextMenu,
    onGroupContextMenu,
    closeContextMenu,
    handleContextAction,
    openJobReport,
    onGlobalClick,
    onGlobalKeydown,
  }
}
