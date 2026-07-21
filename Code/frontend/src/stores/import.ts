/**
 * @deprecated 主界面导入已并入 layersStore + services/data-import。
 * 仅保留类型 re-export，避免旧引用断裂。
 */
export type { ImportedGeometryType } from './layers/imported-vector'

export type ImportedLayerType = 'vector' | 'raster'

/** @deprecated 请使用 useLayersStore().addImportedVectorLayer / addImportedRasterLayer */
export function useImportStore(): never {
  throw new Error(
    '[import store] 已废弃：请使用 useLayersStore 的 addImportedVectorLayer / addImportedRasterLayer',
  )
}
