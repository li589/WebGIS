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

export interface CronPreviewResult {
  cron_expr: string
  next_times: string[]
}

/** 支持的动态日期模板（与后端 resolve_date_templates 对齐） */
export const DATE_TEMPLATES: Array<{ key: string; label: string; description: string }> = [
  { key: '{{today}}', label: '今天', description: '当前日期 YYYYMMDD' },
  { key: '{{yesterday}}', label: '昨天', description: '昨日 YYYYMMDD' },
  { key: '{{tomorrow}}', label: '明天', description: '明日 YYYYMMDD' },
  { key: '{{last_7_days_start}}', label: '近7天起', description: '7天前 YYYYMMDD' },
  { key: '{{last_7_days_end}}', label: '近7天止', description: '昨日 YYYYMMDD' },
  { key: '{{last_30_days_start}}', label: '近30天起', description: '30天前 YYYYMMDD' },
  { key: '{{last_30_days_end}}', label: '近30天止', description: '昨日 YYYYMMDD' },
  { key: '{{this_month_start}}', label: '本月起', description: '本月1日 YYYYMMDD' },
  { key: '{{this_month_end}}', label: '本月止', description: '今日 YYYYMMDD' },
  { key: '{{last_month_start}}', label: '上月起', description: '上月1日 YYYYMMDD' },
  { key: '{{last_month_end}}', label: '上月止', description: '上月末 YYYYMMDD' },
  { key: '{{this_year_start}}', label: '本年起', description: '本年1月1日 YYYYMMDD' },
  { key: '{{this_year_end}}', label: '本年止', description: '今日 YYYYMMDD' },
]

// ─── API 调用层 ────────────────────────────────────────────────────────────
const BASE = '/workflow-timers'

export async function fetchWorkflowTimers(workflowId?: string): Promise<WorkflowTimer[]> {
  const search = new URLSearchParams()
  if (workflowId) search.set('workflow_id', workflowId)
  const suffix = search.toString() ? `?${search.toString()}` : ''
  const data = await requestJson<{ items: WorkflowTimer[]; count: number }>(`${BASE}${suffix}`)
  return data.items
}

export async function fetchWorkflowTimer(timerId: string): Promise<WorkflowTimer> {
  return requestJson<WorkflowTimer>(`${BASE}/${timerId}`)
}

export async function createWorkflowTimer(payload: CreateTimerPayload): Promise<WorkflowTimer> {
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

export async function emitWorkflowEvent(payload: EmitEventPayload): Promise<EmitEventResponse> {
  return requestJson<EmitEventResponse>(`${BASE}/events`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function manualTickTimers(): Promise<TickStats> {
  return requestJson<TickStats>(`${BASE}/tick`, { method: 'POST' })
}

export async function previewCron(cronExpr: string, count: number = 5): Promise<CronPreviewResult> {
  return requestJson<CronPreviewResult>(`${BASE}/cron-preview`, {
    method: 'POST',
    body: JSON.stringify({ cron_expr: cronExpr, count }),
  })
}
