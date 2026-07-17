/**
 * 工作流定义 API 服务
 *
 * 提供与后端 /workflow-definitions 端点的交互。
 * 遵循项目原生 fetch + resolveApiUrl 模式（不使用 axios）。
 */
import { resolveApiUrl } from './runtime-api'
import { withWriteAuthHeaders } from './backend-auth'
import { useUiLoadingStore } from '../stores/ui-loading'

// ─── 类型定义 ──────────────────────────────────────────────────────────────
export interface NodePortSpec {
  name: string
  type: string
  required?: boolean
  description?: string
}

export interface NodeParamSpec {
  key: string
  type: string
  default?: unknown
  description?: string
  options?: string[]
}

export interface NodeTemplate {
  type: string
  engine: string
  category: string
  title: string
  description: string
  inputs: NodePortSpec[]
  outputs: NodePortSpec[]
  params: NodeParamSpec[]
  node_class: string
}

export interface WorkflowDefinitionSummary {
  workflow_id: string
  kind: 'system' | 'user'
  engine: string
  name: string
  description: string | null
  readonly: boolean
  linked_layer_id: string | null
  updated_at: string | null
  node_count: number
}

export interface WorkflowDefinitionNode {
  id: number
  type: string
  title: string
  pos: [number, number]
  properties: Record<string, unknown>
  inputs?: NodePortSpec[]
  outputs?: NodePortSpec[]
}

export interface WorkflowDefinitionLink {
  0: number  // link_id
  1: number  // from_node_id
  2: number  // from_slot
  3: number  // to_node_id
  4: number  // to_slot
  5: string  // type
}

export interface WorkflowDefinitionMeta {
  kind: 'system' | 'user'
  engine: string
  name: string
  description: string | null
  created_at: string
  updated_at: string
  author: string
  readonly: boolean
  linked_layer_id: string | null
}

export interface WorkflowDefinition {
  _meta: WorkflowDefinitionMeta
  workflow_id: string
  name: string
  description: string | null
  nodes: WorkflowDefinitionNode[]
  links: WorkflowDefinitionLink[]
  extra?: Record<string, unknown>
}

// ─── API 调用层 ─────────────────────────────────────────────────────────────
// 复用 runtime-api.ts 中 requestJson 的实现模式：fetch + resolveApiUrl + withWriteAuthHeaders
const BASE = '/workflow-definitions'

async function requestJson<T>(path: string, init?: RequestInit & { timeoutMs?: number; silent?: boolean }): Promise<T> {
  const { headers: initHeaders, timeoutMs, silent, ...restInit } = init ?? {}
  const method = (restInit.method ?? 'GET').toString()
  const mergedHeaders = withWriteAuthHeaders(
    {
      'Content-Type': 'application/json',
      ...(initHeaders as Record<string, string> | undefined),
    },
    method,
  )

  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs ?? 30000)

  // 全局 loading 管理：非 silent 请求触发 loading 动效
  const loading = useUiLoadingStore()
  if (!silent) {
    loading.show()
  }

  try {
    const response = await fetch(resolveApiUrl(path), {
      ...restInit,
      headers: mergedHeaders,
      signal: restInit.signal ?? controller.signal,
    })

    if (!response.ok) {
      let errorDetail = ''
      try {
        const errorBody = await response.json()
        errorDetail = errorBody?.detail || errorBody?.error || JSON.stringify(errorBody)
      } catch {
        errorDetail = await response.text().catch(() => '')
      }
      throw new Error(`Request failed: ${response.status} ${path}${errorDetail ? ` - ${errorDetail}` : ''}`)
    }

    // 处理 204 No Content 等无响应体情况
    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  } finally {
    window.clearTimeout(timeoutId)
    if (!silent) {
      loading.hide()
    }
  }
}

// ─── 公开 API 函数 ──────────────────────────────────────────────────────────

export async function fetchNodeTemplates(): Promise<NodeTemplate[]> {
  const data = await requestJson<{ templates: NodeTemplate[] }>(`${BASE}/node-templates`)
  return data.templates
}

export async function fetchWorkflowDefinitions(): Promise<WorkflowDefinitionSummary[]> {
  const data = await requestJson<{ items: WorkflowDefinitionSummary[] }>(BASE)
  return data.items
}

export async function fetchWorkflowDefinition(workflowId: string): Promise<WorkflowDefinition> {
  return requestJson<WorkflowDefinition>(`${BASE}/${workflowId}`)
}

export async function createWorkflowDefinition(payload: {
  workflow_id: string
  name: string
  description?: string
  engine?: string
  linked_layer_id?: string
  nodes?: unknown[]
  links?: unknown[]
}): Promise<WorkflowDefinition> {
  return requestJson<WorkflowDefinition>(BASE, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateWorkflowDefinition(
  workflowId: string,
  payload: Partial<{
    name: string
    description: string
    engine: string
    linked_layer_id: string
    nodes: unknown[]
    links: unknown[]
  }>,
): Promise<WorkflowDefinition> {
  return requestJson<WorkflowDefinition>(`${BASE}/${workflowId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function deleteWorkflowDefinition(workflowId: string): Promise<void> {
  await requestJson<void>(`${BASE}/${workflowId}`, { method: 'DELETE' })
}

export async function duplicateWorkflowDefinition(
  workflowId: string,
  newId: string,
  newName?: string,
): Promise<WorkflowDefinition> {
  return requestJson<WorkflowDefinition>(`${BASE}/${workflowId}/duplicate`, {
    method: 'POST',
    body: JSON.stringify({ new_id: newId, new_name: newName }),
  })
}
