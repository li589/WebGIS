/** 时间轴播放步进间隔配置（与 Pinia store 解耦，避免 Vite 命名导出解析问题） */

export const TIMELINE_PLAY_INTERVAL_OPTIONS = [
  { ms: 500, label: '0.5 秒' },
  { ms: 1000, label: '1 秒' },
  { ms: 2000, label: '2 秒' },
  { ms: 3000, label: '3 秒' },
  { ms: 5000, label: '5 秒' },
] as const

export const DEFAULT_PLAY_INTERVAL_MS = 2000

export const PLAY_INTERVAL_STORAGE_KEY = 'cgda.timeline.play-interval-ms'

export function isValidPlayIntervalMs(ms: number): boolean {
  return TIMELINE_PLAY_INTERVAL_OPTIONS.some((opt) => opt.ms === ms)
}

export function loadPlayIntervalMs(): number {
  try {
    const raw = window.localStorage?.getItem(PLAY_INTERVAL_STORAGE_KEY)
    const value = Number(raw)
    if (isValidPlayIntervalMs(value)) return value
  } catch {
    /* ignore */
  }
  return DEFAULT_PLAY_INTERVAL_MS
}

export function persistPlayIntervalMs(ms: number): void {
  try {
    window.localStorage?.setItem(PLAY_INTERVAL_STORAGE_KEY, String(ms))
  } catch {
    /* ignore */
  }
}
