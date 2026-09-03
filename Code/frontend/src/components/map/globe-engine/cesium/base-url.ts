/**
 * Cesium 静态资源基址（Workers / Assets / Widgets）。
 * Vite 构建由 vite-plugin-cesium（或等价拷贝）把资源放到 dist 下；
 * 开发态由插件注入 / 同源路径。
 */

declare global {
  interface Window {
    CESIUM_BASE_URL?: string
  }
}

const DEFAULT_BASE = '/cesium/'

/** 在首次 import('cesium') 之前调用。 */
export function ensureCesiumBaseUrl(baseUrl: string = DEFAULT_BASE): void {
  if (typeof window === 'undefined') return
  if (window.CESIUM_BASE_URL) return
  const normalized = baseUrl.endsWith('/') ? baseUrl : `${baseUrl}/`
  window.CESIUM_BASE_URL = normalized
}

export function getCesiumBaseUrl(): string {
  if (typeof window !== 'undefined' && window.CESIUM_BASE_URL) {
    return window.CESIUM_BASE_URL
  }
  return DEFAULT_BASE
}
