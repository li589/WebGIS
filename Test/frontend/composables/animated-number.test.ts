// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref, nextTick } from 'vue'
import {
  useAnimatedNumber,
  easeOutCubic,
} from '../../../Code/frontend/src/composables/useAnimatedNumber'
import * as motionPref from '../../../Code/frontend/src/services/motion-preference'

describe('useAnimatedNumber', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.spyOn(motionPref, 'isReducedMotionActive').mockReturnValue(false)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('calculates cubic ease out curve accurately', () => {
    expect(easeOutCubic(0)).toBe(0)
    expect(easeOutCubic(1)).toBe(1)
    expect(easeOutCubic(0.5)).toBeCloseTo(0.875, 4)
  })

  it('initializes with source value', () => {
    const val = ref(42)
    const { displayValue } = useAnimatedNumber(val)
    expect(displayValue.value).toBe(42)
  })

  it('smoothly interpolates number across animation frames', async () => {
    let rafCallback: FrameRequestCallback | null = null
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb: FrameRequestCallback) => {
      rafCallback = cb
      return 101
    })

    const val = ref(0)
    const { displayValue } = useAnimatedNumber(val, { duration: 200 })

    val.value = 100
    await nextTick()

    expect(rafCallback).toBeTypeOf('function')

    // Step 1: 50% elapsed
    rafCallback!(100) // start
    rafCallback!(200) // 100ms / 200ms = 50% elapsed -> eased ~0.875
    expect(displayValue.value).toBe(88)

    // Step 2: 100% elapsed
    rafCallback!(300) // 200ms / 200ms = 100%
    expect(displayValue.value).toBe(100)
  })

  it('instantly snaps to target when reduce-motion is active', async () => {
    vi.spyOn(motionPref, 'isReducedMotionActive').mockReturnValue(true)
    const rafSpy = vi.spyOn(window, 'requestAnimationFrame')

    const val = ref(10)
    const { displayValue } = useAnimatedNumber(val, { duration: 400 })

    val.value = 85
    await nextTick()

    // 瞬时直达，不得调用 rAF
    expect(displayValue.value).toBe(85)
    expect(rafSpy).not.toHaveBeenCalled()
  })

  it('respects decimal precision option', async () => {
    let rafCallback: FrameRequestCallback | null = null
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb: FrameRequestCallback) => {
      rafCallback = cb
      return 102
    })

    const val = ref(0)
    const { displayValue } = useAnimatedNumber(val, { duration: 100, precision: 1 })

    val.value = 10
    await nextTick()

    rafCallback!(10)
    rafCallback!(60) // 50ms / 100ms = 50% -> 8.75 -> 8.8 with precision 1
    expect(displayValue.value).toBe(8.8)
  })
})
