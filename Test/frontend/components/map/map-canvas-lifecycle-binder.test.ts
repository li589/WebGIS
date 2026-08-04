import { describe, expect, it, vi } from 'vitest'

import { createMapCanvasLifecycleBinder } from '@/components/map/map-canvas-lifecycle-binder'

type NavOptions = { visualizePitch?: boolean; onLocate?: unknown }

class MockNavigationControl {
  options: NavOptions

  constructor(options: NavOptions = {}) {
    this.options = options
  }

  onAdd() {
    return {} as HTMLElement
  }

  onRemove() {}
}

class MockScaleControl {
  options: { unit: 'metric' }

  constructor(options: { unit: 'metric' }) {
    this.options = options
  }

  onAdd() {
    return {} as HTMLElement
  }

  onRemove() {}
}

describe('map-canvas-lifecycle-binder', () => {
  it('adds controls, schedules theme sync, and wires error/load callbacks', async () => {
    const addControl = vi.fn()
    const on = vi.fn()
    const eventHandlers = new Map<string, (...args: unknown[]) => void>()
    const onMapError = vi.fn()
    const onMapLoad = vi.fn(async () => {})
    const scheduleNavigationThemeSync = vi.fn()

    const binder = createMapCanvasLifecycleBinder({
      map: {
        addControl: (control: unknown, position: string) => {
          addControl(control, position)
        },
        on: (event: string, handler: (...args: unknown[]) => void) => {
          eventHandlers.set(event, handler)
          on(event, handler)
        },
      } as any,
      controls: {
        NavigationControl: MockNavigationControl,
        ScaleControl: MockScaleControl,
      },
      onMapError,
      onMapLoad,
      scheduleNavigationThemeSync,
    })

    binder.bind()

    expect(addControl).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ options: expect.anything() }),
      'bottom-right',
    )
    expect(addControl).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ options: { unit: 'metric' } }),
      'bottom-left',
    )
    expect(scheduleNavigationThemeSync).toHaveBeenCalledTimes(1)

    eventHandlers.get('error')?.({ code: 'boom' })
    expect(onMapError).toHaveBeenCalledWith({ code: 'boom' })

    await eventHandlers.get('load')?.()
    expect(onMapLoad).toHaveBeenCalledTimes(1)
  })

  it('binds lifecycle handlers only once', () => {
    const addControl = vi.fn()
    const on = vi.fn()

    const binder = createMapCanvasLifecycleBinder({
      map: {
        addControl,
        on,
      } as any,
      controls: {
        NavigationControl: MockNavigationControl,
        ScaleControl: MockScaleControl,
      },
      onMapError: vi.fn(),
      onMapLoad: vi.fn(),
      scheduleNavigationThemeSync: vi.fn(),
    })

    binder.bind()
    binder.bind()

    expect(addControl).toHaveBeenCalledTimes(2)
    expect(on).toHaveBeenCalledTimes(2)
  })

  it('reports async onMapLoad failures instead of swallowing them silently', async () => {
    const eventHandlers = new Map<string, (...args: unknown[]) => void>()
    const reportError = vi.fn()
    const loadError = new Error('load failed')

    const binder = createMapCanvasLifecycleBinder({
      map: {
        addControl: vi.fn(),
        on: (event: string, handler: (...args: unknown[]) => void) => {
          eventHandlers.set(event, handler)
        },
      } as any,
      controls: {
        NavigationControl: MockNavigationControl,
        ScaleControl: MockScaleControl,
      },
      onMapError: vi.fn(),
      onMapLoad: vi.fn(async () => {
        throw loadError
      }),
      scheduleNavigationThemeSync: vi.fn(),
      dependencies: {
        error: reportError,
      },
    })

    binder.bind()
    eventHandlers.get('load')?.()
    await Promise.resolve()

    expect(reportError).toHaveBeenCalledWith(
      '[MapCanvasLifecycleBinder] onMapLoad failed',
      loadError,
    )
  })
})
