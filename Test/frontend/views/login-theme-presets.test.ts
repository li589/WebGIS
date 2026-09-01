import { describe, expect, it } from 'vitest'

import { resolveLoginThemeStyle } from '@/views/login-theme-presets'

describe('login-theme-presets', () => {
  it('sgfs preset exposes high-contrast title base', () => {
    const style = resolveLoginThemeStyle('sgfs')
    expect(style['--login-title-base']).toBe('#f5fcff')
    expect(style['--login-accent']).toBe('#5ad5ff')
  })

  it('warm-soil preset differs from sgfs accent', () => {
    const style = resolveLoginThemeStyle('warm-soil')
    expect(style['--login-accent']).toBe('#ffc878')
    expect(style['--login-title-base']).toBe('#fff8ef')
  })

  it('unknown slug derives stable accent from hash', () => {
    const a = resolveLoginThemeStyle('lab-alpha')
    const b = resolveLoginThemeStyle('lab-alpha')
    const c = resolveLoginThemeStyle('lab-beta')
    expect(a['--login-accent']).toBe(b['--login-accent'])
    expect(a['--login-accent']).not.toBe(c['--login-accent'])
    expect(a['--login-title-base']).toBe('#f5fcff')
  })
})
