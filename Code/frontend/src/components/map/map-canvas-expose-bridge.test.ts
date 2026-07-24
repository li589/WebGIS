import { afterEach, describe, expect, it, vi } from 'vitest'

import { createMapCanvasExposeBridge } from './map-canvas-expose-bridge'

describe('map-canvas-expose-bridge', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('returns the current stage element and captures canvas output', () => {
    // node 环境无 document：stub createElement 返回可控的合成画布，
    // 验证「stage 存在时底图 + overlay 画布合成输出」路径
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

    const bridge = createMapCanvasExposeBridge({
      getMapStageElement: () => stageElement,
      getMap: () =>
        ({
          render,
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
    expect(bridge.captureMapCanvas()).toBe('data:image/png;base64,composite')
    expect(render).toHaveBeenCalledTimes(1)
    // 合成路径：底图先 drawImage 进合成画布，输出取自合成画布
    expect(drawImage).toHaveBeenCalled()
    expect(outToDataURL).toHaveBeenCalledWith('image/png')
  })

  it('captures raw map canvas when no stage element is available', () => {
    const toDataURL = vi.fn(() => 'data:image/png;base64,abc')
    const render = vi.fn()

    const bridge = createMapCanvasExposeBridge({
      getMapStageElement: () => null,
      getMap: () =>
        ({
          render,
          getCanvas: () => ({
            toDataURL,
          }),
        }) as any,
    })

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
      getMap: () =>
        ({
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
