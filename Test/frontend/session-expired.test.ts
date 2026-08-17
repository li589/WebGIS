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

  describe('clearLocalSession', () => {
    it('delegates to auth store without redirect', async () => {
      const { clearLocalSession } = await import('@/services/session-expired')
      clearLocalSession()
      expect(clearSessionMock).toHaveBeenCalledTimes(1)
      await new Promise((r) => setTimeout(r, 0))
      expect(replaceMock).not.toHaveBeenCalled()
    })
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

    it('falls back to current location when no redirectPath is given', async () => {
      window.history.pushState({}, '', '/deployment?tab=1')
      const { handleSessionExpired } = await import('@/services/session-expired')
      handleSessionExpired()
      await vi.waitFor(() => expect(replaceMock).toHaveBeenCalled())
      expect(replaceMock).toHaveBeenCalledWith({
        name: 'login',
        query: { redirect: '/deployment?tab=1' },
      })
    })

    it('replaces /login redirectPath with current SPA fallback', async () => {
      window.history.pushState({}, '', '/deployment')
      const { handleSessionExpired } = await import('@/services/session-expired')
      handleSessionExpired('/login')
      await vi.waitFor(() => expect(replaceMock).toHaveBeenCalled())
      expect(replaceMock).toHaveBeenCalledWith({
        name: 'login',
        query: { redirect: '/deployment' },
      })
    })

    it('sanitizes external redirect targets via safeRedirect', async () => {
      const { handleSessionExpired } = await import('@/services/session-expired')
      handleSessionExpired('https://evil.example.com/phish')
      await vi.waitFor(() => expect(replaceMock).toHaveBeenCalled())
      expect(replaceMock).toHaveBeenCalledWith({
        name: 'login',
        query: { redirect: '/' },
      })
    })

    it('replaces backend /layers path with current SPA fallback', async () => {
      window.history.pushState({}, '', '/')
      const { handleSessionExpired } = await import('@/services/session-expired')
      handleSessionExpired('/layers?bbox=1')
      await vi.waitFor(() => expect(replaceMock).toHaveBeenCalled())
      expect(replaceMock).toHaveBeenCalledWith({
        name: 'login',
        query: { redirect: '/' },
      })
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
