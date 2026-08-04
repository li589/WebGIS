import { describe, expect, it } from 'vitest'
import {
  isLocalSubmitJobId,
  localSubmitJobId,
  shouldCallCancelApi,
  shouldResubmitInsteadOfRetry,
  shouldTrackWorkflowRunId,
} from '@/utils/workflow-local-submit'

describe('workflow-local-submit contract', () => {
  it('builds and detects local-submit ids', () => {
    expect(localSubmitJobId('wf-out-1')).toBe('local-submit-wf-out-1')
    expect(isLocalSubmitJobId('local-submit-wf-out-1')).toBe(true)
    expect(isLocalSubmitJobId('run-abc')).toBe(false)
    expect(isLocalSubmitJobId(null)).toBe(false)
  })

  it('forbids tracking and cancel API for optimistic ids', () => {
    expect(shouldTrackWorkflowRunId('local-submit-x')).toBe(false)
    expect(shouldCallCancelApi('local-submit-x')).toBe(false)
    expect(shouldTrackWorkflowRunId('run-1')).toBe(true)
    expect(shouldCallCancelApi('run-1')).toBe(true)
  })

  it('routes fake-id retry to resubmit', () => {
    expect(shouldResubmitInsteadOfRetry('local-submit-x')).toBe(true)
    expect(shouldResubmitInsteadOfRetry('run-1')).toBe(false)
  })
})
