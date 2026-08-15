// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiRequestError, SessionExpiredError } from '@/services/http-errors'
import { WorkflowValidationError, requestJson, resolveApiUrl } from '@/services/_http'

const handleSessionExpiredMock = vi.fn()
const withWriteAuthHeadersMock = vi.fn((headers: Record<string, string>) => headers)
const loadingShowMock = vi.fn()
const loadingHideMock = vi.fn()

vi.mock('@/services/session-expired', () => ({
  handleSessionExpired: (...args: unknown[]) => handleSessionExpiredMock(...args),
  isAuthBootstrapPath: (path: string) => {
    const normalized = path.split('?')[0] ?? path
    return (
      normalized === '/auth/login' ||
      normalized === '/auth/config' ||
      normalized === '/auth/me' ||
      normalized === '/auth/logout'
    )
  },
}))

vi.mock('@/services/backend-auth', () => ({
  withWriteAuthHeaders: (...args: unknown[]) => withWriteAuthHeadersMock(...(args as [Record<string, string>])),
}))

vi.mock('@/stores/log', () => ({
  useLogStore: () => ({ logOperation: vi.fn() }),
}))

vi.mock('@/stores/ui-loading', () => ({
  useUiLoadingStore: () => ({ show: loadingShowMock, hide: loadingHideMock }),
}))

function jsonResponse(body: unknown, status: number, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

describe('resolveApiUrl', () => {
  it('passes through absolute http(s) URLs untouched', () => {
    expect(resolveApiUrl('https://example.com/api/x')).toBe('https://example.com/api/x')
  })

  it('normalizes relative paths to leading slash', () => {
    expect(resolveApiUrl('layers/1').startsWith('/layers/1')).toBe(true)
    expect(resolveApiUrl('/layers/1').startsWith('/layers/1')).toBe(true)
  })
})

describe('requestJson', () => {
  beforeEach(() => {
    handleSessionExpiredMock.mockClear()
    withWriteAuthHeadersMock.mockClear()
    loadingShowMock.mockClear()
    loadingHideMock.mockClear()
    vi.stubGlobal('fetch', vi.fn())
  })

  it('throws WorkflowValidationError for structured 422', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse(
        {
          error_type: 'validation',
          user_message: '参数有误',
          issues: [{ field: 'mode', message: 'invalid' }],
        },
        422,
      ),
    )

    const err = await requestJson('/workflow-runs', { method: 'POST', body: '{}' }).catch(
      (e) => e,
    )
    expect(err).toBeInstanceOf(WorkflowValidationError)
    expect((err as WorkflowValidationError).issues).toEqual([
      { field: 'mode', message: 'invalid' },
    ])
  })

  it('unwraps validation payload nested in FastAPI detail envelope', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse(
        {
          detail: {
            error_type: 'validation',
            issues: [{ field: 'bbox', message: 'out of range' }],
          },
        },
        422,
      ),
    )

    const err = await requestJson('/workflow-runs', { silent: true, method: 'POST' }).catch((e) => e)
    expect(err).toBeInstanceOf(WorkflowValidationError)
    expect((err as WorkflowValidationError).issues[0].field).toBe('bbox')
  })

  it('redirects on 401 for protected endpoints', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ detail: 'Unauthorized' }, 401))

    await expect(requestJson('/layers', { silent: true })).rejects.toBeInstanceOf(
      SessionExpiredError,
    )
    expect(handleSessionExpiredMock).toHaveBeenCalled()
  })

  it('does not redirect on 401 for auth bootstrap path', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ detail: 'Unauthorized' }, 401))

    const err = await requestJson('/auth/me', { silent: true }).catch((e) => e)
    expect(err).toBeInstanceOf(ApiRequestError)
    expect((err as ApiRequestError).status).toBe(401)
    expect(handleSessionExpiredMock).not.toHaveBeenCalled()
  })

  it('throws ApiRequestError on 403', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ detail: 'Forbidden' }, 403))

    const err = await requestJson('/config/api-keys', { silent: true }).catch((e) => e)
    expect(err).toBeInstanceOf(ApiRequestError)
    expect((err as ApiRequestError).status).toBe(403)
    expect((err as ApiRequestError).message).toBe('Forbidden')
  })

  it('propagates Retry-After seconds on 429', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ detail: 'too many' }, 429, { 'Retry-After': '5' }),
    )

    const err = await requestJson('/workflow-runs', { silent: true, method: 'POST' }).catch(
      (e) => e,
    )
    expect((err as ApiRequestError).retryAfterSec).toBe(5)
  })

  it('ignores non-numeric Retry-After', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ detail: 'too many' }, 429, { 'Retry-After': 'soon' }),
    )

    const err = await requestJson('/workflow-runs', { silent: true, method: 'POST' }).catch(
      (e) => e,
    )
    expect((err as ApiRequestError).retryAfterSec).toBeUndefined()
  })

  it('extracts request_id and error_code into ApiRequestError', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ request_id: 'req-1', error_code: 'C429001' }, 500),
    )

    const err = await requestJson('/health', { silent: true }).catch((e) => e)
    expect((err as ApiRequestError).requestId).toBe('req-1')
    expect((err as ApiRequestError).errorCode).toBe('C429001')
  })

  it('prefers user_message over error/detail in failure message', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ user_message: '面向用户', error: 'internal', detail: 'd' }, 502),
    )

    const err = await requestJson('/health', { silent: true }).catch((e) => e)
    expect((err as ApiRequestError).message).toContain('面向用户')
  })

  it('returns undefined for 204 when allowEmpty', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 204 }))

    await expect(
      requestJson('/auth/logout', { method: 'POST', allowEmpty: true, silent: true }),
    ).resolves.toBeUndefined()
  })

  it('rejects on 204 without allowEmpty (contract mismatch surfaced)', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 204 }))

    await expect(requestJson('/x', { silent: true })).rejects.toThrow()
  })

  it('maps network failures to readable errors', async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError('Failed to fetch'))

    await expect(requestJson('/health', { silent: true })).rejects.toThrow(/网络不可用/)
  })

  it('converts timeout abort into readable error', async () => {
    vi.mocked(fetch).mockImplementationOnce(
      (_url: unknown, init?: RequestInit) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(init.signal?.reason))
        }),
    )

    await expect(
      requestJson('/health', { silent: true, timeoutMs: 5 }),
    ).rejects.toThrow(/请求超时/)
  })

  it('rethrows external abort signal untouched', async () => {
    const external = new AbortController()
    const reason = new DOMException('user cancelled', 'AbortError')
    vi.mocked(fetch).mockImplementationOnce(
      (_url: unknown, init?: RequestInit) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(init.signal?.reason))
          external.abort(reason)
        }),
    )

    const err = await requestJson('/health', {
      silent: true,
      signal: external.signal,
    }).catch((e) => e)
    expect(err).toBe(reason)
  })

  it('shows and hides global loading for non-silent requests', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ ok: true }, 200))

    await requestJson('/health')
    expect(loadingShowMock).toHaveBeenCalledTimes(1)
    expect(loadingHideMock).toHaveBeenCalledTimes(1)
  })

  it('skips global loading for silent requests', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ ok: true }, 200))

    await requestJson('/health', { silent: true })
    expect(loadingShowMock).not.toHaveBeenCalled()
    expect(loadingHideMock).not.toHaveBeenCalled()
  })

  it('merges caller headers over default Content-Type and passes method to auth headers', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ ok: true }, 200))

    await requestJson('/x', {
      method: 'PATCH',
      silent: true,
      headers: { 'Content-Type': 'text/plain', 'X-Custom': '1' },
    })

    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    const headers = init.headers as Record<string, string>
    expect(headers['Content-Type']).toBe('text/plain')
    expect(headers['X-Custom']).toBe('1')
    expect(withWriteAuthHeadersMock).toHaveBeenCalledWith(
      expect.anything(),
      'PATCH',
      undefined,
    )
  })

  it('forwards sensitiveGet flag to write-auth header builder on GET', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse([], 200))

    await requestJson('/auth/users', { silent: true, sensitiveGet: true })

    expect(withWriteAuthHeadersMock).toHaveBeenCalledWith(expect.anything(), 'GET', true)
  })

  it('sends credentials include and returns parsed body', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ value: 42 }, 200))

    const result = await requestJson<{ value: number }>('/health', { silent: true })
    expect(result).toEqual({ value: 42 })
    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(init.credentials).toBe('include')
  })
})
