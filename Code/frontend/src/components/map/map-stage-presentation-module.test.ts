import { describe, expect, it, vi } from 'vitest'

import { createMapStagePresentationModule } from './map-stage-presentation-module'

describe('map-stage-presentation-module', () => {
  it('prepares mount, updates nav theme, and reveals map', async () => {
    let animationFrameCallback: FrameRequestCallback | null = null
    let timeoutId = 0
    const timeouts = new Map<number, () => void>()
    const setLoadingLabel = vi.fn()
    const setMapVisible = vi.fn()
    const setSkeletonVisible = vi.fn()
    const button = { style: {} as Record<string, string> }

    const module = createMapStagePresentationModule({
      getMapContainer: () =>
        ({
          querySelectorAll: () => [button] as any,
        }) as unknown as HTMLElement,
      getUsesLightNavigationTheme: () => true,
      setLoadingLabel,
      setMapVisible,
      setSkeletonVisible,
      dependencies: {
        requestAnimationFrame: ((callback: FrameRequestCallback) => {
          animationFrameCallback = callback
          return 1
        }) as typeof requestAnimationFrame,
        setTimeout: ((callback: () => void) => {
          timeoutId += 1
          timeouts.set(timeoutId, callback)
          return timeoutId as unknown as ReturnType<typeof setTimeout>
        }) as typeof setTimeout,
        clearTimeout: ((handle: ReturnType<typeof setTimeout>) => {
          timeouts.delete(handle as unknown as number)
        }) as typeof clearTimeout,
      },
    })

    const preparePromise = module.prepareMount()
    expect(setLoadingLabel).toHaveBeenCalledWith('正在准备地图...')
    expect(animationFrameCallback).not.toBeNull()
    animationFrameCallback!(16)
    await preparePromise
    expect(setLoadingLabel).toHaveBeenLastCalledWith('正在加载地图引擎...')

    module.scheduleNavigationThemeSync()
    timeouts.get(1)?.()
    expect(button.style.backgroundColor).toBe('rgba(255,255,255,0.86)')

    module.revealMap()
    expect(animationFrameCallback).not.toBeNull()
    animationFrameCallback!(32)
    expect(setMapVisible).toHaveBeenCalledWith(true)
    timeouts.get(2)?.()
    expect(setSkeletonVisible).toHaveBeenCalledWith(false)
  })

  it('cancels pending timers on dispose', () => {
    let timeoutId = 0
    const timeouts = new Map<number, () => void>()

    const module = createMapStagePresentationModule({
      getMapContainer: () => null,
      getUsesLightNavigationTheme: () => false,
      setLoadingLabel: vi.fn(),
      setMapVisible: vi.fn(),
      setSkeletonVisible: vi.fn(),
      dependencies: {
        requestAnimationFrame: ((callback: FrameRequestCallback) => {
          callback(0)
          return 1
        }) as typeof requestAnimationFrame,
        setTimeout: ((callback: () => void) => {
          timeoutId += 1
          timeouts.set(timeoutId, callback)
          return timeoutId as unknown as ReturnType<typeof setTimeout>
        }) as typeof setTimeout,
        clearTimeout: ((handle: ReturnType<typeof setTimeout>) => {
          timeouts.delete(handle as unknown as number)
        }) as typeof clearTimeout,
      },
    })

    module.scheduleNavigationThemeSync()
    module.revealMap()
    expect(timeouts.size).toBe(2)

    module.dispose()
    expect(timeouts.size).toBe(0)
  })
})
