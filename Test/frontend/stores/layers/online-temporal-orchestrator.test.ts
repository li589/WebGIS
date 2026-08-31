/**
 * W3.4d：online-temporal-orchestrator 在线时间获取编排器测试。
 *
 * 覆盖：buildTimeKey / buildTimeRangeFromKey / shiftTimeKey 纯函数分支，
 * triggerOnlineFetch 的提交 / 去重 / 冷却 / 并发上限 / 失败路径，
 * markSucceeded 预获取调度、markFailed 冷却、cleanupStaleEntries 保留期清理。
 */
import { computed, nextTick, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  buildTimeKey,
  buildTimeRangeFromKey,
  shiftTimeKey,
  useOnlineTemporalOrchestrator,
  type OnlineTemporalOrchestratorDeps,
} from '@/stores/layers/online-temporal-orchestrator'
import type { OnlineTemporalCapability } from '@/services/runtime-api'

function makeCap(overrides: Partial<OnlineTemporalCapability> = {}): OnlineTemporalCapability {
  return {
    native_step: '8d',
    prefetch_depth: 0,
    priority: 'standard',
    ...overrides,
  } as OnlineTemporalCapability
}

// ── 纯函数 ────────────────────────────────────────────────────────────────────

describe('buildTimeKey', () => {
  const date = new Date(2024, 4, 1, 6, 0, 0)

  it('按粒度生成对应键', () => {
    expect(buildTimeKey(date, 6, 'year')).toBe('2024')
    expect(buildTimeKey(date, 6, 'month')).toBe('2024-05')
    expect(buildTimeKey(date, 6, 'day')).toBe('2024-05-01')
    expect(buildTimeKey(date, 6, 'hour')).toBe('2024-05-01T06:00:00')
    expect(buildTimeKey(date, 6.9, 'hour')).toBe('2024-05-01T06:00:00')
    expect(buildTimeKey(date, 6, 'static')).toBe('2024-05-01T06:00:00')
  })
})

describe('buildTimeRangeFromKey', () => {
  it('日键 + 8d 步长生成区间', () => {
    const range = buildTimeRangeFromKey('2024-05-01', '8d', 'day')
    expect(range).toEqual({
      start_at: '2024-05-01T00:00:00',
      end_at: '2024-05-09T00:00:00',
      granularity: 'day',
    })
  })

  it('月键 / 年键 / 小时键各自映射', () => {
    expect(buildTimeRangeFromKey('2024-05', '1m', 'month')).toMatchObject({
      start_at: '2024-05-01T00:00:00',
      end_at: '2024-06-01T00:00:00',
      granularity: 'month',
    })
    expect(buildTimeRangeFromKey('2024', '1y', 'year')).toMatchObject({
      start_at: '2024-01-01T00:00:00',
      end_at: '2025-01-01T00:00:00',
      granularity: 'year',
    })
    expect(buildTimeRangeFromKey('2024-05-01T06:00:00', '1h', 'hour')).toMatchObject({
      start_at: '2024-05-01T06:00:00',
      end_at: '2024-05-01T07:00:00',
      granularity: 'hour',
    })
  })

  it('static 粒度映射为 hour', () => {
    expect(buildTimeRangeFromKey('2024-05-01', '1d', 'static')?.granularity).toBe('hour')
  })

  it('非法输入返回 null', () => {
    expect(buildTimeRangeFromKey('2024-05-01', 'bad-step', 'day')).toBeNull()
    expect(buildTimeRangeFromKey('garbage', '1d', 'day')).toBeNull()
  })
})

describe('shiftTimeKey', () => {
  it('按步长向前/向后平移', () => {
    expect(shiftTimeKey('2024-05-01', '8d', 1, 'day')).toBe('2024-05-09')
    expect(shiftTimeKey('2024-05-01', '8d', -1, 'day')).toBe('2024-04-23')
    expect(shiftTimeKey('2024-05', '1m', 1, 'month')).toBe('2024-06')
    expect(shiftTimeKey('2024-12', '1m', 1, 'month')).toBe('2025-01')
    expect(shiftTimeKey('2024-05-01T06:00:00', '1h', 2, 'hour')).toBe('2024-05-01T08:00:00')
  })

  it('delta 0 / 非法键 / 非法步长', () => {
    expect(shiftTimeKey('2024-05-01', '8d', 0, 'day')).toBe('2024-05-01')
    expect(shiftTimeKey('garbage', '8d', 1, 'day')).toBeNull()
    // 非法步长无法平移：守卫短路返回原键（调用方以 includes 去重，等效跳过）
    expect(shiftTimeKey('2024-05-01', 'bad', 1, 'day')).toBe('2024-05-01')
  })
})

// ── 编排器 ────────────────────────────────────────────────────────────────────

interface OrchHarness {
  orch: ReturnType<typeof useOnlineTemporalOrchestrator>
  deps: OnlineTemporalOrchestratorDeps & {
    runWorkflowForCatalog: ReturnType<typeof vi.fn>
    getOnlineTemporalConfig: ReturnType<typeof vi.fn>
    logOperation: ReturnType<typeof vi.fn>
  }
  selectedCatalogId: ReturnType<typeof ref<string | null>>
  currentDate: ReturnType<typeof ref<Date>>
  currentHour: ReturnType<typeof ref<number>>
  activeLayerGranularity: ReturnType<typeof computed<'day' | 'hour'>>
}

function setupOrch(options: { cap?: OnlineTemporalCapability | null } = {}): OrchHarness {
  const cap = 'cap' in options ? options.cap : makeCap()
  const runWorkflowForCatalog = vi.fn(async () => 'run-1')
  const deps = {
    getOnlineTemporalConfig: vi.fn(() => cap),
    runWorkflowForCatalog,
    selectedCatalogId: ref<string | null>('cat-ndvi'),
    currentDate: ref(new Date(2024, 4, 1, 0, 0, 0)),
    currentHour: ref(0),
    activeLayerGranularity: computed(() => 'day' as const),
    logOperation: vi.fn(),
  }
  const orch = useOnlineTemporalOrchestrator(deps)
  return { orch, deps: deps as unknown as OrchHarness['deps'], ...deps } as OrchHarness
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('computed 状态', () => {
  it('currentTimeKey / currentLayerSupportsOnline / currentFetchStatus', async () => {
    const h = setupOrch()
    expect(h.orch.currentTimeKey.value).toBe('2024-05-01')
    expect(h.orch.currentLayerSupportsOnline.value).toBe(true)
    expect(h.orch.currentFetchStatus.value).toBeNull()

    h.deps.selectedCatalogId.value = null
    await nextTick()
    expect(h.orch.currentTimeKey.value).toBeNull()
    expect(h.orch.currentLayerSupportsOnline.value).toBe(false)
  })

  it('无在线能力的图层不支持', async () => {
    const h = setupOrch({ cap: null })
    expect(h.orch.currentLayerSupportsOnline.value).toBe(false)
    await expect(h.orch.triggerOnlineFetch('cat-ndvi', '2024-05-01')).resolves.toBeUndefined()
    expect(h.deps.runWorkflowForCatalog).not.toHaveBeenCalled()
  })
})

describe('triggerOnlineFetch', () => {
  it('正常提交：in-flight 记录 runId 与 time_range', async () => {
    const h = setupOrch()
    const runId = await h.orch.triggerOnlineFetch('cat-ndvi', '2024-05-01')
    expect(runId).toBe('run-1')
    expect(h.deps.runWorkflowForCatalog).toHaveBeenCalledWith('cat-ndvi', {
      timeRange: {
        start_at: '2024-05-01T00:00:00',
        end_at: '2024-05-09T00:00:00',
        granularity: 'day',
      },
      resourceProfile: 'standard',
      commandLabel: expect.stringContaining('在线获取'),
    })
    const entry = h.orch.fetchEntries.value.get('cat-ndvi:2024-05-01')
    expect(entry).toMatchObject({ status: 'in-flight', runId: 'run-1' })
    expect(h.orch.inFlightCount.value).toBe(1)
    expect(h.deps.logOperation).toHaveBeenCalledWith('online-temporal', expect.stringContaining('在线获取'))
  })

  it('低优先级能力映射 batch 资源档', async () => {
    const h = setupOrch({ cap: makeCap({ priority: 'low' }) })
    await h.orch.triggerOnlineFetch('cat-ndvi', '2024-05-01')
    expect(h.deps.runWorkflowForCatalog).toHaveBeenCalledWith(
      'cat-ndvi',
      expect.objectContaining({ resourceProfile: 'batch' }),
    )
  })

  it('in-flight 去重：重复触发直接返回已有 runId', async () => {
    const h = setupOrch()
    await h.orch.triggerOnlineFetch('cat-ndvi', '2024-05-01')
    const again = await h.orch.triggerOnlineFetch('cat-ndvi', '2024-05-01')
    expect(again).toBe('run-1')
    expect(h.deps.runWorkflowForCatalog).toHaveBeenCalledTimes(1)
  })

  it('succeeded 后不再重复提交', async () => {
    const h = setupOrch()
    await h.orch.triggerOnlineFetch('cat-ndvi', '2024-05-01')
    h.orch.markSucceeded('cat-ndvi', 'run-1')
    const again = await h.orch.triggerOnlineFetch('cat-ndvi', '2024-05-01')
    expect(again).toBe('run-1')
    expect(h.deps.runWorkflowForCatalog).toHaveBeenCalledTimes(1)
  })

  it('提交未返回 run_id 进入冷却，冷却期内跳过，到期后重试', async () => {
    vi.useFakeTimers()
    const h = setupOrch()
    h.deps.runWorkflowForCatalog.mockResolvedValue(undefined)
    const first = await h.orch.triggerOnlineFetch('cat-ndvi', '2024-05-01')
    expect(first).toBeUndefined()
    const entry = h.orch.fetchEntries.value.get('cat-ndvi:2024-05-01')
    expect(entry).toMatchObject({ status: 'cooling', error: '提交未返回 run_id' })

    const cooled = await h.orch.triggerOnlineFetch('cat-ndvi', '2024-05-01')
    expect(cooled).toBeUndefined()
    expect(h.deps.runWorkflowForCatalog).toHaveBeenCalledTimes(1)

    vi.advanceTimersByTime(61_000)
    h.deps.runWorkflowForCatalog.mockResolvedValue('run-2')
    const retried = await h.orch.triggerOnlineFetch('cat-ndvi', '2024-05-01')
    expect(retried).toBe('run-2')
    expect(h.deps.runWorkflowForCatalog).toHaveBeenCalledTimes(2)
  })

  it('提交异常进入冷却并记录失败日志', async () => {
    const h = setupOrch()
    h.deps.runWorkflowForCatalog.mockRejectedValue(new Error('HTTP 429'))
    const runId = await h.orch.triggerOnlineFetch('cat-ndvi', '2024-05-01')
    expect(runId).toBeUndefined()
    const entry = h.orch.fetchEntries.value.get('cat-ndvi:2024-05-01')
    expect(entry).toMatchObject({ status: 'cooling', error: 'HTTP 429' })
    expect(h.deps.logOperation).toHaveBeenCalledWith(
      'online-temporal',
      expect.stringContaining('HTTP 429'),
    )
  })

  it('无法构建 time_range 时记录日志并放弃', async () => {
    const h = setupOrch({ cap: makeCap({ native_step: 'bad' }) })
    await h.orch.triggerOnlineFetch('cat-ndvi', '2024-05-01')
    expect(h.deps.runWorkflowForCatalog).not.toHaveBeenCalled()
    expect(h.deps.logOperation).toHaveBeenCalledWith(
      'online-temporal',
      expect.stringContaining('无法构建 time_range'),
    )
  })

  it('预获取达到并发上限时跳过', async () => {
    const h = setupOrch()
    const pending: Array<(v: string) => void> = []
    h.deps.runWorkflowForCatalog.mockImplementation(
      () => new Promise<string>((resolve) => pending.push(resolve)) as never,
    )
    const p1 = h.orch.triggerOnlineFetch('cat-a', '2024-05-01')
    const p2 = h.orch.triggerOnlineFetch('cat-b', '2024-05-01')
    await nextTick()
    expect(h.orch.inFlightCount.value).toBe(2)
    const skipped = await h.orch.triggerOnlineFetch('cat-c', '2024-05-01', { isPrefetch: true })
    expect(skipped).toBeUndefined()
    expect(h.deps.runWorkflowForCatalog).toHaveBeenCalledTimes(2)
    for (const resolve of pending) resolve('run-x')
    await Promise.all([p1, p2])
  })
})

describe('markSucceeded / markFailed / cleanupStaleEntries', () => {
  it('markSucceeded 记录成功并调度相邻预获取', async () => {
    vi.useFakeTimers()
    const h = setupOrch({ cap: makeCap({ prefetch_depth: 1 }) })
    await h.orch.triggerOnlineFetch('cat-ndvi', '2024-05-01')
    h.deps.runWorkflowForCatalog.mockClear()
    h.orch.markSucceeded('cat-ndvi', 'run-1')
    expect(h.orch.fetchEntries.value.get('cat-ndvi:2024-05-01')?.status).toBe('succeeded')

    vi.advanceTimersByTime(2_000) // PREFETCH_DELAY_MS
    await vi.advanceTimersByTimeAsync(1_200) // 两个相邻键各 500ms 交错 + 余量
    const submitted = h.deps.runWorkflowForCatalog.mock.calls.map((c) => c[0])
    expect(submitted.length).toBeGreaterThan(0)
    const keys = h.deps.runWorkflowForCatalog.mock.calls.map((c) => String(c[1].timeRange.start_at))
    expect(keys).toContain('2024-05-09T00:00:00')
    expect(keys).toContain('2024-04-23T00:00:00')
  })

  it('markFailed 记录失败并转入冷却', async () => {
    vi.useFakeTimers()
    const h = setupOrch()
    await h.orch.triggerOnlineFetch('cat-ndvi', '2024-05-01')
    h.orch.markFailed('cat-ndvi', 'run-1', 'boom')
    expect(h.orch.fetchEntries.value.get('cat-ndvi:2024-05-01')?.status).toBe('failed')
    vi.advanceTimersByTime(1)
    expect(h.orch.fetchEntries.value.get('cat-ndvi:2024-05-01')?.status).toBe('cooling')
  })

  it('markSucceeded/markFailed 对未知 runId 无操作', () => {
    const h = setupOrch()
    expect(() => h.orch.markSucceeded('cat-ndvi', 'run-none')).not.toThrow()
    expect(() => h.orch.markFailed('cat-ndvi', 'run-none')).not.toThrow()
  })

  it('cleanupStaleEntries 清理超过保留期的终态条目', async () => {
    vi.useFakeTimers()
    const h = setupOrch()
    await h.orch.triggerOnlineFetch('cat-ndvi', '2024-05-01')
    h.orch.markSucceeded('cat-ndvi', 'run-1')
    h.orch.cleanupStaleEntries()
    expect(h.orch.fetchEntries.value.size).toBe(1)
    vi.advanceTimersByTime(6 * 60_000)
    h.orch.cleanupStaleEntries()
    expect(h.orch.fetchEntries.value.size).toBe(0)
  })
})

// ── P2：统一在线同步入口（syncLayerAssetOnline）分支 ────────────────────────

describe('triggerOnlineFetch 统一入口（P2）', () => {
  function setupWithSync(
    syncImpl: (catalogId: string, body: Record<string, unknown>) => Promise<unknown>,
  ) {
    const cap = makeCap()
    const runWorkflowForCatalog = vi.fn(async () => 'run-fallback-1')
    const registerExternalWorkflowRun = vi.fn(async () => {})
    const deps = {
      getOnlineTemporalConfig: vi.fn(() => cap),
      runWorkflowForCatalog,
      syncLayerAssetOnline: vi.fn(syncImpl) as never,
      registerExternalWorkflowRun,
      selectedCatalogId: ref<string | null>('cat-ndvi'),
      currentDate: ref(new Date(2024, 4, 1, 0, 0, 0)),
      currentHour: ref(0),
      activeLayerGranularity: computed(() => 'day' as const),
      logOperation: vi.fn(),
    }
    const orch = useOnlineTemporalOrchestrator(deps as unknown as OnlineTemporalOrchestratorDeps)
    return { orch, deps }
  }

  it('succeeded（资产已 fresh）→ 直接标记成功，不注册轮询、不走回退', async () => {
    const h = setupWithSync(async () => ({
      run_id: 'run-sync-fresh',
      status: 'succeeded',
      message: '图层资产已就绪。',
    }))
    const runId = await h.orch.triggerOnlineFetch('cat-ndvi', '2024-05-01')

    expect(runId).toBeUndefined()
    expect(h.deps.runWorkflowForCatalog).not.toHaveBeenCalled()
    expect(h.deps.registerExternalWorkflowRun).not.toHaveBeenCalled()
    const entry = h.orch.fetchEntries.value.get('cat-ndvi:2024-05-01')
    expect(entry?.status).toBe('succeeded')
  })

  it('submitted → 注册外部 run 进轮询链并返回 run_id', async () => {
    const h = setupWithSync(async () => ({
      run_id: 'run-sync-1',
      status: 'submitted',
      message: '工作流已提交。',
    }))
    const runId = await h.orch.triggerOnlineFetch('cat-ndvi', '2024-05-01')

    expect(runId).toBe('run-sync-1')
    expect(h.deps.registerExternalWorkflowRun).toHaveBeenCalledWith('run-sync-1', 'cat-ndvi')
    expect(h.deps.runWorkflowForCatalog).not.toHaveBeenCalled()
    const entry = h.orch.fetchEntries.value.get('cat-ndvi:2024-05-01')
    expect(entry?.status).toBe('in-flight')
    expect(entry?.runId).toBe('run-sync-1')
  })

  it('in-flight 复用后端既有 run（同 run_id 不重复注册）', async () => {
    const h = setupWithSync(async () => ({
      run_id: 'run-sync-existing',
      status: 'in-flight',
      message: '同图层在线同步已在进行。',
    }))
    const runId = await h.orch.triggerOnlineFetch('cat-ndvi', '2024-05-01')

    expect(runId).toBe('run-sync-existing')
    expect(h.deps.registerExternalWorkflowRun).toHaveBeenCalledWith(
      'run-sync-existing',
      'cat-ndvi',
    )
  })

  it('统一入口异常 → 回退 runWorkflowForCatalog 直提路径', async () => {
    const h = setupWithSync(async () => {
      throw new Error('网络不可用')
    })
    const runId = await h.orch.triggerOnlineFetch('cat-ndvi', '2024-05-01')

    expect(runId).toBe('run-fallback-1')
    expect(h.deps.runWorkflowForCatalog).toHaveBeenCalledWith('cat-ndvi', expect.anything())
  })

  it('未注入 syncLayerAssetOnline → 保持旧路径行为', async () => {
    const cap = makeCap()
    const runWorkflowForCatalog = vi.fn(async () => 'run-legacy-1')
    const deps = {
      getOnlineTemporalConfig: vi.fn(() => cap),
      runWorkflowForCatalog,
      selectedCatalogId: ref<string | null>('cat-ndvi'),
      currentDate: ref(new Date(2024, 4, 1, 0, 0, 0)),
      currentHour: ref(0),
      activeLayerGranularity: computed(() => 'day' as const),
      logOperation: vi.fn(),
    }
    const orch = useOnlineTemporalOrchestrator(deps as unknown as OnlineTemporalOrchestratorDeps)
    const runId = await orch.triggerOnlineFetch('cat-ndvi', '2024-05-01')

    expect(runId).toBe('run-legacy-1')
    expect(runWorkflowForCatalog).toHaveBeenCalledOnce()
  })
})
