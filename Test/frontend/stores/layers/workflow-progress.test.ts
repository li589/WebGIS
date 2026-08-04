import { describe, expect, it } from 'vitest'

/** Mirror of normalizeWorkflowProgress in layers/index.ts for unit coverage. */
function normalizeWorkflowProgress(
  raw: number | null | undefined,
  detail?: {
    chunksDone?: number
    chunksTotal?: number
    pixelsDone?: number
    pixelsTotal?: number
  } | null,
): number {
  let pct = 0
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    pct = raw >= 0 && raw <= 1 ? raw * 100 : raw
  }
  if (
    detail &&
    typeof detail.chunksTotal === 'number' &&
    detail.chunksTotal > 0 &&
    typeof detail.chunksDone === 'number' &&
    Number.isFinite(detail.chunksDone)
  ) {
    pct = Math.max(pct, (detail.chunksDone / detail.chunksTotal) * 100)
  } else if (
    detail &&
    typeof detail.pixelsTotal === 'number' &&
    detail.pixelsTotal > 0 &&
    typeof detail.pixelsDone === 'number' &&
    Number.isFinite(detail.pixelsDone)
  ) {
    pct = Math.max(pct, (detail.pixelsDone / detail.pixelsTotal) * 100)
  }
  return Math.max(0, Math.min(100, Math.round(pct)))
}

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
