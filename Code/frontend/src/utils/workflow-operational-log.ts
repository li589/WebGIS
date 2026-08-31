/**
 * Operational workflow log lines (scheduler / node lifecycle / errors).
 * Excludes high-frequency node_progress ticks shown in the node progress UI.
 */

import type { WorkflowEvent } from '@/services/runtime-api'

export type WorkflowEventLike = Pick<
  WorkflowEvent,
  'channel' | 'message' | 'level' | 'payload' | 'created_at' | 'event_id'
>

const STAGE_END_RE = /Finished|skipped=|Downloaded:|Synced:|全部跳过|下载完成/i

/** Progress ticks with node_progress payload — not operational log. */
export function isNodeProgressSurfaceEvent(event: WorkflowEventLike): boolean {
  const payload = event.payload as Record<string, unknown> | null | undefined
  const uiSurface = payload?.ui_surface
  if (uiSurface === 'node_progress') return true
  if (uiSurface === 'operational') return false
  if (payload?.node_progress && event.channel === 'log' && event.level === 'info') {
    return true
  }
  return false
}

export function isOperationalEvent(event: WorkflowEventLike): boolean {
  if (isNodeProgressSurfaceEvent(event)) return false
  const ch = String(event.channel || '').toLowerCase()
  if (ch === 'system' || ch === 'status' || ch === 'notification') return true
  if (ch === 'log' && (event.level === 'warning' || event.level === 'error')) return true
  if (ch === 'log' && !payloadHasNodeProgress(event)) return true
  return false
}

function payloadHasNodeProgress(event: WorkflowEventLike): boolean {
  const payload = event.payload as Record<string, unknown> | null | undefined
  return Boolean(payload?.node_progress)
}

export function formatOperationalLine(event: WorkflowEventLike): string {
  const payload = event.payload as Record<string, unknown> | null | undefined
  const component = payload?.component ? String(payload.component) : ''
  const moduleName = payload?.module_name ? String(payload.module_name) : ''
  const nodeId = payload?.graph_node_id ? String(payload.graph_node_id) : ''
  const prefixParts = [
    component ? `[${component}]` : '',
    moduleName || nodeId ? `[${moduleName || nodeId}]` : '',
  ].filter(Boolean)
  const prefix = prefixParts.length ? `${prefixParts.join(' ')} ` : ''
  const level = event.level && event.level !== 'info' ? `${event.level.toUpperCase()} · ` : ''
  const ch =
    event.channel === 'system' ? '系统 · ' : event.channel === 'status' ? '状态 · ' : ''
  return `${level}${ch}${prefix}${String(event.message || '').trim()}`.trim()
}

export function extractFailureHints(events: WorkflowEventLike[]): string[] {
  const hints: string[] = []
  for (const event of events) {
    if (event.level !== 'error' && event.level !== 'warning') continue
    const line = formatOperationalLine(event)
    if (line) hints.push(line)
    const payload = event.payload as Record<string, unknown> | null | undefined
    if (!payload) continue
    for (const key of ['module_name', 'graph_node_id', 'component', 'queue', 'worker']) {
      const val = payload[key]
      if (val != null && String(val).trim()) {
        hints.push(`${key}=${String(val)}`)
      }
    }
  }
  return [...new Set(hints)].slice(-12)
}

export function messageImpliesTerminalNode(message: string | null | undefined): boolean {
  return STAGE_END_RE.test(String(message || ''))
}

export const MAX_OPERATIONAL_LOG_COUNT = 30

export function mergeOperationalLog(
  existing: string[] | undefined,
  incoming: WorkflowEventLike[],
): string[] {
  const merged = [...(existing ?? [])]
  for (const event of incoming) {
    if (!isOperationalEvent(event)) continue
    const text = formatOperationalLine(event)
    if (!text) continue
    if (merged[merged.length - 1] !== text) {
      merged.push(text)
    }
  }
  return merged.slice(-MAX_OPERATIONAL_LOG_COUNT)
}
