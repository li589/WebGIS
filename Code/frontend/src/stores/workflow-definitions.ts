/**
 * 工作流定义 Pinia Store
 *
 * 管理工作流定义的列表、当前编辑项、节点模板，以及与后端的同步。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  fetchNodeTemplates,
  fetchWorkflowDefinitions,
  fetchWorkflowDefinition,
  createWorkflowDefinition,
  updateWorkflowDefinition,
  deleteWorkflowDefinition,
  duplicateWorkflowDefinition,
  type NodeTemplate,
  type WorkflowDefinitionSummary,
  type WorkflowDefinition,
  type WorkflowDefinitionNode,
  type WorkflowDefinitionLink,
} from '../services/workflow-definition-api'

export const useWorkflowDefinitionsStore = defineStore('workflow-definitions', () => {
  // ─── 状态 ────────────────────────────────────────────────────────────────
  const nodeTemplates = ref<NodeTemplate[]>([])
  const summaries = ref<WorkflowDefinitionSummary[]>([])
  const currentDefinition = ref<WorkflowDefinition | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  // ─── 计算属性 ─────────────────────────────────────────────────────────────
  const systemWorkflows = computed(() => summaries.value.filter((s) => s.kind === 'system'))
  const userWorkflows = computed(() => summaries.value.filter((s) => s.kind === 'user'))
  const isReadonly = computed(() => currentDefinition.value?._meta?.readonly ?? false)

  // 按引擎和类别分组的节点模板
  const templatesByCategory = computed(() => {
    const groups: Record<string, NodeTemplate[]> = {}
    for (const tpl of nodeTemplates.value) {
      const key = tpl.category || tpl.engine || 'other'
      if (!groups[key]) groups[key] = []
      groups[key].push(tpl)
    }
    return groups
  })

  // ─── 动作 ────────────────────────────────────────────────────────────────

  async function loadNodeTemplates() {
    try {
      nodeTemplates.value = await fetchNodeTemplates()
    } catch (err) {
      console.error('[workflow-definitions] Failed to load node templates:', err)
      error.value = err instanceof Error ? err.message : String(err)
    }
  }

  async function loadSummaries() {
    loading.value = true
    error.value = null
    try {
      summaries.value = await fetchWorkflowDefinitions()
    } catch (err) {
      console.error('[workflow-definitions] Failed to load summaries:', err)
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      loading.value = false
    }
  }

  async function loadDefinition(workflowId: string) {
    loading.value = true
    error.value = null
    try {
      currentDefinition.value = await fetchWorkflowDefinition(workflowId)
      return currentDefinition.value
    } catch (err) {
      console.error('[workflow-definitions] Failed to load definition:', err)
      error.value = err instanceof Error ? err.message : String(err)
      return null
    } finally {
      loading.value = false
    }
  }

  async function createNew(payload: {
    workflow_id: string
    name: string
    description?: string
    engine?: string
    linked_layer_id?: string
    nodes?: WorkflowDefinitionNode[]
    links?: WorkflowDefinitionLink[]
  }) {
    const created = await createWorkflowDefinition(payload)
    // 刷新列表
    await loadSummaries()
    return created
  }

  async function updateCurrent(payload: {
    name?: string
    description?: string
    nodes?: WorkflowDefinitionNode[]
    links?: WorkflowDefinitionLink[]
  }) {
    if (!currentDefinition.value) return null
    const id = currentDefinition.value.workflow_id
    const updated = await updateWorkflowDefinition(id, payload)
    currentDefinition.value = updated
    // 更新列表中的摘要
    const idx = summaries.value.findIndex((s) => s.workflow_id === id)
    if (idx >= 0) {
      summaries.value[idx] = {
        ...summaries.value[idx],
        name: updated.name,
        description: updated.description,
        updated_at: updated._meta.updated_at,
        node_count: updated.nodes.length,
      }
    }
    return updated
  }

  async function remove(workflowId: string) {
    await deleteWorkflowDefinition(workflowId)
    if (currentDefinition.value?.workflow_id === workflowId) {
      currentDefinition.value = null
    }
    await loadSummaries()
  }

  async function duplicate(workflowId: string, newId: string, newName?: string) {
    const created = await duplicateWorkflowDefinition(workflowId, newId, newName)
    await loadSummaries()
    return created
  }

  function clearCurrent() {
    currentDefinition.value = null
  }

  return {
    // 状态
    nodeTemplates,
    summaries,
    currentDefinition,
    loading,
    error,
    // 计算
    systemWorkflows,
    userWorkflows,
    isReadonly,
    templatesByCategory,
    // 动作
    loadNodeTemplates,
    loadSummaries,
    loadDefinition,
    createNew,
    updateCurrent,
    remove,
    duplicate,
    clearCurrent,
  }
})
