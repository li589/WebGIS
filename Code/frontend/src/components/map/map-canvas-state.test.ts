import { describe, expect, it } from 'vitest'

import { createMapCanvasState } from './map-canvas-state'

describe('map-canvas-state', () => {
  it('creates default stage refs and runtime flags', () => {
    const state = createMapCanvasState()

    expect(state.mapContainer.value).toBeNull()
    expect(state.mapStageRef.value).toBeNull()
    expect(state.hotspotPins.value).toEqual([])
    expect(state.selectedHotspotId.value).toBeNull()
    expect(state.mapReady.value).toBe(false)
    expect(state.mapVisible.value).toBe(false)
    expect(state.skeletonVisible.value).toBe(true)
    expect(state.isMapInteracting.value).toBe(false)
    expect(state.isSourceTransitioning.value).toBe(false)
    expect(state.loadingLabel.value).toBe('正在加载地图...')
    expect(state.tileLoadFailed.value).toBe(false)
    expect(state.tileFailedProvider.value).toBeNull()
  })

  it('clears module resources back to null', () => {
    const state = createMapCanvasState()
    state.resources.map = {} as any
    state.resources.adminBoundaryModule = {} as any
    state.resources.basemapModule = {} as any
    state.resources.mapStagePresentationModule = {} as any
    state.resources.weatherOverlayModule = {} as any
    state.resources.hotspotPinsModule = {} as any
    state.resources.mapInteractionModule = {} as any
    state.resources.mapCanvasRuntimeModule = {} as any
    state.resources.selectedLayerFocusModule = {} as any
    state.resources.measureModule = {} as any

    state.clearResources()

    expect(state.resources).toEqual({
      map: null,
      adminBoundaryModule: null,
      basemapModule: null,
      mapStagePresentationModule: null,
      weatherOverlayModule: null,
      hotspotPinsModule: null,
      mapInteractionModule: null,
      mapCanvasRuntimeModule: null,
      selectedLayerFocusModule: null,
      measureModule: null,
    })
  })
})
