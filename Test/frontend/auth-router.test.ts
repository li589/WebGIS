import { describe, expect, it } from 'vitest'

import { safeRedirect, isBackendApiPath } from '@/app/safe-redirect'

describe('safeRedirect', () => {
  it('allows dashboard root', () => {
    expect(safeRedirect('/')).toBe('/')
  })

  it('rejects open redirects', () => {
    expect(safeRedirect('//evil.example')).toBe('/')
    expect(safeRedirect('https://evil.example')).toBe('/')
    expect(safeRedirect(undefined)).toBe('/')
  })

  it('rejects encoded slashes and login loop targets', () => {
    expect(safeRedirect('/%2fevil')).toBe('/')
    expect(safeRedirect('/%2Fevil')).toBe('/')
    expect(safeRedirect('/login')).toBe('/')
    expect(safeRedirect('/login?redirect=/')).toBe('/')
  })

  it('rejects backend API paths mistaken as SPA routes', () => {
    expect(safeRedirect('/config/api-keys')).toBe('/')
    expect(safeRedirect('/auth/me')).toBe('/')
    expect(safeRedirect('/runtime/status')).toBe('/')
    expect(isBackendApiPath('/config/api-keys')).toBe(true)
  })

  it('rejects unknown SPA paths that would 404', () => {
    expect(safeRedirect('/layers')).toBe('/')
    expect(safeRedirect('/unknown-page')).toBe('/')
  })
})
