/**
 * Layer tile cache trim: drop far-zoom tiles, then FIFO-evict non-viewport keys.
 * Viewport (pinned) tiles are never evicted — prevents evict↔refetch oscillation.
 */

export const MAX_LAYER_CACHE_TILES = 96

export interface WeatherTileCacheTrimState {
  zoom: number
  tiles: Map<string, unknown>
  viewportTiles: Array<{ z: number; x: number; y: number }>
  layerId: string
  hour: number
  model: string
  provider: string
}

export function trimWeatherLayerTileCache(
  state: WeatherTileCacheTrimState,
  tileCoordsToKey: (
    tile: { z: number; x: number; y: number },
    layerId: string,
    hour: number,
    model: string,
    provider: string,
  ) => string,
  maxTiles: number = MAX_LAYER_CACHE_TILES,
  preserveZoomRadius: number = 1,
): void {
  const clampedZoom = Math.max(0, Math.min(12, Math.round(state.zoom)))
  if (state.tiles.size > maxTiles / 2) {
    for (const cacheKey of Array.from(state.tiles.keys())) {
      const zMatch = /:z(\d+):/.exec(cacheKey)
      const z = Number(zMatch?.[1] ?? clampedZoom)
      if (Math.abs(z - clampedZoom) > preserveZoomRadius) {
        state.tiles.delete(cacheKey)
      }
    }
  }

  const pinnedKeys = new Set<string>(
    state.viewportTiles.map((t) =>
      tileCoordsToKey(t, state.layerId, state.hour, state.model, state.provider),
    ),
  )
  let guard = 0
  while (state.tiles.size > maxTiles && guard < state.tiles.size + 1) {
    guard += 1
    let evicted = false
    for (const key of state.tiles.keys()) {
      if (pinnedKeys.has(key)) continue
      state.tiles.delete(key)
      evicted = true
      break
    }
    if (!evicted) break
  }
}
