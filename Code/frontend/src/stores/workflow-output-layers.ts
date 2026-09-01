/**
 * 工作流产出图层注册表
 *
 * 管理用户通过工作流编辑器「新建图层」方式创建的产出图层条目。
 * 这些条目在前端本地维护（持久化到 localStorage），后端提交时仍使用
 * 源工作流的 linked_layer_id 解析引擎请求，在图层面板中归入
 * 「核心资产 → 模型输出」展示。
 */
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

import { readScopedItem, writeScopedItem } from '../services/user-local-isolation'
import { isEnglishInversionCatalogId } from './layers/inversion-catalog'

/** 工作流产出图层在图层面板中的二级分类（research-group 子类） */
export const WORKFLOW_OUTPUT_SUBCATEGORY = '模型输出' as const

export interface WorkflowOutputLayerEntry {
  /** 本地唯一 ID，用作 catalogId（前缀 wf-out-） */
  localId: string
  /** 用户指定的显示名称 */
  name: string
  /** @deprecated 历史字段；现统一归入 WORKFLOW_OUTPUT_SUBCATEGORY */
  group: string
  /** 源工作流定义 ID */
  sourceWorkflowId: string
  /** 源工作流关联的 layer_id（用于后端提交时解析引擎请求） */
  sourceLayerId: string
  /** 引擎类型（weather / python_provider / gee / general） */
  engine: string
  /** 创建时间 ISO */
  createdAt: string
  /** 最近一次运行 ID（可选，用于状态关联） */
  lastRunId?: string
  /** 最近一次运行状态 */
  lastRunStatus?: string
}

const STORAGE_KEY = 'geo:workflow-output-layers:v1'

function isPollutingOutputEntry(item: { name?: string; localId?: string }): boolean {
  // 仅拦「显示名 / localId」泄漏英文技术 id。
  // sourceWorkflowId / sourceLayerId 本就是机器路由键（omega_sf_fenkuai_*），
  // 必须允许保留——否则编辑器无法为反演工作流登记产出卡，且会把合法中文名条目滤掉。
  return isEnglishInversionCatalogId(item.name) || isEnglishInversionCatalogId(item.localId)
}

function loadFromStorage(): WorkflowOutputLayerEntry[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = readScopedItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((item): item is WorkflowOutputLayerEntry => {
        return item && typeof item.localId === 'string' && typeof item.sourceLayerId === 'string'
      })
      .filter((item) => !isPollutingOutputEntry(item))
      .map((item) => ({
        ...item,
        group: WORKFLOW_OUTPUT_SUBCATEGORY,
      }))
  } catch {
    return []
  }
}

function saveToStorage(entries: WorkflowOutputLayerEntry[]) {
  if (typeof window === 'undefined') return
  try {
    writeScopedItem(STORAGE_KEY, JSON.stringify(entries))
  } catch {
    // localStorage 满或不可用时静默降级
  }
}

export const useWorkflowOutputLayersStore = defineStore('workflow-output-layers', () => {
  const entries = ref<WorkflowOutputLayerEntry[]>(loadFromStorage())

  // 防抖持久化：deep watch 会在任何嵌套属性变化时触发，
  // 频繁调用 saveToStorage 会同步阻塞主线程（localStorage.setItem 是同步操作）。
  // 300ms 防抖确保连续修改只保存一次。
  let _saveTimer: ReturnType<typeof setTimeout> | null = null
  watch(
    entries,
    (value) => {
      if (_saveTimer !== null) clearTimeout(_saveTimer)
      _saveTimer = setTimeout(() => {
        _saveTimer = null
        saveToStorage(value)
      }, 300)
    },
    { deep: true },
  )

  /** 所有已注册的产出图层条目 */
  const allEntries = computed(() => entries.value)

  /** 所有分组名（去重，按创建顺序）；现固定为模型输出 */
  const groups = computed(() => [WORKFLOW_OUTPUT_SUBCATEGORY])

  /** 按 sourceLayerId 查找产出图层（用于"默认图层"下拉选择） */
  function getBySourceLayerId(sourceLayerId: string): WorkflowOutputLayerEntry[] {
    return entries.value.filter((e) => e.sourceLayerId === sourceLayerId)
  }

  function getByLocalId(localId: string): WorkflowOutputLayerEntry | undefined {
    return entries.value.find((e) => e.localId === localId)
  }

  /** 创建新的产出图层条目 */
  function createOutputLayer(params: {
    name: string
    group: string
    sourceWorkflowId: string
    sourceLayerId: string
    engine: string
  }): WorkflowOutputLayerEntry {
    const safeName = params.name.trim() || `产出图层 ${new Date().toLocaleString()}`
    // 显示名若落成英文技术 id，就地改写；不因 sourceWorkflowId 为机器键而拒绝创建
    const displayName = isEnglishInversionCatalogId(safeName)
      ? `产出图层 ${new Date().toLocaleString()}`
      : safeName
    const entry: WorkflowOutputLayerEntry = {
      localId: `wf-out-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      name: displayName,
      group: WORKFLOW_OUTPUT_SUBCATEGORY,
      sourceWorkflowId: params.sourceWorkflowId,
      sourceLayerId: params.sourceLayerId,
      engine: params.engine,
      createdAt: new Date().toISOString(),
    }
    entries.value.unshift(entry)
    return entry
  }

  /** 批量创建产出图层条目（multi 模式） */
  function createOutputLayers(
    targets: Array<{ name: string; group: string }>,
    sourceWorkflowId: string,
    sourceLayerId: string,
    engine: string,
  ): WorkflowOutputLayerEntry[] {
    return targets.map((t) =>
      createOutputLayer({
        name: t.name,
        group: t.group,
        sourceWorkflowId,
        sourceLayerId,
        engine,
      }),
    )
  }

  /** 更新最近运行状态 */
  function updateRunStatus(localId: string, runId: string, status: string) {
    const entry = entries.value.find((e) => e.localId === localId)
    if (entry) {
      entry.lastRunId = runId
      entry.lastRunStatus = status
    }
  }

  /** 更新产出图层显示名 */
  function renameOutputLayer(localId: string, name: string) {
    const entry = entries.value.find((e) => e.localId === localId)
    if (!entry) return
    const trimmed = name.trim()
    if (!trimmed) return
    entry.name = trimmed
  }

  /** 删除产出图层条目 */
  function removeOutputLayer(localId: string) {
    const index = entries.value.findIndex((e) => e.localId === localId)
    if (index >= 0) {
      entries.value.splice(index, 1)
    }
  }

  return {
    entries,
    allEntries,
    groups,
    getBySourceLayerId,
    getByLocalId,
    createOutputLayer,
    createOutputLayers,
    updateRunStatus,
    renameOutputLayer,
    removeOutputLayer,
  }
})
