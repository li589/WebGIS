import { describe, expect, it, vi } from 'vitest'
import { MapChromeNavigationControl } from '@/components/map/map-chrome-controls'

function ensureTestWindow() {
  if (typeof globalThis.window !== 'undefined') return
  const listeners: Record<string, Array<(event?: any) => void>> = {}
  ;(globalThis as any).window = {
    addEventListener: (event: string, fn: (event?: any) => void) => {
      listeners[event] = listeners[event] || []
      listeners[event].push(fn)
    },
    removeEventListener: (event: string, fn: (event?: any) => void) => {
      listeners[event] = (listeners[event] || []).filter((h) => h !== fn)
    },
    __listeners: listeners,
  }
}

describe('MapChromeNavigationControl', () => {
  function setupMockDom() {
    ensureTestWindow()
    const buttonsCreated: any[] = []
    const createElementSpy = vi.fn((tag: string) => {
      const el = {
        tagName: tag.toUpperCase(),
        type: '',
        className: '',
        title: '',
        id: '',
        textContent: '',
        innerHTML: '',
        style: {} as Record<string, string>,
        listeners: {} as Record<string, Array<(event?: any) => void>>,
        addEventListener: (event: string, fn: (event?: any) => void) => {
          el.listeners[event] = el.listeners[event] || []
          el.listeners[event].push(fn)
        },
        appendChild: (child: any) => {
          if (child?.className?.includes?.('map-nav-btn')) {
            buttonsCreated.push(child)
          }
        },
        setAttribute: vi.fn(),
        getBoundingClientRect: () => ({
          left: 100,
          top: 100,
          width: 40,
          height: 40,
          right: 140,
          bottom: 140,
        }),
        setPointerCapture: vi.fn(),
        classList: {
          add: vi.fn((cls: string) => {
            if (!el.className.includes(cls)) el.className = `${el.className} ${cls}`.trim()
          }),
          remove: vi.fn((cls: string) => {
            el.className = el.className
              .split(/\s+/)
              .filter((c) => c && c !== cls)
              .join(' ')
          }),
          contains: (cls: string) => el.className.includes(cls),
        },
        click: () => {
          for (const fn of el.listeners['click'] || []) fn()
        },
        dispatch: (event: string, payload?: any) => {
          for (const fn of el.listeners[event] || []) fn(payload)
        },
      }
      return el as any
    })

    if (typeof globalThis.document === 'undefined') {
      ;(globalThis as any).document = {
        createElement: createElementSpy,
        getElementById: () => null,
        head: { appendChild: vi.fn() },
      }
    } else {
      vi.spyOn(document, 'createElement').mockImplementation(createElementSpy as any)
      vi.spyOn(document, 'getElementById').mockReturnValue(null)
      if (!document.head) {
        Object.defineProperty(document, 'head', {
          value: { appendChild: vi.fn() },
          configurable: true,
        })
      } else {
        vi.spyOn(document.head, 'appendChild').mockImplementation(() => null as any)
      }
    }

    return { buttonsCreated, createElementSpy }
  }

  it('creates 4 vertical buttons in exact order (ZoomIn -> Compass -> ZoomOut -> Locate)', () => {
    const easeTo = vi.fn()
    const zoomIn = vi.fn()
    const zoomOut = vi.fn()
    const on = vi.fn()
    const off = vi.fn()
    const setBearing = vi.fn()

    const mockMap = {
      easeTo,
      zoomIn,
      zoomOut,
      setBearing,
      getBearing: () => 45,
      getPitch: () => 15,
      on,
      off,
      flyTo: vi.fn(),
    } as any

    const { buttonsCreated } = setupMockDom()
    const control = new MapChromeNavigationControl()
    const element = control.onAdd(mockMap)
    expect(element).toBeTruthy()

    expect(buttonsCreated.length).toBe(4)
    expect(buttonsCreated[0].className).toContain('map-nav-btn--zoom-in')
    expect(buttonsCreated[1].className).toContain('map-nav-btn--compass')
    expect(buttonsCreated[2].className).toContain('map-nav-btn--zoom-out')
    expect(buttonsCreated[3].className).toContain('map-nav-btn--locate')

    buttonsCreated[0].click()
    expect(zoomIn).toHaveBeenCalledTimes(1)

    buttonsCreated[2].click()
    expect(zoomOut).toHaveBeenCalledTimes(1)

    control.onRemove()
    expect(off).toHaveBeenCalledWith('rotate', expect.any(Function))
    expect(off).toHaveBeenCalledWith('pitch', expect.any(Function))
  })

  it('clicking compass without drag resets north; drag rotates bearing', () => {
    const easeTo = vi.fn()
    const setBearing = vi.fn()
    const mockMap = {
      easeTo,
      zoomIn: vi.fn(),
      zoomOut: vi.fn(),
      setBearing,
      getBearing: () => 10,
      getPitch: () => 0,
      on: vi.fn(),
      off: vi.fn(),
      flyTo: vi.fn(),
    } as any

    const { buttonsCreated } = setupMockDom()
    const addWindowListener = vi.spyOn(window, 'addEventListener')
    const removeWindowListener = vi.spyOn(window, 'removeEventListener')

    const control = new MapChromeNavigationControl()
    control.onAdd(mockMap)
    const compass = buttonsCreated[1]

    // 短按（无拖拽）→ 归北
    compass.dispatch('pointerdown', {
      button: 0,
      pointerType: 'mouse',
      pointerId: 1,
      clientX: 120,
      clientY: 100,
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
    })
    const moveHandler = addWindowListener.mock.calls.find((c) => c[0] === 'pointermove')?.[1] as
      | ((e: any) => void)
      | undefined
    const upHandler = addWindowListener.mock.calls.find((c) => c[0] === 'pointerup')?.[1] as
      | ((e: any) => void)
      | undefined
    expect(moveHandler).toBeTypeOf('function')
    expect(upHandler).toBeTypeOf('function')

    upHandler?.({ pointerId: 1 })
    expect(easeTo).toHaveBeenCalledWith({ bearing: 0, pitch: 0, duration: 500 })
    expect(setBearing).not.toHaveBeenCalled()

    // 拖拽旋转
    easeTo.mockClear()
    compass.dispatch('pointerdown', {
      button: 0,
      pointerType: 'mouse',
      pointerId: 2,
      clientX: 120,
      clientY: 100, // 正上方，约 0°
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
    })
    const move2 = addWindowListener.mock.calls.filter((c) => c[0] === 'pointermove').at(-1)?.[1] as (
      e: any,
    ) => void
    const up2 = addWindowListener.mock.calls.filter((c) => c[0] === 'pointerup').at(-1)?.[1] as (
      e: any,
    ) => void

    move2?.({
      pointerId: 2,
      clientX: 140,
      clientY: 120, // 右方，约 90°
      preventDefault: vi.fn(),
    })
    expect(setBearing).toHaveBeenCalled()
    up2?.({ pointerId: 2 })
    expect(easeTo).not.toHaveBeenCalled()

    control.onRemove()
    expect(removeWindowListener).toHaveBeenCalled()
  })
})
