import { describe, expect, it } from 'vitest'
import {
  localizeWorkflowDiagnostic,
  localizeWorkflowDiagnostics,
  localizeWorkflowErrorMessage,
} from '@/utils/workflow-error-messages'

describe('localizeWorkflowErrorMessage', () => {
  it('maps capacity errors to Chinese', () => {
    expect(localizeWorkflowErrorMessage('workflow capacity reached')).toContain('并发')
    expect(localizeWorkflowErrorMessage('HTTP 429 Too Many Requests')).toContain('并发')
  })

  it('preserves existing Chinese text', () => {
    expect(localizeWorkflowErrorMessage('工作流已取消')).toBe('工作流已取消')
  })
})

describe('localizeWorkflowDiagnostic', () => {
  it('translates error_code tokens', () => {
    expect(localizeWorkflowDiagnostic('error_code=workflow_cancelled_by_user')).toContain('取消')
  })

  it('unwraps error_message= prefix', () => {
    expect(localizeWorkflowDiagnostic('error_message=no workflow bridge matched')).toContain('引擎')
  })
})

describe('localizeWorkflowDiagnostics', () => {
  it('filters empty lines', () => {
    expect(localizeWorkflowDiagnostics(['', 'error_code=compile_error'])).toEqual(['工作流图编译失败。'])
  })
})
