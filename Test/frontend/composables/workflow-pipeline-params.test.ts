/**
 * applyPipelineParamsToGraph / deriveJobTimeRangeFromGraph
 */
import { describe, expect, it } from 'vitest'

import {
  applyPipelineParamsToGraph,
  deriveJobTimeRangeFromGraph,
  yyyymmddPairToTimeRange,
} from '@/composables/workflow-pipeline-params'
import type { WorkflowDefinitionNode } from '@/services/workflow-definition-api'

function makeNode(overrides: Partial<WorkflowDefinitionNode>): WorkflowDefinitionNode {
  return {
    id: 1,
    type: 'io/output',
    title: 'n',
    properties: {},
    ...overrides,
  } as WorkflowDefinitionNode
}

describe('yyyymmddPairToTimeRange', () => {
  it('半开区间：end 为 end_date 次日 00:00', () => {
    expect(yyyymmddPairToTimeRange('20251201', '20260131')).toEqual({
      start_at: '2025-12-01T00:00:00',
      end_at: '2026-02-01T00:00:00',
      granularity: 'day',
    })
  })
})

describe('deriveJobTimeRangeFromGraph', () => {
  it('无 time_range 节点时从 download 日期推导（流水线路径）', () => {
    const tr = deriveJobTimeRangeFromGraph([
      makeNode({
        type: 'download/nsidc_smap_download',
        properties: { start_date: '20251201', end_date: '20260131' },
      }),
    ])
    expect(tr).toEqual({
      start_at: '2025-12-01T00:00:00',
      end_at: '2026-02-01T00:00:00',
      granularity: 'day',
    })
  })

  it('优先 data/time_range 节点', () => {
    const tr = deriveJobTimeRangeFromGraph([
      makeNode({
        type: 'download/fy_download',
        properties: { start_date: '20251201', end_date: '20260131' },
      }),
      makeNode({
        type: 'data/time_range',
        properties: {
          start_at: '2024-01-01T00:00:00',
          end_at: '2024-01-09T00:00:00',
        },
      }),
    ])
    expect(tr?.start_at).toBe('2024-01-01T00:00:00')
  })
})

describe('applyPipelineParamsToGraph', () => {
  const params = { start_date: '20240101', end_date: '20240108', tb_source: 'SMAP' }

  it('展开 download 节点 {YYYYMMDD} 占位并写入日期', () => {
    const graph = {
      nodes: [
        makeNode({
          id: 1,
          type: 'download/nsidc_smap_download',
          properties: {
            start_date: '{YYYYMMDD}',
            end_date: '{YYYYMMDD}',
            version: '6',
          },
        }),
      ],
      links: [],
    }
    const out = applyPipelineParamsToGraph(graph, params)
    expect(out.nodes[0].properties).toMatchObject({
      start_date: '20240101',
      end_date: '20240108',
      version: '6',
    })
  })

  it('同步 data/time_range 的 start_at/end_at（半开终点）', () => {
    const graph = {
      nodes: [
        makeNode({
          id: 7,
          type: 'data/time_range',
          properties: {
            start_at: '{TODAY-10}T00:00:00',
            end_at: '{TODAY-3}T00:00:00',
            bind_timeline: true,
          },
        }),
      ],
      links: [],
    }
    const out = applyPipelineParamsToGraph(graph, params)
    expect(out.nodes[0].properties).toMatchObject({
      start_at: '2024-01-01T00:00:00',
      end_at: '2024-01-09T00:00:00',
    })
  })

  it('合并 algorithm_params 并同步 target_year', () => {
    const graph = {
      nodes: [
        makeNode({
          id: 6,
          type: 'module/omega_avg_daily',
          properties: {
            module_name: 'omega_avg_daily',
            algorithm_params: {
              target_year: 2023,
              start_date: '{YYYYMMDD}',
              end_date: '{YYYYMMDD}',
              freq_ghz: 1.4,
            },
          },
        }),
      ],
      links: [],
    }
    const out = applyPipelineParamsToGraph(graph, {
      start_date: '20251201',
      end_date: '20260131',
      tb_source: 'SMAP',
    })
    expect(out.nodes[0].properties.algorithm_params).toMatchObject({
      start_date: '20251201',
      end_date: '20260131',
      tb_source: 'SMAP',
      target_year: 2025,
      freq_ghz: 1.4,
    })
  })

  it('无合法日期时不改写 download 占位', () => {
    const graph = {
      nodes: [
        makeNode({
          type: 'download/nsidc_smap_download',
          properties: { start_date: '{YYYYMMDD}', end_date: '{YYYYMMDD}' },
        }),
      ],
      links: [],
    }
    const out = applyPipelineParamsToGraph(graph, { tb_source: 'SMAP' })
    expect(out.nodes[0].properties).toMatchObject({
      start_date: '{YYYYMMDD}',
      end_date: '{YYYYMMDD}',
    })
  })
})
