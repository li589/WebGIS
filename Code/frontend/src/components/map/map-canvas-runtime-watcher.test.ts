import { nextTick, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import {
  watchAdminBoundaryOverlay,
  watchBasemapSource,
  watchInteractionMode,
  watchMeasureState,
} from './map-canvas-runtime-watcher'

describe('map-canvas-runtime-watcher', () => {
  it('reacts to basemap changes only after the map is ready', async () => {
    const tileSourceId = ref<'esri-street' | 'gaode-street'>('esri-street')
    const mapReady = ref(false)
    const onTileSourceChange = vi.fn()

    const stop = watchBasemapSource({
      getTileSourceId: () => tileSourceId.value,
      getMapReady: () => mapReady.value,
      onTileSourceChange,
    })

    tileSourceId.value = 'gaode-street'
    await nextTick()
    expect(onTileSourceChange).not.toHaveBeenCalled()

    mapReady.value = true
    await nextTick()
    expect(onTileSourceChange).toHaveBeenCalledWith('gaode-street')

    stop()
  })

  it('reapplies interaction mode only when the map is ready', async () => {
    const interactionMode = ref<'move' | 'select'>('move')
    const mapReady = ref(false)
    const onInteractionModeChange = vi.fn()

    const stop = watchInteractionMode({
      getInteractionMode: () => interactionMode.value,
      getMapReady: () => mapReady.value,
      onInteractionModeChange,
    })

    interactionMode.value = 'select'
    await nextTick()
    expect(onInteractionModeChange).not.toHaveBeenCalled()

    mapReady.value = true
    await nextTick()
    expect(onInteractionModeChange).toHaveBeenCalledTimes(1)

    stop()
  })

  it('syncs admin boundary overlay only when the map is ready', async () => {
    const hasAdminBoundary = ref(false)
    const adminBoundaryOpacity = ref(1)
    const mapReady = ref(false)
    const onAdminBoundaryOverlayChange = vi.fn()

    const stop = watchAdminBoundaryOverlay({
      getHasAdminBoundary: () => hasAdminBoundary.value,
      getAdminBoundaryOpacity: () => adminBoundaryOpacity.value,
      getMapReady: () => mapReady.value,
      onAdminBoundaryOverlayChange,
    })

    hasAdminBoundary.value = true
    adminBoundaryOpacity.value = 0.4
    await nextTick()
    expect(onAdminBoundaryOverlayChange).not.toHaveBeenCalled()

    mapReady.value = true
    await nextTick()
    expect(onAdminBoundaryOverlayChange).toHaveBeenCalledTimes(1)

    stop()
  })

  it('syncs measure visuals when measure sync key changes and map is ready', async () => {
    const syncKey = ref('0:0')
    const mapReady = ref(false)
    const onMeasureStateChange = vi.fn()

    const stop = watchMeasureState({
      getMeasureSyncKey: () => syncKey.value,
      getMapReady: () => mapReady.value,
      onMeasureStateChange,
    })

    syncKey.value = '2:1'
    await nextTick()
    expect(onMeasureStateChange).not.toHaveBeenCalled()

    mapReady.value = true
    await nextTick()
    expect(onMeasureStateChange).toHaveBeenCalledTimes(1)

    syncKey.value = '0:0'
    await nextTick()
    expect(onMeasureStateChange).toHaveBeenCalledTimes(2)

    stop()
  })
})
