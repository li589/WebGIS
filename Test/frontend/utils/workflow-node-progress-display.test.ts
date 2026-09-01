import { describe, expect, it } from 'vitest'

import { nodeMessageRedundantWithDetail } from '@/utils/workflow-node-progress-display'

describe('nodeMessageRedundantWithDetail', () => {
  it('hides message when download detail already formats skipping', () => {
    expect(
      nodeMessageRedundantWithDetail({
        message: '全部跳过 (66/66)',
        detail: { phase: 'skipping', downloaded_items: 66, total_items: 66 },
      }),
    ).toBe(true)
  })

  it('hides message when chunk ratio is repeated in detail row', () => {
    expect(
      nodeMessageRedundantWithDetail({
        message: 'chunk 1/32 · pixel 0/6262144 · preload',
        detail: { chunksDone: 1, chunksTotal: 32, pixelsDone: 0, pixelsTotal: 6262144, phase: 'preload' },
      }),
    ).toBe(true)
  })

  it('keeps message when it adds information beyond detail', () => {
    expect(
      nodeMessageRedundantWithDetail({
        message: 'SF block inversion: TB_SOURCE=SMAP',
        detail: { chunksDone: 1, chunksTotal: 32, phase: 'preload' },
      }),
    ).toBe(false)
  })
})
