// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { vSpotlight } from '../../../Code/frontend/src/directives/spotlight'
import * as motionPref from '../../../Code/frontend/src/services/motion-preference'

describe('vSpotlight Directive', () => {
  let el: HTMLElement
  const directive = vSpotlight as {
    mounted: (el: HTMLElement, binding: any) => void
    unmounted: (el: HTMLElement) => void
  }

  beforeEach(() => {
    el = document.createElement('div')
    vi.spyOn(motionPref, 'isReducedMotionActive').mockReturnValue(false)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('adds cgda-spotlight-card class on mounted', () => {
    directive.mounted(el, { value: undefined })
    expect(el.classList.contains('cgda-spotlight-card')).toBe(true)
  })

  it('updates spotlight coordinates on pointermove', () => {
    let rafCb: FrameRequestCallback | null = null
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb: FrameRequestCallback) => {
      rafCb = cb
      return 1
    })

    vi.spyOn(el, 'getBoundingClientRect').mockReturnValue({
      left: 100,
      top: 50,
      width: 200,
      height: 100,
      right: 300,
      bottom: 150,
      x: 100,
      y: 50,
      toJSON: () => {},
    })

    directive.mounted(el, { value: { color: 'rgba(56, 189, 248, 0.2)' } })

    const moveEvent = new PointerEvent('pointermove', {
      clientX: 150,
      clientY: 80,
      pointerType: 'mouse',
    })
    el.dispatchEvent(moveEvent)

    expect(rafCb).toBeTypeOf('function')
    rafCb!(1000)

    expect(el.style.getPropertyValue('--spotlight-x')).toBe('50px')
    expect(el.style.getPropertyValue('--spotlight-y')).toBe('30px')
    expect(el.style.getPropertyValue('--spotlight-opacity')).toBe('1')
    expect(el.style.getPropertyValue('--spotlight-color')).toBe('rgba(56, 189, 248, 0.2)')
  })

  it('resets opacity on pointerleave', () => {
    directive.mounted(el, { value: undefined })
    el.style.setProperty('--spotlight-opacity', '1')

    const leaveEvent = new PointerEvent('pointerleave')
    el.dispatchEvent(leaveEvent)

    expect(el.style.getPropertyValue('--spotlight-opacity')).toBe('0')
  })

  it('skips spotlight updates when reduce-motion is active', () => {
    vi.spyOn(motionPref, 'isReducedMotionActive').mockReturnValue(true)
    const rafSpy = vi.spyOn(window, 'requestAnimationFrame')

    directive.mounted(el, { value: undefined })

    const moveEvent = new PointerEvent('pointermove', {
      clientX: 120,
      clientY: 60,
      pointerType: 'mouse',
    })
    el.dispatchEvent(moveEvent)

    expect(rafSpy).not.toHaveBeenCalled()
  })

  it('cleans up listeners on unmount', () => {
    const removeSpy = vi.spyOn(el, 'removeEventListener')
    directive.mounted(el, { value: undefined })
    directive.unmounted(el)

    expect(removeSpy).toHaveBeenCalledWith('pointermove', expect.any(Function))
    expect(removeSpy).toHaveBeenCalledWith('pointerleave', expect.any(Function))
  })
})
