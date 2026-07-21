import { describe, expect, it, afterEach } from 'vitest'

import {
  PARTICLE_RESOLUTION_FULL,
  PARTICLE_RESOLUTION_LITE,
  isWindGlLiteRequested,
  resolveParticleResolution,
} from './wind-particle-gl-profile'

function installWindow(search: string): void {
  const store = new Map<string, string>()
  ;(globalThis as any).window = {
    location: { search },
    localStorage: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => store.set(k, v),
      removeItem: (k: string) => store.delete(k),
    },
  }
  ;(globalThis as any).document = undefined
}

describe('wind-particle-gl-profile', () => {
  afterEach(() => {
    delete (globalThis as any).window
    delete (globalThis as any).document
  })

  it('?windgl=lite 强制 lite 分辨率', () => {
    installWindow('?windgl=lite')
    expect(isWindGlLiteRequested()).toBe(true)
    expect(resolveParticleResolution()).toBe(PARTICLE_RESOLUTION_LITE)
  })

  it('无 lite 标记且无 document 时默认全量', () => {
    installWindow('')
    expect(resolveParticleResolution()).toBe(PARTICLE_RESOLUTION_FULL)
  })
})
