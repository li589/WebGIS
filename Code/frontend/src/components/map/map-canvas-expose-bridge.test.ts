import { afterEach, describe, expect, it, vi } from 'vitest'

import { createMapCanvasExposeBridge } from './map-canvas-expose-bridge'

describe('map-canvas-expose-bridge', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('returns the current stage element and captures canvas output', async () => {
    vi.useFakeTimers()
    const outToDataURL = vi.fn(() => 'data:image/png;base64,composite')
    const drawImage = vi.fn()
    const getContext = vi.fn(() => ({ drawImage }))
    vi.stubGlobal('document', {
      createElement: vi.fn(() => ({
        width: 0,
        height: 0,
        getContext,
        toDataURL: outToDataURL,
      })),
    })
    const stageElement = {
      querySelectorAll: vi.fn(() => []),
    } as unknown as HTMLElement
    const toDataURL = vi.fn(() => 'data:image/png;base64,abc')
    const render = vi.fn()
    const triggerRepaint = vi.fn()
    const once = vi.fn((_event: string, cb: () => void) => {
      cb()
    })

    const bridge = createMapCanvasExposeBridge({
      getMapStageElement: () => stageElement,
      getMap: () =>
        ({
          render,
          triggerRepaint,
          once,
          getCanvas: () => ({
            width: 800,
            height: 600,
            clientWidth: 800,
            clientHeight: 600,
            toDataURL,
          }),
        }) as any,
    })

    expect(bridge.getMapStageElement()).toBe(stageElement)
    await expect(bridge.captureMapCanvas()).resolves.toBe('data:image/png;base64,composite')
    expect(triggerRepaint).toHaveBeenCalled()
    expect(render).toHaveBeenCalled()
    expect(drawImage).toHaveBeenCalled()
    expect(outToDataURL).toHaveBeenCalledWith('image/png')
  })

  it('captures raw map canvas when no stage element is available', async () => {
    const toDataURL = vi.fn(() => 'data:image/png;base64,abc')
    const render = vi.fn()
    const triggerRepaint = vi.fn()
    const once = vi.fn((_event: string, cb: () => void) => {
      cb()
    })

    const bridge = createMapCanvasExposeBridge({
      getMapStageElement: () => null,
      getMap: () =>
        ({
          render,
          triggerRepaint,
          once,
          getCanvas: () => ({
            toDataURL,
          }),
        }) as any,
    })

    await expect(bridge.captureMapCanvas()).resolves.toBe('data:image/png;base64,abc')
    expect(triggerRepaint).toHaveBeenCalled()
    expect(render).toHaveBeenCalled()
    expect(toDataURL).toHaveBeenCalledWith('image/png')
  })

  it('returns null when no map is available or capture fails', async () => {
    const warn = vi.fn()
    const bridgeWithoutMap = createMapCanvasExposeBridge({
      getMapStageElement: () => null,
      getMap: () => null,
      dependencies: { warn },
    })

    await expect(bridgeWithoutMap.captureMapCanvas()).resolves.toBeNull()
    expect(warn).not.toHaveBeenCalled()

    const bridgeWithError = createMapCanvasExposeBridge({
      getMapStageElement: () => null,
      getMap: () =>
        ({
          triggerRepaint: vi.fn(),
          once: vi.fn((_e: string, cb: () => void) => cb()),
          render: () => {
            throw new Error('boom')
          },
          getCanvas: () => ({
            toDataURL: vi.fn(),
          }),
        }) as any,
      dependencies: { warn },
    })

    await expect(bridgeWithError.captureMapCanvas()).resolves.toBeNull()
    expect(warn).toHaveBeenCalled()
    expect(warn).toHaveBeenCalledWith('[MapCanvas] captureMapCanvas failed:', expect.any(Error))
  })
})
