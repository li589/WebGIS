/**
 * 图层侧栏右键菜单：按图层类型生成分组项（纯函数，便于单测）。
 */
import { LAYERS_COPY } from '../../ui-copy/layers'
import { DATA_COPY } from '../../ui-copy/data'

export type LayerContextActionId =
  | 'zoom'
  | 'toggleVisible'
  | 'viewDetails'
  | 'bringToFront'
  | 'sendToBack'
  | 'rename'
  | 'openAttributes'
  | 'openDetails'
  | 'openStyle'
  | 'exportGeoJson'
  | 'exportCsv'
  | 'exportShp'
  | 'exportPng'
  | 'exportTif'
  | 'exportNc'
  | 'exportMat'
  | 'openExportPanel'
  | 'exportPending'
  | 'viewReport'
  | 'runWorkflow'
  | 'runWorkflowNoCache'
  | 'dissolveGroup'
  | 'toggleGroupVisible'
  | 'removeGroup'
  | 'remove'

export type LayerContextGroupId = 'view' | 'appearance' | 'order' | 'data' | 'workflow' | 'danger'

export interface LayerContextMenuItem {
  id: LayerContextActionId
  label: string
  icon: string
  danger?: boolean
  disabled?: boolean
}

export interface LayerContextMenuGroup {
  id: LayerContextGroupId
  label: string
  items: LayerContextMenuItem[]
}

/** 菜单生成所需的最小图层视图 */
export interface LayerContextMenuInput {
  visible: boolean
  isAdminBoundary: boolean
  isImported: boolean
  isImportedRaster: boolean
  /** 工作流占位：有 run 组但尚无 overlay，导出不可用 */
  isExportPending?: boolean
  /** 有 jobLayer 且带报告摘要时可「查看报告」 */
  hasJobReport: boolean
  /** 可提交分析工作流（非天气/导入/边界） */
  canRunWorkflow: boolean
  /** 所属计算组可拆 */
  canDissolveGroup?: boolean
}

const GROUP_LABEL: Record<LayerContextGroupId, string> = {
  view: LAYERS_COPY.groupView,
  appearance: LAYERS_COPY.groupAppearance,
  order: LAYERS_COPY.groupOrder,
  data: LAYERS_COPY.groupData,
  workflow: LAYERS_COPY.groupWorkflow,
  danger: LAYERS_COPY.groupDanger,
}

export function buildLayerContextMenu(input: LayerContextMenuInput): LayerContextMenuGroup[] {
  const groups: LayerContextMenuGroup[] = []

  groups.push({
    id: 'view',
    label: GROUP_LABEL.view,
    items: [
      {
        id: 'zoom',
        label: LAYERS_COPY.zoomToExtent,
        icon: '◎',
      },
      {
        id: 'toggleVisible',
        label: input.visible ? LAYERS_COPY.hideLayer : LAYERS_COPY.showLayer,
        icon: input.visible ? '👁' : '○',
      },
      {
        id: 'viewDetails',
        label: LAYERS_COPY.viewDetails,
        icon: 'ℹ',
      },
      {
        id: 'rename',
        label: LAYERS_COPY.rename,
        icon: '✎',
      },
    ],
  })

  // 样式统一进分析面板「样式」Tab（含透明度 / 配色 / 矢量样式 / 风场等）
  groups.push({
    id: 'appearance',
    label: GROUP_LABEL.appearance,
    items: [
      {
        id: 'openStyle',
        label: LAYERS_COPY.openStyle,
        icon: '🎨',
      },
    ],
  })

  groups.push({
    id: 'order',
    label: GROUP_LABEL.order,
    items: [
      { id: 'bringToFront', label: LAYERS_COPY.bringToFront, icon: '⬆' },
      { id: 'sendToBack', label: LAYERS_COPY.sendToBack, icon: '⬇' },
    ],
  })

  const dataItems: LayerContextMenuItem[] = []
  if (input.isImported) {
    dataItems.push(
      { id: 'openAttributes', label: DATA_COPY.openAttrTable, icon: '☰' },
      { id: 'openDetails', label: DATA_COPY.openDetails, icon: 'ℹ' },
      { id: 'exportGeoJson', label: LAYERS_COPY.exportGeoJson, icon: '⇩' },
      { id: 'exportCsv', label: LAYERS_COPY.exportCsv, icon: '⇩' },
      { id: 'exportShp', label: LAYERS_COPY.exportShp, icon: '⇩' },
      { id: 'openExportPanel', label: LAYERS_COPY.openExportPanel, icon: '▤' },
    )
  }
  if (input.isImportedRaster) {
    dataItems.push(
      { id: 'openDetails', label: DATA_COPY.openDetails, icon: 'ℹ' },
      { id: 'exportTif', label: LAYERS_COPY.exportTif, icon: '⇩' },
      { id: 'exportNc', label: LAYERS_COPY.exportNc, icon: '⇩' },
      { id: 'exportMat', label: LAYERS_COPY.exportMat, icon: '⇩' },
      { id: 'exportPng', label: LAYERS_COPY.exportPng, icon: '⇩' },
      { id: 'openExportPanel', label: LAYERS_COPY.openExportPanel, icon: '▤' },
    )
  }
  if (input.isExportPending && !input.isImported && !input.isImportedRaster) {
    dataItems.push({
      id: 'exportPending',
      label: LAYERS_COPY.exportPending,
      icon: '⇩',
      disabled: true,
    })
  }
  if (dataItems.length) {
    groups.push({
      id: 'data',
      label: GROUP_LABEL.data,
      items: dataItems,
    })
  }

  const workflowItems: LayerContextMenuItem[] = []
  if (input.hasJobReport) {
    workflowItems.push({
      id: 'viewReport',
      label: LAYERS_COPY.viewReport,
      icon: '▤',
    })
  }
  if (input.canRunWorkflow) {
    workflowItems.push({
      id: 'runWorkflow',
      label: LAYERS_COPY.runWorkflow,
      icon: '▶',
    })
    workflowItems.push({
      id: 'runWorkflowNoCache',
      label: LAYERS_COPY.runWorkflowNoCache,
      icon: '↺',
    })
  }
  if (input.canDissolveGroup) {
    workflowItems.push({
      id: 'dissolveGroup',
      label: LAYERS_COPY.dissolveGroup,
      icon: '⧉',
    })
  }
  if (workflowItems.length) {
    groups.push({
      id: 'workflow',
      label: GROUP_LABEL.workflow,
      items: workflowItems,
    })
  }

  groups.push({
    id: 'danger',
    label: GROUP_LABEL.danger,
    items: [
      {
        id: 'remove',
        label: LAYERS_COPY.removeLayer,
        icon: '✕',
        danger: true,
      },
    ],
  })

  return groups
}

/** 计算组标题专用右键菜单（拆分 / 整组显隐 / 移除整组） */
export function buildGroupContextMenu(input: {
  dissolvable: boolean
  computing: boolean
  anyVisible: boolean
}): LayerContextMenuGroup[] {
  const items: LayerContextMenuItem[] = [
    {
      id: 'toggleGroupVisible',
      label: input.anyVisible ? LAYERS_COPY.hideLayer : LAYERS_COPY.showLayer,
      icon: input.anyVisible ? '👁' : '○',
    },
    {
      id: 'dissolveGroup',
      label: LAYERS_COPY.dissolveGroup,
      icon: '⧉',
      disabled: !input.dissolvable || input.computing,
    },
    {
      id: 'removeGroup',
      label: LAYERS_COPY.removeGroup,
      icon: '✕',
      danger: true,
    },
  ]
  return [
    {
      id: 'workflow',
      label: LAYERS_COPY.groupHeaderMenu,
      items,
    },
  ]
}
