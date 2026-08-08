export class ApiRequestError extends Error {
  readonly status: number
  readonly path: string
  readonly requestId?: string

  constructor(message: string, status: number, path: string, requestId?: string) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = status
    this.path = path
    this.requestId = requestId
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

export function extractErrorDetail(body: unknown, fallbackText = ''): string {
  if (!body || typeof body !== 'object') return fallbackText
  const bodyRec = body as Record<string, unknown>
  const userMsg = typeof bodyRec.user_message === 'string' ? bodyRec.user_message : ''
  const err = typeof bodyRec.error === 'string' ? bodyRec.error : ''
  const detail = typeof bodyRec.detail === 'string' ? bodyRec.detail : ''
  if (userMsg || err || detail) return userMsg || err || detail
  return fallbackText || JSON.stringify(body)
}
