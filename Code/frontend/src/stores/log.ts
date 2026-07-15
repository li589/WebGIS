import { ref } from 'vue'
import { defineStore } from 'pinia'

export type LogCategory = 'operation' | 'workflow'

export interface LogEntry {
  id: string
  timestamp: number
  category: LogCategory
  type: string
  message: string
  details?: string
}

const MAX_ENTRIES = 500

export const useLogStore = defineStore('log', () => {
  const entries = ref<LogEntry[]>([])
  let counter = 0

  function _genId(): string {
    counter += 1
    return `log-${Date.now()}-${counter}`
  }

  function addLogEntry(
    category: LogCategory,
    type: string,
    message: string,
    details?: string,
  ) {
    const entry: LogEntry = {
      id: _genId(),
      timestamp: Date.now(),
      category,
      type,
      message,
      details,
    }
    entries.value.push(entry)
    // 超出上限时移除最早的记录
    if (entries.value.length > MAX_ENTRIES) {
      entries.value = entries.value.slice(-MAX_ENTRIES)
    }
  }

  /** 记录操作日志（用户交互行为的快捷方法） */
  function logOperation(type: string, message: string, details?: string) {
    addLogEntry('operation', type, message, details)
  }

  /** 记录工作流日志 */
  function logWorkflow(type: string, message: string, details?: string) {
    addLogEntry('workflow', type, message, details)
  }

  function clearLogs() {
    entries.value = []
  }

  function clearCategory(category: LogCategory) {
    entries.value = entries.value.filter((e) => e.category !== category)
  }

  return {
    entries,
    addLogEntry,
    logOperation,
    logWorkflow,
    clearLogs,
    clearCategory,
  }
})
