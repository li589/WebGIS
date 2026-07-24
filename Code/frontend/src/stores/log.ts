import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export type LogCategory = 'operation' | 'workflow'

export interface LogEntry {
  id: string
  timestamp: number
  category: LogCategory
  type: string
  /** 前端列表主文案（简短） */
  message: string
  /** 展开后可见的技术细节（后台级信息） */
  details?: string
}

const MAX_ENTRIES = 500

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
  'workflow-editor-open': '流配置',
  'workflow-timer-open': '定时器',
  'weather-tile-error': '天气瓦片',
  'settings-open': '设置',
  'mode-switch': '交互模式',
}

function typeLabel(type: string): string {
  return TYPE_LABELS[type] || type.replace(/[-_]/g, ' ')
}

/**
 * 把过长 / 含技术堆栈的文案拆成「简短主文案 + 详情」。
 * 后台（Python logger）仍可详细；前端只默认显示主文案。
 */
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
      // 疑似「失败: Error: ...」类
      if (
        /失败|错误|error|Error|Exception/i.test(head) ||
        /Error|Exception|Traceback|\bat\b/i.test(tail)
      ) {
        parts.unshift(tail)
        display = head
      }
    }
  }

  // 去掉括号内过长技术片段
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

export const useLogStore = defineStore('log', () => {
  const entries = ref<LogEntry[]>([])
  let counter = 0

  function _genId(): string {
    counter += 1
    return `log-${Date.now()}-${counter}`
  }

  function addLogEntry(category: LogCategory, type: string, message: string, details?: string) {
    const split = splitForDisplay(message, details)
    const entry: LogEntry = {
      id: _genId(),
      timestamp: Date.now(),
      category,
      type,
      message: split.message,
      details: split.details,
    }
    entries.value.push(entry)
    if (entries.value.length > MAX_ENTRIES) {
      entries.value = entries.value.slice(-MAX_ENTRIES)
    }
  }

  function logOperation(type: string, message: string, details?: string) {
    addLogEntry('operation', type, message, details)
  }

  function logWorkflow(type: string, message: string, details?: string) {
    addLogEntry('workflow', type, message, details)
  }

  function clearLogs() {
    entries.value = []
  }

  function clearCategory(category: LogCategory) {
    entries.value = entries.value.filter((e) => e.category !== category)
  }

  const labelFor = computed(() => (type: string) => typeLabel(type))

  return {
    entries,
    addLogEntry,
    logOperation,
    logWorkflow,
    clearLogs,
    clearCategory,
    typeLabel,
    labelFor,
  }
})
