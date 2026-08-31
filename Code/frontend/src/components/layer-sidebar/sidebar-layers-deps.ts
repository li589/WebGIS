/**
 * 侧栏 composable 的 layers 窄依赖接口（P3 god-facade 收口续，2026-08-23）。
 *
 * 此前 useSidebarContextMenu / useSidebarDragReorder 以
 * `ReturnType<typeof useLayersStore>` 整店类型作参数——god-facade 在侧栏的
 * 最后残留。本文件把依赖收窄为显式成员清单（类型自 selector composables
 * 返回面推导，与 selectors 契约同源）；LayerSidebar 负责从 selectors 解构
 * 组装传入。
 */
import type { useLayerWorkspace, useWorkflowRun } from '../../stores/layers/selectors'

type Workspace = ReturnType<typeof useLayerWorkspace>
type WorkflowRun = ReturnType<typeof useWorkflowRun>

/** 右键菜单所需 layers 依赖（10 成员，2026-08-23 扫描定格）。 */
export interface SidebarLayersDeps {
  /** 响应式当前图层（toRef 包裹） */
  activeLayers: Workspace['activeLayers']
  canRunCatalog: Workspace['canRunCatalog']
  bringLayerToFront: Workspace['bringLayerToFront']
  sendLayerToBack: Workspace['sendLayerToBack']
  removeLayer: Workspace['removeLayer']
  setLayerDisplayName: Workspace['setLayerDisplayName']
  toggleLayerVisibility: Workspace['toggleLayerVisibility']
  dissolveRunGroup: WorkflowRun['dissolveRunGroup']
  findRunGroupById: WorkflowRun['findRunGroupById']
  runWorkflowForCatalog: WorkflowRun['runWorkflowForCatalog']
}

/** 拖拽排序所需 layers 依赖（2 成员）。 */
export interface SidebarDragDeps {
  reorderLayers: WorkflowRun['reorderLayers']
  moveRunGroupBlock: WorkflowRun['moveRunGroupBlock']
}
