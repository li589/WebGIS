/**
 * GET|PUT /config/data-input-policies — 时间窗对齐 / 本地优先源路由策略。
 * PUT 写入 runtime 覆盖，mtime 热载，无需重启后端。
 */
import { resolveApiUrl } from './_http'
import { withWriteAuthHeaders } from './backend-auth'
import { applyApiFetchDefaults } from './http-credentials'

export type DataInputPolicyMode = 'deny' | 'allow_with_confirm' | 'allow_silent'

export interface DataInputPolicyItem {
  id: string
  scope: string
  scope_id?: string | null
  input_key: string
  mode: DataInputPolicyMode | string
  notes?: string | null
}

export interface DataInputPoliciesResponse {
  version: number
  policies: DataInputPolicyItem[]
  seed_path?: string
  runtime_path?: string
  runtime_override_present?: boolean
  /** 仅种子条目（只读参考） */
  seed_policies?: DataInputPolicyItem[]
  /** 仅 runtime 覆盖 */
  runtime_policies?: DataInputPolicyItem[]
}

export const INPUT_KEY_TIME_WINDOW_ALIGN = 'time_window_align_on_zero_intersection'
/** 本地有数走本地、否则走在线（需 descriptor.workflow_variants） */
export const INPUT_KEY_SOURCE_ROUTE_LOCAL_FIRST = 'source_route_local_first'

export async function fetchDataInputPolicies(): Promise<DataInputPoliciesResponse> {
  const url = resolveApiUrl('/config/data-input-policies')
  const headers = withWriteAuthHeaders({}, 'GET', true)
  const response = await fetch(
    url,
    applyApiFetchDefaults({
      method: 'GET',
      headers,
      credentials: 'include',
    }),
  )
  if (!response.ok) {
    throw new Error(`data-input-policies HTTP ${response.status}`)
  }
  return (await response.json()) as DataInputPoliciesResponse
}

/** admin：整表写入 runtime 覆盖（同 id 覆盖 seed）。 */
export async function putDataInputPolicies(body: {
  version: number
  policies: DataInputPolicyItem[]
}): Promise<DataInputPoliciesResponse> {
  const url = resolveApiUrl('/config/data-input-policies')
  const headers = {
    ...withWriteAuthHeaders({}, 'PUT', true),
    'Content-Type': 'application/json',
  }
  const response = await fetch(
    url,
    applyApiFetchDefaults({
      method: 'PUT',
      headers,
      credentials: 'include',
      body: JSON.stringify(body),
    }),
  )
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(
      `data-input-policies PUT HTTP ${response.status}${detail ? `: ${detail.slice(0, 200)}` : ''}`,
    )
  }
  return (await response.json()) as DataInputPoliciesResponse
}

/** 解析任意 input_key 模式：layer_id > workflow_id > module > *；未命中 → deny */
export function resolvePolicyMode(
  policies: DataInputPolicyItem[],
  inputKey: string,
  opts: { layerId?: string | null; workflowId?: string | null; module?: string | null },
): DataInputPolicyMode {
  const rank: Record<string, number> = { layer_id: 3, workflow_id: 2, module: 1, '*': 0 }
  let best: { r: number; mode: DataInputPolicyMode } | null = null
  for (const p of policies) {
    if (p.input_key !== inputKey) continue
    const scope = p.scope || '*'
    if (scope === 'layer_id') {
      if (!opts.layerId || p.scope_id !== opts.layerId) continue
    } else if (scope === 'workflow_id') {
      if (!opts.workflowId || p.scope_id !== opts.workflowId) continue
    } else if (scope === 'module') {
      if (!opts.module || p.scope_id !== opts.module) continue
    } else if (scope !== '*') {
      continue
    }
    const mode = (
      ['deny', 'allow_with_confirm', 'allow_silent'].includes(String(p.mode)) ? p.mode : 'deny'
    ) as DataInputPolicyMode
    const r = rank[scope] ?? -1
    if (!best || r > best.r) best = { r, mode }
  }
  return best?.mode ?? 'deny'
}

/** @deprecated 使用 resolvePolicyMode(..., INPUT_KEY_TIME_WINDOW_ALIGN, ...) */
export function resolveAlignPolicyMode(
  policies: DataInputPolicyItem[],
  opts: { layerId?: string | null; workflowId?: string | null; module?: string | null },
): DataInputPolicyMode {
  return resolvePolicyMode(policies, INPUT_KEY_TIME_WINDOW_ALIGN, opts)
}
