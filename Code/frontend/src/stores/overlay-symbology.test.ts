import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useOverlaySymbologyStore } from './overlay-symbology'

describe('overlay-symbology store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('retries after miss TTL instead of sticky empty forever', async () => {
    const store = useOverlaySymbologyStore()
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 404 })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ meta: { palette: 'viridis', vmin: 0, vmax: 1 } }),
      })
    vi.stubGlobal('fetch', fetchMock)

    await store.ensureMeta('layer-a')
    expect(store.getMeta('layer-a')).toEqual({})
    expect(store.shouldSkipFetch('layer-a')).toBe(true)

    // 强制跳过退避，模拟重试
    await store.ensureMeta('layer-a', { force: true })
    expect(store.getMeta('layer-a')?.palette).toBe('viridis')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('putMeta overrides miss and bumps version', async () => {
    const store = useOverlaySymbologyStore()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }))
    await store.ensureMeta('layer-b')
    const v0 = store.version
    store.putMeta('layer-b', { palette: 'reds', unit: 'x' })
    expect(store.getMeta('layer-b')?.palette).toBe('reds')
    expect(store.version).toBeGreaterThan(v0)
  })
})
