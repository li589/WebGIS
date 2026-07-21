type DebugLogger = (module: string, ...args: unknown[]) => void

export type WeatherOverlaySyncReason = 'move' | 'zoom' | 'data' | 'hour'

interface CreateWeatherOverlaySyncSchedulerOptions {
  debounceMs: number
  /** zoom / dataVersion 触发时使用的更短防抖（默认约 110ms） */
  zoomDebounceMs?: number
  /** 时间轴 hour 变更：与瓦片 dataVersion coalesce（~100ms）对齐 */
  hourDebounceMs?: number
  debugLog?: DebugLogger
}

export interface WeatherOverlaySyncScheduler {
  getCurrentToken: () => number
  beginSync: () => number
  schedule: (runSync: () => void, reason?: WeatherOverlaySyncReason) => void
  runNow: (runSync: () => void) => void
  dispose: () => void
}

export function createWeatherOverlaySyncScheduler(
  options: CreateWeatherOverlaySyncSchedulerOptions,
): WeatherOverlaySyncScheduler {
  let syncToken = 0
  let debounceHandle: number | null = null
  const zoomDebounceMs = options.zoomDebounceMs ?? 110
  const hourDebounceMs = options.hourDebounceMs ?? 100

  function clearScheduledRun() {
    if (debounceHandle !== null && typeof window !== 'undefined') {
      window.clearTimeout(debounceHandle)
      debounceHandle = null
    }
  }

  function delayForReason(reason: WeatherOverlaySyncReason): number {
    if (reason === 'zoom') return zoomDebounceMs
    if (reason === 'hour') return hourDebounceMs
    return options.debounceMs
  }

  return {
    getCurrentToken() {
      return syncToken
    },
    beginSync() {
      syncToken += 1
      return syncToken
    },
    schedule(runSync: () => void, reason: WeatherOverlaySyncReason = 'data') {
      clearScheduledRun()
      const delay = delayForReason(reason)
      options.debugLog?.(
        'WeatherOverlaySyncScheduler',
        `schedule (debounce ${delay}ms, reason=${reason})`,
      )
      debounceHandle = window.setTimeout(() => {
        debounceHandle = null
        runSync()
      }, delay)
    },
    runNow(runSync: () => void) {
      clearScheduledRun()
      runSync()
    },
    dispose() {
      clearScheduledRun()
    },
  }
}
