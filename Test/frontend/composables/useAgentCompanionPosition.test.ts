import { describe, expect, it } from 'vitest'
import {
  companionDockOffset,
  COMPANION_PEEK_PX,
  COMPANION_SIZE_PX,
  isCompanionDragGesture,
  snapCompanionPosition,
} from '@/composables/useAgentCompanionPosition'

describe('snapCompanionPosition', () => {
  const stage = { width: 800, height: 600 }

  it('clamps inside stage', () => {
    const r = snapCompanionPosition({ x: -50, y: 9999 }, stage)
    expect(r.x).toBe(0)
    expect(r.y).toBe(600 - COMPANION_SIZE_PX)
  })

  it('docks left near left edge', () => {
    const r = snapCompanionPosition({ x: 10, y: 100 }, stage)
    expect(r.dock).toBe('left')
    expect(r.x).toBe(0)
  })

  it('docks right near right edge', () => {
    const r = snapCompanionPosition({ x: 780, y: 100 }, stage)
    expect(r.dock).toBe('right')
    expect(r.x).toBe(800 - COMPANION_SIZE_PX)
  })

  it('stays undocked in the middle', () => {
    const r = snapCompanionPosition({ x: 300, y: 200 }, stage)
    expect(r.dock).toBe('none')
    expect(r.x).toBe(300)
  })
})

describe('companionDockOffset', () => {
  it('offsets toward the docked edge for peek', () => {
    const hidden = COMPANION_SIZE_PX - COMPANION_PEEK_PX
    expect(companionDockOffset('left')).toBe(-hidden)
    expect(companionDockOffset('right')).toBe(hidden)
    expect(companionDockOffset('none')).toBe(0)
  })
})

describe('isCompanionDragGesture', () => {
  it('distinguishes click vs drag', () => {
    expect(isCompanionDragGesture(2, 2)).toBe(false)
    expect(isCompanionDragGesture(10, 0)).toBe(true)
  })
})
