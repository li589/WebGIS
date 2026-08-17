/**
 * W3.4e：log store 测试（node 环境 + stubGlobal）。
 *
 * 覆盖 addLogEntry 分流（logOperation/logWorkflow/logApiError/logClientError）、
 * inferSeverity 规则、splitForDisplay（破折号/冒号拆分/超长截断/括号收尾）、
 * MAX_ENTRIES 截断、错误缓冲持久化（sessionStorage 上限 100）、
 * clearLogs/clearCategory、exportEntries/downloadExport、errorCount、
 * typeLabel 映射与 safeLog 兜底。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { safeLog, useLogStore, type LogEntry } from '@/stores/log'

function stubSession() {
  const store = new Map<string, string>()
  vi.stubGlobal('sessionStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => store.set(k, v),
  })
  return store
}

beforeEach(() => {
  vi.clearAllMocks()
  setActivePinia(createPinia())
  stubSession()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('severity 推断与分流', () => {
  it('显式 severity 优先；ERROR_TYPES 自动 error；含 warn 字样推断 warn；其余 info', () => {
    const store = useLogStore()
    store.logOperation('layer-add', '添加图层')
    store.logOperation('mode-switch', '切换模式', undefined, 'warn')
    store.logWorkflow('api-error', '请求失败')
    store.logOperation('weather-tile-warn-thing', '注意')
    const severities = store.entries.map((e) => e.severity)
    expect(severities).toEqual(['info', 'warn', 'error', 'warn'])
  })

  it('logApiError / logClientError 固定 operation + error', () => {
    const store = useLogStore()
    store.logApiError('请求 /layers 失败', '404')
    store.logClientError('渲染失败', 'TypeError: x')
    expect(store.errorCount).toBe(2)
    expect(store.entries.every((e) => e.category === 'operation')).toBe(true)
    expect(store.entries[1].message).toBe('渲染失败')
  })

  it('logWorkflow 归入 workflow 分类', () => {
    const store = useLogStore()
    store.logWorkflow('workflow-submit', '提交 run-1')
    expect(store.entries[0].category).toBe('workflow')
  })
})

describe('splitForDisplay 文案拆分', () => {
  it('破折号分隔时主文案为前半，后半进 details', () => {
    const store = useLogStore()
    store.logOperation('layer-add', '添加图层 — soil-moisture@2024-05-01')
    const entry = store.entries[0]
    expect(entry.message).toBe('添加图层')
    expect(entry.details).toBe('soil-moisture@2024-05-01')
  })

  it('冒号拆分仅对失败/错误类长文案生效', () => {
    const store = useLogStore()
    const longTail = `共 ${'x'.repeat(60)} 项`
    store.logOperation('api-error', `加载图层失败: ${longTail}`)
    const entry = store.entries[0]
    expect(entry.message).toBe('加载图层失败')
    expect(entry.details).toContain('xxx')
  })

  it('超长主文案截断为 40 字符加省略号，原文进 details', () => {
    const store = useLogStore()
    const long = 'a'.repeat(80)
    store.logOperation('layer-add', long)
    const entry = store.entries[0]
    expect(entry.message).toBe(`${'a'.repeat(40)}…`)
    expect(entry.details).toBe(long)
  })

  it('尾部超长括号从主文案剥离（不产生 details）', () => {
    const store = useLogStore()
    store.logOperation('layer-add', `更新图层(${'detail'.repeat(20)})`)
    const entry = store.entries[0]
    expect(entry.message).toBe('更新图层')
    expect(entry.details).toBeUndefined()
  })

  it('显式 details 与拆分内容合并显示', () => {
    const store = useLogStore()
    store.logOperation('workflow-error', '任务失败 — 节点A', 'traceback: boom')
    const entry = store.entries[0]
    expect(entry.message).toBe('任务失败')
    expect(entry.details).toBe('节点A\ntraceback: boom')
  })
})

describe('容量与错误缓冲', () => {
  it('超过 500 条截断保留最新', () => {
    const store = useLogStore()
    for (let i = 0; i < 505; i++) store.logOperation('layer-add', `第${i}条`)
    expect(store.entries).toHaveLength(500)
    expect(store.entries.at(-1)!.message).toBe('第504条')
  })

  it('error 条目写入 sessionStorage 缓冲并封顶 100', () => {
    const store = useLogStore()
    for (let i = 0; i < 105; i++) store.logApiError(`错误${i}`)
    const raw = (globalThis as { sessionStorage: Storage }).sessionStorage.getItem('cgda_log_errors')
    const list = JSON.parse(raw!) as LogEntry[]
    expect(list).toHaveLength(100)
    expect(list[0].message).toBe('错误5')
  })

  it('非 error 条目不写缓冲', () => {
    const store = useLogStore()
    store.logOperation('layer-add', '普通')
    const raw = (globalThis as { sessionStorage: Storage }).sessionStorage.getItem('cgda_log_errors')
    expect(raw).toBeNull()
  })

  it('sessionStorage 抛异常时静默忽略', () => {
    vi.stubGlobal('sessionStorage', {
      getItem: () => {
        throw new Error('quota')
      },
      setItem: () => {
        throw new Error('quota')
      },
    })
    const store = useLogStore()
    expect(() => store.logApiError('错误')).not.toThrow()
    expect(store.errorCount).toBe(1)
  })
})

describe('清理与导出', () => {
  it('clearLogs 清空；clearCategory 按分类清理', () => {
    const store = useLogStore()
    store.logOperation('layer-add', 'A')
    store.logWorkflow('workflow-submit', 'B')
    store.clearCategory('workflow')
    expect(store.entries).toHaveLength(1)
    expect(store.entries[0].category).toBe('operation')
    store.clearLogs()
    expect(store.entries).toHaveLength(0)
  })

  it('exportEntries 输出 JSON 数组', () => {
    const store = useLogStore()
    store.logOperation('layer-add', 'A')
    const parsed = JSON.parse(store.exportEntries()) as LogEntry[]
    expect(parsed).toHaveLength(1)
    expect(parsed[0].message).toBe('A')
  })

  it('downloadExport 创建 Blob 下载链接并回收', () => {
    const clicks: unknown[] = []
    const revoked: string[] = []
    const objectUrl = 'blob:mock-url'
    vi.stubGlobal('URL', {
      createObjectURL: () => objectUrl,
      revokeObjectURL: (u: string) => revoked.push(u),
    })
    vi.stubGlobal('document', {
      createElement: () => ({ click: () => clicks.push(1) }),
    })
    const store = useLogStore()
    store.logOperation('layer-add', 'A')
    store.downloadExport()
    expect(clicks).toHaveLength(1)
    expect(revoked).toEqual([objectUrl])
  })
})

describe('typeLabel 映射', () => {
  it('已知类型返回中文标签，未知类型替换分隔符', () => {
    const store = useLogStore()
    expect(store.typeLabel('layer-add')).toBe('添加图层')
    expect(store.typeLabel('timeline-play')).toBe('播放')
    expect(store.typeLabel('custom_event_type')).toBe('custom event type')
    expect(store.labelFor('route-not-found')).toBe('404')
  })
})

describe('safeLog', () => {
  it('pinia 激活时写入日志', () => {
    safeLog('layer-add', 'safeLog 写入')
    expect(useLogStore().entries).toHaveLength(1)
  })

  it('pinia 未激活时静默不抛错', () => {
    setActivePinia(null as never)
    expect(() => safeLog('layer-add', 'no pinia')).not.toThrow()
  })
})
