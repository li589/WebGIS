/**
 * Adaptive concurrency for weather tile fetches (AIMD + memory pressure).
 * Cap must stay ≤ backend WeatherTileService semaphore
 * (`_DEFAULT_MAX_CONCURRENT_TILE_REQUESTS = 4`) and Open-Meteo API concurrent
 * cap (=4). Higher frontend caps only queue against a saturated backend and
 * amplify 429/timeout AIMD oscillation.
 */
const MIN_CONCURRENT_TILES = 2
export const MAX_CONCURRENT_TILES_CAP = 4
const SUCCESS_THRESHOLD_FOR_INCREASE = 8
const MEMORY_PRESSURE_RATIO = 0.8

type ConcurrencyDebugLog = (module: string, ...args: unknown[]) => void

function computeInitialConcurrency(): number {
  const cores = typeof navigator !== 'undefined' ? (navigator.hardwareConcurrency ?? 4) : 4
  return Math.min(MAX_CONCURRENT_TILES_CAP, Math.max(MIN_CONCURRENT_TILES, Math.floor(cores / 2)))
}

let currentMaxConcurrent = computeInitialConcurrency()
let consecutiveSuccesses = 0
let debugLog: ConcurrencyDebugLog = () => {}
/** Zoom-out 并发提升过期时间戳（ms）；过期后回退到 AIMD 正常值 */
let zoomOutBoostUntil = 0
const ZOOM_OUT_BOOST_DURATION_MS = 5_000

export function setWeatherTileConcurrencyDebugLog(log: ConcurrencyDebugLog): void {
  debugLog = log
}

export function getWeatherTileMaxConcurrent(): number {
  // Zoom-out boost 过期后回退到 AIMD 正常值
  if (zoomOutBoostUntil > 0 && Date.now() > zoomOutBoostUntil) {
    zoomOutBoostUntil = 0
    currentMaxConcurrent = computeInitialConcurrency()
    debugLog('concurrency', 'zoom-out boost expired →', currentMaxConcurrent)
  }
  return currentMaxConcurrent
}

/** Zoom-out 时临时提升并发上限至 cap，加速新区域瓦片填充；5s 后自动过期 */
export function boostConcurrencyForZoomOut(): void {
  currentMaxConcurrent = MAX_CONCURRENT_TILES_CAP
  zoomOutBoostUntil = Date.now() + ZOOM_OUT_BOOST_DURATION_MS
  debugLog('concurrency', 'zoom-out boost →', currentMaxConcurrent)
}

/** Test/reset helper — restores initial concurrency. */
export function resetWeatherTileConcurrencyForTests(): void {
  currentMaxConcurrent = computeInitialConcurrency()
  consecutiveSuccesses = 0
}

export function recordWeatherTileSuccess(): void {
  consecutiveSuccesses += 1
  if (
    consecutiveSuccesses >= SUCCESS_THRESHOLD_FOR_INCREASE &&
    currentMaxConcurrent < MAX_CONCURRENT_TILES_CAP
  ) {
    currentMaxConcurrent += 1
    consecutiveSuccesses = 0
    debugLog('concurrency', 'increase →', currentMaxConcurrent)
  }
}

export function recordWeatherTileFailure(): void {
  const newLimit = Math.max(MIN_CONCURRENT_TILES, Math.floor(currentMaxConcurrent / 2))
  if (newLimit < currentMaxConcurrent) {
    currentMaxConcurrent = newLimit
    debugLog('concurrency', 'decrease →', currentMaxConcurrent)
  }
  consecutiveSuccesses = 0
}

/** 检查 JS 堆内存压力，超阈值时降低并发 */
export function checkWeatherTileMemoryPressure(): void {
  try {
    const perfMemory = (
      performance as Performance & {
        memory?: { usedJSHeapSize: number; jsHeapSizeLimit: number }
      }
    ).memory
    if (!perfMemory) return
    const usedRatio = perfMemory.usedJSHeapSize / perfMemory.jsHeapSizeLimit
    if (usedRatio > MEMORY_PRESSURE_RATIO && currentMaxConcurrent > MIN_CONCURRENT_TILES) {
      const newLimit = Math.max(MIN_CONCURRENT_TILES, Math.floor(currentMaxConcurrent / 2))
      if (newLimit < currentMaxConcurrent) {
        currentMaxConcurrent = newLimit
        debugLog(
          'concurrency',
          'memory-pressure →',
          currentMaxConcurrent,
          `heap=${usedRatio.toFixed(2)}`,
        )
      }
      consecutiveSuccesses = 0
    }
  } catch {
    // performance.memory 可能不可用
  }
}
