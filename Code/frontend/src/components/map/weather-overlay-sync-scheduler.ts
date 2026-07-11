type DebugLogger = (module: string, ...args: unknown[]) => void

interface CreateWeatherOverlaySyncSchedulerOptions {
  debounceMs: number
  debugLog?: DebugLogger
}

export interface WeatherOverlaySyncScheduler {
  getCurrentToken: () => number
  beginSync: () => number
  schedule: (runSync: () => void) => void
  runNow: (runSync: () => void) => void
  dispose: () => void
}

export function createWeatherOverlaySyncScheduler(
  options: CreateWeatherOverlaySyncSchedulerOptions,
): WeatherOverlaySyncScheduler {
  let syncToken = 0
  let debounceHandle: number | null = null

  function clearScheduledRun() {
    if (debounceHandle !== null && typeof window !== 'undefined') {
      window.clearTimeout(debounceHandle)
      debounceHandle = null
    }
  }

  return {
    getCurrentToken() {
      return syncToken
    },
    beginSync() {
      syncToken += 1
      return syncToken
    },
    schedule(runSync: () => void) {
      clearScheduledRun()
      options.debugLog?.(
        'WeatherOverlaySyncScheduler',
        `schedule (debounce ${options.debounceMs}ms)`,
      )
      debounceHandle = window.setTimeout(() => {
        debounceHandle = null
        runSync()
      }, options.debounceMs)
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
