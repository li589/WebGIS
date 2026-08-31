// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  clearChunkReloadFlag,
  importLazyChunk,
  isChunkLoadError,
} from '@/utils/lazy-chunk'

describe('isChunkLoadError', () => {
  it('matches Vite dynamic import failures', () => {
    expect(
      isChunkLoadError(
        new TypeError(
          'Failed to fetch dynamically imported module: http://localhost:5175/assets/SettingsPanel-BJy-QsVQ.js',
        ),
      ),
    ).toBe(true)
    expect(isChunkLoadError(new Error('Loading chunk 12 failed'))).toBe(true)
    expect(isChunkLoadError(new Error('Importing a module script failed.'))).toBe(true)
  })

  it('ignores unrelated errors', () => {
    expect(isChunkLoadError(new Error('Network timeout'))).toBe(false)
    expect(isChunkLoadError(null)).toBe(false)
  })
})

describe('importLazyChunk', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  afterEach(() => {
    clearChunkReloadFlag()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('returns module on success and clears reload flag', async () => {
    sessionStorage.setItem('cgda:chunk-reload', '1')
    const mod = { default: 'ok' }
    await expect(importLazyChunk(async () => mod)).resolves.toBe(mod)
    expect(sessionStorage.getItem('cgda:chunk-reload')).toBeNull()
  })

  it('reloads once on chunk load failure', async () => {
    const reload = vi.fn()
    vi.stubGlobal('location', { ...window.location, reload })
    const pending = importLazyChunk(async () => {
      throw new TypeError(
        'Failed to fetch dynamically imported module: http://localhost:5175/assets/SettingsPanel-BJy-QsVQ.js',
      )
    })
    await Promise.race([
      pending.then(() => 'resolved'),
      new Promise((r) => setTimeout(() => r('pending'), 20)),
    ]).then((v) => expect(v).toBe('pending'))
    expect(reload).toHaveBeenCalledOnce()
    expect(sessionStorage.getItem('cgda:chunk-reload')).toBe('1')
  })

  it('rethrows after a failed reload attempt', async () => {
    sessionStorage.setItem('cgda:chunk-reload', '1')
    const reload = vi.fn()
    vi.stubGlobal('location', { ...window.location, reload })
    const err = new TypeError(
      'Failed to fetch dynamically imported module: http://localhost:5175/assets/SettingsPanel-BJy-QsVQ.js',
    )
    await expect(
      importLazyChunk(async () => {
        throw err
      }),
    ).rejects.toBe(err)
    expect(reload).not.toHaveBeenCalled()
    expect(sessionStorage.getItem('cgda:chunk-reload')).toBeNull()
  })
})
