import { describe, expect, it } from 'vitest'

import { safeRedirect } from '@/app/safe-redirect'

describe('safeRedirect', () => {
  it('allows same-origin relative paths', () => {
    expect(safeRedirect('/layers')).toBe('/layers')
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
})
