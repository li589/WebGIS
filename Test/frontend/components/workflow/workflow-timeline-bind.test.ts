import { describe, expect, it } from 'vitest'

import { applyBoundTimelineToGraphNodes } from '@/components/workflow/workflow-timeline-bind'
import type { WorkflowDefinitionNode } from '@/services/workflow-definition-api'

function timeNode(
  id: string,
  props: Record<string, unknown>,
): WorkflowDefinitionNode {
  return {
    id,
    type: 'data/time_range',
    title: '时间窗',
    properties: props,
  } as WorkflowDefinitionNode
}

describe('applyBoundTimelineToGraphNodes', () => {
  it('updates bind_timeline time_range nodes', () => {
    const nodes = [
      timeNode('a', { bind_timeline: true, start_at: '2025-01-01', end_at: '2025-01-08' }),
      timeNode('b', { bind_timeline: false, start_at: '2024-01-01', end_at: '2024-01-08' }),
      { id: 'c', type: 'module/other', title: 'x', properties: {} } as WorkflowDefinitionNode,
    ]
    const { nodes: next, changed } = applyBoundTimelineToGraphNodes(nodes, {
      start_at: '2025-12-01',
      end_at: '2025-12-08',
    })
    expect(changed).toBe(1)
    expect(next[0]!.properties).toMatchObject({
      start_at: '2025-12-01',
      end_at: '2025-12-08',
    })
    expect(next[1]!.properties).toMatchObject({
      start_at: '2024-01-01',
      end_at: '2024-01-08',
    })
  })

  it('defaults bind_timeline to true when unset', () => {
    const nodes = [timeNode('a', { start_at: 'a', end_at: 'b' })]
    const { changed } = applyBoundTimelineToGraphNodes(nodes, {
      start_at: '2026-01-01',
      end_at: '2026-01-08',
    })
    expect(changed).toBe(1)
  })

  it('no-ops when range empty', () => {
    const nodes = [timeNode('a', { bind_timeline: true, start_at: 'a', end_at: 'b' })]
    const { changed } = applyBoundTimelineToGraphNodes(nodes, { start_at: '', end_at: '' })
    expect(changed).toBe(0)
  })
})
