import { describe, expect, it } from 'vitest'

import { normalizeWorkflowProgress } from '@/stores/layers/workflow-progress'

describe('normalizeWorkflowProgress', () => {
  it('keeps 0-100 values', () => {
    expect(normalizeWorkflowProgress(35)).toBe(35)
  })

  it('scales 0-1 fractions', () => {
    expect(normalizeWorkflowProgress(0.31)).toBe(31)
  })

  it('uses chunk ratio when raw progress truncates to 0', () => {
    expect(
      normalizeWorkflowProgress(0, {
        chunksDone: 5,
        chunksTotal: 32,
        pixelsDone: 50734,
        pixelsTotal: 6262144,
      }),
    ).toBe(16)
  })

  it('prefers the larger of raw and chunk progress', () => {
    expect(
      normalizeWorkflowProgress(6, {
        chunksDone: 10,
        chunksTotal: 32,
      }),
    ).toBe(31)
  })
})
