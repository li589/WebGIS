import { describe, expect, it } from 'vitest'
import { matchSliceLabelInTimeList, timelineTargetFromWorkflowTimeKey } from '@/utils/workflow-timekey-seek'

describe('timelineTargetFromWorkflowTimeKey', () => {
  it('parses YYYYMMDD point key', () => {
    const t = timelineTargetFromWorkflowTimeKey('20251203')
    expect(t?.sliceLabel).toBe('20251203')
    expect(t?.date.getFullYear()).toBe(2025)
    expect(t?.granularity).toBe('day')
  })

  it('builds range label from dateStart and dateEnd', () => {
    const t = timelineTargetFromWorkflowTimeKey('20251227', '20251231')
    expect(t?.sliceLabel).toBe('20251227_20251231')
  })

  it('accepts preformatted range key', () => {
    const t = timelineTargetFromWorkflowTimeKey('20251227_20251231')
    expect(t?.sliceLabel).toBe('20251227_20251231')
  })
})

describe('matchSliceLabelInTimeList', () => {
  it('prefers exact match', () => {
    expect(matchSliceLabelInTimeList(['20251201', '20251227_20251231'], '20251227_20251231')).toBe(
      '20251227_20251231',
    )
  })
})
