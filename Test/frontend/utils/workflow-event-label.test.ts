import { describe, expect, it } from 'vitest'
import { formatWorkflowEventLine } from '@/utils/workflow-event-label'

describe('formatWorkflowEventLine', () => {
  it('labels known channels in Chinese', () => {
    expect(formatWorkflowEventLine('system', 'queued')).toBe('系统 · queued')
    expect(formatWorkflowEventLine('progress', '50%')).toBe('进度 · 50%')
  })

  it('passes through unknown channels', () => {
    expect(formatWorkflowEventLine('custom', 'hello')).toBe('custom · hello')
  })

  it('returns label only when message empty', () => {
    expect(formatWorkflowEventLine('log', '')).toBe('日志')
  })
})
