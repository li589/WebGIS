import { describe, expect, it } from 'vitest'

import { resolveLoginThemeStyle } from '@/views/login-theme-presets'

describe('login-theme-presets', () => {
  it('sgfs slug falls back to cyan palette', () => {
    const style = resolveLoginThemeStyle('sgfs')
    expect(style['--login-title-base']).toBe('#f5fcff')
    expect(style['--login-accent']).toBe('#5ad5ff')
  })

  it('warm-soil slug falls back to warm palette', () => {
    const style = resolveLoginThemeStyle('warm-soil')
    expect(style['--login-accent']).toBe('#ffc878')
    expect(style['--login-title-base']).toBe('#fff8ef')
  })

  it('login_palette green overrides slug accent', () => {
    const style = resolveLoginThemeStyle('sgfs', 'green')
    expect(style['--login-accent']).toBe('#5dce8a')
    expect(style['--login-title-base']).toBe('#f2fff6')
  })

  it('palette id as first arg resolves without second arg', () => {
    expect(resolveLoginThemeStyle('violet')['--login-accent']).toBe('#b49cff')
    expect(resolveLoginThemeStyle('slate')['--login-accent']).toBe('#9eb0c4')
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
