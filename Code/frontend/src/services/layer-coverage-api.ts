/**
 * layer-coverage-api — 双通道可用性（本地日期列表 + 在线覆盖窗）。
 * 后端：GET /layers/{id}/data-coverage（扩展自 online-temporal 语义）。
 */
import { requestJson } from './_http'

export type LayerDataCoverageChannelOnline = {
  available: boolean
  coverage_start?: string | null
  coverage_end?: string | null
  native_step?: string | null
}

export type LayerDataCoverageChannelLocal = {
  available: boolean
  dates: string[]
}

export type LayerDataCoverageResponse = {
  layer_id: string
  channels: {
    online: LayerDataCoverageChannelOnline
    local: LayerDataCoverageChannelLocal
  }
}

export function fetchLayerDataCoverage(layerId: string): Promise<LayerDataCoverageResponse> {
  return requestJson<LayerDataCoverageResponse>(
    `/layers/${encodeURIComponent(layerId)}/data-coverage`,
    { method: 'GET' },
  )
}

/** 选定日或时段是否落在至少一侧有数（或仅在线窗内可预拉） */
export function isDateCoveredByAnyChannel(
  dateKey: string,
  coverage: LayerDataCoverageResponse | null | undefined,
  opts?: { allowOnlinePrefetchOnly?: boolean },
): boolean {
  if (!coverage || !dateKey) return false
  const trimmed = dateKey.trim()
  const parts = trimmed.includes('~')
    ? trimmed.split('~').map((s) => s.trim())
    : trimmed.includes('_')
      ? trimmed.split('_').map((s) => s.trim())
      : [trimmed]
  const startKey = parts[0]
  const endKey = parts[1] || startKey

  const local = coverage.channels?.local?.dates ?? []
  if (
    local.some((d) => {
      if (d === startKey || d === endKey || d.startsWith(startKey) || startKey.startsWith(d)) {
        return true
      }
      if (d >= startKey && d <= endKey) return true
      return false
    })
  ) {
    return true
  }
  const online = coverage.channels?.online
  if (!online?.available) return false
  if (!opts?.allowOnlinePrefetchOnly && !online.coverage_start && !online.coverage_end) {
    return false
  }
  const start = online.coverage_start
  const end = online.coverage_end
  if (!start && !end) return Boolean(opts?.allowOnlinePrefetchOnly && online.available)
  if (start && endKey < start.slice(0, endKey.length)) return false
  if (end && startKey > end.slice(0, startKey.length)) return false
  return true
}
