/**
 * 图层侧栏右键菜单：按图层类型生成分组项（纯函数，便于单测）。
 */
import { LAYERS_COPY } from '../../ui-copy/layers'
import { DATA_COPY } from '../../ui-copy/data'

export type LayerContextActionId =
  | 'zoom'
  | 'toggleVisible'
  | 'symbology'
  | 'viewDetails'
  | 'bringToFront'
  | 'sendToBack'
  | 'rename'
  | 'openAttributes'
  | 'openDetails'
  | 'openStyle'
  | 'exportGeoJson'
  | 'exportCsv'
  | 'exportPng'
  | 'exportTif'
  | 'viewReport'
  | 'runWorkflow'
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
  /** 有 jobLayer 且带报告摘要时可「查看报告」 */
  hasJobReport: boolean
  /** 可提交分析工作流（非天气/导入/边界） */
  canRunWorkflow: boolean
  /** 是否有颜色图例（决定菜单文案：符号化 vs 透明度） */
  hasColorSymbology: boolean
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

  const appearanceItems: LayerContextMenuItem[] = []
  if (!input.isAdminBoundary) {
    appearanceItems.push({
      id: 'symbology',
      label: input.hasColorSymbology ? LAYERS_COPY.symbology : LAYERS_COPY.opacity,
      icon: '🎨',
    })
  }
  if (input.isImported) {
    appearanceItems.push({
      id: 'openStyle',
      label: LAYERS_COPY.openStyle,
      icon: '🖌',
    })
  }
  if (appearanceItems.length) {
    groups.push({
      id: 'appearance',
      label: GROUP_LABEL.appearance,
      items: appearanceItems,
    })
  }

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
    )
  }
  if (input.isImportedRaster) {
    dataItems.push(
      { id: 'openDetails', label: DATA_COPY.openDetails, icon: 'ℹ' },
      { id: 'exportPng', label: LAYERS_COPY.exportPng, icon: '⇩' },
      { id: 'exportTif', label: LAYERS_COPY.exportTif, icon: '⇩' },
    )
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
