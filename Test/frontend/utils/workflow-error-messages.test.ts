import { describe, expect, it } from 'vitest'
import {
  extractFailureCategory,
  extractWorkflowTechLogs,
  formatWorkflowCommandChip,
  formatWorkflowValidationError,
  isCoverageGapFailure,
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

  it('maps asset_state and hides noise keys', () => {
    expect(localizeWorkflowDiagnostic('asset_state=missing')).toBe('资产状态：缺失')
    expect(localizeWorkflowDiagnostic('returncode=0')).toBe('')
    expect(localizeWorkflowDiagnostic('remaining_stale=[]')).toBe('')
    expect(localizeWorkflowDiagnostic('bake_log=huge dump')).toBe('')
  })

  it('compresses legacy overlay export dumps', () => {
    const dump =
      '==== Overlay Assets Export Tool === [SKIP] File not found === Summary: [OK]'
    expect(localizeWorkflowDiagnostic(dump)).toContain('源数据文件未找到')
  })
})

describe('localizeWorkflowDiagnostics', () => {
  it('filters empty lines', () => {
    expect(localizeWorkflowDiagnostics(['', 'error_code=compile_error'])).toEqual([
      '工作流图编译失败。',
    ])
  })
})

describe('formatWorkflowCommandChip', () => {
  it('prefers command_label over enum', () => {
    expect(formatWorkflowCommandChip('custom', '图层资产工作流')).toBe('图层资产工作流')
    expect(formatWorkflowCommandChip('custom')).toBe('自定义')
    expect(formatWorkflowCommandChip('analysis')).toBe('分析')
  })
})

describe('extractWorkflowTechLogs', () => {
  it('extracts bake_log and legacy dumps', () => {
    expect(
      extractWorkflowTechLogs([
        'asset_state=missing',
        'bake_log=line1\nline2',
        '==== Overlay Assets Export Tool ===',
      ]),
    ).toEqual(['line1\nline2', '==== Overlay Assets Export Tool ==='])
  })
})

describe('extractFailureCategory / isCoverageGapFailure', () => {
  it('parses failure_category= and error_code= from diagnostics', () => {
    expect(
      extractFailureCategory({
        diagnostics: ['failure_category=coverage_gap', 'retryable=False'],
      }),
    ).toBe('coverage_gap')
    expect(
      extractFailureCategory({
        diagnostics: ['error_code=coverage_gap 时间窗零交集'],
      }),
    ).toBe('coverage_gap')
    expect(
      extractFailureCategory({
        message: 'error_code=coverage_gap 本地无数据',
      }),
    ).toBe('coverage_gap')
  })

  it('detects coverage_gap via category, token, or Chinese fallback', () => {
    expect(isCoverageGapFailure({ failureCategory: 'coverage_gap' })).toBe(true)
    expect(
      isCoverageGapFailure({
        diagnostics: ['failure_category=coverage_gap'],
        message: '工作流执行失败',
      }),
    ).toBe(true)
    expect(
      isCoverageGapFailure({
        message: '时间窗与本地 SMAP 零交集（未启用对齐）',
      }),
    ).toBe(true)
    expect(
      isCoverageGapFailure({
        message:
          'No FY HDF files found in I:\\Geograph_DataSet\\Soil_Moisture\\FY3D',
        failureCategory: 'transient_upstream',
      }),
    ).toBe(true)
    expect(
      isCoverageGapFailure({
        message: '文件不存在: I:\\Geograph_DataSet\\FY',
      }),
    ).toBe(true)
    expect(isCoverageGapFailure({ message: '工作流执行失败，请查看服务端日志。' })).toBe(
      false,
    )
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
