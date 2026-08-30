/**
 * 将主界面时间轴窗口写入工作流图中 bind_timeline 的 time_range 节点。
 */
import type { WorkflowDefinitionNode } from '../../services/workflow-definition-api'
import { buildTimeRangeFromProps } from './dimension-model'

export function isWorkflowTimeRangeNode(node: {
  type?: string | null
  properties?: Record<string, unknown> | null
}): boolean {
  const props = (node.properties ?? {}) as Record<string, unknown>
  const ntype = String(node.type ?? '')
  return (
    ntype === 'data/time_range' ||
    ntype.endsWith('/time_range') ||
    props.module_name === 'time_range'
  )
}

export function nodeBindsMainTimeline(props: Record<string, unknown> | null | undefined): boolean {
  const built = buildTimeRangeFromProps(props ?? {})
  return Boolean(built.bind_timeline)
}

/** 纯函数：更新图节点 properties；不改其它字段。返回是否有变更。 */
export function applyBoundTimelineToGraphNodes(
  nodes: WorkflowDefinitionNode[],
  range: { start_at: string; end_at: string },
): { nodes: WorkflowDefinitionNode[]; changed: number } {
  const start = String(range.start_at || '').trim()
  const end = String(range.end_at || '').trim()
  if (!start || !end) return { nodes, changed: 0 }

  let changed = 0
  const next = nodes.map((node) => {
    if (!isWorkflowTimeRangeNode(node)) return node
    const props = { ...(node.properties as Record<string, unknown>) }
    if (!nodeBindsMainTimeline(props)) return node
    if (String(props.start_at ?? '') === start && String(props.end_at ?? '') === end) {
      return node
    }
    changed += 1
    return {
      ...node,
      properties: {
        ...props,
        start_at: start,
        end_at: end,
      },
    }
  })
  return { nodes: changed ? next : nodes, changed }
}
