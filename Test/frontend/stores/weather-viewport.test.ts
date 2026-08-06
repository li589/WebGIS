import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createWeatherViewportSlice } from '@/stores/layers/weather-viewport'

const bboxA = { west: 110, south: 20, east: 115, north: 25, crs: 'EPSG:4326' as const }
const bboxB = { west: 100, south: 10, east: 105, north: 15, crs: 'EPSG:4326' as const }

describe('weather-viewport setMapViewport', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  function createSlice(setWeatherTileViewport = vi.fn()) {
    return {
      setWeatherTileViewport,
      slice: createWeatherViewportSlice({
        getActiveLayers: () => [{ catalogId: 'temperature', visible: true }],
        isWeatherEngineLayer: (id) => id === 'temperature',
        supportsViewportDrivenRefresh: () => false,
        getCurrentHour: () => 3,
        weatherProviderArg: () => 'auto',
        setWeatherTileViewport,
        onWorkflowViewportRefresh: vi.fn(),
        debugLog: vi.fn(),
      }),
    }
  }

  it('maxWait fires with the latest viewport, not the first snap', () => {
    const { setWeatherTileViewport, slice } = createSlice()

    // Keep zoom near-stable so debounce/maxWait stay on the normal (non zoom-out) path
    slice.setMapViewport({ lng: 112, lat: 22 }, bboxA, 5)
    for (let i = 0; i < 5; i += 1) {
      // Reset debounce every 90ms (< 120ms) so only maxWait can fire first
      vi.advanceTimersByTime(90)
      slice.setMapViewport({ lng: 100 + i, lat: 10 + i }, bboxB, 5 + i * 0.01)
    }
    vi.advanceTimersByTime(50)

    expect(setWeatherTileViewport.mock.calls.length).toBeGreaterThanOrEqual(1)
    const firstFire = setWeatherTileViewport.mock.calls[0]!
    // Old bug: maxWait closed over the first snap (112,22) and cleared the latest debounce
    expect(firstFire[1]).not.toEqual({ lng: 112, lat: 22 })
    expect((firstFire[1] as { lng: number }).lng).toBeGreaterThanOrEqual(100)
    expect(firstFire[5]).toEqual(bboxB)
  })

  it('immediate option flushes without waiting for debounce', () => {
    const { setWeatherTileViewport, slice } = createSlice()

    slice.setMapViewport({ lng: 112, lat: 22 }, bboxA, 7, { immediate: true })

    expect(setWeatherTileViewport).toHaveBeenCalledTimes(1)
    expect(setWeatherTileViewport).toHaveBeenCalledWith(
      'temperature',
      { lng: 112, lat: 22 },
      7,
      3,
      undefined,
      bboxA,
      'auto',
    )
  })

  it('debounce coalesces mid-gesture updates then fires latest', () => {
    const { setWeatherTileViewport, slice } = createSlice()

    slice.setMapViewport({ lng: 112, lat: 22 }, bboxA, 8)
    slice.setMapViewport({ lng: 113, lat: 23 }, bboxA, 7.5)
    expect(setWeatherTileViewport).not.toHaveBeenCalled()

    vi.advanceTimersByTime(120)
    expect(setWeatherTileViewport).toHaveBeenCalledTimes(1)
    expect(setWeatherTileViewport).toHaveBeenCalledWith(
      'temperature',
      { lng: 113, lat: 23 },
      7.5,
      3,
      undefined,
      bboxA,
      'auto',
    )
  })
})
