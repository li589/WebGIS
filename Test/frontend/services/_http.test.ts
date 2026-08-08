// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiRequestError, SessionExpiredError } from '@/services/http-errors'
import { WorkflowValidationError, requestJson } from '@/services/_http'

const handleSessionExpiredMock = vi.fn()

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
  withWriteAuthHeaders: (headers: Record<string, string>) => headers,
}))

vi.mock('@/stores/log', () => ({
  useLogStore: () => ({ logOperation: vi.fn() }),
}))

vi.mock('@/stores/ui-loading', () => ({
  useUiLoadingStore: () => ({ show: vi.fn(), hide: vi.fn() }),
}))

describe('requestJson', () => {
  beforeEach(() => {
    handleSessionExpiredMock.mockClear()
    vi.stubGlobal('fetch', vi.fn())
  })

  it('throws WorkflowValidationError for structured 422', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error_type: 'validation',
          user_message: '参数有误',
          issues: [{ field: 'mode', message: 'invalid' }],
        }),
        { status: 422, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    await expect(requestJson('/workflow-runs', { method: 'POST', body: '{}' })).rejects.toBeInstanceOf(
      WorkflowValidationError,
    )
  })

  it('redirects on 401 for protected endpoints', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: 'Unauthorized' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    await expect(requestJson('/layers', { silent: true })).rejects.toBeInstanceOf(
      SessionExpiredError,
    )
    expect(handleSessionExpiredMock).toHaveBeenCalled()
  })

  it('throws ApiRequestError on 403', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: 'Forbidden' }), {
        status: 403,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const err = await requestJson('/config/api-keys', { silent: true }).catch((e) => e)
    expect(err).toBeInstanceOf(ApiRequestError)
    expect((err as ApiRequestError).status).toBe(403)
  })

  it('maps network failures to readable errors', async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError('Failed to fetch'))

    await expect(requestJson('/health', { silent: true })).rejects.toThrow(/网络不可用/)
  })
})
