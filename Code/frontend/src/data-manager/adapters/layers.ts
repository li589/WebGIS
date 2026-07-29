/**
 * 数据管理器 → layersStore 薄适配（耦合边界）。
 *
 * | 模块 | 职责 |
 * |------|------|
 * | data-manager | 上传/导入作业/导出/属性表编辑；不直接操作 MapLibre |
 * | layersStore | 仅持有展示态（importedVector/Raster）、选中、侧栏视图、「当前图层」列表 |
 * | MapCanvas | 订阅 activeLayers / highlight，负责上图与高亮，不 import 面板 |
 * | 分析/workflow | 独立；后续可通过 adapter「发送到工作流」挂接，勿在导入路径硬编码 |
 *
 * 大数据：>100MiB 矢量 / 批导出走 async job；属性表分页服务端真源，不一次载入全量到浏览器。
 */
import { useLayersStore } from '../../stores/layers'
import { deleteImportedLayer } from '../core/api'

function activateInLayerManager(instanceId: string) {
  const store = useLayersStore()
  const layer = store.activeLayers.find((l) => l.instanceId === instanceId)
  if (layer) {
    layer.visible = true
  }
  store.selectLayer(instanceId)
  // 图层管理器必须切到「当前图层」，否则用户在目录视图看不到刚导入的层
  store.setSidebarView('active')
}

export async function registerImportedVectorLayer(
  ...args: Parameters<ReturnType<typeof useLayersStore>['addImportedVectorLayer']>
) {
  const store = useLayersStore()
  const layer = store.addImportedVectorLayer(...args)
  activateInLayerManager(layer.instanceId)
  return layer
}

export async function registerImportedRasterLayer(
  ...args: Parameters<ReturnType<typeof useLayersStore>['addImportedRasterLayer']>
) {
  const store = useLayersStore()
  const layer = store.addImportedRasterLayer(...args)
  activateInLayerManager(layer.instanceId)
  return layer
}

export function focusImportedLayer(instanceId: string) {
  const store = useLayersStore()
  store.selectLayer(instanceId)
  store.setSidebarView('active')
}

export async function removeImportedLayer(catalogOrInstanceId: string, backendLayerId?: string) {
  const store = useLayersStore()
  store.removeLayer(catalogOrInstanceId)
  if (backendLayerId) {
    try {
      await deleteImportedLayer(backendLayerId)
    } catch {
      /* store 侧可能已清理 */
    }
  }
}
