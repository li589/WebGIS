import { describe, expect, it, vi } from 'vitest'

import { createMapCanvasExposeBridge } from './map-canvas-expose-bridge'

describe('map-canvas-expose-bridge', () => {
  it('returns the current stage element and captures canvas output', () => {
    const stageElement = {} as HTMLElement
    const toDataURL = vi.fn(() => 'data:image/png;base64,abc')
    const render = vi.fn()

    const bridge = createMapCanvasExposeBridge({
      getMapStageElement: () => stageElement,
      getMap: () => ({
        render,
        getCanvas: () => ({
          toDataURL,
        }),
      }) as any,
    })

    expect(bridge.getMapStageElement()).toBe(stageElement)
    expect(bridge.captureMapCanvas()).toBe('data:image/png;base64,abc')
    expect(render).toHaveBeenCalledTimes(1)
    expect(toDataURL).toHaveBeenCalledWith('image/png')
  })

  it('returns null when no map is available or capture fails', () => {
    const warn = vi.fn()
    const bridgeWithoutMap = createMapCanvasExposeBridge({
      getMapStageElement: () => null,
      getMap: () => null,
      dependencies: { warn },
    })

    expect(bridgeWithoutMap.captureMapCanvas()).toBeNull()
    expect(warn).not.toHaveBeenCalled()

    const bridgeWithError = createMapCanvasExposeBridge({
      getMapStageElement: () => null,
      getMap: () => ({
        render: () => {
          throw new Error('boom')
        },
        getCanvas: () => ({
          toDataURL: vi.fn(),
        }),
      }) as any,
      dependencies: { warn },
    })

    expect(bridgeWithError.captureMapCanvas()).toBeNull()
    expect(warn).toHaveBeenCalledTimes(1)
    expect(warn).toHaveBeenCalledWith('[MapCanvas] captureMapCanvas failed:', expect.any(Error))
  })
})
