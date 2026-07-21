/**
 * 轻量性能探针。默认关闭；`?perf=1` 或 localStorage `cgda.perf=1` 开启。
 * 不引入外部 profiler；指标打到 console + 内存环形缓冲供文档抄录。
 */

export type PerfSample = {
  t: number
  kind: string
  detail?: Record<string, unknown>
}

const BUFFER_MAX = 200
const samples: PerfSample[] = []
let enabledCache: boolean | null = null
let bumpCount = 0
let syncCount = 0
let lastViewportFillMs: number | null = null

function readEnabled(): boolean {
  if (typeof window === 'undefined') return false
  try {
    if (new URLSearchParams(window.location.search).get('perf') === '1') return true
    if (window.localStorage?.getItem('cgda.perf') === '1') return true
  } catch {
    /* ignore */
  }
  return false
}

export function isPerfEnabled(): boolean {
  if (enabledCache === null) enabledCache = readEnabled()
  return enabledCache
}

/** 测试或运行时强制开关 */
export function setPerfEnabled(on: boolean): void {
  enabledCache = on
}

export function perfMark(kind: string, detail?: Record<string, unknown>): void {
  if (!isPerfEnabled()) return
  const sample: PerfSample = { t: performance.now(), kind, detail }
  samples.push(sample)
  if (samples.length > BUFFER_MAX) samples.shift()
  // 单行，便于过滤
  console.log(`[cgda.perf] ${kind}`, detail ?? '')
}

export function perfIncBump(): void {
  bumpCount += 1
  perfMark('dataVersion.bump', { total: bumpCount })
}

export function perfIncSync(): void {
  syncCount += 1
  perfMark('overlay.sync', { total: syncCount })
}

export function perfNoteViewportFill(ms: number): void {
  lastViewportFillMs = ms
  perfMark('tile.viewportFillMs', { ms })
}

export function getPerfSnapshot(): {
  bumpCount: number
  syncCount: number
  lastViewportFillMs: number | null
  recent: PerfSample[]
} {
  return {
    bumpCount,
    syncCount,
    lastViewportFillMs,
    recent: samples.slice(-40),
  }
}

/** 暴露到 window 便于控制台抄录 */
export function installPerfGlobal(): void {
  if (typeof window === 'undefined' || !isPerfEnabled()) return
  ;(window as unknown as { __cgdaPerf?: typeof getPerfSnapshot }).__cgdaPerf = getPerfSnapshot
}
