import { describe, expect, it } from 'vitest'
import {
  claimOrphanWorkflowRun,
  isSubmitTimeoutError,
} from '@/utils/workflow-submit-reconcile'

describe('claimOrphanWorkflowRun', () => {
  const t0 = Date.parse('2026-08-03T12:00:00.000Z')

  it('claims by command_label within window', () => {
    const claimed = claimOrphanWorkflowRun(
      [
        {
          run_id: 'run-a',
          command_label: 'other',
          created_at: new Date(t0 + 1000).toISOString(),
        },
        {
          run_id: 'run-b',
          command_label: 'SMAP 流水线',
          created_at: new Date(t0 + 2000).toISOString(),
        },
      ],
      { commandLabel: 'SMAP 流水线', submitStartedAt: t0 },
    )
    expect(claimed?.run_id).toBe('run-b')
  })

  it('ignores local-submit and excluded ids', () => {
    const claimed = claimOrphanWorkflowRun(
      [
        {
          run_id: 'local-submit-x',
          command_label: 'SMAP',
          created_at: new Date(t0 + 1000).toISOString(),
        },
        {
          run_id: 'run-c',
          command_label: 'SMAP',
          created_at: new Date(t0 + 1500).toISOString(),
        },
      ],
      {
        commandLabel: 'SMAP',
        submitStartedAt: t0,
        excludeRunIds: ['run-c'],
      },
    )
    expect(claimed).toBeNull()
  })

  it('detects timeout errors', () => {
    expect(isSubmitTimeoutError(new Error('请求超时（120000ms）'))).toBe(true)
    expect(isSubmitTimeoutError(new Error('Request failed: 400'))).toBe(false)
  })
})
