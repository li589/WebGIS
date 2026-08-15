/**
 * W3.4e：workflow-validator 纯逻辑校验器测试。
 *
 * 覆盖 validateNode（module_name / 必填 / 数值范围 / enum / 日期格式与范围 /
 * 路径非法字符 / 下载节点专用 / 必填端口）、validateWorkflowBeforeRun（空画布 /
 * 模板查找 / 连接映射 / 汇总）、findDatePairs 嵌套 algorithm_params，
 * 以及 groupIssuesByNode / getIssuesForNode / getIssuesForField /
 * formatValidationSummary / formatIssue 工具函数。
 */
import { describe, expect, it } from 'vitest'

import {
  formatIssue,
  formatValidationSummary,
  getIssuesForField,
  getIssuesForNode,
  groupIssuesByNode,
  validateNode,
  validateWorkflowBeforeRun,
} from '@/composables/workflow-validator'
import type {
  NodeTemplate,
  WorkflowDefinitionLink,
  WorkflowDefinitionNode,
} from '@/services/workflow-definition-api'

function makeNode(overrides: Partial<WorkflowDefinitionNode> = {}): WorkflowDefinitionNode {
  return {
    id: 1,
    type: 'io/output',
    title: '输出',
    properties: {},
    ...overrides,
  } as WorkflowDefinitionNode
}

function makeTemplate(overrides: Partial<NodeTemplate> = {}): NodeTemplate {
  return {
    type: 'io/output',
    title: '输出',
    params: [],
    inputs: [],
    ...overrides,
  } as NodeTemplate
}

describe('validateNode：module 节点', () => {
  it('module/ 前缀节点缺 module_name 报 error', () => {
    const node = makeNode({ type: 'module/omega_sf_fenkuai' })
    const issues = validateNode(node, null, undefined)
    expect(issues).toHaveLength(1)
    expect(issues[0]).toMatchObject({
      code: 'module_name_missing',
      field: 'module_name',
      severity: 'error',
    })
  })

  it('module_name 已设置时不报', () => {
    const node = makeNode({ type: 'module/x', properties: { module_name: 'm1' } })
    expect(validateNode(node, null, undefined)).toHaveLength(0)
  })
})

describe('validateNode：模板声明式校验', () => {
  it('无 default 的参数为必填，空值报 required_empty', () => {
    const tpl = makeTemplate({
      params: [{ key: 'threshold', type: 'number' } as never],
    })
    const issues = validateNode(makeNode(), tpl, undefined)
    expect(issues).toHaveLength(1)
    expect(issues[0]).toMatchObject({ code: 'required_empty', field: 'threshold' })
  })

  it('algorithm_params / datasource_selection 必填豁免', () => {
    const tpl = makeTemplate({
      params: [
        { key: 'algorithm_params' } as never,
        { key: 'datasource_selection' } as never,
      ],
    })
    expect(validateNode(makeNode(), tpl, undefined)).toHaveLength(0)
  })

  it('有 default 的参数空值不报错', () => {
    const tpl = makeTemplate({
      params: [{ key: 'level', type: 'number', default: 2 } as never],
    })
    expect(validateNode(makeNode(), tpl, undefined)).toHaveLength(0)
  })

  it('数值小于 min / 大于 max 各报 number_out_of_range', () => {
    const tpl = makeTemplate({
      params: [{ key: 'ratio', type: 'number', min: 0, max: 1 } as never],
    })
    const low = validateNode(
      makeNode({ properties: { ratio: -0.5 } }),
      tpl,
      undefined,
    )
    expect(low).toHaveLength(1)
    expect(low[0].message).toContain('小于最小值')

    const high = validateNode(
      makeNode({ properties: { ratio: 1.5 } }),
      tpl,
      undefined,
    )
    expect(high[0].message).toContain('超过最大值')
  })

  it('enum allow_custom=false 时非法值报 enum_value_invalid', () => {
    const tpl = makeTemplate({
      params: [
        { key: 'mode', type: 'enum', options: ['a', 'b'], allow_custom: false } as never,
      ],
    })
    const issues = validateNode(makeNode({ properties: { mode: 'c' } }), tpl, undefined)
    expect(issues).toHaveLength(1)
    expect(issues[0].code).toBe('enum_value_invalid')
    expect(issues[0].message).toContain('a, b')
  })

  it('enum 合法值或 allow_custom=true 不报', () => {
    const tpl = makeTemplate({
      params: [
        { key: 'mode', type: 'enum', options: ['a'], allow_custom: false } as never,
      ],
    })
    expect(validateNode(makeNode({ properties: { mode: 'a' } }), tpl, undefined)).toHaveLength(0)
    const custom = makeTemplate({
      params: [{ key: 'mode', type: 'enum', options: ['a'], allow_custom: true } as never],
    })
    expect(validateNode(makeNode({ properties: { mode: 'z' } }), custom, undefined)).toHaveLength(0)
  })
})

describe('validateNode：日期校验', () => {
  it('start > end 报 date_range_invalid', () => {
    const issues = validateNode(
      makeNode({ properties: { start_date: '20240702', end_date: '20240701' } }),
      null,
      undefined,
    )
    expect(issues).toHaveLength(1)
    expect(issues[0]).toMatchObject({ code: 'date_range_invalid', field: 'end_date' })
  })

  it('非 YYYYMMDD 格式报 date_format_invalid（start 与 end 各一）', () => {
    const issues = validateNode(
      makeNode({ properties: { start_date: '2024-07-01', end_date: '99999999' } }),
      null,
      undefined,
    )
    expect(issues).toHaveLength(2)
    expect(issues.map((i) => i.code)).toEqual(['date_format_invalid', 'date_format_invalid'])
    expect(issues.map((i) => i.field)).toEqual(['start_date', 'end_date'])
  })

  it('非法月份/日期（13 月、32 日）视为格式无效', () => {
    const issues = validateNode(
      makeNode({ properties: { start_date: '20241301', end_date: '20240132' } }),
      null,
      undefined,
    )
    expect(issues.map((i) => i.code)).toEqual(['date_format_invalid', 'date_format_invalid'])
  })

  it('algorithm_params 嵌套日期对同样参与校验', () => {
    const issues = validateNode(
      makeNode({
        properties: { algorithm_params: { start_date: '20240502', end_date: '20240501' } },
      }),
      null,
      undefined,
    )
    expect(issues).toHaveLength(1)
    expect(issues[0].field).toBe('algorithm_params.end_date')
  })

  it('仅一侧有日期（另一侧空）不做范围比较', () => {
    const issues = validateNode(
      makeNode({ properties: { start_date: '20240701' } }),
      null,
      undefined,
    )
    expect(issues).toHaveLength(0)
  })

  it('数字型日期被 asString 接受并可参与比较', () => {
    const issues = validateNode(
      makeNode({ properties: { start_date: 20240702, end_date: 20240701 } }),
      null,
      undefined,
    )
    expect(issues).toHaveLength(1)
    expect(issues[0].code).toBe('date_range_invalid')
  })
})

describe('validateNode：路径非法字符', () => {
  it.each([
    ['output_dir', 'I:\\data<illegal>'],
    ['local_path', 'D:/a|b'],
    ['path', 'E:/x?y'],
  ])('%s 含非法字符报 warning', (key, value) => {
    const issues = validateNode(makeNode({ properties: { [key]: value } }), null, undefined)
    expect(issues).toHaveLength(1)
    expect(issues[0]).toMatchObject({
      code: 'path_format_invalid',
      severity: 'warning',
      field: key,
    })
  })

  it('合法路径不报', () => {
    const issues = validateNode(
      makeNode({ properties: { output_dir: 'I:/Geograph_DataSet/out' } }),
      null,
      undefined,
    )
    expect(issues).toHaveLength(0)
  })
})

describe('validateNode：下载节点专用校验', () => {
  it('download/ssh_sync 缺 remote_path/local_path/server_type 报三条', () => {
    const issues = validateNode(makeNode({ type: 'download/ssh_sync' }), null, undefined)
    expect(issues.map((i) => i.field)).toEqual(['remote_path', 'local_path', 'server_type'])
  })

  it('download/nsidc_smap_download 缺 short_name/local_dir 报两条', () => {
    const issues = validateNode(makeNode({ type: 'download/nsidc_smap_download' }), null, undefined)
    expect(issues.map((i) => i.field)).toEqual(['short_name', 'local_dir'])
  })

  it('download/gldas_download 缺 short_name/local_dir 报两条', () => {
    const issues = validateNode(makeNode({ type: 'download/gldas_download' }), null, undefined)
    expect(issues.map((i) => i.field)).toEqual(['short_name', 'local_dir'])
  })

  it('download/gldas_nc4_to_mat 缺 input_dir/output_dir 报两条', () => {
    const issues = validateNode(makeNode({ type: 'download/gldas_nc4_to_mat' }), null, undefined)
    expect(issues.map((i) => i.field)).toEqual(['input_dir', 'output_dir'])
  })

  it('download/fy_preprocess 缺 input_dir/output_dir/satellite 报三条', () => {
    const issues = validateNode(makeNode({ type: 'download/fy_preprocess' }), null, undefined)
    expect(issues.map((i) => i.field)).toEqual(['input_dir', 'output_dir', 'satellite'])
  })

  it('未知 download/ 类型无专用问题', () => {
    expect(validateNode(makeNode({ type: 'download/other' }), null, undefined)).toHaveLength(0)
  })
})

describe('validateNode：必填端口连接', () => {
  const tpl = makeTemplate({
    inputs: [
      { name: 'raster_in', type: 'raster', required: true },
      { name: 'config_in', type: 'config/dict', required: true },
      { name: 'optional_in', type: 'raster', required: false },
    ] as never,
  })

  it('必填端口未连接报 port_disconnected；config/dict 类型豁免', () => {
    const issues = validateNode(makeNode(), tpl, new Set([2]))
    expect(issues).toHaveLength(1)
    expect(issues[0]).toMatchObject({
      code: 'port_disconnected',
      field: 'raster_in',
      severity: 'error',
    })
  })

  it('端口已连接（槽位命中）不报', () => {
    expect(validateNode(makeNode(), tpl, new Set([0]))).toHaveLength(0)
  })
})

describe('validateWorkflowBeforeRun', () => {
  const nodeA = makeNode({ id: 10, type: 'module/m1' })
  const nodeB = makeNode({ id: 20, type: 'io/output', properties: { start_date: '20240102', end_date: '20240101' } })
  const templates = [makeTemplate({ type: 'io/output' })]

  it('空画布 / null 返回画布为空错误', () => {
    for (const graph of [null, { nodes: [], links: [] }]) {
      const result = validateWorkflowBeforeRun(graph as never, [])
      expect(result.hasErrors).toBe(true)
      expect(result.errorCount).toBe(1)
      expect(result.issues[0].message).toContain('画布为空')
    }
  })

  it('多节点问题汇总与 error/warning 计数', () => {
    const links: WorkflowDefinitionLink[] = [
      [1, 5, 0, 10, 0, 'raster'],
    ] as unknown as WorkflowDefinitionLink[]
    const result = validateWorkflowBeforeRun({ nodes: [nodeA, nodeB], links }, templates)
    expect(result.errorCount).toBe(2)
    expect(result.warningCount).toBe(0)
    expect(result.issues.map((i) => i.nodeId).sort()).toEqual([10, 20])
  })

  it('无问题时校验通过', () => {
    const ok = makeNode({
      id: 1,
      type: 'io/output',
      properties: { module_name: 'x', start_date: '20240101', end_date: '20240102' },
    })
    const result = validateWorkflowBeforeRun({ nodes: [ok], links: [] }, templates)
    expect(result.hasErrors).toBe(false)
    expect(result.issues).toHaveLength(0)
  })

  it('links 槽位为空值时跳过（防御分支）', () => {
    const links = [[1, 5, 0, null, null, 'raster']] as unknown as WorkflowDefinitionLink[]
    const result = validateWorkflowBeforeRun({ nodes: [makeNode({ id: 1 })], links }, [])
    expect(result.issues).toHaveLength(0)
  })
})

describe('格式化与分组工具', () => {
  const issueA = {
    nodeId: 1,
    nodeType: 't',
    nodeTitle: '节点一',
    field: 'f1',
    severity: 'error',
    code: 'required_empty',
    message: '参数 "f1" 未设置',
  } as never
  const issueB = {
    nodeId: 2,
    nodeType: 't',
    nodeTitle: '',
    field: 'f2',
    severity: 'warning',
    code: 'path_format_invalid',
    message: '路径含非法字符',
  } as never
  const issueC = { ...issueA, field: 'f3' } as never

  it('groupIssuesByNode 按节点分组保持顺序', () => {
    const map = groupIssuesByNode([issueA, issueB, issueC])
    expect(map.size).toBe(2)
    expect(map.get(1)!.map((i) => i.field)).toEqual(['f1', 'f3'])
    expect(map.get(2)!.map((i) => i.field)).toEqual(['f2'])
  })

  it('getIssuesForNode / getIssuesForField 过滤', () => {
    const issues = [issueA, issueB, issueC]
    expect(getIssuesForNode(issues, 2)).toHaveLength(1)
    expect(getIssuesForField(issues, 1, 'f3')).toHaveLength(1)
    expect(getIssuesForField(issues, 2, 'f3')).toHaveLength(0)
  })

  it('formatValidationSummary：通过 / 错误 / 错误+警告', () => {
    expect(
      formatValidationSummary({
        issues: [],
        hasErrors: false,
        hasWarnings: false,
        errorCount: 0,
        warningCount: 0,
      }),
    ).toBe('校验通过')
    expect(
      formatValidationSummary({
        issues: [issueA],
        hasErrors: true,
        hasWarnings: false,
        errorCount: 1,
        warningCount: 0,
      }),
    ).toBe('1 个错误')
    expect(
      formatValidationSummary({
        issues: [issueA, issueB],
        hasErrors: true,
        hasWarnings: true,
        errorCount: 1,
        warningCount: 1,
      }),
    ).toBe('1 个错误，1 个警告')
  })

  it('formatIssue：带标题 / 不带标题', () => {
    expect(formatIssue(issueA)).toBe('[错误] 节点一 → 参数 "f1" 未设置')
    expect(formatIssue(issueB)).toBe('[警告] 路径含非法字符')
  })
})
