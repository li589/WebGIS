export class ApiRequestError extends Error {
  readonly status: number
  readonly path: string
  readonly requestId?: string
  /** 后端统一业务错误码（如 C403001 / C429001，见后端 app/api/error_codes.py）。 */
  readonly errorCode?: string
  /** 429 限流时后端返回的 Retry-After（秒），供调用方提示退避。 */
  readonly retryAfterSec?: number

  constructor(
    message: string,
    status: number,
    path: string,
    requestId?: string,
    errorCode?: string,
    retryAfterSec?: number,
  ) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = status
    this.path = path
    this.requestId = requestId
    this.errorCode = errorCode
    this.retryAfterSec = retryAfterSec
  }
}

export class SessionExpiredError extends Error {
  readonly path: string

  constructor(path: string) {
    super('会话已过期，请重新登录')
    this.name = 'SessionExpiredError'
    this.path = path
  }
}

export function extractRequestId(body: unknown): string | undefined {
  if (!body || typeof body !== 'object') return undefined
  const rec = body as Record<string, unknown>
  return typeof rec.request_id === 'string' ? rec.request_id : undefined
}

export function extractErrorCode(body: unknown): string | undefined {
  if (!body || typeof body !== 'object') return undefined
  const rec = body as Record<string, unknown>
  return typeof rec.error_code === 'string' ? rec.error_code : undefined
}

export function extractErrorDetail(body: unknown, fallbackText = ''): string {
  if (!body || typeof body !== 'object') return fallbackText
  const bodyRec = body as Record<string, unknown>
  const userMsg = typeof bodyRec.user_message === 'string' ? bodyRec.user_message : ''
  const err = typeof bodyRec.error === 'string' ? bodyRec.error : ''
  const detail = typeof bodyRec.detail === 'string' ? bodyRec.detail : ''
  if (userMsg || err || detail) return userMsg || err || detail
  return fallbackText || JSON.stringify(body)
}
