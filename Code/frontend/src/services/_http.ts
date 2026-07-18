/**
 * 统一 HTTP fetch 包装器（Sprint 3.6 抽取）。
 *
 * 此前 runtime-api.ts 和 workflow-definition-api.ts 各自维护了一份近乎相同的
 * requestJson 实现，差异仅在于：204 处理、错误体字段名（detail vs user_message）。
 * 本模块统一这些差异，通过 options 暴露可选行为：
 *
 *   - `timeoutMs`：超时毫秒数，默认 30000。超时通过 AbortController.abort() 触发。
 *   - `silent`：true 时跳过全局 ui-loading 动效（适用于轮询、热路径请求）。
 *   - `allowEmpty`：true 时 204 No Content 返回 undefined（适用于 DELETE 等无响应体端点）。
 *
 * 不纳入本模块的场景：
 *   - weather-tile-api.ts 的 fetchWeatherTile：需要组合外部 AbortSignal + 不需要 auth
 *     头 + 不需要 loading + tile 专用超时，模式差异过大，强行合并会降低可读性。
 *   - 需要原始 Response 对象的调用方：直接使用 fetch。
 */
import { withWriteAuthHeaders } from './backend-auth'
import { useUiLoadingStore } from '../stores/ui-loading'

export function getApiBaseUrl(): string {
  // 开发模式走 Vite proxy（相对路径），避免 CORS 问题
  if (import.meta.env.DEV) return ''
  return import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
}

export function resolveApiUrl(pathOrUrl: string): string {
  if (/^https?:\/\//i.test(pathOrUrl)) return pathOrUrl
  const normalizedPath = pathOrUrl.startsWith('/') ? pathOrUrl : `/${pathOrUrl}`
  return `${getApiBaseUrl()}${normalizedPath}`
}

export interface RequestJsonInit extends RequestInit {
  /** 超时毫秒数，默认 30000。 */
  timeoutMs?: number
  /** true 时跳过全局 loading 动效（轮询/热路径）。 */
  silent?: boolean
  /** true 时允许 204 No Content 返回 undefined（DELETE 等无响应体端点）。 */
  allowEmpty?: boolean
}

/**
 * 统一 JSON fetch 包装器。
 *
 * 行为契约：
 *   1. 默认 GET 方法；非 GET/HEAD/OPTIONS 自动附加 X-Api-Key（via withWriteAuthHeaders）。
 *   2. 默认 Content-Type: application/json，可通过 init.headers 覆盖。
 *   3. 默认 30s 超时，通过 AbortController 实现；外部 init.signal 优先于超时 signal。
 *   4. 非 silent 请求触发全局 loading（300ms 延迟显示，避免短请求闪烁，由 store 实现）。
 *   5. 错误响应解析顺序：user_message → error → detail → JSON.stringify(body) → text。
 *   6. allowEmpty=true 且状态码 204 时返回 undefined as T；否则统一 await response.json()。
 *
 * 量纲：timeoutMs 单位毫秒；HTTP status 单位为 status code。
 */
export async function requestJson<T>(
  path: string,
  init?: RequestJsonInit,
): Promise<T> {
  const { headers: initHeaders, timeoutMs, silent, allowEmpty, ...restInit } = init ?? {}
  const method = (restInit.method ?? 'GET').toString()
  const mergedHeaders: Record<string, string> = withWriteAuthHeaders(
    {
      'Content-Type': 'application/json',
      ...(initHeaders as Record<string, string> | undefined),
    },
    method,
  )

  const controller = new AbortController()
  const timeoutId = window.setTimeout(
    () => controller.abort(),
    timeoutMs ?? 30000,
  )

  // 全局 loading 管理：非 silent 请求触发 loading 动效
  // 300ms 延迟显示机制确保短请求不闪烁（在 store 内部实现）
  const loading = useUiLoadingStore()
  if (!silent) {
    loading.show()
  }

  try {
    const response = await fetch(resolveApiUrl(path), {
      ...restInit,
      headers: mergedHeaders,
      signal: restInit.signal ?? controller.signal,
    })

    if (!response.ok) {
      // 解析结构化错误体（兼容 user_message / error / detail 三种字段命名）
      let errorDetail = ''
      try {
        const errorBody = await response.json()
        errorDetail =
          errorBody?.user_message ||
          errorBody?.error ||
          errorBody?.detail ||
          JSON.stringify(errorBody)
      } catch {
        errorDetail = await response.text().catch(() => '')
      }
      throw new Error(
        `Request failed: ${response.status} ${path}${errorDetail ? ` - ${errorDetail}` : ''}`,
      )
    }

    // 204 No Content：仅在 allowEmpty=true 时返回 undefined
    if (response.status === 204) {
      if (allowEmpty) return undefined as T
      // allowEmpty=false 时仍尝试解析 JSON（与原 runtime-api.ts 行为一致，
      // 对端返回 204 但调用方期望 JSON 时会抛出 SyntaxError，暴露契约不一致）
    }
    return (await response.json()) as T
  } finally {
    window.clearTimeout(timeoutId)
    // 对应 try 前的 loading.show()，非 silent 请求完成后隐藏 loading
    if (!silent) {
      loading.hide()
    }
  }
}