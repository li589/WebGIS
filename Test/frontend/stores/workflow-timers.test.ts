/**
 * W3.4e：workflow-timers store 测试。
 *
 * 覆盖 loadTimers（含 silent）/loadTimer（替换或追加）/createTimer/updateTimer/
 * removeTimer/toggleEnabled（lastActionTimerId 生命周期）/runTimer（run 注册与
 * 注册失败降级）/emitEvent/tick，以及 enabledCount 与按触发类型分组的 computed。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import {
  fetchWorkflowTimers,
  fetchWorkflowTimer,
  createWorkflowTimer,
  updateWorkflowTimer,
  deleteWorkflowTimer,
  runWorkflowTimer,
  emitWorkflowEvent,
  manualTickTimers,
} from '@/services/workflow-timer-api'
import { useWorkflowTimersStore } from '@/stores/workflow-timers'

vi.mock('@/services/workflow-timer-api', () => ({
  fetchWorkflowTimers: vi.fn(),
  fetchWorkflowTimer: vi.fn(),
  createWorkflowTimer: vi.fn(),
  updateWorkflowTimer: vi.fn(),
  deleteWorkflowTimer: vi.fn(),
  runWorkflowTimer: vi.fn(),
  emitWorkflowEvent: vi.fn(),
  manualTickTimers: vi.fn(),
}))

vi.mock('@/stores/log', () => ({
  useLogStore: () => ({ logOperation: vi.fn() }),
}))

const registerExternalWorkflowRun = vi.fn()

vi.mock('@/stores/layers', () => ({
  useLayersStore: () => ({ registerExternalWorkflowRun }),
}))

const api = {
  fetchWorkflowTimers,
  fetchWorkflowTimer,
  createWorkflowTimer,
  updateWorkflowTimer,
  deleteWorkflowTimer,
  runWorkflowTimer,
  emitWorkflowEvent,
  manualTickTimers,
}

function makeTimer(overrides: Record<string, unknown> = {}) {
  return {
    timer_id: 't-1',
    workflow_id: 'w-1',
    enabled: true,
    trigger_type: 'cron',
    payload_overrides: { layer_id: 'ndvi' },
    ...overrides,
  }
}

const timers = [makeTimer(), makeTimer({ timer_id: 't-2', enabled: false, trigger_type: 'interval' })]

beforeEach(() => {
  vi.clearAllMocks()
  setActivePinia(createPinia())
  // 每次返回浅拷贝，避免 store 的 splice/push 反向污染共享 fixture
  api.fetchWorkflowTimers.mockResolvedValue([...timers] as never)
  api.fetchWorkflowTimer.mockImplementation(async (id: string) => makeTimer({ timer_id: id }) as never)
  api.createWorkflowTimer.mockResolvedValue(makeTimer({ timer_id: 't-new' }) as never)
  api.updateWorkflowTimer.mockImplementation(
    async (id: string, patch: Record<string, unknown>) => makeTimer({ timer_id: id, ...patch }) as never,
  )
  api.deleteWorkflowTimer.mockResolvedValue(undefined as never)
  api.runWorkflowTimer.mockResolvedValue({ triggered: 1, run_id: 'run-9' } as never)
  api.emitWorkflowEvent.mockResolvedValue({ emitted: 1 } as never)
  api.manualTickTimers.mockResolvedValue({ fired: 2 } as never)
  registerExternalWorkflowRun.mockResolvedValue(undefined)
})

describe('加载', () => {
  it('loadTimers 成功填充列表', async () => {
    const store = useWorkflowTimersStore()
    await store.loadTimers()
    expect(store.timers).toHaveLength(2)
    expect(store.loading).toBe(false)
    expect(store.error).toBeNull()
  })

  it('loadTimers 失败记录 error 且复位 loading', async () => {
    api.fetchWorkflowTimers.mockRejectedValueOnce(new Error('超时'))
    const store = useWorkflowTimersStore()
    await store.loadTimers()
    expect(store.error).toBe('超时')
    expect(store.loading).toBe(false)
  })

  it('loadTimers silent 模式不置 loading', async () => {
    const store = useWorkflowTimersStore()
    const done = store.loadTimers(undefined, { silent: true })
    expect(store.loading).toBe(false)
    await done
    expect(store.error).toBeNull()
  })

  it('loadTimers silent 失败仍写 error；成功时清 error', async () => {
    const store = useWorkflowTimersStore()
    await store.loadTimers(undefined, { silent: true }).catch(() => undefined)
    api.fetchWorkflowTimers.mockRejectedValueOnce(new Error('静默失败'))
    await store.loadTimers(undefined, { silent: true })
    expect(store.error).toBe('静默失败')
    await store.loadTimers(undefined, { silent: true })
    expect(store.error).toBeNull()
  })

  it('loadTimer 列表中已存在则替换，不存在则追加', async () => {
    const store = useWorkflowTimersStore()
    await store.loadTimers()
    await store.loadTimer('t-1')
    expect(store.timers).toHaveLength(2)
    await store.loadTimer('t-3')
    expect(store.timers).toHaveLength(3)
  })

  it('loadTimer 失败返回 null 并记录 error', async () => {
    api.fetchWorkflowTimer.mockRejectedValueOnce(new Error('404'))
    const store = useWorkflowTimersStore()
    expect(await store.loadTimer('missing')).toBeNull()
    expect(store.error).toBe('404')
  })
})

describe('CRUD 与开关', () => {
  it('createTimer 追加新项', async () => {
    const store = useWorkflowTimersStore()
    await store.createTimer({ workflow_id: 'w-1', name: 'x' } as never)
    expect(store.timers.map((t) => t.timer_id)).toContain('t-new')
  })

  it('updateTimer 列表内替换；列表外不影响', async () => {
    const store = useWorkflowTimersStore()
    await store.loadTimers()
    await store.updateTimer('t-1', { enabled: false })
    expect(store.timers.find((t) => t.timer_id === 't-1')!.enabled).toBe(false)
    const updated = await store.updateTimer('t-x', { enabled: true })
    expect(updated.timer_id).toBe('t-x')
    expect(store.timers).toHaveLength(2)
  })

  it('removeTimer 从列表移除', async () => {
    const store = useWorkflowTimersStore()
    await store.loadTimers()
    await store.removeTimer('t-1')
    expect(store.timers.map((t) => t.timer_id)).toEqual(['t-2'])
  })

  it('toggleEnabled 翻转并在结束后清 lastActionTimerId', async () => {
    const store = useWorkflowTimersStore()
    await store.loadTimers()
    let duringAction: string | null = null
    api.updateWorkflowTimer.mockImplementationOnce(async () => {
      duringAction = store.lastActionTimerId
      return makeTimer({ enabled: false }) as never
    })
    await store.toggleEnabled(store.timers[0])
    expect(duringAction).toBe('t-1')
    expect(store.lastActionTimerId).toBeNull()
  })
})

describe('runTimer', () => {
  it('触发后重载定时器并注册 run（带 catalog 提示）', async () => {
    const store = useWorkflowTimersStore()
    await store.loadTimers()
    const result = await store.runTimer('t-1')
    expect(result.run_id).toBe('run-9')
    expect(api.fetchWorkflowTimer).toHaveBeenCalledWith('t-1')
    expect(registerExternalWorkflowRun).toHaveBeenCalledWith('run-9', 'ndvi')
    expect(store.lastActionTimerId).toBeNull()
  })

  it('结果无 run_id 时不注册', async () => {
    api.runWorkflowTimer.mockResolvedValueOnce({ triggered: 0 } as never)
    const store = useWorkflowTimersStore()
    await store.runTimer('t-1')
    expect(registerExternalWorkflowRun).not.toHaveBeenCalled()
  })

  it('注册失败仅记 warning 不抛错', async () => {
    registerExternalWorkflowRun.mockRejectedValueOnce(new Error('layers 不可用'))
    const store = useWorkflowTimersStore()
    await expect(store.runTimer('t-1')).resolves.toMatchObject({ run_id: 'run-9' })
  })
})

describe('事件与 tick', () => {
  it('emitEvent 触发后刷新列表', async () => {
    const store = useWorkflowTimersStore()
    const result = await store.emitEvent({ event_type: 'x' } as never)
    expect(result).toMatchObject({ emitted: 1 })
    expect(api.fetchWorkflowTimers).toHaveBeenCalled()
  })

  it('tick 返回统计并刷新列表', async () => {
    const store = useWorkflowTimersStore()
    const stats = await store.tick()
    expect(stats).toMatchObject({ fired: 2 })
    expect(api.fetchWorkflowTimers).toHaveBeenCalled()
  })
})

describe('computed 分组', () => {
  it('enabledCount / cronTimers / intervalTimers / eventTimers / timersForWorkflow', async () => {
    const store = useWorkflowTimersStore()
    await store.loadTimers()
    expect(store.enabledCount).toBe(1)
    expect(store.cronTimers).toHaveLength(1)
    expect(store.intervalTimers).toHaveLength(1)
    expect(store.eventTimers).toHaveLength(0)
    expect(store.timersForWorkflow('w-1')).toHaveLength(2)
    expect(store.timersForWorkflow('w-2')).toHaveLength(0)
  })
})
