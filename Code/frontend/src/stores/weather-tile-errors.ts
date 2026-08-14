/**
 * Weather tile manager — error classification helpers (P1-1 split).
 */
import type { WeatherTileCoords } from '../services/weather-tile-api'
import type { WeatherTileErrorType } from './weather-tile-types'

export type DebugLogFn = (module: string, ...args: unknown[]) => void

export function parseTileCoordsFromCacheKey(cacheKey: string): WeatherTileCoords | null {
  const zMatch = /:z(\d+):/.exec(cacheKey)
  const xMatch = /:x(\d+):/.exec(cacheKey)
  const yMatch = /:y(\d+):/.exec(cacheKey)
  if (!zMatch || !xMatch || !yMatch) return null
  return {
    z: Number(zMatch[1]),
    x: Number(xMatch[1]),
    y: Number(yMatch[1]),
  }
}

/** UI / 日志用：去掉 HTML 并截断，避免 Cloudflare 502 整页污染界面 */
function sanitizeUiErrorMessage(message: string, maxLen = 180): string {
  if (
    /<!DOCTYPE\s+html|<html[\s>]|<head[\s>]|<body[\s>]/i.test(message) ||
    message.includes('<!DOCTYPE')
  ) {
    const statusMatch = /failed:\s*(\d{3})/.exec(message)
    const status = statusMatch?.[1] ?? '错误'
    return `天气瓦片请求失败（HTTP ${status}），服务暂时不可达`
  }
  const oneLine = message.replace(/\s+/g, ' ').trim()
  return oneLine.length > maxLen ? `${oneLine.slice(0, maxLen)}…` : oneLine
}

export function classifyTileError(err: unknown): { type: WeatherTileErrorType; message: string } {
  const raw = String((err as Error)?.message ?? err ?? '天气瓦片加载失败')
  if (raw.includes('timeout')) {
    return { type: 'timeout', message: '天气瓦片请求超时，上游可能限流，稍后自动重试' }
  }
  if (raw.includes('429')) {
    return { type: 'rate-limited', message: '天气 API 请求频率超限，请稍后重试' }
  }
  if (
    raw.includes('422') ||
    /all-null|empty payload|empty grid|model_empty|no usable data|无数据/i.test(raw)
  ) {
    return {
      type: 'data-empty',
      message: '本地模型无数据，请同步 Open-Meteo',
    }
  }
  if (
    raw.includes('503') ||
    raw.includes('502') ||
    raw.includes('504') ||
    /Bad gateway/i.test(raw)
  ) {
    return {
      type: 'circuit-open',
      message: '天气服务暂时不可达（网关/断路器），请稍后重试',
    }
  }
  // 兜底：绝不把 HTML 错误页原文推到地图横幅
  return { type: 'unknown', message: sanitizeUiErrorMessage(raw) }
}

export function isAbortError(err: unknown): boolean {
  return err instanceof DOMException && err.name === 'AbortError'
}
