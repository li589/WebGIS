/**
 * Shared weather tile readiness — keep banner「完整数据」and InfoPanel stage in sync.
 */

export type WeatherTileStatsLike = {
  pending: number
  cached: number
  visible: number
}

/** idle | partial（加载中/等待）| ready（完整数据） */
export type WeatherTileReadyKind = 'idle' | 'partial' | 'ready'

export function resolveWeatherTileReadyKind(
  stats: WeatherTileStatsLike | null | undefined,
): WeatherTileReadyKind {
  if (!stats) return 'idle'
  if (stats.cached > 0 && stats.cached >= stats.visible && stats.pending === 0) {
    return 'ready'
  }
  if (stats.cached > 0 || stats.pending > 0) return 'partial'
  return 'idle'
}

/** Map readiness to workflow-like stage used by InfoPanel pills. */
export function resolveWeatherWorkflowStage(
  stats: WeatherTileStatsLike | null | undefined,
): 'idle' | 'running' | 'succeeded' {
  const kind = resolveWeatherTileReadyKind(stats)
  if (kind === 'ready') return 'succeeded'
  if (kind === 'partial') return 'running'
  return 'idle'
}
