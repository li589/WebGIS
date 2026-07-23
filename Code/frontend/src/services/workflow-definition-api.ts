/**
 * 工作流定义 API 服务
 *
 * 提供与后端 /workflow-definitions 端点的交互。
 * 遵循项目原生 fetch + resolveApiUrl 模式（不使用 axios）Sprint 3.6 后由 _http.ts 统一实现。
 */
// Sprint 3.6: requestJson 已抽取到 _http.ts 统一维护
import { requestJson } from './_http'

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
  /** 有 options 时是否允许输入不在列表中的自定义值；默认 true（enum/option 类型默认 false） */
  allow_custom?: boolean
  unit?: string
  min?: number
  max?: number
  step?: number
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
  0: number // link_id
  1: number // from_node_id
  2: number // from_slot
  3: number // to_node_id
  4: number // to_slot
  5: string // type
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
// Sprint 3.6: requestJson 实现已抽取到 _http.ts，此处直接复用
const BASE = '/workflow-definitions'

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
  // DELETE 端点返回 204 No Content；allowEmpty=true 显式声明允许空响应
  await requestJson<void>(`${BASE}/${workflowId}`, { method: 'DELETE', allowEmpty: true })
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

export async function compileWorkflowGraph(payload: {
  workflow_id: string
  name?: string
  description?: string | null
  nodes: unknown[]
  links: unknown[]
}): Promise<{ ok: boolean; workflow_definition: Record<string, unknown> }> {
  return requestJson(`${BASE}/compile`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
