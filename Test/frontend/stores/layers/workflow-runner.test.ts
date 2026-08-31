/**
 * P1-6: workflow-runner.ts 编排逻辑测试
 *
 * 覆盖核心编排路径：
 *  - tracked runs localStorage 持久化（loadTrackedWorkflowRuns / saveTrackedWorkflowRuns）
 *  - rememberTrackedWorkflowRun / forgetTrackedWorkflowRun
 *  - interruptWorkflowForCatalog（中断旧活跃工作流）
 *  - runWorkflowForCatalog（提交 + 429 重试 + 失败处理）
 *  - cancelWorkflowRunForJob（乐观 ID + 真实 run）
 *  - retryWorkflowRunForJob
 *  - scheduleWorkflowRetry（上限 / 计数递增）
 *  - registerExternalWorkflowRun
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createWorkflowRunner,
  loadTrackedWorkflowRuns,
  saveTrackedWorkflowRuns,
  type WorkflowRunnerDeps,
} from '@/stores/layers/workflow-runner'
import type { ActiveLayer, ActiveRunLayerGroup, JobLayerItem } from '@/stores/layers/types'
import type { BoundingBox, LayerDescriptor, WorkflowEvent } from '@/services/runtime-api'

// ── Mock runtime-api ──────────────────────────────────────────────────────────

vi.mock('@/services/runtime-api', () => ({
  submitWorkflow: vi.fn(),
  cancelWorkflowRun: vi.fn(),
  getWorkflowRun: vi.fn(),
  getWorkflowEvents: vi.fn(),
  listActiveWorkflowRuns: vi.fn(),
  listRecentSucceededRuns: vi.fn(),
  retryWorkflowRun: vi.fn(),
  submitOverlayAssetWorkflow: vi.fn(),
}))

vi.mock('@/stores/workflow-output-layers', () => ({
  useWorkflowOutputLayersStore: () => ({
    entries: [],
    getBySourceLayerId: () => [],
    updateRunStatus: vi.fn(),
  }),
}))

vi.mock('@/stores/layers/workspace-sync', () => ({
  suppressWorkspaceSyncPush: vi.fn(),
  scheduleWorkspaceSyncPush: vi.fn(),
}))

// Mock buildJobLayer to avoid needing full WorkflowRun shape
vi.mock('@/stores/layers/result-adapter', () => ({
  buildJobLayer: vi.fn(async (run: Record<string, unknown>, catalogId: string) => ({
    jobId: run.run_id as string,
    catalogId,
    name: 'Test',
    commandType: 'analysis',
    status: (run.status as string) || 'queued',
    progress: 10,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    message: '',
    metrics: [],
  })),
}))

vi.mock('@/utils/job-layer-coverage', () => ({
  buildExpectedCoverageForSubmit: () => ({
    expectedTimeRange: null,
    expectedNativeStep: null,
  }),
}))

vi.mock('@/utils/workflow-submit-reconcile', () => ({
  claimOrphanWorkflowRun: () => null,
  isSubmitTimeoutError: () => false,
}))

vi.mock('@/utils/perf-probe', () => ({
  debugLog: () => {},
}))

import {
  submitWorkflow,
  cancelWorkflowRun,
  getWorkflowRun,
  getWorkflowEvents,
  listActiveWorkflowRuns,
  listRecentSucceededRuns,
  retryWorkflowRun,
  submitOverlayAssetWorkflow,
} from '@/services/runtime-api'

// ── Helpers ───────────────────────────────────────────────────────────────────

function mockBrowserStorage() {
  const store = new Map<string, string>()
  const storage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
  }
  vi.stubGlobal('localStorage', storage)
  vi.stubGlobal('window', {
    localStorage: storage,
    setTimeout: (fn: () => void, ms?: number) => setTimeout(fn, ms),
    clearTimeout: (id: number) => clearTimeout(id),
    crypto: { randomUUID: () => `uuid-${Math.random().toString(36).slice(2)}` },
  })
}

function makeJobLayer(overrides: Partial<JobLayerItem> = {}): JobLayerItem {
  return {
    jobId: 'run-123',
    name: 'Test Workflow',
    commandType: 'analysis',
    status: 'queued',
    progress: 10,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    message: 'queued',
    metrics: [],
    ...overrides,
  }
}

function makeDeps(overrides: Partial<WorkflowRunnerDeps> = {}): WorkflowRunnerDeps {
  const activeLayers: ActiveLayer[] = []
  const jobLayers: JobLayerItem[] = []
  const runLayerGroups: ActiveRunLayerGroup[] = []
  const runtimeLayerCatalog: Record<string, LayerDescriptor> = {}
  const layerLibrary: Array<{ catalogId: string; name: string }> = []

  return {
    // PollerDeps
    startPolling: vi.fn(),
    stopWorkflowPolling: vi.fn(),
    isPolling: vi.fn(() => false),
    syncWorkflowRunSnapshot: vi.fn(async () => true),
    applyWorkflowEventsToJobLayer: vi.fn((layer: JobLayerItem) => layer),

    // StateReaderDeps
    getActiveLayers: () => activeLayers,
    getJobLayers: () => jobLayers,
    getRunLayerGroups: () => runLayerGroups,
    getRuntimeLayerCatalog: () => runtimeLayerCatalog,
    getLayerLibrary: () => layerLibrary as never,
    getMapBBox: (): BoundingBox | null => ({ west: 116, south: 39, east: 117, north: 40 }),
    activeWorkflowCatalogIds: new Set<string>(),
    submittingCatalogIds: new Set<string>(),
    workflowRetryTimers: new Map<string, number>(),
    workflowRetryCounts: new Map<string, number>(),

    // StateWriterDeps
    setRunLayerGroups: (groups: ActiveRunLayerGroup[]) => {
      runLayerGroups.length = 0
      runLayerGroups.push(...groups)
    },
    upsertJobLayer: vi.fn((catalogId: string, jobLayer: JobLayerItem) => {
      const idx = jobLayers.findIndex((j) => j.jobId === jobLayer.jobId)
      if (idx >= 0) jobLayers[idx] = jobLayer
      else jobLayers.push(jobLayer)
    }),
    removeJobLayerById: vi.fn((jobId: string) => {
      const idx = jobLayers.findIndex((j) => j.jobId === jobId)
      if (idx >= 0) jobLayers.splice(idx, 1)
    }),
    setWorkflowError: vi.fn(),
    scheduleWorkspacePersist: vi.fn(),
    flushWorkspacePersistNow: vi.fn(),
    cleanupUnproducedRunLayers: vi.fn(),
    createRunLayerGroup: vi.fn(() => ({
      groupId: 'grp-1',
      memberInstanceIds: [],
      memberCatalogIds: [],
    })),
    bindRunIdToGroup: vi.fn(),
    attachAlgorithmProductOverlays: vi.fn(async () => 0),

    // BusinessDeps
    isLocalSubmitJobId: (jobId: string | null | undefined) =>
      Boolean(jobId?.startsWith('local-submit-')),
    isViewportRefreshStale: vi.fn(() => false),
    isWeatherEngineLayer: vi.fn(() => false),
    resolveBackendLayerId: (catalogId: string) => catalogId,
    ensureRuntimeLayerCatalog: vi.fn(async () => {}),
    getCatalogRunBlockReason: vi.fn(() => null),
    supportsAnalysisWorkflow: vi.fn(() => true),
    isOverlayDisplayOnlyLayer: vi.fn(() => false),
    supportsMapLayerResult: vi.fn(() => false),
    buildWorkflowPayloadForCatalog: vi.fn(() => ({})),
    activateWeatherTileViewport: vi.fn(),

    // SnapshotDeps
    hydrateWorkspaceFromSnapshot: () => new Map<string, string>(),
    hydrateVectorLayersFromSnapshot: vi.fn(async () => {}),
    reconcileOmegaBlockLayers: vi.fn(),

    ...overrides,
  } as WorkflowRunnerDeps
}

// ── Tests ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  mockBrowserStorage()
  // Default: all API mocks return resolved Promises so fire-and-forget .catch() works
  vi.mocked(cancelWorkflowRun).mockResolvedValue({ run_id: '', status: 'cancelled' } as never)
  vi.mocked(submitWorkflow).mockResolvedValue({ run_id: '', created_at: '', message: '' } as never)
  vi.mocked(getWorkflowRun).mockResolvedValue({ run_id: '', status: 'queued' } as never)
  vi.mocked(getWorkflowEvents).mockResolvedValue({ items: [] } as never)
  vi.mocked(listActiveWorkflowRuns).mockResolvedValue([] as never)
  vi.mocked(listRecentSucceededRuns).mockResolvedValue([] as never)
  vi.mocked(retryWorkflowRun).mockResolvedValue({ run_id: '', created_at: '', message: '' } as never)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('loadTrackedWorkflowRuns / saveTrackedWorkflowRuns', () => {
  it('returns empty array when localStorage is empty', () => {
    expect(loadTrackedWorkflowRuns()).toEqual([])
  })

  it('round-trips through localStorage', () => {
    const runs = [
      { runId: 'r1', catalogId: 'c1', updatedAt: '2026-01-01T00:00:00Z' },
      { runId: 'r2', catalogId: 'c2', updatedAt: '2026-01-02T00:00:00Z' },
    ]
    saveTrackedWorkflowRuns(runs)
    const loaded = loadTrackedWorkflowRuns()
    expect(loaded).toHaveLength(2)
    expect(loaded[0].runId).toBe('r1')
    expect(loaded[1].runId).toBe('r2')
  })

  it('keeps at most 40 entries', () => {
    const runs = Array.from({ length: 50 }, (_, i) => ({
      runId: `r${i}`,
      catalogId: `c${i}`,
      updatedAt: `2026-01-0${i % 9}T00:00:00Z`,
    }))
    saveTrackedWorkflowRuns(runs)
    expect(loadTrackedWorkflowRuns()).toHaveLength(40)
  })

  it('filters malformed entries', () => {
    localStorage.setItem(
      'geo:tracked-workflow-runs:v1',
      JSON.stringify([{ runId: 'r1' }, { catalogId: 'c1' }, 'garbage']),
    )
    const loaded = loadTrackedWorkflowRuns()
    expect(loaded).toEqual([])
  })
})

describe('rememberTrackedWorkflowRun', () => {
  it('skips optimistic local submit IDs', () => {
    const deps = makeDeps()
    const runner = createWorkflowRunner(deps)
    runner.rememberTrackedWorkflowRun('cat-1', makeJobLayer({ jobId: 'local-submit-cat-1' }))
    expect(loadTrackedWorkflowRuns()).toHaveLength(0)
  })

  it('forgets cancelled runs from tracking', () => {
    const deps = makeDeps()
    const runner = createWorkflowRunner(deps)
    runner.rememberTrackedWorkflowRun('cat-1', makeJobLayer({ jobId: 'run-1', status: 'cancelled' }))
    expect(loadTrackedWorkflowRuns()).toHaveLength(0)
  })

  it('forgets succeeded runs so only in-flight runs survive refresh', () => {
    const deps = makeDeps()
    const runner = createWorkflowRunner(deps)
    runner.rememberTrackedWorkflowRun('cat-1', makeJobLayer({ jobId: 'run-1', status: 'running' }))
    expect(loadTrackedWorkflowRuns()).toHaveLength(1)
    runner.rememberTrackedWorkflowRun('cat-1', makeJobLayer({ jobId: 'run-1', status: 'succeeded' }))
    expect(loadTrackedWorkflowRuns()).toHaveLength(0)
  })

  it('adds a real run to the tracking list', () => {
    const deps = makeDeps()
    const runner = createWorkflowRunner(deps)
    runner.rememberTrackedWorkflowRun('cat-1', makeJobLayer({ jobId: 'run-100', status: 'running' }))
    const loaded = loadTrackedWorkflowRuns()
    expect(loaded).toHaveLength(1)
    expect(loaded[0].runId).toBe('run-100')
    expect(loaded[0].catalogId).toBe('cat-1')
  })

  it('replaces an existing run instead of duplicating', () => {
    const deps = makeDeps()
    const runner = createWorkflowRunner(deps)
    runner.rememberTrackedWorkflowRun('cat-1', makeJobLayer({ jobId: 'run-1', status: 'running' }))
    runner.rememberTrackedWorkflowRun('cat-1', makeJobLayer({ jobId: 'run-1', status: 'queued' }))
    const loaded = loadTrackedWorkflowRuns()
    expect(loaded).toHaveLength(1)
    expect(loaded[0].runId).toBe('run-1')
  })
})

describe('forgetTrackedWorkflowRun', () => {
  it('removes a run from tracking', () => {
    const deps = makeDeps()
    const runner = createWorkflowRunner(deps)
    runner.rememberTrackedWorkflowRun('cat-1', makeJobLayer({ jobId: 'run-x' }))
    expect(loadTrackedWorkflowRuns()).toHaveLength(1)
    runner.forgetTrackedWorkflowRun('run-x')
    expect(loadTrackedWorkflowRuns()).toHaveLength(0)
  })
})

describe('interruptWorkflowForCatalog', () => {
  it('clears retry timer and cancels active job', () => {
    const deps = makeDeps()
    const timerId = 999
    deps.workflowRetryTimers.set('cat-1', timerId)
    // Place an active job layer linked to cat-1
    const activeLayer: ActiveLayer = {
      instanceId: 'inst-1',
      catalogId: 'cat-1',
      visible: true,
      opacity: 1,
      order: 0,
      isAdminBoundary: false,
      dataState: 'catalog',
      jobLayer: makeJobLayer({ jobId: 'run-active', status: 'running' }),
    } as ActiveLayer
    deps.getActiveLayers().push(activeLayer)
    deps.getJobLayers().push(makeJobLayer({ jobId: 'run-active', status: 'running' }))

    const runner = createWorkflowRunner(deps)
    runner.interruptWorkflowForCatalog('cat-1')

    expect(deps.workflowRetryTimers.has('cat-1')).toBe(false)
    expect(deps.stopWorkflowPolling).toHaveBeenCalledWith('run-active')
    expect(deps.activeWorkflowCatalogIds.has('cat-1')).toBe(false)
    expect(cancelWorkflowRun).toHaveBeenCalledWith('run-active')
  })

  it('does nothing when no active job exists', () => {
    const deps = makeDeps()
    const runner = createWorkflowRunner(deps)
    runner.interruptWorkflowForCatalog('cat-nojob')
    expect(deps.stopWorkflowPolling).not.toHaveBeenCalled()
    expect(cancelWorkflowRun).not.toHaveBeenCalled()
  })
})

describe('runWorkflowForCatalog', () => {
  it('throws if catalog is already submitting', async () => {
    const deps = makeDeps()
    deps.submittingCatalogIds.add('cat-1')
    const runner = createWorkflowRunner(deps)
    await expect(runner.runWorkflowForCatalog('cat-1')).rejects.toThrow('正在提交中')
  })

  it('submits workflow and starts polling on success', async () => {
    const deps = makeDeps()
    vi.mocked(submitWorkflow).mockResolvedValue({
      run_id: 'run-new',
      created_at: '2026-01-01T00:00:00Z',
      message: 'accepted',
    } as never)

    const runner = createWorkflowRunner(deps)
    const runId = await runner.runWorkflowForCatalog('cat-1')

    expect(runId).toBe('run-new')
    expect(submitWorkflow).toHaveBeenCalledOnce()
    expect(deps.upsertJobLayer).toHaveBeenCalled()
    expect(deps.startPolling).toHaveBeenCalledWith('run-new', 'cat-1', undefined)
    expect(deps.activeWorkflowCatalogIds.has('cat-1')).toBe(true)
    expect(deps.submittingCatalogIds.has('cat-1')).toBe(false)
  })

  it('creates failed jobLayer on validation error', async () => {
    const deps = makeDeps()
    vi.mocked(submitWorkflow).mockRejectedValue(new Error('invalid params') as never)

    const runner = createWorkflowRunner(deps)
    await expect(runner.runWorkflowForCatalog('cat-1')).rejects.toThrow('invalid params')

    expect(deps.setWorkflowError).toHaveBeenCalled()
    const upsertCalls = vi.mocked(deps.upsertJobLayer).mock.calls
    const failedCall = upsertCalls.find(
      ([, layer]) => (layer as JobLayerItem).status === 'failed',
    )
    expect(failedCall).toBeTruthy()
    expect(deps.submittingCatalogIds.has('cat-1')).toBe(false)
  })

  it('schedules retry on 429 capacity error', async () => {
    const deps = makeDeps()
    vi.mocked(submitWorkflow).mockRejectedValue(new Error('429 Too Many Requests') as never)

    const runner = createWorkflowRunner(deps)
    await expect(runner.runWorkflowForCatalog('cat-1')).rejects.toThrow('429')

    expect(deps.workflowRetryCounts.get('cat-1')).toBe(1)
    // A timer should be set
    expect(deps.workflowRetryTimers.has('cat-1')).toBe(true)
    // Clean up timer
    const timer = deps.workflowRetryTimers.get('cat-1')
    if (timer !== undefined) clearTimeout(timer)
  })

  // 2026-08-25 回归修复：overlay_registry 静态图层（ERA5 热浪/柯本/土壤容重等）
  // 曾因 supportsAnalysisWorkflow 反转落入通用 analysis 提交 → 后端 no_bridge 误报失败。
  // 锁定：overlay 图层必须走 /overlay-asset-workflows 资产检查，不走通用提交。
  it('overlay_display_only layers submit asset workflow, not generic analysis', async () => {
    const deps = makeDeps({
      isOverlayDisplayOnlyLayer: vi.fn(() => true),
      supportsAnalysisWorkflow: vi.fn(() => true),
    })
    vi.mocked(submitOverlayAssetWorkflow).mockResolvedValue({
      run_id: 'run-asset-1',
      status: 'succeeded',
      message: '图层资产已就绪。',
      created_at: '2026-01-01T00:00:00Z',
    } as never)

    const runner = createWorkflowRunner(deps)
    const runId = await runner.runWorkflowForCatalog('cat-1')

    expect(runId).toBe('run-asset-1')
    expect(submitOverlayAssetWorkflow).toHaveBeenCalledOnce()
    expect(submitOverlayAssetWorkflow).toHaveBeenCalledWith('cat-1')
    // 关键回归锁：通用 analysis 提交路径不得被触发
    expect(submitWorkflow).not.toHaveBeenCalled()
  })

  it('non-overlay layers still submit generic analysis workflow', async () => {
    const deps = makeDeps({
      isOverlayDisplayOnlyLayer: vi.fn(() => false),
      supportsAnalysisWorkflow: vi.fn(() => true),
    })
    vi.mocked(submitWorkflow).mockResolvedValue({
      run_id: 'run-analysis-1',
      created_at: '2026-01-01T00:00:00Z',
      message: 'accepted',
    } as never)

    const runner = createWorkflowRunner(deps)
    await runner.runWorkflowForCatalog('cat-1')

    expect(submitWorkflow).toHaveBeenCalledOnce()
    expect(submitOverlayAssetWorkflow).not.toHaveBeenCalled()
  })
})

describe('workflow variant preference (X2 online/local 反演切换)', () => {
  const VARIANT_CATALOG_ID = 'method-fy-omega-doy-dynamic'
  const VARIANT_DESCRIPTOR = {
    layer_id: VARIANT_CATALOG_ID,
    display_name: 'FY 动态 ω 反演',
    workflow_id: 'omega_sf_fenkuai_fy_online',
    workflow_variants: {
      online: { workflow_id: 'omega_sf_fenkuai_fy_online', label: '在线反演' },
      local: { workflow_id: 'omega_sf_fenkuai_fy_single', label: '本地反演' },
    },
  } as unknown as LayerDescriptor

  function makeVariantDeps(overrides: Partial<WorkflowRunnerDeps> = {}) {
    return makeDeps({
      getRuntimeLayerCatalog: () => ({ [VARIANT_CATALOG_ID]: VARIANT_DESCRIPTOR }),
      ...overrides,
    })
  }

  it('sets / gets / clears preference per catalog', () => {
    const runner = createWorkflowRunner(makeVariantDeps())
    expect(runner.getWorkflowVariantPreference(VARIANT_CATALOG_ID)).toBeUndefined()
    runner.setWorkflowVariantPreference(VARIANT_CATALOG_ID, 'local')
    expect(runner.getWorkflowVariantPreference(VARIANT_CATALOG_ID)).toBe('local')
    runner.setWorkflowVariantPreference(VARIANT_CATALOG_ID, null)
    expect(runner.getWorkflowVariantPreference(VARIANT_CATALOG_ID)).toBeUndefined()
  })

  it('injects preferred variant seed when no explicit workflowVariant option', async () => {
    const deps = makeVariantDeps()
    vi.mocked(submitWorkflow).mockResolvedValue({
      run_id: 'run-variant',
      created_at: '2026-01-01T00:00:00Z',
      message: 'accepted',
    } as never)

    const runner = createWorkflowRunner(deps)
    runner.setWorkflowVariantPreference(VARIANT_CATALOG_ID, 'local')
    await runner.runWorkflowForCatalog(VARIANT_CATALOG_ID)

    const buildCall = vi.mocked(deps.buildWorkflowPayloadForCatalog).mock.calls[0]
    expect(buildCall?.[5]).toMatchObject({
      workflow_entry_name: 'omega_sf_fenkuai_fy_single',
    })
  })

  it('explicit workflowVariant option overrides stored preference', async () => {
    const deps = makeVariantDeps()
    vi.mocked(submitWorkflow).mockResolvedValue({
      run_id: 'run-variant',
      created_at: '2026-01-01T00:00:00Z',
      message: 'accepted',
    } as never)

    const runner = createWorkflowRunner(deps)
    runner.setWorkflowVariantPreference(VARIANT_CATALOG_ID, 'local')
    await runner.runWorkflowForCatalog(VARIANT_CATALOG_ID, { workflowVariant: 'online' })

    const buildCall = vi.mocked(deps.buildWorkflowPayloadForCatalog).mock.calls[0]
    expect(buildCall?.[5]).toMatchObject({
      workflow_entry_name: 'omega_sf_fenkuai_fy_online',
    })
  })

  it('no preference → descriptor default path (no variant injection)', async () => {
    const deps = makeVariantDeps()
    vi.mocked(submitWorkflow).mockResolvedValue({
      run_id: 'run-default',
      created_at: '2026-01-01T00:00:00Z',
      message: 'accepted',
    } as never)

    const runner = createWorkflowRunner(deps)
    await runner.runWorkflowForCatalog(VARIANT_CATALOG_ID)

    const buildCall = vi.mocked(deps.buildWorkflowPayloadForCatalog).mock.calls[0]
    expect(buildCall?.[5]).toBeUndefined()
  })
})

describe('scheduleWorkflowRetry', () => {
  it('stops retrying after MAX_WORKFLOW_429_RETRIES (6)', async () => {
    const deps = makeDeps()
    // Pre-set retry count to the limit
    deps.workflowRetryCounts.set('cat-1', 6)

    const runner = createWorkflowRunner(deps)
    runner.scheduleWorkflowRetry('cat-1')

    // Should have created a failed jobLayer, not scheduled a timer
    expect(deps.workflowRetryTimers.has('cat-1')).toBe(false)
    const upsertCalls = vi.mocked(deps.upsertJobLayer).mock.calls
    const failedCall = upsertCalls.find(
      ([, layer]) => (layer as JobLayerItem).status === 'failed',
    )
    expect(failedCall).toBeTruthy()
  })

  it('increments retry count and sets a timer', () => {
    const deps = makeDeps()
    deps.workflowRetryCounts.set('cat-1', 2)

    const runner = createWorkflowRunner(deps)
    runner.scheduleWorkflowRetry('cat-1')

    expect(deps.workflowRetryCounts.get('cat-1')).toBe(3)
    expect(deps.workflowRetryTimers.has('cat-1')).toBe(true)

    // Cleanup
    const timer = deps.workflowRetryTimers.get('cat-1')
    if (timer !== undefined) clearTimeout(timer)
  })
})

describe('cancelWorkflowRunForJob', () => {
  it('handles optimistic local-submit ID without API call', async () => {
    const deps = makeDeps()
    deps.getJobLayers().push(
      makeJobLayer({ jobId: 'local-submit-cat-1', catalogId: 'cat-1', status: 'queued' }),
    )

    const runner = createWorkflowRunner(deps)
    await runner.cancelWorkflowRunForJob('local-submit-cat-1', 'cat-1')

    expect(cancelWorkflowRun).not.toHaveBeenCalled()
    expect(deps.removeJobLayerById).toHaveBeenCalledWith('local-submit-cat-1')
    expect(deps.scheduleWorkspacePersist).toHaveBeenCalled()
  })

  it('cancels real run via API and stops polling', async () => {
    const deps = makeDeps()
    vi.mocked(cancelWorkflowRun).mockResolvedValue({
      run_id: 'run-real',
      status: 'cancelled',
    } as never)

    const runner = createWorkflowRunner(deps)
    await runner.cancelWorkflowRunForJob('run-real', 'cat-1')

    expect(cancelWorkflowRun).toHaveBeenCalledWith('run-real')
    expect(deps.stopWorkflowPolling).toHaveBeenCalledWith('run-real')
    expect(deps.activeWorkflowCatalogIds.has('cat-1')).toBe(false)
    expect(deps.cleanupUnproducedRunLayers).toHaveBeenCalledWith('run-real')
  })

  it('sets error message on cancellation failure', async () => {
    const deps = makeDeps()
    vi.mocked(cancelWorkflowRun).mockRejectedValue(new Error('network error') as never)

    const runner = createWorkflowRunner(deps)
    await runner.cancelWorkflowRunForJob('run-fail', 'cat-1')

    expect(deps.setWorkflowError).toHaveBeenCalledWith('network error')
  })
})

describe('retryWorkflowRunForJob', () => {
  it('re-submits for optimistic local-submit ID', async () => {
    const deps = makeDeps()
    vi.mocked(submitWorkflow).mockResolvedValue({
      run_id: 'run-new',
      created_at: '2026-01-01T00:00:00Z',
      message: 'accepted',
    } as never)

    const runner = createWorkflowRunner(deps)
    const runId = await runner.retryWorkflowRunForJob('local-submit-cat-1', 'cat-1')

    expect(runId).toBe('run-new')
    expect(submitWorkflow).toHaveBeenCalledOnce()
  })

  it('skips if catalog is already submitting', async () => {
    const deps = makeDeps()
    deps.submittingCatalogIds.add('cat-1')
    const runner = createWorkflowRunner(deps)
    const result = await runner.retryWorkflowRunForJob('run-1', 'cat-1')
    expect(result).toBeUndefined()
    expect(retryWorkflowRun).not.toHaveBeenCalled()
  })

  it('retries via API and starts polling', async () => {
    const deps = makeDeps()
    vi.mocked(retryWorkflowRun).mockResolvedValue({
      run_id: 'run-retried',
      created_at: '2026-01-01T00:00:00Z',
      message: 'retried',
    } as never)

    const runner = createWorkflowRunner(deps)
    const runId = await runner.retryWorkflowRunForJob('run-orig', 'cat-1')

    expect(runId).toBe('run-retried')
    expect(retryWorkflowRun).toHaveBeenCalledWith('run-orig')
    expect(deps.startPolling).toHaveBeenCalledWith('run-retried', 'cat-1')
    expect(deps.activeWorkflowCatalogIds.has('cat-1')).toBe(true)
  })

  it('sets error on retry failure', async () => {
    const deps = makeDeps()
    vi.mocked(retryWorkflowRun).mockRejectedValue(new Error('retry failed') as never)

    const runner = createWorkflowRunner(deps)
    await expect(runner.retryWorkflowRunForJob('run-orig', 'cat-1')).rejects.toThrow('retry failed')
    expect(deps.setWorkflowError).toHaveBeenCalledWith('retry failed')
  })
})

describe('registerExternalWorkflowRun', () => {
  it('skips if already polling', async () => {
    const deps = makeDeps()
    deps.isPolling = vi.fn(() => true)
    const runner = createWorkflowRunner(deps)
    await runner.registerExternalWorkflowRun('run-ext')
    expect(getWorkflowRun).not.toHaveBeenCalled()
  })

  it('skips if existing non-terminal job layer found', async () => {
    const deps = makeDeps()
    deps.getJobLayers().push(makeJobLayer({ jobId: 'run-ext', status: 'running' }))
    const runner = createWorkflowRunner(deps)
    await runner.registerExternalWorkflowRun('run-ext')
    expect(getWorkflowRun).not.toHaveBeenCalled()
  })

  it('registers and starts polling for a new run', async () => {
    const deps = makeDeps()
    vi.mocked(getWorkflowRun).mockResolvedValue({
      run_id: 'run-ext',
      status: 'running',
      layer_id: 'cat-ext',
    } as never)

    const runner = createWorkflowRunner(deps)
    await runner.registerExternalWorkflowRun('run-ext', 'cat-ext')

    expect(getWorkflowRun).toHaveBeenCalledWith('run-ext')
    expect(deps.upsertJobLayer).toHaveBeenCalled()
    expect(deps.activeWorkflowCatalogIds.has('cat-ext')).toBe(true)
    expect(deps.startPolling).toHaveBeenCalledWith('run-ext', 'cat-ext')
  })

  it('catches errors without throwing', async () => {
    const deps = makeDeps()
    vi.mocked(getWorkflowRun).mockRejectedValue(new Error('404') as never)
    const runner = createWorkflowRunner(deps)
    // Should not throw
    await expect(runner.registerExternalWorkflowRun('run-missing')).resolves.toBeUndefined()
  })
})

describe('restoreActiveWorkflows / ensureRestoredRunGroup（F2 manifest 成员）', () => {
  function setupRestore(
    workflowDefinition: Record<string, unknown> | null,
  ) {
    const deps = makeDeps()
    const catalog = deps.getRuntimeLayerCatalog()
    catalog['layer-fy'] = {
      layer_id: 'layer-fy',
      dataset_key: 'ds-fy',
      display_name: '反演图层',
      description: '',
      category: 'analysis',
      source_type: 'imported' as never,
      render_type: 'raster' as never,
      supported_map_modes: ['2d'] as never,
      extent: { west: 116, south: 39, east: 117, north: 40 },
      workflow_id: 'wf-fy',
      workflow_definition: workflowDefinition,
    } as LayerDescriptor

    vi.mocked(listActiveWorkflowRuns).mockResolvedValue(
      [{ run_id: 'run-f2', layer_id: 'layer-fy', command_label: '反演', status: 'running' }] as never,
    )
    vi.mocked(getWorkflowRun).mockResolvedValue({
      run_id: 'run-f2',
      layer_id: 'layer-fy',
      command_label: '反演',
      status: 'running',
      result_refs: [],
    } as never)
    vi.mocked(getWorkflowEvents).mockResolvedValue({ items: [] } as never)

    // 真实写回：创建组 + 占位成员（对齐 run-layers.ts createRunLayerGroup 行为）
    deps.createRunLayerGroup = (options: {
      title: string
      targets: Array<{ name: string; productTag: string }>
      memberCatalogIds?: string[]
    }) => {
      const groups = deps.getRunLayerGroups()
      const activeLayers = deps.getActiveLayers()
      const groupId = `grp-restore-${groups.length + 1}`
      const memberInstanceIds: string[] = []
      options.targets.forEach((t, i) => {
        const catalogId =
          options.memberCatalogIds?.[i] || `wf-run-${groupId}-${String(t.productTag).toLowerCase()}`
        const layer: ActiveLayer = {
          instanceId: `inst-${groupId}-${i}`,
          catalogId,
          name: t.name,
          visible: true,
          opacity: 1,
          order: activeLayers.length,
          isAdminBoundary: false,
          dataState: 'catalog',
          runGroupId: groupId,
          runGroupProductTag: t.productTag,
          runGroupLocked: true,
        }
        activeLayers.push(layer)
        memberInstanceIds.push(layer.instanceId)
      })
      groups.push({
        groupId,
        runId: '',
        title: options.title,
        status: 'computing',
        memberInstanceIds,
        dissolvable: false,
      } as ActiveRunLayerGroup)
      return { groupId, memberInstanceIds, memberCatalogIds: [] }
    }
    deps.bindRunIdToGroup = (groupId: string, runId: string) => {
      const g = deps.getRunLayerGroups().find((x) => x.groupId === groupId)
      if (g) g.runId = runId
    }
    return deps
  }

  it('manifest extra.outputs 优先：占位成员按 manifest 标签生成', async () => {
    const deps = setupRestore({ extra: { outputs: ['SM', 'LST'] }, nodes: [] })
    const runner = createWorkflowRunner(deps)
    await runner.restoreActiveWorkflows()

    const groups = deps.getRunLayerGroups()
    const group = groups.find((g) => g.runId === 'run-f2')
    expect(group).toBeDefined()
    expect(group!.status).toBe('computing')

    const memberTags = group!.memberInstanceIds
      .map((id) => deps.getActiveLayers().find((l) => l.instanceId === id)?.runGroupProductTag)
      .filter(Boolean)
    expect(memberTags.sort()).toEqual(['LST', 'SM'])
  })

  it('无 extra.outputs 时回退 nodes main_layers', async () => {
    const deps = setupRestore({
      nodes: [{ properties: { main_layers: ['NDVI'] } }],
    })
    const runner = createWorkflowRunner(deps)
    await runner.restoreActiveWorkflows()

    const group = deps.getRunLayerGroups().find((g) => g.runId === 'run-f2')
    expect(group).toBeDefined()
    const memberTags = group!.memberInstanceIds
      .map((id) => deps.getActiveLayers().find((l) => l.instanceId === id)?.runGroupProductTag)
      .filter(Boolean)
    expect(memberTags).toEqual(['NDVI'])
  })

  it('无 manifest 时回退单产出 result（LEGACY 三件套已退役 2026-08-24）', async () => {
    const deps = setupRestore(null)
    const runner = createWorkflowRunner(deps)
    await runner.restoreActiveWorkflows()

    const group = deps.getRunLayerGroups().find((g) => g.runId === 'run-f2')
    expect(group).toBeDefined()
    const memberTags = group!.memberInstanceIds
      .map((id) => deps.getActiveLayers().find((l) => l.instanceId === id)?.runGroupProductTag)
      .filter(Boolean)
    // 退役决策：旧 run 快照不再回退 SM/VOD/OMEGA 三占位——
    // 61 种子全带 extra 中文配置，无 manifest 一律单产出 'result' 语义
    expect(memberTags.sort()).toEqual(['result'])
  })

  it('同工作流已有成功产物时仍恢复未跟踪的 running run 到指示器', async () => {
    const deps = makeDeps()
    const catalog = deps.getRuntimeLayerCatalog()
    catalog['method-omega-fy'] = {
      layer_id: 'method-omega-fy',
      dataset_key: 'ds',
      display_name: '风云ω',
      description: '',
      category: 'analysis',
      source_type: 'imported' as never,
      render_type: 'raster' as never,
      supported_map_modes: ['2d'] as never,
      extent: { west: 116, south: 39, east: 117, north: 40 },
      workflow_id: 'wf-fy',
      workflow_definition: null,
    } as LayerDescriptor

    vi.mocked(listRecentSucceededRuns).mockResolvedValue([
      {
        run_id: 'run-old-ok',
        layer_id: 'omega_sf_fenkuai_fy',
        command_label: '反演',
        status: 'succeeded',
        result_refs: [],
      },
    ] as never)
    vi.mocked(listActiveWorkflowRuns).mockResolvedValue([
      {
        run_id: 'run-new-active',
        layer_id: 'omega_sf_fenkuai_fy',
        command_label: '反演',
        status: 'running',
      },
    ] as never)
    vi.mocked(getWorkflowRun).mockImplementation(async (runId: string) => {
      if (runId === 'run-new-active') {
        return {
          run_id: 'run-new-active',
          layer_id: 'omega_sf_fenkuai_fy',
          command_label: '反演',
          status: 'running',
          result_refs: [],
        } as never
      }
      return {
        run_id: runId,
        layer_id: 'omega_sf_fenkuai_fy',
        command_label: '反演',
        status: 'succeeded',
        result_refs: [],
      } as never
    })
    vi.mocked(getWorkflowEvents).mockResolvedValue({ items: [] } as never)

    const runner = createWorkflowRunner(deps)
    await runner.restoreActiveWorkflows()

    const jobs = deps.getJobLayers()
    expect(jobs.some((j) => j.jobId === 'run-new-active' && j.status === 'running')).toBe(true)
    expect(deps.startPolling).toHaveBeenCalledWith('run-new-active', expect.any(String))
  })
})
