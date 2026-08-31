import { describe, expect, it } from 'vitest'

import {
  isNodeProgressSurfaceEvent,
  isOperationalEvent,
  mergeOperationalLog,
  messageImpliesTerminalNode,
} from '@/utils/workflow-operational-log'

describe('workflow-operational-log', () => {
  it('excludes node_progress surface ticks from operational log', () => {
    expect(
      isNodeProgressSurfaceEvent({
        channel: 'log',
        level: 'info',
        message: '文件 2/5',
        payload: { ui_surface: 'node_progress', node_progress: { node_id: 'x' } },
      }),
    ).toBe(true)
    expect(
      isOperationalEvent({
        channel: 'log',
        level: 'info',
        message: '文件 2/5',
        payload: { ui_surface: 'node_progress', node_progress: { node_id: 'x' } },
      }),
    ).toBe(false)
  })

  it('includes system channel events', () => {
    expect(
      isOperationalEvent({
        channel: 'system',
        level: 'info',
        message: '[nsidc] 开始',
        payload: { ui_surface: 'operational' },
      }),
    ).toBe(true)
  })

  it('mergeOperationalLog dedupes consecutive identical lines', () => {
    const merged = mergeOperationalLog([], [
      {
        channel: 'system',
        level: 'info',
        message: '派发到队列 workflow',
        payload: { ui_surface: 'operational', component: 'scheduler' },
      },
      {
        channel: 'system',
        level: 'info',
        message: '派发到队列 workflow',
        payload: { ui_surface: 'operational', component: 'scheduler' },
      },
    ])
    expect(merged).toHaveLength(1)
    expect(merged[0]).toContain('scheduler')
  })

  it('messageImpliesTerminalNode detects stage_end patterns', () => {
    expect(messageImpliesTerminalNode('Downloaded: 3/3 skipped=3')).toBe(true)
    expect(messageImpliesTerminalNode('running chunk 2/5')).toBe(false)
  })
})
