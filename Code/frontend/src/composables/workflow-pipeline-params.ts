/**
 * 流水线启动器参数 → 工作流图节点注入；以及从图推导 job 级 time_range。
 *
 * 覆盖：
 * - data/time_range（start_at / end_at）
 * - 任意节点顶层 start_date / end_date（含种子 {YYYYMMDD} 占位）
 * - download/* 节点（即便种子未写日期键也会写入）
 * - module.algorithm_params 合并（含 target_year 与流水线日期对齐）
 *
 * 注意：多数 online 种子无 data/time_range 节点。提交时必须用
 * deriveJobTimeRangeFromGraph / yyyymmddPairToTimeRange 把流水线日期写成
 * payload.time_range，禁止回落主界面时间轴「今天」。
 */
import type {
  WorkflowDefinitionLink,
  WorkflowDefinitionNode,
} from '@/services/workflow-definition-api'

const DATE_PLACEHOLDER = '{YYYYMMDD}'

function isYyyymmdd(value: string): boolean {
  return /^\d{8}$/.test(value)
}

function toIsoDateTime(value: string): string {
  return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}T00:00:00`
}

/** end_date 当日的次日 00:00（半开区间 [start, end)）。 */
function toExclusiveEndIso(yyyymmdd: string): string {
  const y = Number(yyyymmdd.slice(0, 4))
  const m = Number(yyyymmdd.slice(4, 6))
  const d = Number(yyyymmdd.slice(6, 8))
  const dt = new Date(y, m - 1, d)
  dt.setDate(dt.getDate() + 1)
  const yy = dt.getFullYear()
  const mm = String(dt.getMonth() + 1).padStart(2, '0')
  const dd = String(dt.getDate()).padStart(2, '0')
  return `${yy}-${mm}-${dd}T00:00:00`
}

function shouldOverwriteDateField(value: unknown): boolean {
  if (value == null) return true
  if (typeof value !== 'string') return false
  const trimmed = value.trim()
  return trimmed === '' || trimmed === DATE_PLACEHOLDER || isYyyymmdd(trimmed)
}

export type JobTimeRangePayload = {
  start_at: string
  end_at: string
  granularity: string
}

/**
 * 流水线 YYYYMMDD 对 → 提交用 time_range（半开 [start, end+1day)）。
 */
export function yyyymmddPairToTimeRange(
  startDate: string,
  endDate: string,
  granularity = 'day',
): JobTimeRangePayload | null {
  const sd = String(startDate || '').trim()
  const ed = String(endDate || '').trim()
  if (!isYyyymmdd(sd) || !isYyyymmdd(ed) || sd > ed) return null
  return {
    start_at: toIsoDateTime(sd),
    end_at: toExclusiveEndIso(ed),
    granularity,
  }
}

/**
 * 从画布节点推导 job 级 time_range。
 * 优先级：data/time_range 节点 → 节点/algorithm_params 的 start_date+end_date。
 */
export function deriveJobTimeRangeFromGraph(
  nodes: Array<Record<string, unknown> | WorkflowDefinitionNode>,
): JobTimeRangePayload | null {
  let fromDates: JobTimeRangePayload | null = null

  for (const node of nodes) {
    const props = ((node as { properties?: unknown; params?: unknown }).properties ??
      (node as { params?: unknown }).params ??
      {}) as Record<string, unknown>
    const ntype = String(
      (node as { type?: unknown }).type ?? (node as { node_type?: unknown }).node_type ?? '',
    )
    const isTime =
      ntype === 'data/time_range' ||
      ntype.endsWith('/time_range') ||
      props.module_name === 'time_range'
    if (isTime) {
      const startAt = String(props.start_at ?? '').trim()
      const endAt = String(props.end_at ?? '').trim()
      if (startAt && endAt && !startAt.includes('{') && !endAt.includes('{')) {
        return {
          start_at: startAt,
          end_at: endAt,
          granularity: String(props.granularity ?? 'day'),
        }
      }
    }

    const topSd = typeof props.start_date === 'string' ? props.start_date.trim() : ''
    const topEd = typeof props.end_date === 'string' ? props.end_date.trim() : ''
    if (!fromDates && isYyyymmdd(topSd) && isYyyymmdd(topEd)) {
      fromDates = yyyymmddPairToTimeRange(topSd, topEd)
    }

    const ap = props.algorithm_params
    if (ap && typeof ap === 'object' && !Array.isArray(ap)) {
      const rec = ap as Record<string, unknown>
      const sd = typeof rec.start_date === 'string' ? rec.start_date.trim() : ''
      const ed = typeof rec.end_date === 'string' ? rec.end_date.trim() : ''
      if (!fromDates && isYyyymmdd(sd) && isYyyymmdd(ed)) {
        fromDates = yyyymmddPairToTimeRange(sd, ed)
      }
    }
  }

  return fromDates
}

/**
 * 将流水线启动器参数同步到算法节点、下载节点与 data/time_range。
 */
export function applyPipelineParamsToGraph(
  graphData: { nodes: WorkflowDefinitionNode[]; links: WorkflowDefinitionLink[] },
  params: Record<string, unknown>,
): { nodes: WorkflowDefinitionNode[]; links: WorkflowDefinitionLink[] } {
  const startDate = typeof params.start_date === 'string' ? params.start_date.trim() : ''
  const endDate = typeof params.end_date === 'string' ? params.end_date.trim() : ''
  const hasDates = isYyyymmdd(startDate) && isYyyymmdd(endDate)
  const startAt = hasDates ? toIsoDateTime(startDate) : ''
  // time_range 节点：半开终点，与 job payload / 时间轴切片一致
  const endAtExclusive = hasDates ? toExclusiveEndIso(endDate) : ''
  const inferredYear = hasDates ? Number(startDate.slice(0, 4)) : null

  const updatedNodes = graphData.nodes.map((node) => {
    const nodeProps = { ...(node.properties as Record<string, unknown>) }
    let changed = false

    const isTimeRangeNode =
      node.type === 'data/time_range' || nodeProps.module_name === 'time_range'
    if (isTimeRangeNode && startAt && endAtExclusive) {
      nodeProps.start_at = startAt
      nodeProps.end_at = endAtExclusive
      changed = true
    }

    if (hasDates) {
      const isDownload = node.type.startsWith('download/')
      const hasDateKeys = 'start_date' in nodeProps || 'end_date' in nodeProps
      if (
        isDownload ||
        (hasDateKeys &&
          shouldOverwriteDateField(nodeProps.start_date) &&
          shouldOverwriteDateField(nodeProps.end_date))
      ) {
        if (isDownload || hasDateKeys) {
          nodeProps.start_date = startDate
          nodeProps.end_date = endDate
          changed = true
        }
      }
    }

    if (
      nodeProps.algorithm_params &&
      typeof nodeProps.algorithm_params === 'object' &&
      !Array.isArray(nodeProps.algorithm_params)
    ) {
      const ap = {
        ...(nodeProps.algorithm_params as Record<string, unknown>),
        ...params,
      }
      // ω 平均链种子默认 target_year=2023；流水线给了日期则对齐到起始年
      if (
        inferredYear != null &&
        Number.isFinite(inferredYear) &&
        ('target_year' in ap || String(nodeProps.module_name || '').includes('omega_avg'))
      ) {
        ap.target_year = inferredYear
      }
      nodeProps.algorithm_params = ap
      changed = true
    }

    if (!changed) return node
    return { ...node, properties: nodeProps }
  })

  return { nodes: updatedNodes, links: graphData.links }
}
