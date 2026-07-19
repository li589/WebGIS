/**
 * 本地导入栅格（TIF → 后端预览 overlay）的 payload。
 *
 * Phase 1 CRS 模块：sourceCrs / lngOffset / latOffset 字段记录用户在
 * RasterImportConfirmDialog 中确认的源 CRS 与偏移；bounds 始终是后端
 * 重投影后的 WGS84 bounds（与 overlay 在 MapLibre 中渲染一致）。
 */
export interface ImportedRasterPayload {
  /** 与后端 register_overlay 的 layer_id 一致，并用作 ActiveLayer.catalogId */
  overlayLayerId: string
  bounds?: [number, number, number, number]
  fileName?: string
  /** 源 CRS（如 'EPSG:32650' / 'GCJ02'）；WGS84 等价系时为 'EPSG:4326' */
  sourceCrs?: string
  /** 经度偏移（CRS 转换后追加，度） */
  lngOffset?: number
  /** 纬度偏移（CRS 转换后追加，度） */
  latOffset?: number
}

export function buildImportedRasterPayload(
  overlayLayerId: string,
  options?: {
    bounds?: [number, number, number, number]
    fileName?: string
    sourceCrs?: string
    lngOffset?: number
    latOffset?: number
  },
): ImportedRasterPayload {
  return {
    overlayLayerId,
    bounds: options?.bounds,
    fileName: options?.fileName,
    sourceCrs: options?.sourceCrs,
    lngOffset: options?.lngOffset,
    latOffset: options?.latOffset,
  }
}
