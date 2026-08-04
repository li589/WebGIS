import { describe, expect, it } from 'vitest'

import {
  formatProgressShell,
  pickLatestNodeProgress,
} from '@/utils/workflow-progress-format'

describe('formatProgressShell', () => {
  it('joins node, time, chunk and percent', () => {
    expect(
      formatProgressShell({
        progress: 42,
        nodeLabel: 'omega_sf',
        detail: {
          timeKey: '20251203',
          chunkId: 'chunk-4/32',
          productTag: 'OMEGA',
        },
      }),
    ).toBe('omega_sf · 20251203 · chunk-4/32 · OMEGA · 42%')
  })

  it('falls back to message when no structured parts', () => {
    expect(formatProgressShell({ message: 'still running' })).toBe('still running')
  })

  it('uses chunk ratio labels', () => {
    expect(
      formatProgressShell({
        progress: 16,
        detail: { chunksDone: 5, chunksTotal: 32 },
      }),
    ).toBe('块 5/32 · 16%')
  })
})

describe('pickLatestNodeProgress', () => {
  it('picks highest progress node when no timestamps', () => {
    const latest = pickLatestNodeProgress([
      { progress: 10, message: 'a' },
      { progress: 55, message: 'b' },
      { progress: 20, message: 'c' },
    ])
    expect(latest?.message).toBe('b')
  })

  it('prefers newest updatedAt over higher stale progress', () => {
    const latest = pickLatestNodeProgress([
      { progress: 90, message: 'stale', updatedAt: '2026-08-04T00:00:00Z' },
      { progress: 12, message: 'fresh', updatedAt: '2026-08-04T01:00:00Z' },
    ])
    expect(latest?.message).toBe('fresh')
  })
})
