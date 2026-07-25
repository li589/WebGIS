/**
 * 统一 HTTP fetch 包装器（Sprint 3.6 抽取）。
 *
 * 此前 runtime-api.ts 和 workflow-definition-api.ts 各自维护了一份近乎相同的
 * requestJson 实现，差异仅在于：204 处理、错误体字段名（detail vs user_message）。
 * 本模块统一这些差异，通过 options 暴露可选行为：
 *
 *   - `timeoutMs`：超时毫秒数，默认 30000。超时通过 AbortController.abort() 触发。
 *   - `silent`：true 时跳过全局 ui-loading（轮询/热路径）。
 *   - 非 silent 默认走 compact 顶栏，不挡全屏地球动画。
 *   - 大面板首开请用 ui-loading.showImmediate（hero）。
 *   - `allowEmpty`：true 时 204 No Content 返回 undefined（适用于 DELETE 等无响应体端点）。
 *
 * 不纳入本模块的场景：
 *   - weather-tile-api.ts 的 fetchWeatherTile：需要组合外部 AbortSignal + 不需要 auth
 *     头 + 不需要 loading + tile 专用超时，模式差异过大，强行合并会降低可读性。
 *   - 需要原始 Response 对象的调用方：直接使用 fetch。
 */
import { withWriteAuthHeaders } from './backend-auth'
import { useUiLoadingStore } from '../stores/ui-loading'

/**
 * 字段级校验问题，对应后端 WorkflowValidationError 的 issues 元素。
 */
export interface ValidationIssue {
  /** 字段路径，如 "algorithm_params.mode" / "datasource_selection.input_dir"。 */
  field: string
  /** 人类可读的校验错误描述。 */
  message: string
}

/**
 * 提交期参数预校验错误。
 *
 * 后端 submission_service 在提交阶段调用 validate_request_against_template
 * 做静态校验，失败时返回 422 + {"error_type":"validation","issues":[...]}。
 * 本类携带字段级 issues 列表，供调用方（如表单组件）定位具体字段并展示
 * 行内错误，而非仅显示一个笼统的错误消息。
 *
 * 调用方可用 `instanceof WorkflowValidationError` 区分校验错误与其他
 * 网络/服务器错误，进而决定是否把 issues 映射到表单字段。
 */
export class WorkflowValidationError extends Error {
  /** 字段级校验问题列表，供 UI 定位具体表单字段。 */
  readonly issues: ValidationIssue[]
  /** HTTP 状态码（通常为 422）。 */
  readonly status: number
  /** 请求路径，便于调试。 */
  readonly path: string

  constructor(message: string, issues: ValidationIssue[], path = '', status = 422) {
    super(message)
    this.name = 'WorkflowValidationError'
    this.issues = issues
    this.status = status
    this.path = path
  }
}

/**
 * 从后端错误响应体中提取结构化校验负载。
 *
 * 兼容两种返回格式：
 *   1. FastAPI HTTPException 包裹：{"detail": {"error_type": "validation", ...}}
 *   2. 扁平结构：{"error_type": "validation", ...}
 *
 * 非 validation 类型或不包含 issues 数组时返回 null。
 */
function extractValidationPayload(
  errorBody: any,
): { user_message?: string; issues: ValidationIssue[] } | null {
  if (!errorBody || typeof errorBody !== 'object') return null
  // 扁平结构
  if (errorBody.error_type === 'validation' && Array.isArray(errorBody.issues)) {
    return {
      user_message: typeof errorBody.user_message === 'string' ? errorBody.user_message : undefined,
      issues: errorBody.issues as ValidationIssue[],
    }
  }
  // FastAPI HTTPException 包裹在 detail 里
  const detail = errorBody.detail
  if (
    detail &&
    typeof detail === 'object' &&
    !Array.isArray(detail) &&
    detail.error_type === 'validation' &&
    Array.isArray(detail.issues)
  ) {
    return {
      user_message: typeof detail.user_message === 'string' ? detail.user_message : undefined,
      issues: detail.issues as ValidationIssue[],
    }
  }
  return null
}

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
 *      若响应体为结构化校验错误（error_type="validation" + issues 数组），
 *      抛出 WorkflowValidationError（携带字段级 issues）而非普通 Error。
 *   6. allowEmpty=true 且状态码 204 时返回 undefined as T；否则统一 await response.json()。
 *
 * 量纲：timeoutMs 单位毫秒；HTTP status 单位为 status code。
 */
export async function requestJson<T>(path: string, init?: RequestJsonInit): Promise<T> {
  const { headers: initHeaders, timeoutMs, silent, allowEmpty, ...restInit } = init ?? {}
  const method = (restInit.method ?? 'GET').toString()
  const mergedHeaders: Record<string, string> = withWriteAuthHeaders(
    {
      'Content-Type': 'application/json',
      ...(initHeaders as Record<string, string> | undefined),
    },
    method,
  )

  const effectiveTimeout = timeoutMs ?? 30000
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => {
    // 带 reason，避免浏览器默认文案 “signal is aborted without reason”
    controller.abort(new DOMException(`请求超时（${effectiveTimeout}ms）`, 'AbortError'))
  }, effectiveTimeout)

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
      let errorBody: any = null
      let errorDetail = ''
      try {
        errorBody = await response.json()
        errorDetail =
          (typeof errorBody?.user_message === 'string' && errorBody.user_message) ||
          (typeof errorBody?.error === 'string' && errorBody.error) ||
          (typeof errorBody?.detail === 'string' ? errorBody.detail : '') ||
          JSON.stringify(errorBody)
      } catch {
        errorDetail = await response.text().catch(() => '')
      }
      // 结构化校验错误：携带字段级 issues 供 UI 定位具体表单字段。
      // 后端 FastAPI HTTPException 把 detail 包在 {"detail": {...}} 里，
      // extractValidationPayload 兼容扁平与包裹两种格式。
      const validationPayload = extractValidationPayload(errorBody)
      if (validationPayload) {
        throw new WorkflowValidationError(
          validationPayload.user_message || '参数校验失败',
          validationPayload.issues,
          path,
          response.status,
        )
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
  } catch (err) {
    // 超时 Abort → 可读错误；外部主动 abort 仍抛原始 AbortError
    if (err instanceof DOMException && err.name === 'AbortError') {
      if (restInit.signal?.aborted) throw err
      const reason = controller.signal.reason
      const reasonMsg =
        reason instanceof DOMException ? reason.message : typeof reason === 'string' ? reason : ''
      throw new Error(reasonMsg || `请求超时（${effectiveTimeout}ms）：${path}`, { cause: err })
    }
    if (err instanceof TypeError && /fetch|network|Failed to fetch/i.test(err.message)) {
      throw new Error(`网络不可用或服务未启动：${path}`, { cause: err })
    }
    throw err
  } finally {
    window.clearTimeout(timeoutId)
    // 对应 try 前的 loading.show()，非 silent 请求完成后隐藏 loading
    if (!silent) {
      loading.hide()
    }
  }
}
