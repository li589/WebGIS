import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export type LogCategory = 'operation' | 'workflow'
export type LogSeverity = 'info' | 'warn' | 'error'

export interface LogEntry {
  id: string
  timestamp: number
  category: LogCategory
  type: string
  severity: LogSeverity
  /** 前端列表主文案（简短） */
  message: string
  /** 展开后可见的技术细节（后台级信息） */
  details?: string
}

const MAX_ENTRIES = 500
const ERROR_BUFFER_KEY = 'cgda_log_errors'
const ERROR_BUFFER_MAX = 100

const ERROR_TYPES = new Set([
  'api-error',
  'client-error',
  'client-render-error',
  'workflow-error',
  'weather-tile-error',
  'route-not-found',
])

/** 类型 → 简短中文标签（列表左侧辅助） */
const TYPE_LABELS: Record<string, string> = {
  'timeline-step': '时间轴',
  'timeline-change': '时间轴',
  'timeline-date-change': '日期',
  'timeline-play': '播放',
  'timeline-unified': '时间模式',
  'timeline-restore-layer': '图层时刻',
  'timeline-snap-latest': '对齐时次',
  'layer-select': '选中图层',
  'layer-add': '添加图层',
  'layer-remove': '移除图层',
  'layer-visibility': '图层显隐',
  'map-point': '地图选点',
  'map-point-select': '地图选点',
  'map-point-clear': '清除选点',
  'workflow-submit': '提交工作流',
  'workflow-error': '工作流失败',
  'workflow-editor-open': '工作流',
  'workflow-timer-open': '定时器',
  'weather-tile-error': '天气瓦片',
  'settings-open': '设置',
  'mode-switch': '交互模式',
  'api-error': 'API 错误',
  'client-error': '客户端错误',
  'client-render-error': '渲染错误',
  'route-not-found': '404',
}

function typeLabel(type: string): string {
  return TYPE_LABELS[type] || type.replace(/[-_]/g, ' ')
}

function inferSeverity(type: string, explicit?: LogSeverity): LogSeverity {
  if (explicit) return explicit
  if (ERROR_TYPES.has(type)) return 'error'
  if (type.includes('warn')) return 'warn'
  return 'info'
}

function splitForDisplay(message: string, details?: string): { message: string; details?: string } {
  const parts: string[] = []
  if (details?.trim()) parts.push(details.trim())

  let display = (message || '').trim()
  const dash = display.indexOf(' — ')
  if (dash > 0) {
    parts.unshift(display.slice(dash + 3).trim())
    display = display.slice(0, dash).trim()
  } else {
    const colon = display.search(/:\s+/)
    if (colon > 0 && display.length - colon > 40) {
      const head = display.slice(0, colon).trim()
      const tail = display.slice(colon + 1).trim()
      if (
        /失败|错误|error|Error|Exception/i.test(head) ||
        /Error|Exception|Traceback|\bat\b/i.test(tail)
      ) {
        parts.unshift(tail)
        display = head
      }
    }
  }

  display = display.replace(/\s*\([^)]{40,}\)\s*$/, '').trim() || display

  if (display.length > 42) {
    parts.unshift(display)
    display = `${display.slice(0, 40)}…`
  }

  const merged = parts.filter(Boolean).join('\n')
  return {
    message: display || '操作记录',
    details: merged || undefined,
  }
}

function persistErrorBuffer(entry: LogEntry): void {
  if (entry.severity !== 'error' || typeof sessionStorage === 'undefined') return
  try {
    const raw = sessionStorage.getItem(ERROR_BUFFER_KEY)
    const list: LogEntry[] = raw ? (JSON.parse(raw) as LogEntry[]) : []
    list.push(entry)
    sessionStorage.setItem(ERROR_BUFFER_KEY, JSON.stringify(list.slice(-ERROR_BUFFER_MAX)))
  } catch {
    /* ignore quota / private mode */
  }
}

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
    severity?: LogSeverity,
  ) {
    const split = splitForDisplay(message, details)
    const entry: LogEntry = {
      id: _genId(),
      timestamp: Date.now(),
      category,
      type,
      severity: inferSeverity(type, severity),
      message: split.message,
      details: split.details,
    }
    entries.value.push(entry)
    if (entries.value.length > MAX_ENTRIES) {
      entries.value = entries.value.slice(-MAX_ENTRIES)
    }
    if (entry.severity === 'error') {
      persistErrorBuffer(entry)
    }
  }

  function logOperation(type: string, message: string, details?: string, severity?: LogSeverity) {
    addLogEntry('operation', type, message, details, severity)
  }

  function logWorkflow(type: string, message: string, details?: string, severity?: LogSeverity) {
    addLogEntry('workflow', type, message, details, severity)
  }

  function logApiError(message: string, details?: string) {
    logOperation('api-error', message, details, 'error')
  }

  function logClientError(message: string, details?: string) {
    logOperation('client-error', message, details, 'error')
  }

  function exportEntries(): string {
    return JSON.stringify(entries.value, null, 2)
  }

  function downloadExport(): void {
    const blob = new Blob([exportEntries()], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `cgda-logs-${new Date().toISOString().replace(/[:.]/g, '-')}.json`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  function clearLogs() {
    entries.value = []
  }

  function clearCategory(category: LogCategory) {
    entries.value = entries.value.filter((e) => e.category !== category)
  }

  const errorCount = computed(() => entries.value.filter((e) => e.severity === 'error').length)

  const labelFor = computed(() => (type: string) => typeLabel(type))

  return {
    entries,
    errorCount,
    addLogEntry,
    logOperation,
    logWorkflow,
    logApiError,
    logClientError,
    exportEntries,
    downloadExport,
    clearLogs,
    clearCategory,
    typeLabel,
    labelFor,
  }
})
