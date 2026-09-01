// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
  REDUCE_MOTION_STORAGE_KEY,
  applyReducedMotionPreference,
  bootstrapMotionPreference,
  isReducedMotionActive,
  resolveReducedMotionPreference,
  setReducedMotionPreference,
} from '@/services/motion-preference'

describe('motion-preference', () => {
  beforeEach(() => {
    window.localStorage.clear()
    document.documentElement.classList.remove('reduce-motion')
  })

  afterEach(() => {
    window.localStorage.clear()
    document.documentElement.classList.remove('reduce-motion')
  })

  it('applies and clears html.reduce-motion class', () => {
    applyReducedMotionPreference(true)
    expect(document.documentElement.classList.contains('reduce-motion')).toBe(true)
    expect(isReducedMotionActive()).toBe(true)

    applyReducedMotionPreference(false)
    expect(document.documentElement.classList.contains('reduce-motion')).toBe(false)
    expect(isReducedMotionActive()).toBe(false)
  })

  it('persists preference and resolves from localStorage', () => {
    setReducedMotionPreference(true)
    expect(window.localStorage.getItem(REDUCE_MOTION_STORAGE_KEY)).toBe('true')
    expect(resolveReducedMotionPreference()).toBe(true)

    setReducedMotionPreference(false)
    expect(window.localStorage.getItem(REDUCE_MOTION_STORAGE_KEY)).toBe('false')
    expect(resolveReducedMotionPreference()).toBe(false)
  })

  it('bootstraps from stored preference before mount', () => {
    window.localStorage.setItem(REDUCE_MOTION_STORAGE_KEY, 'true')
    const enabled = bootstrapMotionPreference()
    expect(enabled).toBe(true)
    expect(document.documentElement.classList.contains('reduce-motion')).toBe(true)
  })
})
