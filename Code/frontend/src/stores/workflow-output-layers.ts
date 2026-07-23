/**
 * 工作流产出图层注册表
 *
 * 管理用户通过工作流编辑器"新建图层"方式创建的产出图层条目。
 * 这些条目在前端本地维护（持久化到 localStorage），后端提交时仍使用
 * 源工作流的 linked_layer_id 解析引擎请求，但前端按用户指定的名称与分组
 * 在图层面板中独立展示。
 *
 * 设计要点：
 *  - 后端 API 不支持动态创建图层目录条目，因此采用前端本地注册表方案
 *  - 每个产出条目记录源工作流 ID 与源 layer_id，便于复用现有提交链路
 *  - 分组（group）由用户自定义，可在新建时指定或创建新分组
 */
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

export interface WorkflowOutputLayerEntry {
  /** 本地唯一 ID，用作 catalogId（前缀 wf-out-） */
  localId: string
  /** 用户指定的显示名称 */
  name: string
  /** 用户指定的分组名称（对应 LayerSidebar 中的子分组） */
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

function loadFromStorage(): WorkflowOutputLayerEntry[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((item): item is WorkflowOutputLayerEntry => {
      return item && typeof item.localId === 'string' && typeof item.sourceLayerId === 'string'
    })
  } catch {
    return []
  }
}

function saveToStorage(entries: WorkflowOutputLayerEntry[]) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries))
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

  /** 所有分组名（去重，按创建顺序） */
  const groups = computed(() => {
    const seen = new Set<string>()
    const result: string[] = []
    for (const entry of entries.value) {
      if (!seen.has(entry.group)) {
        seen.add(entry.group)
        result.push(entry.group)
      }
    }
    return result
  })

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
    const entry: WorkflowOutputLayerEntry = {
      localId: `wf-out-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      name: params.name.trim() || `产出图层 ${new Date().toLocaleString()}`,
      group: params.group.trim() || '默认分组',
      sourceWorkflowId: params.sourceWorkflowId,
      sourceLayerId: params.sourceLayerId,
      engine: params.engine,
      createdAt: new Date().toISOString(),
    }
    entries.value.unshift(entry)
    return entry
  }

  /** 更新最近运行状态 */
  function updateRunStatus(localId: string, runId: string, status: string) {
    const entry = entries.value.find((e) => e.localId === localId)
    if (entry) {
      entry.lastRunId = runId
      entry.lastRunStatus = status
    }
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
    updateRunStatus,
    removeOutputLayer,
  }
})
