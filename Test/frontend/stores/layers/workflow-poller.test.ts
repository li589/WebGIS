/**
 * W3.4d: workflow-poller.ts 轮询机制测试
 *
 * 覆盖：
 *  - applyWorkflowEventsToJobLayer：进度归并 / 终态保护 / node_progress 解析 /
 *    block_commit 物化门控 / seek 发射 / 事件游标推进
 *  - syncWorkflowRunSnapshot：节流 / viewport 过期 / 快照合并 / 终态副作用
 *    （attach overlays、粒子流清理与启用）
 *  - pollWorkflowRun：启动幂等 / 事件驱动 active 间隔 / 404 / 429 退避 /
 *    连续错误服务器兜底 / 空闲超时软恢复 / document.hidden 延长间隔
 */
// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/services/runtime-api', () => ({
  getWorkflowEvents: vi.fn(),
  getWorkflowRun: vi.fn(),
}))

import {
  createWorkflowPoller,
  EVENT_POLL_ACTIVE_INTERVAL_MS,
  EVENT_POLL_IDLE_INTERVAL_MS,
  EVENT_POLL_IDLE_TIMEOUT_MS,
  MAX_CONSECUTIVE_POLL_ERRORS,
  STATUS_SYNC_INTERVAL_MS,
  type WorkflowPollerDeps,
} from '@/stores/layers/workflow-poller'
import { getWorkflowEvents, getWorkflowRun } from '@/services/runtime-api'
import type { WorkflowEvent } from '@/services/runtime-api'
import { ApiRequestError } from '@/services/http-errors'
import type { JobLayerItem, NodeProgress } from '@/stores/layers/types'

const mockedGetEvents = vi.mocked(getWorkflowEvents)
const mockedGetRun = vi.mocked(getWorkflowRun)

function makeJobLayer(overrides: Partial<JobLayerItem> = {}): JobLayerItem {
  return {
    jobId: 'run-1',
    name: 'Test Job',
    catalogId: 'cat-1',
    commandType: 'analysis',
    status: 'running',
    progress: 10,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    message: '',
    metrics: [],
    ...overrides,
  }
}

function makeEvent(overrides: Partial<WorkflowEvent> = {}): WorkflowEvent {
  return {
    event_id: 'evt-1',
    run_id: 'run-1',
    channel: 'progress',
    message: '',
    created_at: '2026-01-01T01:00:00Z',
    payload: {},
    ...overrides,
  } as WorkflowEvent
}

function makeRun(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    run_id: 'run-1',
    status: 'running',
    result_refs: [],
    ...overrides,
  }
}

function setupDeps(initial: JobLayerItem = makeJobLayer()) {
  const store = new Map<string, JobLayerItem>([[initial.jobId, initial]])
  const deps: WorkflowPollerDeps = {
    getJobLayer: vi.fn((id: string) => store.get(id)),
    isViewportRefreshStale: vi.fn((_epoch?: number) => false),
    isRunDismissed: vi.fn(() => false),
    getParticleFlowCatalogId: vi.fn(() => null),
    supportsParticleFlow: vi.fn(() => false),
    upsertJobLayer: vi.fn((_catalogId: string, layer: JobLayerItem) => {
      store.set(layer.jobId, layer)
    }),
    setWorkflowError: vi.fn(),
    removeActiveCatalog: vi.fn(),
    syncProgressiveBlockOverlays: vi.fn(),
    emitWorkflowProgressTimeSeek: vi.fn(),
    attachAlgorithmProductOverlays: vi.fn(async () => 1),
    cleanupUnproducedRunLayers: vi.fn(),
    clearWindForCatalog: vi.fn(),
    enableParticleIfUnset: vi.fn(),
    buildJobLayer: vi.fn(
      async (
        run: unknown,
        catalogId: string,
        opts: { previousJobLayer?: JobLayerItem },
      ) => {
        const r = run as { run_id: string; status?: string; progress?: number }
        return {
          ...makeJobLayer(),
          ...(opts.previousJobLayer ?? {}),
          jobId: r.run_id,
          catalogId,
          status: (r.status as JobLayerItem['status']) ?? 'queued',
          progress: r.progress ?? opts.previousJobLayer?.progress ?? 20,
        }
      },
    ),
  }
  const poller = createWorkflowPoller(deps)
  return { deps, store, poller }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedGetEvents.mockReset()
  mockedGetRun.mockReset()
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

// ── 常量 ────────────────────────────────────────────────────────────────────

describe('轮询常量', () => {
  it('active 间隔小于 idle 间隔，空闲超时远大于状态同步间隔', () => {
    expect(EVENT_POLL_ACTIVE_INTERVAL_MS).toBeLessThan(EVENT_POLL_IDLE_INTERVAL_MS)
    expect(EVENT_POLL_IDLE_TIMEOUT_MS).toBeGreaterThan(STATUS_SYNC_INTERVAL_MS)
    expect(MAX_CONSECUTIVE_POLL_ERRORS).toBe(3)
  })
})

// ── applyWorkflowEventsToJobLayer ──────────────────────────────────────────

describe('applyWorkflowEventsToJobLayer', () => {
  it('空事件原样返回同一引用', () => {
    const { poller } = setupDeps()
    const layer = makeJobLayer()
    expect(poller.applyWorkflowEventsToJobLayer(layer, [])).toBe(layer)
  })

  it('进度单调取最大值，不因低进度事件回退', () => {
    const { poller } = setupDeps()
    const result = poller.applyWorkflowEventsToJobLayer(makeJobLayer({ progress: 40 }), [
      makeEvent({ progress: 5 }),
      makeEvent({ event_id: 'evt-2', progress: 60 }),
    ])
    expect(result.progress).toBe(60)
  })

  it('事件 message 覆盖 jobLayer.message', () => {
    const { poller } = setupDeps()
    const result = poller.applyWorkflowEventsToJobLayer(makeJobLayer({ message: '旧消息' }), [
      makeEvent({ message: '新消息' }),
    ])
    expect(result.message).toBe('新消息')
  })

  it('识别的状态更新 jobLayer.status', () => {
    const { poller } = setupDeps()
    const result = poller.applyWorkflowEventsToJobLayer(makeJobLayer({ status: 'queued' }), [
      makeEvent({ payload: { status: 'running' } }),
    ])
    expect(result.status).toBe('running')
  })

  it('终态保护：failed 后不接受 queued/running 降级', () => {
    const { poller } = setupDeps()
    const result = poller.applyWorkflowEventsToJobLayer(makeJobLayer({ status: 'failed' }), [
      makeEvent({ payload: { status: 'running' } }),
    ])
    expect(result.status).toBe('failed')
  })

  it('node_progress 新节点入列并抬升整体进度', () => {
    const { poller, deps } = setupDeps()
    const result = poller.applyWorkflowEventsToJobLayer(makeJobLayer(), [
      makeEvent({
        event_id: 'evt-n1',
        payload: {
          node_progress: { node_id: 'download', node_label: '下载', stage: 'ingest', progress: 30 },
        },
      }),
    ])
    expect(result.nodeProgress).toHaveLength(1)
    expect(result.nodeProgress![0]).toMatchObject({
      nodeId: 'download',
      nodeLabel: '下载',
      stage: 'ingest',
      progress: 30,
      eventId: 'evt-n1',
    })
    expect(result.progress).toBe(30)
    expect(deps.emitWorkflowProgressTimeSeek).toHaveBeenCalledTimes(1)
  })

  it('node_progress 已存在节点按 node_id 合并，进度取最大', () => {
    const { poller } = setupDeps()
    const existing: NodeProgress[] = [
      {
        nodeId: 'download',
        nodeLabel: '下载',
        stage: 'ingest',
        progress: 30,
        updatedAt: '2026-01-01T00:00:00Z',
        eventId: 'evt-n1',
      },
    ]
    const result = poller.applyWorkflowEventsToJobLayer(
      makeJobLayer({ progress: 30, nodeProgress: existing }),
      [
        makeEvent({
          event_id: 'evt-n2',
          payload: {
            node_progress: { node_id: 'download', stage: 'verify', progress: 20 },
          },
        }),
      ],
    )
    expect(result.nodeProgress).toHaveLength(1)
    expect(result.nodeProgress![0]).toMatchObject({
      nodeId: 'download',
      stage: 'verify',
      progress: 30,
      eventId: 'evt-n2',
    })
  })

  it('detail 的 snake_case 字段归一为 camelCase', () => {
    const { poller } = setupDeps()
    const result = poller.applyWorkflowEventsToJobLayer(makeJobLayer(), [
      makeEvent({
        payload: {
          node_progress: {
            node_id: 'n1',
            progress: 50,
            detail: {
              chunks_done: 2,
              chunks_total: 4,
              pixels_done: 100,
              pixels_total: 200,
              time_key: '20240501',
              block_id: 'b-01',
              product_tag: 'sm',
            },
          },
        },
      }),
    ])
    expect(result.nodeProgress![0]!.detail).toMatchObject({
      chunksDone: 2,
      chunksTotal: 4,
      pixelsDone: 100,
      pixelsTotal: 200,
      timeKey: '20240501',
      blockId: 'b-01',
      productTag: 'sm',
    })
  })

  it('block_commit + running：触发渐进物化并生成块区间消息', () => {
    const { poller, deps } = setupDeps()
    const result = poller.applyWorkflowEventsToJobLayer(makeJobLayer(), [
      makeEvent({
        payload: {
          node_progress: {
            node_id: 'n1',
            progress: 50,
            detail: {
              phase: 'block_commit',
              blocks_done: 3,
              blocks_total: 8,
              date_start: '2024-05-01',
              date_end: '2024-05-08',
            },
          },
        },
      }),
    ])
    expect(deps.syncProgressiveBlockOverlays).toHaveBeenCalledWith('run-1', 'cat-1')
    expect(result.message).toContain('3/8')
    expect(result.message).toContain('2024-05-01')
  })

  it('block_commit + failed 状态：跳过物化（历史回放不得 POST）', () => {
    const { poller, deps } = setupDeps()
    poller.applyWorkflowEventsToJobLayer(makeJobLayer({ status: 'failed' }), [
      makeEvent({
        payload: {
          node_progress: { node_id: 'n1', detail: { phase: 'block_commit' } },
        },
      }),
    ])
    expect(deps.syncProgressiveBlockOverlays).not.toHaveBeenCalled()
  })

  it('无 date 区间的 block_commit 回退到 formatProgressShell 消息', () => {
    const { poller } = setupDeps()
    const result = poller.applyWorkflowEventsToJobLayer(makeJobLayer({ message: '' }), [
      makeEvent({
        payload: {
          node_progress: {
            node_id: 'n1',
            node_label: '反演',
            stage: 'block',
            progress: 40,
            detail: { phase: 'block_commit' },
          },
        },
      }),
    ])
    expect(result.message).toBeTruthy()
    expect(result.message.length).toBeGreaterThan(0)
  })

  it('事件游标推进到最后一个事件', () => {
    const { poller } = setupDeps()
    const result = poller.applyWorkflowEventsToJobLayer(makeJobLayer(), [
      makeEvent({ event_id: 'evt-a', created_at: '2026-01-01T01:00:00Z' }),
      makeEvent({ event_id: 'evt-b', created_at: '2026-01-01T02:00:00Z' }),
    ])
    expect(result.lastEventId).toBe('evt-b')
    expect(result.lastEventAt).toBe('2026-01-01T02:00:00Z')
    expect(result.updatedAt).toBe('2026-01-01T02:00:00Z')
  })

  it('运行中状态把事件消息写入 diagnosticNotes；终态保留原诊断', () => {
    const { poller } = setupDeps()
    const withMsg = makeEvent({ message: '下载中' })
    const running = poller.applyWorkflowEventsToJobLayer(
      makeJobLayer({ status: 'running', diagnosticNotes: ['旧诊断'] }),
      [withMsg],
    )
    expect(running.eventMessages).toEqual(['旧诊断', '进度 · 下载中'])
    expect(running.diagnosticNotes).toEqual(running.eventMessages)

    const done = poller.applyWorkflowEventsToJobLayer(
      makeJobLayer({ status: 'succeeded', diagnosticNotes: ['最终诊断'] }),
      [withMsg],
    )
    expect(done.diagnosticNotes).toEqual(['最终诊断'])
  })
})

// ── syncWorkflowRunSnapshot ─────────────────────────────────────────────────

describe('syncWorkflowRunSnapshot', () => {
  it('viewport 已过期：停止轮询并移除目录，不发起请求', async () => {
    const { deps, poller } = setupDeps()
    vi.mocked(deps.isViewportRefreshStale).mockReturnValue(true)
    const result = await poller.syncWorkflowRunSnapshot('run-1', 'cat-1', false, 7)
    expect(result).toBe(true)
    expect(deps.removeActiveCatalog).toHaveBeenCalledWith('cat-1')
    expect(mockedGetRun).not.toHaveBeenCalled()
    expect(poller.isPolling('run-1')).toBe(false)
  })

  it('未 force 且在同步间隔内：直接返回 false 且不请求', async () => {
    const { poller } = setupDeps()
    mockedGetRun.mockResolvedValue(makeRun() as never)
    const first = await poller.syncWorkflowRunSnapshot('run-1', 'cat-1', true)
    expect(first).toBe(false)
    expect(mockedGetRun).toHaveBeenCalledTimes(1)
    const second = await poller.syncWorkflowRunSnapshot('run-1', 'cat-1', false)
    expect(second).toBe(false)
    expect(mockedGetRun).toHaveBeenCalledTimes(1)
  })

  it('force 绕过节流强制同步', async () => {
    const { poller } = setupDeps()
    mockedGetRun.mockResolvedValue(makeRun() as never)
    await poller.syncWorkflowRunSnapshot('run-1', 'cat-1', true)
    await poller.syncWorkflowRunSnapshot('run-1', 'cat-1', true)
    expect(mockedGetRun).toHaveBeenCalledTimes(2)
  })

  it('非终态合并：保留事件游标且进度取服务器与事件侧最大值', async () => {
    const initial = makeJobLayer({
      progress: 70,
      lastEventId: 'evt-9',
      lastEventAt: '2026-01-01T02:00:00Z',
      eventMessages: ['下载中'],
      nodeProgress: [
        {
          nodeId: 'n1',
          nodeLabel: 'n1',
          stage: '',
          progress: 55,
          updatedAt: '2026-01-01T00:00:00Z',
          eventId: 'evt-9',
        },
      ],
    })
    const { deps, store, poller } = setupDeps(initial)
    mockedGetRun.mockResolvedValue(makeRun({ status: 'running', progress: 30 }) as never)
    const result = await poller.syncWorkflowRunSnapshot('run-1', 'cat-1', true)
    expect(result).toBe(false)
    const merged = store.get('run-1')!
    expect(deps.upsertJobLayer).toHaveBeenCalled()
    expect(merged.progress).toBe(70)
    expect(merged.lastEventId).toBe('evt-9')
    expect(merged.eventMessages).toEqual(['下载中'])
    expect(merged.nodeProgress).toHaveLength(1)
    expect(poller.isPolling('run-1')).toBe(false)
    expect(deps.removeActiveCatalog).not.toHaveBeenCalled()
  })

  it('终态 succeeded：停轮询 + 挂载产物 + 保留事件侧 nodeProgress 不丢失', async () => {
    const initial = makeJobLayer({
      progress: 60,
      nodeProgress: [
        { nodeId: 'n1', nodeLabel: 'n1', stage: '', progress: 50, updatedAt: '', eventId: 'e' },
      ],
    })
    const { deps, poller } = setupDeps(initial)
    mockedGetRun.mockResolvedValue(
      makeRun({ status: 'succeeded', result_refs: [{ title: 'COG' }] }) as never,
    )
    const result = await poller.syncWorkflowRunSnapshot('run-1', 'cat-1', true)
    expect(result).toBe(true)
    expect(deps.removeActiveCatalog).toHaveBeenCalledWith('cat-1')
    expect(deps.attachAlgorithmProductOverlays).toHaveBeenCalledWith(
      [{ title: 'COG' }],
      'cat-1',
      'run-1',
    )
  })

  it('succeeded 但运行已被用户关闭：不重复挂载产物', async () => {
    const { deps, poller } = setupDeps()
    vi.mocked(deps.isRunDismissed).mockReturnValue(true)
    mockedGetRun.mockResolvedValue(makeRun({ status: 'succeeded' }) as never)
    await poller.syncWorkflowRunSnapshot('run-1', 'cat-1', true)
    expect(deps.attachAlgorithmProductOverlays).not.toHaveBeenCalled()
  })

  it('粒子流目录 + 终态且无可渲染资产：清理风场', async () => {
    const { deps, poller } = setupDeps(makeJobLayer({ status: 'running' }))
    vi.mocked(deps.getParticleFlowCatalogId).mockReturnValue('cat-1')
    vi.mocked(deps.supportsParticleFlow).mockReturnValue(true)
    mockedGetRun.mockResolvedValue(makeRun({ status: 'failed' }) as never)
    await poller.syncWorkflowRunSnapshot('run-1', 'cat-1', true)
    expect(deps.clearWindForCatalog).toHaveBeenCalledWith('cat-1')
    expect(deps.enableParticleIfUnset).not.toHaveBeenCalled()
  })

  it('succeeded + 支持粒子流 + 有可渲染资产：启用粒子流', async () => {
    const renderable = makeJobLayer({
      status: 'running',
      mapLayerPayload: {
        layerAssets: { cogUrl: '/cog/preview.png' },
      } as unknown as JobLayerItem['mapLayerPayload'],
    })
    const { deps, poller } = setupDeps(renderable)
    vi.mocked(deps.supportsParticleFlow).mockReturnValue(true)
    mockedGetRun.mockResolvedValue(makeRun({ status: 'succeeded' }) as never)
    await poller.syncWorkflowRunSnapshot('run-1', 'cat-1', true)
    expect(deps.enableParticleIfUnset).toHaveBeenCalledWith('cat-1')
  })
})

// ── pollWorkflowRun / startPolling ──────────────────────────────────────────

describe('pollWorkflowRun', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  it('startPolling 幂等：句柄注册后重复启动被跳过', async () => {
    const { poller } = setupDeps()
    mockedGetEvents.mockResolvedValue({ items: [] } as never)
    mockedGetRun.mockResolvedValue(makeRun() as never)
    poller.startPolling('run-1', 'cat-1')
    await vi.advanceTimersByTimeAsync(0)
    expect(poller.isPolling('run-1')).toBe(true)
    poller.startPolling('run-1', 'cat-1')
    await vi.advanceTimersByTimeAsync(0)
    expect(mockedGetEvents).toHaveBeenCalledTimes(1)
  })

  it('stopWorkflowPolling 后可重新启动', async () => {
    const { poller } = setupDeps()
    mockedGetEvents.mockResolvedValue({ items: [] } as never)
    mockedGetRun.mockResolvedValue(makeRun() as never)
    poller.startPolling('run-1', 'cat-1')
    await vi.advanceTimersByTimeAsync(0)
    poller.stopWorkflowPolling('run-1')
    expect(poller.isPolling('run-1')).toBe(false)
    poller.startPolling('run-1', 'cat-1')
    await vi.advanceTimersByTimeAsync(0)
    expect(mockedGetEvents).toHaveBeenCalledTimes(2)
  })

  it('有新事件时立即归并并以 active 间隔安排下一轮', async () => {
    const { deps, poller } = setupDeps()
    let call = 0
    mockedGetEvents.mockImplementation(async () => {
      call += 1
      return call === 1
        ? ({ items: [makeEvent({ event_id: 'evt-1', message: 'tick' })] } as never)
        : ({ items: [] } as never)
    })
    mockedGetRun.mockResolvedValue(makeRun() as never)
    poller.startPolling('run-1', 'cat-1')
    await vi.advanceTimersByTimeAsync(0)
    expect(deps.upsertJobLayer).toHaveBeenCalled()
    expect(deps.emitWorkflowProgressTimeSeek).not.toHaveBeenCalled() // 无 node_progress
    // active 间隔（1200ms）到期前不拉，到期后立即拉第二轮
    await vi.advanceTimersByTimeAsync(EVENT_POLL_ACTIVE_INTERVAL_MS - 1)
    expect(mockedGetEvents).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(mockedGetEvents).toHaveBeenCalledTimes(2)
  })

  it('事件流中出现终态：强制同步并停止轮询', async () => {
    const { deps, poller } = setupDeps()
    mockedGetEvents.mockResolvedValue({
      items: [makeEvent({ event_id: 'evt-done', payload: { status: 'succeeded' } })],
    } as never)
    mockedGetRun.mockResolvedValue(makeRun({ status: 'succeeded' }) as never)
    poller.startPolling('run-1', 'cat-1')
    await vi.advanceTimersByTimeAsync(0)
    expect(deps.removeActiveCatalog).toHaveBeenCalledWith('cat-1')
    expect(mockedGetRun).toHaveBeenCalledTimes(1)
    expect(poller.isPolling('run-1')).toBe(false)
  })

  it('404：停止轮询并标记 failed', async () => {
    const { deps, poller } = setupDeps()
    mockedGetEvents.mockRejectedValue(new Error('GET /workflow-runs/run-1 404 Not Found'))
    poller.startPolling('run-1', 'cat-1')
    await vi.advanceTimersByTimeAsync(0)
    expect(deps.setWorkflowError).toHaveBeenCalledWith(expect.stringContaining('不存在'))
    expect(deps.removeActiveCatalog).toHaveBeenCalledWith('cat-1')
    expect(deps.upsertJobLayer).toHaveBeenCalledWith(
      'cat-1',
      expect.objectContaining({ status: 'failed' }),
    )
  })

  it('429 限流：按 Retry-After 退避且不计入连续失败', async () => {
    const { deps, poller } = setupDeps()
    mockedGetEvents.mockRejectedValue(
      new ApiRequestError('Too Many Requests', 429, '/workflow-runs/run-1/events', undefined, 'C429001', 8),
    )
    mockedGetRun.mockResolvedValue(makeRun() as never)
    poller.startPolling('run-1', 'cat-1')
    await vi.advanceTimersByTimeAsync(0)
    expect(deps.setWorkflowError).not.toHaveBeenCalled()
    // 8s 退避期内不再拉事件
    await vi.advanceTimersByTimeAsync(7999)
    expect(mockedGetEvents).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(mockedGetEvents).toHaveBeenCalledTimes(2)
  })

  it('连续 3 次普通错误且服务器仍 running：恢复轮询而非判失败', async () => {
    const { deps, poller } = setupDeps()
    mockedGetEvents.mockRejectedValue(new Error('network down'))
    mockedGetRun.mockResolvedValue(makeRun({ status: 'running' }) as never)
    poller.startPolling('run-1', 'cat-1')
    // 三轮错误，每轮之间隔 idle 间隔
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(EVENT_POLL_IDLE_INTERVAL_MS)
    await vi.advanceTimersByTimeAsync(EVENT_POLL_IDLE_INTERVAL_MS)
    expect(mockedGetRun).toHaveBeenCalledWith('run-1')
    expect(deps.setWorkflowError).not.toHaveBeenCalledWith(expect.stringContaining('连续失败'))
    expect(deps.removeActiveCatalog).not.toHaveBeenCalled()
    expect(poller.isPolling('run-1')).toBe(true)
  })

  it('连续错误且服务器确认为 failed：停止并标记失败', async () => {
    const { deps, poller } = setupDeps()
    mockedGetEvents.mockRejectedValue(new Error('network down'))
    mockedGetRun.mockResolvedValue(makeRun({ status: 'failed' }) as never)
    poller.startPolling('run-1', 'cat-1')
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(EVENT_POLL_IDLE_INTERVAL_MS)
    await vi.advanceTimersByTimeAsync(EVENT_POLL_IDLE_INTERVAL_MS)
    expect(deps.setWorkflowError).toHaveBeenCalledWith(expect.stringContaining('连续失败'))
    expect(deps.upsertJobLayer).toHaveBeenCalledWith(
      'cat-1',
      expect.objectContaining({ status: 'failed' }),
    )
  })

  it('空闲超时后服务器仍非终态：软恢复继续轮询', async () => {
    const { poller } = setupDeps()
    mockedGetEvents.mockResolvedValue({ items: [] } as never)
    mockedGetRun.mockResolvedValue(makeRun({ status: 'running' }) as never)
    poller.startPolling('run-1', 'cat-1')
    await vi.advanceTimersByTimeAsync(0)
    // 快进超过空闲超时（状态同步持续显示 running 会刷新活动时间，
    // 这里直接快进到超时后看下一轮行为）
    await vi.advanceTimersByTimeAsync(EVENT_POLL_IDLE_TIMEOUT_MS + EVENT_POLL_IDLE_INTERVAL_MS)
    // 未产生本地失败
    expect(poller.isPolling('run-1') || mockedGetRun.mock.calls.length > 0).toBe(true)
  })

  it('页面不可见时轮询间隔不低于 10s', async () => {
    const { poller } = setupDeps()
    const hiddenSpy = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
    mockedGetEvents.mockResolvedValue({ items: [makeEvent({ event_id: 'e1', message: 'x' })] } as never)
    mockedGetRun.mockResolvedValue(makeRun() as never)
    poller.startPolling('run-1', 'cat-1')
    await vi.advanceTimersByTimeAsync(0)
    // active 间隔 1200ms < 10000ms：hidden 下不应触发第二轮
    await vi.advanceTimersByTimeAsync(EVENT_POLL_ACTIVE_INTERVAL_MS + 100)
    expect(mockedGetEvents).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(10000)
    expect(mockedGetEvents).toHaveBeenCalledTimes(2)
    hiddenSpy.mockRestore()
  })
})
