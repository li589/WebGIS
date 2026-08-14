import { describe, expect, it } from 'vitest'
import {
  formatWorkflowValidationError,
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

describe('formatWorkflowValidationError', () => {
  it('appends field-level issues to summary and notes', () => {
    const { summary, notes } = formatWorkflowValidationError(
      '请求参数未通过业务校验，请检查表单字段。',
      [
        {
          field: 'datasource_selection._data_access_requests.fy_folder',
          message: "dataset 'fy_folder' not in accepted_data_access_datasets",
        },
      ],
    )
    expect(summary).toContain('请求参数未通过业务校验')
    expect(summary).toContain('fy_folder')
    expect(notes.some((n) => n.includes('fy_folder'))).toBe(true)
  })
})
