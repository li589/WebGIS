import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useOverlaySymbologyStore } from '@/stores/overlay-symbology'

function mockOverlaysAndBounds(handlers: {
  overlays?: string[]
  bounds?: (id: string) => { ok: boolean; status?: number; meta?: Record<string, unknown> }
}) {
  return vi.fn(async (url: string) => {
    const path = String(url)
    if (path.includes('/overlays') && !path.includes('overlay-bounds')) {
      return {
        ok: true,
        json: async () => ({ overlay_layer_ids: handlers.overlays ?? [] }),
      }
    }
    if (path.includes('/overlay-bounds/')) {
      const id = path.split('/overlay-bounds/')[1]?.split('?')[0] ?? ''
      const result = handlers.bounds?.(id) ?? { ok: false, status: 404 }
      if (!result.ok) {
        return { ok: false, status: result.status ?? 404 }
      }
      return {
        ok: true,
        json: async () => ({ meta: result.meta ?? {} }),
      }
    }
    return { ok: false, status: 404 }
  })
}

describe('overlay-symbology store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('skips bounds fetch for catalog ids not in /overlays registry', async () => {
    const store = useOverlaySymbologyStore()
    const fetchMock = mockOverlaysAndBounds({ overlays: ['aridity-cn'] })
    vi.stubGlobal('fetch', fetchMock)

    await store.ensureMeta('omega-sf-fenkuai')
    expect(store.getMeta('omega-sf-fenkuai')).toEqual({})
    expect(store.shouldSkipFetch('omega-sf-fenkuai')).toBe(true)
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('/overlay-bounds/'))).toBe(
      false,
    )
  })

  it('retries after miss TTL instead of sticky empty forever', async () => {
    const store = useOverlaySymbologyStore()
    let boundsCalls = 0
    const fetchMock = mockOverlaysAndBounds({
      overlays: ['layer-a'],
      bounds: () => {
        boundsCalls += 1
        if (boundsCalls === 1) return { ok: false, status: 404 }
        return { ok: true, meta: { palette: 'viridis', vmin: 0, vmax: 1 } }
      },
    })
    vi.stubGlobal('fetch', fetchMock)

    await store.ensureMeta('layer-a')
    expect(store.getMeta('layer-a')).toEqual({})
    expect(store.shouldSkipFetch('layer-a')).toBe(true)

    // 强制跳过退避，模拟重试
    await store.ensureMeta('layer-a', { force: true })
    expect(store.getMeta('layer-a')?.palette).toBe('viridis')
    expect(boundsCalls).toBe(2)
  })

  it('putMeta overrides miss and bumps version', async () => {
    const store = useOverlaySymbologyStore()
    vi.stubGlobal(
      'fetch',
      mockOverlaysAndBounds({
        overlays: ['layer-b'],
        bounds: () => ({ ok: false, status: 404 }),
      }),
    )
    await store.ensureMeta('layer-b')
    const v0 = store.version
    store.putMeta('layer-b', { palette: 'reds', unit: 'x' })
    expect(store.getMeta('layer-b')?.palette).toBe('reds')
    expect(store.version).toBeGreaterThan(v0)
  })
})
