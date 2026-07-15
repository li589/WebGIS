/**
 * 本地导入栅格（TIF → 后端 COG/overlay）的 payload。
 */
export interface ImportedRasterPayload {
  /** 与后端 register_overlay 的 layer_id 一致，并用作 ActiveLayer.catalogId */
  overlayLayerId: string
  bounds?: [number, number, number, number]
  fileName?: string
}

export function buildImportedRasterPayload(
  overlayLayerId: string,
  options?: {
    bounds?: [number, number, number, number]
    fileName?: string
  },
): ImportedRasterPayload {
  return {
    overlayLayerId,
    bounds: options?.bounds,
    fileName: options?.fileName,
  }
}
