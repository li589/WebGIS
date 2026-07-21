/**
 * 工作流定时器 API 服务
 *
 * Phase 4: 提供与后端 /workflow-timers 端点的交互。
 * 支持三种触发类型：cron（Cron 表达式）、interval（固定间隔）、event（事件触发）。
 */
import { requestJson } from './_http'

// ─── 类型定义 ──────────────────────────────────────────────────────────────
export type TriggerType = 'cron' | 'interval' | 'event'

export interface TriggerConfig {
  /** cron 触发器：5 字段 cron 表达式（minute hour day month weekday） */
  cron?: string
  /** interval 触发器：间隔秒数（>= 60） */
  seconds?: number
  /** event 触发器：事件类型字符串 */
  event_type?: string
}

export interface PayloadOverrides {
  layer_id?: string
  command_label?: string
  parameters?: Record<string, unknown>
  time_range?: unknown
  spatial_filter?: unknown
  config_overrides?: Record<string, unknown>
  realtime_preferred?: boolean
  priority?: string
  resource_profile?: string
  queue_tag?: string | null
}

export interface WorkflowTimer {
  timer_id: string
  workflow_id: string
  name: string
  trigger_type: TriggerType
  trigger_config: TriggerConfig
  payload_overrides: PayloadOverrides
  enabled: boolean
  last_fired_at: string | null
  next_fire_at: string | null
  last_run_id: string | null
  last_error: string | null
  fire_count: number
  created_at: string
  updated_at: string
}

export interface CreateTimerPayload {
  workflow_id: string
  name: string
  trigger_type: TriggerType
  trigger_config: TriggerConfig
  payload_overrides?: PayloadOverrides
  enabled?: boolean
}

export interface UpdateTimerPayload {
  name?: string
  enabled?: boolean
  trigger_type?: TriggerType
  trigger_config?: TriggerConfig
  payload_overrides?: PayloadOverrides
}

export interface ManualTriggerResponse {
  timer_id: string
  run_id: string
  status_url: string
  triggered_at: string
}

export interface EmitEventPayload {
  event_type: string
  payload?: Record<string, unknown>
}

export interface EmitEventResponse {
  matched: number
  fired: number
  failed: number
}

export interface TickStats {
  checked: number
  fired: number
  failed: number
  skipped: number
}

// ─── API 调用层 ────────────────────────────────────────────────────────────
const BASE = '/workflow-timers'

export async function fetchWorkflowTimers(
  workflowId?: string,
): Promise<WorkflowTimer[]> {
  const search = new URLSearchParams()
  if (workflowId) search.set('workflow_id', workflowId)
  const suffix = search.toString() ? `?${search.toString()}` : ''
  const data = await requestJson<{ items: WorkflowTimer[]; count: number }>(`${BASE}${suffix}`)
  return data.items
}

export async function fetchWorkflowTimer(timerId: string): Promise<WorkflowTimer> {
  return requestJson<WorkflowTimer>(`${BASE}/${timerId}`)
}

export async function createWorkflowTimer(
  payload: CreateTimerPayload,
): Promise<WorkflowTimer> {
  return requestJson<WorkflowTimer>(BASE, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateWorkflowTimer(
  timerId: string,
  payload: UpdateTimerPayload,
): Promise<WorkflowTimer> {
  return requestJson<WorkflowTimer>(`${BASE}/${timerId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function deleteWorkflowTimer(timerId: string): Promise<void> {
  await requestJson<void>(`${BASE}/${timerId}`, { method: 'DELETE', allowEmpty: true })
}

export async function runWorkflowTimer(timerId: string): Promise<ManualTriggerResponse> {
  return requestJson<ManualTriggerResponse>(`${BASE}/${timerId}/run`, {
    method: 'POST',
  })
}

export async function emitWorkflowEvent(
  payload: EmitEventPayload,
): Promise<EmitEventResponse> {
  return requestJson<EmitEventResponse>(`${BASE}/events`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function manualTickTimers(): Promise<TickStats> {
  return requestJson<TickStats>(`${BASE}/tick`, { method: 'POST' })
}
