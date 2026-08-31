import { describe, expect, it } from 'vitest'

import {
  isInternalWorkflowNodeStage,
  isOverallProgressStage,
  normalizeWorkflowProgress,
  resolveJobOverallProgress,
} from '@/stores/layers/workflow-progress'

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

describe('isOverallProgressStage', () => {
  it('matches only workflow.dispatch', () => {
    expect(isOverallProgressStage('workflow.dispatch')).toBe(true)
    expect(isOverallProgressStage('workflow.node.n1')).toBe(false)
    expect(isOverallProgressStage('fy_download')).toBe(false)
    expect(isOverallProgressStage('omega_sf_fenkuai')).toBe(false)
  })
})

describe('isInternalWorkflowNodeStage', () => {
  it('detects workflow.node.* bookkeeping stages', () => {
    expect(isInternalWorkflowNodeStage('workflow.node.n1')).toBe(true)
    expect(isInternalWorkflowNodeStage('workflow.dispatch')).toBe(false)
    expect(isInternalWorkflowNodeStage('fy_download')).toBe(false)
  })
})

describe('filterDisplayableNodeProgress', () => {
  it('excludes workflow.dispatch from node list', async () => {
    const { filterDisplayableNodeProgress } = await import('@/stores/layers/workflow-progress')
    const nodes = filterDisplayableNodeProgress([
      { nodeId: 'workflow.dispatch', progress: 14, stage: 'processing', nodeLabel: 'dispatch' },
      { nodeId: 'nsidc_smap_download', progress: 40, stage: 'download', nodeLabel: 'nsidc' },
    ])
    expect(nodes.map((n) => n.nodeId)).toEqual(['nsidc_smap_download'])
  })

  it('keeps scoped graphNode:stage ids separate even with same label', async () => {
    const { dedupeNodeProgress } = await import('@/stores/layers/workflow-progress')
    const nodes = dedupeNodeProgress([
      {
        nodeId: 'n1:nsidc_smap_download',
        nodeLabel: 'nsidc_smap_download',
        stage: 'download',
        progress: 10,
        updatedAt: '2026-01-01T00:00:00Z',
      },
      {
        nodeId: 'n2:nsidc_smap_download',
        nodeLabel: 'nsidc_smap_download',
        stage: 'download',
        progress: 50,
        updatedAt: '2026-01-01T00:01:00Z',
      },
    ])
    expect(nodes).toHaveLength(2)
  })

  it('dedupes bare module ids by stage+label keeping latest', async () => {
    const { dedupeNodeProgress } = await import('@/stores/layers/workflow-progress')
    const nodes = dedupeNodeProgress([
      {
        nodeId: 'a',
        nodeLabel: 'nsidc',
        stage: 'download',
        progress: 10,
        updatedAt: '2026-01-01T00:00:00Z',
      },
      {
        nodeId: 'b',
        nodeLabel: 'nsidc',
        stage: 'download',
        progress: 50,
        updatedAt: '2026-01-01T00:01:00Z',
      },
    ])
    expect(nodes).toHaveLength(1)
    expect(nodes[0]?.progress).toBe(50)
  })
})

describe('resolveJobOverallProgress', () => {
  it('uses weighted workflow.dispatch and ignores module / node stage_end 100%', () => {
    expect(
      resolveJobOverallProgress({
        current: 100,
        nodeProgress: [
          { nodeId: 'workflow.node.n1', progress: 100 },
          { nodeId: 'fy_download', progress: 100 },
          {
            nodeId: 'workflow.dispatch',
            progress: 14,
            detail: { chunksDone: 18, chunksTotal: 32 },
          },
          { nodeId: 'omega_sf_fenkuai', progress: 56 },
        ],
      }),
    ).toBe(14)
  })

  it('does not inflate dispatch with chunk detail', () => {
    expect(
      resolveJobOverallProgress({
        nodeProgress: [
          {
            nodeId: 'workflow.dispatch',
            progress: 0.142,
            detail: { chunksDone: 18, chunksTotal: 32, pixelsDone: 64619, pixelsTotal: 6262144 },
          },
        ],
      }),
    ).toBe(14)
  })

  it('falls back to snapshot/current when dispatch is absent', () => {
    expect(
      resolveJobOverallProgress({
        current: 12,
        snapshot: 35,
        nodeProgress: [
          { nodeId: 'fy_download', progress: 100 },
          { nodeId: 'workflow.node.n1', progress: 100 },
        ],
      }),
    ).toBe(35)
  })
})
