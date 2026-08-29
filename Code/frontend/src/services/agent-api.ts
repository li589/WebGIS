import { requestJson } from './_http'

export type AgentProtocol = 'openai' | 'anthropic' | 'demo'
export type AgentScope = 'global' | 'personal'

export interface AgentUiIntent {
  name: string
  args: Record<string, unknown>
}

export interface AgentTokenUsage {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  estimated?: boolean
}

export interface AgentStep {
  type: 'thought' | 'tool' | 'tool_result'
  summary: string
  detail?: string | null
}

export interface AgentConfirmation {
  confirmation_id: string
  action?: string
  expires_at?: string
  summary?: Record<string, unknown>
  message?: string
}

export interface AgentChatClientContext {
  active_catalog_ids?: string[]
  active_layers?: Array<{
    catalog_id: string
    instance_id?: string
    name?: string
  }>
}

export interface AgentChatRequest {
  message: string
  session_id?: string | null
  client_context?: AgentChatClientContext
}

export interface AgentChatResponse {
  session_id: string
  reply: string
  ui_intents: AgentUiIntent[]
  provider?: string
  profile_id?: string | null
  usage?: AgentTokenUsage | null
  steps?: AgentStep[]
  confirmations?: AgentConfirmation[]
}

export interface AgentConfirmRequest {
  confirmation_id: string
  decision: 'approve' | 'reject'
}

export interface AgentConfirmResponse {
  confirmation_id: string
  status: string
  summary?: Record<string, unknown>
  run_id?: string | null
  status_url?: string | null
  message?: string
}

export interface AgentProfile {
  id: string
  name: string
  provider_kind: string
  protocol: AgentProtocol
  base_url: string
  model: string
  context_window_input: number
  context_window_output: number
  preset_id?: string | null
  scope: AgentScope
  enabled: boolean
  has_api_key: boolean
}

export interface AgentPreset {
  id: string
  name: string
  provider_kind: string
  protocol: AgentProtocol
  base_url: string
  model: string
  context_window_input: number
  context_window_output: number
  needs_api_key: boolean
}

export interface AgentConfigBundle {
  active_profile_id: string
  active_scope: AgentScope
  can_manage_global: boolean
  can_manage_personal: boolean
  profiles: AgentProfile[]
  presets: AgentPreset[]
}

export interface AgentProfileUpdate {
  scope?: AgentScope
  name?: string
  protocol?: AgentProtocol
  base_url?: string
  model?: string
  context_window_input?: number
  context_window_output?: number
  api_key?: string | null
  clear_api_key?: boolean
}

export interface AgentModelsRefreshResult {
  profile_id: string
  models: string[]
  manual: boolean
  error?: string | null
}

export function postAgentChat(body: AgentChatRequest): Promise<AgentChatResponse> {
  return requestJson<AgentChatResponse>('/agent/chat', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function confirmAgentAction(body: AgentConfirmRequest): Promise<AgentConfirmResponse> {
  return requestJson<AgentConfirmResponse>('/agent/confirm', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function fetchAgentConfig(): Promise<AgentConfigBundle> {
  const raw = await requestJson<Partial<AgentConfigBundle> & Record<string, unknown>>(
    '/agent/config',
    { sensitiveGet: true },
  )
  // 旧版单配置响应：无 profiles[]
  if (!Array.isArray(raw?.profiles) && (raw?.provider != null || raw?.has_api_key != null)) {
    throw new Error(
      '后端 Agent API 仍为旧版（无多配置档）。请执行 launch.py restart fastapi 后硬刷新页面。',
    )
  }
  const rawProfiles = Array.isArray(raw?.profiles) ? raw.profiles : []
  const profiles: AgentProfile[] = rawProfiles.map((p) => ({
    ...p,
    scope: p.scope === 'personal' ? 'personal' : 'global',
    enabled: Boolean(p.enabled),
    has_api_key: Boolean(p.has_api_key),
    name: String(p.name || p.id || '未命名'),
    id: String(p.id || ''),
    provider_kind: String(p.provider_kind || 'custom'),
    protocol: (p.protocol === 'anthropic' || p.protocol === 'demo' ? p.protocol : 'openai') as AgentProtocol,
    base_url: String(p.base_url || ''),
    model: String(p.model || ''),
    context_window_input: Number(p.context_window_input) || 8192,
    context_window_output: Number(p.context_window_output) || 4096,
  }))
  const presets = Array.isArray(raw?.presets) ? (raw.presets as AgentPreset[]) : []
  return {
    active_profile_id: String(raw?.active_profile_id ?? profiles[0]?.id ?? ''),
    active_scope: raw?.active_scope === 'personal' ? 'personal' : 'global',
    can_manage_global: Boolean(raw?.can_manage_global),
    can_manage_personal: Boolean(raw?.can_manage_personal),
    profiles,
    presets,
  }
}

export function createAgentProfile(body: {
  preset_id: string
  name?: string
  scope?: AgentScope
}): Promise<AgentProfile> {
  return requestJson<AgentProfile>('/agent/config/profiles', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function updateAgentProfile(
  profileId: string,
  body: AgentProfileUpdate,
): Promise<AgentProfile> {
  return requestJson<AgentProfile>(`/agent/config/profiles/${encodeURIComponent(profileId)}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}

export function deleteAgentProfile(
  profileId: string,
  scope: AgentScope = 'personal',
): Promise<AgentConfigBundle> {
  return requestJson<AgentConfigBundle>(
    `/agent/config/profiles/${encodeURIComponent(profileId)}?scope=${encodeURIComponent(scope)}`,
    { method: 'DELETE' },
  )
}

export function setActiveAgentProfile(
  profileId: string,
  scope: AgentScope = 'personal',
): Promise<AgentConfigBundle> {
  return requestJson<AgentConfigBundle>('/agent/config/active', {
    method: 'POST',
    body: JSON.stringify({ profile_id: profileId, scope }),
  })
}

export function useGlobalAgentProfile(): Promise<AgentConfigBundle> {
  return requestJson<AgentConfigBundle>('/agent/config/use-global', {
    method: 'POST',
    body: '{}',
  })
}

export function refreshAgentModels(
  profileId?: string,
  scope?: AgentScope,
): Promise<AgentModelsRefreshResult> {
  return requestJson<AgentModelsRefreshResult>('/agent/models/refresh', {
    method: 'POST',
    body: JSON.stringify({ profile_id: profileId ?? null, scope: scope ?? null }),
  })
}
