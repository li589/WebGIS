import { describe, expect, it } from 'vitest'

import { trimWeatherLayerTileCache } from './weather-tile-cache-trim'

function entry(lastAccess: number) {
  return { geojson: {}, fetchedAt: lastAccess, lastAccess }
}

describe('trimWeatherLayerTileCache', () => {
  it('never evicts viewport-pinned keys even when over max', () => {
    const tiles = new Map<string, unknown>()
    for (let i = 0; i < 5; i += 1) {
      tiles.set(`temp:z5:x${i}:y0:h0:m:p`, entry(1000 + i))
    }
    const state = {
      zoom: 5,
      tiles,
      viewportTiles: [
        { z: 5, x: 0, y: 0 },
        { z: 5, x: 1, y: 0 },
        { z: 5, x: 2, y: 0 },
        { z: 5, x: 3, y: 0 },
        { z: 5, x: 4, y: 0 },
      ],
      layerId: 'temp',
      hour: 0,
      model: 'm',
      provider: 'p',
    }

    trimWeatherLayerTileCache(
      state,
      (t, layerId, hour, model, provider) =>
        `${layerId}:z${t.z}:x${t.x}:y${t.y}:h${hour}:${model}:${provider}`,
      3,
    )

    expect(state.tiles.size).toBe(5)
  })

  it('evicts non-pinned keys first', () => {
    const tiles = new Map<string, unknown>([
      ['temp:z5:x0:y0:h0:m:p', entry(3000)],
      ['temp:z5:x9:y9:h0:m:p', entry(1000)],
      ['temp:z5:x8:y8:h0:m:p', entry(2000)],
    ])
    const state = {
      zoom: 5,
      tiles,
      viewportTiles: [{ z: 5, x: 0, y: 0 }],
      layerId: 'temp',
      hour: 0,
      model: 'm',
      provider: 'p',
    }

    trimWeatherLayerTileCache(
      state,
      (t, layerId, hour, model, provider) =>
        `${layerId}:z${t.z}:x${t.x}:y${t.y}:h${hour}:${model}:${provider}`,
      1,
    )

    expect(state.tiles.has('temp:z5:x0:y0:h0:m:p')).toBe(true)
    expect(state.tiles.size).toBe(1)
  })

  it('LRU-evicts the least-recently-accessed non-pinned key', () => {
    const tiles = new Map<string, unknown>([
      ['temp:z5:x0:y0:h0:m:p', entry(5000)],
      ['temp:z5:x1:y0:h0:m:p', entry(100)],
      ['temp:z5:x2:y0:h0:m:p', entry(4000)],
    ])
    const state = {
      zoom: 5,
      tiles,
      viewportTiles: [{ z: 5, x: 0, y: 0 }],
      layerId: 'temp',
      hour: 0,
      model: 'm',
      provider: 'p',
    }

    trimWeatherLayerTileCache(
      state,
      (t, layerId, hour, model, provider) =>
        `${layerId}:z${t.z}:x${t.x}:y${t.y}:h${hour}:${model}:${provider}`,
      2,
    )

    expect(state.tiles.has('temp:z5:x0:y0:h0:m:p')).toBe(true)
    expect(state.tiles.has('temp:z5:x2:y0:h0:m:p')).toBe(true)
    expect(state.tiles.has('temp:z5:x1:y0:h0:m:p')).toBe(false)
  })
})
