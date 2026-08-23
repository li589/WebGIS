/**
 * 数据管理器 → layers store 薄适配（耦合边界）。
 *
 * | 模块 | 职责 |
 * |------|------|
 * | data-manager | 上传/导入作业/导出/属性表编辑；不直接操作 MapLibre |
 * | layersStore | 仅持有展示态（importedVector/Raster）、选中、侧栏视图、「当前图层」列表 |
 * | MapCanvas | 订阅 activeLayers / highlight，负责上图与高亮，不 import 面板 |
 * | 分析/workflow | 独立；后续可通过 adapter「发送到工作流」挂接，勿在导入路径硬编码 |
 *
 * 大数据：>100MiB 矢量 / 批导出走 async job；属性表分页服务端真源，不一次载入全量到浏览器。
 *
 * P3 god-facade 收口（2026-08-23）：改经 selector composable（useLayerWorkspace）
 * 消费，不再直连 flat store——类型从 selectors 返回面推导。
 */
import { useLayerWorkspace } from '../../stores/layers/selectors'
import { deleteImportedLayer } from '../core/api'

type Workspace = ReturnType<typeof useLayerWorkspace>

function activateInLayerManager(instanceId: string) {
  const { activeLayers, selectLayer, setSidebarView } = useLayerWorkspace()
  const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
  if (layer) {
    layer.visible = true
  }
  selectLayer(instanceId)
  // 图层管理器必须切到「当前图层」，否则用户在目录视图看不到刚导入的层
  setSidebarView('active')
}

export async function registerImportedVectorLayer(
  ...args: Parameters<Workspace['addImportedVectorLayer']>
) {
  const { addImportedVectorLayer } = useLayerWorkspace()
  const layer = addImportedVectorLayer(...args)
  activateInLayerManager(layer.instanceId)
  return layer
}

export async function registerImportedRasterLayer(
  ...args: Parameters<Workspace['addImportedRasterLayer']>
) {
  const { addImportedRasterLayer } = useLayerWorkspace()
  const layer = addImportedRasterLayer(...args)
  activateInLayerManager(layer.instanceId)
  return layer
}

export function focusImportedLayer(instanceId: string) {
  const { selectLayer, setSidebarView } = useLayerWorkspace()
  selectLayer(instanceId)
  setSidebarView('active')
}

function resolveLayerInstanceId(workspace: Workspace, catalogOrInstanceId: string): string {
  const byInstance = workspace.activeLayers.value.find((l) => l.instanceId === catalogOrInstanceId)
  if (byInstance) return byInstance.instanceId
  const byCatalog = workspace.activeLayers.value.find((l) => l.catalogId === catalogOrInstanceId)
  return byCatalog?.instanceId ?? catalogOrInstanceId
}

export async function removeImportedLayer(catalogOrInstanceId: string, backendLayerId?: string) {
  const workspace = useLayerWorkspace()
  workspace.removeLayer(resolveLayerInstanceId(workspace, catalogOrInstanceId))
  if (backendLayerId) {
    // 传播错误给调用方，以便向用户展示后端清理失败的信息
    await deleteImportedLayer(backendLayerId)
  }
}
