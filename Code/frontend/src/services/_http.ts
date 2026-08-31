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
import { handleSessionExpired, isAuthBootstrapPath } from './session-expired'
import {
  ApiRequestError,
  SessionExpiredError,
  extractErrorCode,
  extractErrorDetail,
  extractRequestId,
} from './http-errors'
import { withWriteAuthHeaders } from './backend-auth'
import { useLogStore } from '../stores/log'
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
  errorBody: unknown,
): { user_message?: string; issues: ValidationIssue[] } | null {
  if (!errorBody || typeof errorBody !== 'object') return null
  const body = errorBody as Record<string, unknown>
  // 扁平结构
  if (body.error_type === 'validation' && Array.isArray(body.issues)) {
    return {
      user_message: typeof body.user_message === 'string' ? body.user_message : undefined,
      issues: body.issues as ValidationIssue[],
    }
  }
  // FastAPI HTTPException 包裹在 detail 里
  const detail = body.detail
  if (
    detail &&
    typeof detail === 'object' &&
    !Array.isArray(detail) &&
    (detail as Record<string, unknown>).error_type === 'validation' &&
    Array.isArray((detail as Record<string, unknown>).issues)
  ) {
    const detailRec = detail as Record<string, unknown>
    return {
      user_message: typeof detailRec.user_message === 'string' ? detailRec.user_message : undefined,
      issues: detailRec.issues as ValidationIssue[],
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
  /** true 时 GET/HEAD 也附加 X-Api-Key（敏感读端点，如 /runtime/*、/cleanup/*）。 */
  sensitiveGet?: boolean
}

function logApiFailure(path: string, message: string, details?: string, silent?: boolean): void {
  if (silent) return
  try {
    useLogStore().logOperation('api-error', message, details ?? `path=${path}`)
  } catch {
    // Pinia may be unavailable during early bootstrap tests.
  }
}

function handleHttpError(
  path: string,
  status: number,
  errorBody: unknown,
  errorDetail: string,
  silent?: boolean,
  retryAfterSec?: number,
): never {
  const requestId = extractRequestId(errorBody)
  const errorCode = extractErrorCode(errorBody)

  if (status === 401 && !isAuthBootstrapPath(path)) {
    logApiFailure(path, `未授权：${path}`, errorDetail, silent)
    handleSessionExpired(path)
    throw new SessionExpiredError(path)
  }

  if (status === 403) {
    const msg = errorDetail || '权限不足'
    logApiFailure(path, `禁止访问：${path}`, msg, silent)
    throw new ApiRequestError(msg, 403, path, requestId, errorCode)
  }

  const msg = `Request failed: ${status} ${path}${errorDetail ? ` - ${errorDetail}` : ''}`
  logApiFailure(path, `请求失败 ${status}`, msg, silent)
  throw new ApiRequestError(msg, status, path, requestId, errorCode, retryAfterSec)
}

/**
 * 统一 JSON fetch 包装器。
 *
 * 行为契约：
 *   1. 默认 GET 方法；非 GET/HEAD/OPTIONS 自动附加 X-Api-Key（via withWriteAuthHeaders）；
 *      sensitiveGet=true 时 GET/HEAD 也附加密钥（与 settings 敏感读一致）。
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
  const {
    headers: initHeaders,
    timeoutMs,
    silent,
    allowEmpty,
    sensitiveGet,
    ...restInit
  } = init ?? {}
  const method = (restInit.method ?? 'GET').toString()
  const mergedHeaders: Record<string, string> = withWriteAuthHeaders(
    {
      'Content-Type': 'application/json',
      ...(initHeaders as Record<string, string> | undefined),
    },
    method,
    sensitiveGet,
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
    // D-3：组合外部 signal 与超时 signal——此前 `restInit.signal ?? controller.signal`
    // 在调用方传 signal 时超时完全静默失效（getWeatherCoverage 等 8s 超时失效）。
    // AbortSignal.any 为 2024 标准（Chrome 116+）；旧环境手动桥接外部 signal
    // 到超时 controller，保证超时始终生效（悬挂请求会让全局 loading 永不结束）。
    let requestSignal: AbortSignal | null | undefined = controller.signal
    if (restInit.signal && typeof AbortSignal.any === 'function') {
      requestSignal = AbortSignal.any([restInit.signal, controller.signal])
    } else if (restInit.signal) {
      const external = restInit.signal
      if (external.aborted) {
        controller.abort(external.reason)
      } else {
        external.addEventListener('abort', () => controller.abort(external.reason), { once: true })
      }
      requestSignal = controller.signal
    }
    const response = await fetch(resolveApiUrl(path), {
      ...restInit,
      headers: mergedHeaders,
      signal: requestSignal,
      credentials: 'include',
    })

    if (!response.ok) {
      // 解析结构化错误体（兼容 user_message / error / detail 三种字段命名）
      let errorBody: unknown = null
      let errorDetail = ''
      try {
        errorBody = await response.json()
        const bodyRec =
          errorBody && typeof errorBody === 'object' ? (errorBody as Record<string, unknown>) : null
        const userMsg =
          bodyRec && typeof bodyRec.user_message === 'string' ? bodyRec.user_message : ''
        const err = bodyRec && typeof bodyRec.error === 'string' ? bodyRec.error : ''
        const detail = bodyRec && typeof bodyRec.detail === 'string' ? bodyRec.detail : ''
        errorDetail = userMsg || err || detail || JSON.stringify(errorBody)
      } catch {
        errorDetail = await response.text().catch(() => '')
      }
      const validationPayload = extractValidationPayload(errorBody)
      if (validationPayload) {
        if (!silent) {
          logApiFailure(path, `参数校验失败：${path}`, errorDetail, silent)
        }
        throw new WorkflowValidationError(
          validationPayload.user_message || '参数校验失败',
          validationPayload.issues,
          path,
          response.status,
        )
      }
      // 429 限流（C429001）：透传 Retry-After 供调用方退避提示。
      // 注意：写请求（POST/PUT/DELETE/PATCH）不做自动重试——重试存在重复
      // 提交/副作用风险（如重复创建工作流运行），由 UI 提示用户稍后操作。
      const retryAfterRaw = response.headers.get('Retry-After')
      const retryAfterSec = retryAfterRaw ? Number.parseInt(retryAfterRaw, 10) : undefined
      handleHttpError(
        path,
        response.status,
        errorBody,
        extractErrorDetail(errorBody, errorDetail),
        silent,
        Number.isFinite(retryAfterSec) && (retryAfterSec as number) > 0 ? retryAfterSec : undefined,
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
      const netMsg = `网络不可用或服务未启动：${path}`
      logApiFailure(path, netMsg, err.message, silent)
      throw new Error(netMsg, { cause: err })
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
