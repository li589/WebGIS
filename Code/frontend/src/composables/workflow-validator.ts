/**
 * workflow-validator.ts
 *
 * 工作流运行前统一参数校验器。
 * 遍历画布中所有节点，基于节点模板的 params/inputs 定义执行声明式校验，
 * 返回结构化 ValidationIssue 列表供 UI 展示和运行拦截。
 *
 * 校验项：
 *   1. 必填参数非空（无 default 值的 param）
 *   2. 日期范围 start_date <= end_date（YYYYMMDD 格式）
 *   3. 数值参数 min/max 范围
 *   4. enum 参数值在 options 列表内（allow_custom=false 时）
 *   5. 路径参数格式（非空、无非法字符）
 *   6. 节点必填输入端口已连接
 *   7. 下载节点专用校验（remote_path / local_path / 日期）
 */
import type {
  NodeTemplate,
  WorkflowDefinitionNode,
  WorkflowDefinitionLink,
} from '../services/workflow-definition-api'

// ─── 类型定义 ──────────────────────────────────────────────────────────────

export type ValidationSeverity = 'error' | 'warning'

export interface ValidationIssue {
  /** 产生问题的节点 ID */
  nodeId: number
  /** 节点类型（如 module/omega_sf_fenkuai） */
  nodeType: string
  /** 节点标题（用户可读） */
  nodeTitle: string
  /** 出错的参数 key 或端口名 */
  field: string
  /** 严重级别：error 阻止运行，warning 仅提示 */
  severity: ValidationSeverity
  /** 错误代码 */
  code:
    | 'required_empty'
    | 'date_range_invalid'
    | 'date_format_invalid'
    | 'number_out_of_range'
    | 'enum_value_invalid'
    | 'path_format_invalid'
    | 'port_disconnected'
    | 'module_name_missing'
    | 'custom'
  /** 用户可读的错误消息 */
  message: string
}

export interface ValidationResult {
  issues: ValidationIssue[]
  hasErrors: boolean
  hasWarnings: boolean
  errorCount: number
  warningCount: number
}

// ─── 常量 ──────────────────────────────────────────────────────────────────

/** 路径参数 key 模式（匹配 path/dir/folder 结尾的 key） */
const PATH_KEY_PATTERNS = [
  /_path$/,
  /_dir$/,
  /_folder$/,
  /^path$/,
  /^remote_path$/,
  /^local_path$/,
  /^input_dir$/,
  /^output_dir$/,
  /^local_dir$/,
]

/** 需要 module_name 属性的节点类型前缀 */
const MODULE_NODE_PREFIX = 'module/'

/** 下载节点类型前缀 */
const DOWNLOAD_NODE_PREFIX = 'download/'

/** Windows 非法路径字符（不含控制字符，控制字符单独检测） */
const ILLEGAL_PATH_CHARS = /[<>:"|?*]/

/** 检测字符串是否包含 ASCII 控制字符 (0x00-0x1f) */
function hasControlChars(s: string): boolean {
  for (let i = 0; i < s.length; i++) {
    if (s.charCodeAt(i) < 0x20) return true
  }
  return false
}

// ─── 工具函数 ──────────────────────────────────────────────────────────────

/** 判断 key 是否为路径类参数 */
function isPathKey(key: string): boolean {
  return PATH_KEY_PATTERNS.some((p) => p.test(key))
}

/** YYYYMMDD 格式校验 */
function isValidYYYYMMDD(value: string): boolean {
  if (!/^\d{8}$/.test(value)) return false
  const y = parseInt(value.slice(0, 4), 10)
  const m = parseInt(value.slice(4, 6), 10)
  const d = parseInt(value.slice(6, 8), 10)
  if (y < 1900 || y > 2100) return false
  if (m < 1 || m > 12) return false
  if (d < 1 || d > 31) return false
  return true
}

/** 比较两个 YYYYMMDD 日期字符串（返回 -1/0/1） */
function compareDates(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0
}

/** 判断值是否为"空"（null/undefined/空字符串/空数组） */
function isEmpty(value: unknown): boolean {
  if (value == null) return true
  if (typeof value === 'string') return value.trim() === ''
  if (Array.isArray(value)) return value.length === 0
  return false
}

// ─── 端口连接分析 ──────────────────────────────────────────────────────────

/**
 * 构建节点→已连接输入槽位索引集合的映射。
 * links 数组格式：[link_id, from_node, from_slot, to_node, to_slot, type]
 */
function buildConnectedInputSlotsMap(links: WorkflowDefinitionLink[]): Map<number, Set<number>> {
  const map = new Map<number, Set<number>>()
  for (const link of links) {
    const toNode = link[3]
    const toSlot = link[4]
    if (toNode == null || toSlot == null) continue
    if (!map.has(toNode)) map.set(toNode, new Set())
    map.get(toNode)!.add(toSlot)
  }
  return map
}

// ─── 单节点校验 ────────────────────────────────────────────────────────────

/**
 * 校验单个节点，返回 ValidationIssue 列表。
 *
 * @param node 工作流节点
 * @param template 节点模板（可为 null，表示未注册类型）
 * @param connectedInputSlots 已连接的输入槽位索引集合
 */
export function validateNode(
  node: WorkflowDefinitionNode,
  template: NodeTemplate | null,
  connectedInputSlots: Set<number> | undefined,
): ValidationIssue[] {
  const issues: ValidationIssue[] = []
  const nodeId = node.id
  const nodeType = node.type
  const nodeTitle = node.title || nodeType
  const props = node.properties ?? {}

  // ── 1. module 节点必须有 module_name ──
  if (nodeType.startsWith(MODULE_NODE_PREFIX)) {
    if (isEmpty(props.module_name)) {
      issues.push({
        nodeId,
        nodeType,
        nodeTitle,
        field: 'module_name',
        severity: 'error',
        code: 'module_name_missing',
        message: '缺少 module_name 属性',
      })
    }
  }

  // ── 2. 基于模板 params 的声明式校验 ──
  if (template?.params?.length) {
    for (const paramSpec of template.params) {
      const key = paramSpec.key
      const value = props[key]

      // 2a. 必填校验：无 default 值的参数视为必填
      if (paramSpec.default === undefined && isEmpty(value)) {
        // 跳过特殊情况：algorithm_params 和 datasource_selection 由端口提供
        if (key === 'algorithm_params' || key === 'datasource_selection') continue
        issues.push({
          nodeId,
          nodeType,
          nodeTitle,
          field: key,
          severity: 'error',
          code: 'required_empty',
          message: `参数 "${key}" 未设置`,
        })
        continue
      }

      // 空值跳过后续检查
      if (isEmpty(value)) continue

      // 2b. 数值范围校验
      if (paramSpec.type === 'number' && typeof value === 'number') {
        if (paramSpec.min != null && value < paramSpec.min) {
          issues.push({
            nodeId,
            nodeType,
            nodeTitle,
            field: key,
            severity: 'error',
            code: 'number_out_of_range',
            message: `参数 "${key}" 值 ${value} 小于最小值 ${paramSpec.min}`,
          })
        }
        if (paramSpec.max != null && value > paramSpec.max) {
          issues.push({
            nodeId,
            nodeType,
            nodeTitle,
            field: key,
            severity: 'error',
            code: 'number_out_of_range',
            message: `参数 "${key}" 值 ${value} 超过最大值 ${paramSpec.max}`,
          })
        }
      }

      // 2c. enum 校验（allow_custom=false 时值必须在 options 内）
      if (
        paramSpec.options?.length &&
        paramSpec.allow_custom === false &&
        typeof value === 'string'
      ) {
        if (!paramSpec.options.includes(value)) {
          issues.push({
            nodeId,
            nodeType,
            nodeTitle,
            field: key,
            severity: 'error',
            code: 'enum_value_invalid',
            message: `参数 "${key}" 值 "${value}" 不在允许列表内: ${paramSpec.options.join(', ')}`,
          })
        }
      }
    }
  }

  // ── 3. 日期范围校验 ──
  // 检查 properties 中的日期对，也检查 algorithm_params 内的日期
  const datePairs = findDatePairs(props)
  for (const { startKey, endKey, startVal, endVal } of datePairs) {
    if (startVal && endVal) {
      // 格式校验
      if (!isValidYYYYMMDD(startVal)) {
        issues.push({
          nodeId,
          nodeType,
          nodeTitle,
          field: startKey,
          severity: 'error',
          code: 'date_format_invalid',
          message: `日期 "${startKey}" 格式无效: ${startVal}（应为 YYYYMMDD）`,
        })
      }
      if (!isValidYYYYMMDD(endVal)) {
        issues.push({
          nodeId,
          nodeType,
          nodeTitle,
          field: endKey,
          severity: 'error',
          code: 'date_format_invalid',
          message: `日期 "${endKey}" 格式无效: ${endVal}（应为 YYYYMMDD）`,
        })
      }
      // 范围校验
      if (
        isValidYYYYMMDD(startVal) &&
        isValidYYYYMMDD(endVal) &&
        compareDates(startVal, endVal) > 0
      ) {
        issues.push({
          nodeId,
          nodeType,
          nodeTitle,
          field: endKey,
          severity: 'error',
          code: 'date_range_invalid',
          message: `日期范围无效: ${startKey}=${startVal} > ${endKey}=${endVal}`,
        })
      }
    }
  }

  // ── 4. 路径格式校验 ──
  for (const [key, value] of Object.entries(props)) {
    if (isPathKey(key) && typeof value === 'string' && value.trim()) {
      if (ILLEGAL_PATH_CHARS.test(value) || hasControlChars(value)) {
        issues.push({
          nodeId,
          nodeType,
          nodeTitle,
          field: key,
          severity: 'warning',
          code: 'path_format_invalid',
          message: `路径 "${key}" 含非法字符: ${value}`,
        })
      }
    }
  }

  // ── 5. 下载节点专用校验 ──
  if (nodeType.startsWith(DOWNLOAD_NODE_PREFIX)) {
    issues.push(...validateDownloadNode(node))
  }

  // ── 6. 必填输入端口连接检查 ──
  if (template?.inputs?.length) {
    for (let slotIdx = 0; slotIdx < template.inputs.length; slotIdx++) {
      const port = template.inputs[slotIdx]
      if (port.required) {
        // 跳过 config/dict 类型端口（datasource_selection / algorithm_params 等）
        // 这些端口通过属性而非连线提供数据
        if (port.type.includes('config') || port.type.includes('dict')) continue
        if (!connectedInputSlots?.has(slotIdx)) {
          issues.push({
            nodeId,
            nodeType,
            nodeTitle,
            field: port.name,
            severity: 'error',
            code: 'port_disconnected',
            message: `必填输入端口 "${port.name}" 未连接`,
          })
        }
      }
    }
  }

  return issues
}

/** 从节点属性中查找日期对（支持顶层和 algorithm_params 嵌套） */
function findDatePairs(props: Record<string, unknown>): Array<{
  startKey: string
  endKey: string
  startVal: string
  endVal: string
}> {
  const pairs: Array<{ startKey: string; endKey: string; startVal: string; endVal: string }> = []

  // 顶层属性
  const sd = asString(props.start_date)
  const ed = asString(props.end_date)
  if (sd || ed) {
    pairs.push({ startKey: 'start_date', endKey: 'end_date', startVal: sd ?? '', endVal: ed ?? '' })
  }

  // algorithm_params 嵌套
  const algoParams = props.algorithm_params
  if (algoParams && typeof algoParams === 'object' && !Array.isArray(algoParams)) {
    const ap = algoParams as Record<string, unknown>
    const apSd = asString(ap.start_date)
    const apEd = asString(ap.end_date)
    if (apSd || apEd) {
      pairs.push({
        startKey: 'algorithm_params.start_date',
        endKey: 'algorithm_params.end_date',
        startVal: apSd ?? '',
        endVal: apEd ?? '',
      })
    }
  }

  return pairs
}

/** 安全转为字符串 */
function asString(value: unknown): string | undefined {
  if (typeof value === 'string' && value.trim()) return value.trim()
  if (typeof value === 'number') return String(value)
  return undefined
}

// ─── 下载节点专用校验 ──────────────────────────────────────────────────────

function validateDownloadNode(node: WorkflowDefinitionNode): ValidationIssue[] {
  const issues: ValidationIssue[] = []
  const props = node.properties ?? {}
  const nodeType = node.type
  const nodeTitle = node.title || nodeType
  const nodeId = node.id

  if (nodeType === 'download/ssh_sync') {
    if (isEmpty(props.remote_path)) {
      issues.push({
        nodeId,
        nodeType,
        nodeTitle,
        field: 'remote_path',
        severity: 'error',
        code: 'required_empty',
        message: '远程路径不能为空',
      })
    }
    if (isEmpty(props.local_path)) {
      issues.push({
        nodeId,
        nodeType,
        nodeTitle,
        field: 'local_path',
        severity: 'error',
        code: 'required_empty',
        message: '本地路径不能为空',
      })
    }
    if (isEmpty(props.server_type)) {
      issues.push({
        nodeId,
        nodeType,
        nodeTitle,
        field: 'server_type',
        severity: 'error',
        code: 'required_empty',
        message: '服务器类型不能为空',
      })
    }
  }

  if (nodeType === 'download/nsidc_smap_download') {
    if (isEmpty(props.short_name)) {
      issues.push({
        nodeId,
        nodeType,
        nodeTitle,
        field: 'short_name',
        severity: 'error',
        code: 'required_empty',
        message: 'NSIDC 产品 short_name 不能为空',
      })
    }
    if (isEmpty(props.local_dir)) {
      issues.push({
        nodeId,
        nodeType,
        nodeTitle,
        field: 'local_dir',
        severity: 'error',
        code: 'required_empty',
        message: '本地下载目录不能为空',
      })
    }
  }

  if (nodeType === 'download/fy_preprocess') {
    if (isEmpty(props.input_dir)) {
      issues.push({
        nodeId,
        nodeType,
        nodeTitle,
        field: 'input_dir',
        severity: 'error',
        code: 'required_empty',
        message: '输入目录不能为空',
      })
    }
    if (isEmpty(props.output_dir)) {
      issues.push({
        nodeId,
        nodeType,
        nodeTitle,
        field: 'output_dir',
        severity: 'error',
        code: 'required_empty',
        message: '输出目录不能为空',
      })
    }
    if (isEmpty(props.satellite)) {
      issues.push({
        nodeId,
        nodeType,
        nodeTitle,
        field: 'satellite',
        severity: 'error',
        code: 'required_empty',
        message: '卫星类型不能为空',
      })
    }
  }

  return issues
}

// ─── 主校验入口 ────────────────────────────────────────────────────────────

/**
 * 校验整个工作流图，返回所有校验问题。
 *
 * @param graphData 画布序列化数据 { nodes, links }
 * @param nodeTemplates 节点模板列表（从 store 获取）
 * @returns ValidationResult 包含所有问题和汇总计数
 */
export function validateWorkflowBeforeRun(
  graphData: { nodes: WorkflowDefinitionNode[]; links: WorkflowDefinitionLink[] } | null,
  nodeTemplates: NodeTemplate[],
): ValidationResult {
  if (!graphData || !graphData.nodes?.length) {
    return {
      issues: [
        {
          nodeId: -1,
          nodeType: '',
          nodeTitle: '',
          field: '',
          severity: 'error',
          code: 'custom',
          message: '画布为空，请先添加节点',
        },
      ],
      hasErrors: true,
      hasWarnings: false,
      errorCount: 1,
      warningCount: 0,
    }
  }

  // 构建模板查找表
  const templateMap = new Map<string, NodeTemplate>()
  for (const tpl of nodeTemplates) {
    templateMap.set(tpl.type, tpl)
  }

  // 构建端口连接映射
  const connectedSlotsMap = buildConnectedInputSlotsMap(graphData.links ?? [])

  // 遍历所有节点
  const allIssues: ValidationIssue[] = []
  for (const node of graphData.nodes) {
    const template = templateMap.get(node.type) ?? null
    const connectedSlots = connectedSlotsMap.get(node.id)
    const nodeIssues = validateNode(node, template, connectedSlots)
    allIssues.push(...nodeIssues)
  }

  // 汇总
  const errorCount = allIssues.filter((i) => i.severity === 'error').length
  const warningCount = allIssues.filter((i) => i.severity === 'warning').length

  return {
    issues: allIssues,
    hasErrors: errorCount > 0,
    hasWarnings: warningCount > 0,
    errorCount,
    warningCount,
  }
}

// ─── 格式化工具 ────────────────────────────────────────────────────────────

/** 按节点分组校验问题 */
export function groupIssuesByNode(issues: ValidationIssue[]): Map<number, ValidationIssue[]> {
  const map = new Map<number, ValidationIssue[]>()
  for (const issue of issues) {
    if (!map.has(issue.nodeId)) map.set(issue.nodeId, [])
    map.get(issue.nodeId)!.push(issue)
  }
  return map
}

/** 获取指定节点的校验问题 */
export function getIssuesForNode(issues: ValidationIssue[], nodeId: number): ValidationIssue[] {
  return issues.filter((i) => i.nodeId === nodeId)
}

/** 获取指定节点指定字段的校验问题 */
export function getIssuesForField(
  issues: ValidationIssue[],
  nodeId: number,
  field: string,
): ValidationIssue[] {
  return issues.filter((i) => i.nodeId === nodeId && i.field === field)
}

/** 格式化为用户可读的摘要字符串 */
export function formatValidationSummary(result: ValidationResult): string {
  if (!result.hasErrors && !result.hasWarnings) {
    return '校验通过'
  }
  const parts: string[] = []
  if (result.errorCount > 0) {
    parts.push(`${result.errorCount} 个错误`)
  }
  if (result.warningCount > 0) {
    parts.push(`${result.warningCount} 个警告`)
  }
  return parts.join('，')
}

/** 格式化单个问题为可读字符串 */
export function formatIssue(issue: ValidationIssue): string {
  const prefix = issue.severity === 'error' ? '[错误]' : '[警告]'
  if (issue.nodeTitle) {
    return `${prefix} ${issue.nodeTitle} → ${issue.message}`
  }
  return `${prefix} ${issue.message}`
}
