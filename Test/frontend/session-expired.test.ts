// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'

const clearSessionMock = vi.fn()
const replaceMock = vi.fn()

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    clearSession: clearSessionMock,
  }),
}))

vi.mock('@/app/router', () => ({
  router: {
    replace: (...args: unknown[]) => replaceMock(...args),
  },
}))

describe('session-expired', () => {
  beforeEach(() => {
    clearSessionMock.mockClear()
    replaceMock.mockReset()
    replaceMock.mockResolvedValue(undefined)
    window.history.pushState({}, '', '/')
    vi.resetModules()
  })

  describe('handleSessionExpired', () => {
    it('redirects to login with SPA path when API path is passed', async () => {
      const { handleSessionExpired } = await import('@/services/session-expired')
      handleSessionExpired('/runtime/status')
      await vi.waitFor(() => expect(replaceMock).toHaveBeenCalled())
      expect(replaceMock).toHaveBeenCalledWith({
        name: 'login',
        query: { redirect: '/' },
      })
      expect(clearSessionMock).toHaveBeenCalledTimes(1)
    })

    it('ignores concurrent calls while redirect is in flight', async () => {
      let resolveReplace!: () => void
      replaceMock.mockReturnValueOnce(
        new Promise<void>((resolve) => {
          resolveReplace = resolve
        }),
      )
      const { handleSessionExpired } = await import('@/services/session-expired')
      handleSessionExpired()
      handleSessionExpired()
      await vi.waitFor(() => expect(replaceMock).toHaveBeenCalledTimes(1))
      expect(clearSessionMock).toHaveBeenCalledTimes(1)
      resolveReplace()
      await vi.waitFor(() => expect(replaceMock).toHaveBeenCalledTimes(1))
    })
  })

  describe('isAuthBootstrapPath', () => {
    it('matches auth bootstrap endpoints only', async () => {
      const { isAuthBootstrapPath } = await import('@/services/session-expired')
      expect(isAuthBootstrapPath('/auth/me')).toBe(true)
      expect(isAuthBootstrapPath('/auth/config')).toBe(true)
      expect(isAuthBootstrapPath('/layers')).toBe(false)
      expect(isAuthBootstrapPath('/runtime/status')).toBe(false)
    })
  })
})
