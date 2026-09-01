import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import {
  __testSetExitModalPrompt,
  getDrawSessionState,
  useDrawSessionTransition,
} from '@/composables/useDrawSessionTransition'
import { useDrawStore, type DrawFeature } from '@/stores/draw-store'
import { useLayerWorkspace } from '@/stores/layers/selectors'

function polygonFeature(): DrawFeature {
  return {
    geometry: {
      type: 'Polygon',
      coordinates: [
        [
          [0, 0],
          [1, 0],
          [1, 1],
          [0, 0],
        ],
      ],
    },
    properties: {},
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  __testSetExitModalPrompt(null)
})

afterEach(() => {
  __testSetExitModalPrompt(null)
})

describe('getDrawSessionState', () => {
  it('detects empty, unclosed, and closed sessions', () => {
    expect(getDrawSessionState([], [])).toEqual({
      isEmptySession: true,
      hasUnclosedSketch: false,
      hasClosedFeatures: false,
    })
    expect(getDrawSessionState([], [{ lng: 1, lat: 2 }])).toEqual({
      isEmptySession: false,
      hasUnclosedSketch: true,
      hasClosedFeatures: false,
    })
    expect(getDrawSessionState([polygonFeature()], [])).toEqual({
      isEmptySession: false,
      hasUnclosedSketch: false,
      hasClosedFeatures: true,
    })
  })
})

describe('useDrawSessionTransition', () => {
  it('discards empty draft layer when leaving draw', async () => {
    const drawStore = useDrawStore()
    const layersStore = useLayerWorkspace()
    const layer = layersStore.addDrawDraftLayer('空草稿')
    drawStore.setDraftLayerId(layer.instanceId)
    expect(layersStore.activeLayers.value).toHaveLength(1)

    const { leaveDrawMode } = useDrawSessionTransition()
    const ok = await leaveDrawMode()
    expect(ok).toBe(true)
    expect(layersStore.activeLayers.value).toHaveLength(0)
    expect(drawStore.draftLayerId).toBeNull()
  })

  it('keeps closed features and clears unclosed sketch when user keeps changes', async () => {
    __testSetExitModalPrompt(async () => 'keep')
    const drawStore = useDrawStore()
    drawStore.features = [polygonFeature()]
    drawStore.activeVertices = [{ lng: 2, lat: 3 }]

    const { leaveDrawMode } = useDrawSessionTransition()
    await leaveDrawMode()

    expect(drawStore.features).toHaveLength(1)
    expect(drawStore.activeVertices).toHaveLength(0)
  })

  it('reverts edit baseline when user discards unclosed sketch', async () => {
    __testSetExitModalPrompt(async () => 'discard')
    const drawStore = useDrawStore()
    const baseline = [polygonFeature()]
    drawStore.beginEditLayer('edit-1', baseline)
    drawStore.features = [...baseline, polygonFeature()]
    drawStore.activeVertices = [{ lng: 9, lat: 9 }]

    const { leaveDrawMode } = useDrawSessionTransition()
    await leaveDrawMode()

    expect(drawStore.features).toHaveLength(1)
    expect(drawStore.activeVertices).toHaveLength(0)
  })
})
