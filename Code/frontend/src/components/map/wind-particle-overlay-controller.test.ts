import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

import { WindParticleOverlayController } from './wind-particle-overlay-controller'

describe('WindParticleOverlayController fetch abort', () => {
  const originalFetch = globalThis.fetch

  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.useRealTimers()
  })

  it('aborts in-flight geojson fetch when a newer sync starts', async () => {
    const signals: AbortSignal[] = []
    globalThis.fetch = vi.fn((_url: string, init?: RequestInit) => {
      const signal = init!.signal as AbortSignal
      signals.push(signal)
      return new Promise((_resolve, reject) => {
        if (signal.aborted) {
          reject(new DOMException('Aborted', 'AbortError'))
          return
        }
        signal.addEventListener('abort', () => {
          reject(new DOMException('Aborted', 'AbortError'))
        })
      })
    }) as typeof fetch

    const map = {
      getLayer: vi.fn(() => undefined),
      removeLayer: vi.fn(),
      getSource: vi.fn(() => undefined),
      removeSource: vi.fn(),
    }

    const controller = new WindParticleOverlayController(map as any)
    controller.activeCatalogId = 'wind-field'

    const overlayState = {
      catalogId: 'wind-field',
      geojsonUrl: 'https://example.com/a.geojson',
      geojsonData: null,
      renderHint: { paint_mode: 'particle_flow' },
    } as any

    const syncOptions = {
      overlayToken: 1,
      getSyncWeatherToken: () => 1,
      getEnabledParticleFlowCatalogId: () => 'wind-field',
    }

    const first = controller.sync(overlayState, syncOptions)
    expect(signals).toHaveLength(1)
    expect(signals[0].aborted).toBe(false)

    const second = controller.sync(
      { ...overlayState, geojsonUrl: 'https://example.com/b.geojson' },
      syncOptions,
    )
    expect(signals).toHaveLength(2)
    expect(signals[0].aborted).toBe(true)

    controller.reset()
    await Promise.allSettled([first, second])
  })
})
