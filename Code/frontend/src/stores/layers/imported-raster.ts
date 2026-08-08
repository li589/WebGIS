import type { TemporalFollowPolicy, TimeSlice, TimeStep } from '../../utils/temporal-interval'
import { parseTimeStep, timeListToSlices } from '../../utils/temporal-interval'

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
  /** 原生时间步，如 8d / 1d / 6h */
  nativeStep?: TimeStep | string | null
  /** 可用时间切片（块或日） */
  timeSlices?: TimeSlice[]
  /** 原始 time_list（与 overlay meta 对齐） */
  timeList?: string[]
  followPolicy?: TemporalFollowPolicy
  /** 当前生效切片标签（跟随策略结果） */
  effectiveTimeLabel?: string
}

export function buildImportedRasterPayload(
  overlayLayerId: string,
  options?: {
    bounds?: [number, number, number, number]
    fileName?: string
    sourceCrs?: string
    lngOffset?: number
    latOffset?: number
    nativeStep?: TimeStep | string | null
    timeList?: string[]
    timeSlices?: TimeSlice[]
    followPolicy?: TemporalFollowPolicy
    effectiveTimeLabel?: string
  },
): ImportedRasterPayload {
  const timeList = options?.timeList
  const timeSlices =
    options?.timeSlices ?? (timeList?.length ? timeListToSlices(timeList) : undefined)
  const nativeStep =
    typeof options?.nativeStep === 'string'
      ? parseTimeStep(options.nativeStep)
      : options?.nativeStep
  return {
    overlayLayerId,
    bounds: options?.bounds,
    fileName: options?.fileName,
    sourceCrs: options?.sourceCrs,
    lngOffset: options?.lngOffset,
    latOffset: options?.latOffset,
    nativeStep: nativeStep ?? null,
    timeList,
    timeSlices,
    followPolicy: options?.followPolicy,
    effectiveTimeLabel: options?.effectiveTimeLabel,
  }
}
