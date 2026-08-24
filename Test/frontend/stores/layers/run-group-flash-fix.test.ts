/**
 * 症状一回归：静态图层闪现 + 越权反演图层组（2026-08-23）
 *
 * 三处修复的四条锁定测试：
 *  ① workflow-runner 提交路径禁用 LEGACY_RESTORE_TAGS（SM/VOD/OMEGA）：
 *    提交即建组时无 manifest 的 run 恒为单产出 'result' 语义，
 *    不再闪现 3 个实验室旧 seed 占位成员。
 *  ② autoAttachProductsForNewLayer 仅当 supportsMapLayerResult 才执行：
 *    纯静态/展示型图层（干旱指数 AI 等）添加时不去 attach 反演产物。
 *  ③ reconcileOmegaBlockLayers 孤儿合并保护用户静态层：
 *    无 run 组归属的 OMEGA_BLOCK（用户手动导入）不被吞并/改名；
 *    有归属的工作流产物仍正常并入组内占位。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createWorkflowRunner,
  type WorkflowRunnerDeps,
} from '@/stores/layers/workflow-runner'
import { createRunLayersSlice } from '@/stores/layers/run-layers'
import type { ActiveLayer, ActiveRunLayerGroup, JobLayerItem } from '@/stores/layers/types'
import type { BoundingBox, LayerDescriptor } from '@/services/runtime-api'

// ── Mock runtime-api（与 workflow-runner.test.ts 同套约定）──────────────────

vi.mock('@/services/runtime-api', () => ({
  submitWorkflow: vi.fn(),
  cancelWorkflowRun: vi.fn(),
  getWorkflowRun: vi.fn(),
  getWorkflowEvents: vi.fn(),
  listActiveWorkflowRuns: vi.fn(),
  listRecentSucceededRuns: vi.fn(),
  retryWorkflowRun: vi.fn(),
}))

vi.mock('@/stores/workflow-output-layers', () => ({
  useWorkflowOutputLayersStore: () => ({
    entries: [],
    getBySourceLayerId: () => [],
    updateRunStatus: vi.fn(),
  }),
}))

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
  extractOverlayImportsFromResultRefs: vi.fn(() => []),
  normalizeProductTag: (v: string) => v.trim().toUpperCase(),
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

import { listRecentSucceededRuns, submitWorkflow } from '@/services/runtime-api'

// ── Helpers ──────────────────────────────────────────────────────────────────

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

function makeDeps(overrides: Partial<WorkflowRunnerDeps> = {}): WorkflowRunnerDeps {
  const activeLayers: ActiveLayer[] = []
  const jobLayers: JobLayerItem[] = []
  const runLayerGroups: ActiveRunLayerGroup[] = []
  const runtimeLayerCatalog: Record<string, LayerDescriptor> = {}
  const layerLibrary: Array<{ catalogId: string; name: string }> = []

  return {
    startPolling: vi.fn(),
    stopWorkflowPolling: vi.fn(),
    isPolling: vi.fn(() => false),
    syncWorkflowRunSnapshot: vi.fn(async () => true),
    applyWorkflowEventsToJobLayer: vi.fn((layer: JobLayerItem) => layer),

    getActiveLayers: () => activeLayers,
    getJobLayers: () => jobLayers,
    getRunLayerGroups: () => runLayerGroups,
    getRuntimeLayerCatalog: () => runtimeLayerCatalog,
    getLayerLibrary: () => layerLibrary as never,
    getMapBBox: (): BoundingBox | null => ({ west: 116, south: 39, east: 117, north: 40 }),
    activeWorkflowCatalogIds: new Set<string>(),
    submittingCatalogIds: new Set<string>(),
    workflowRetryTimers: new Map<string, number>(),
    workflowRetryCounts: new Map<string, string | number>(),

    setRunLayerGroups: (groups: ActiveRunLayerGroup[]) => {
      runLayerGroups.length = 0
      runLayerGroups.push(...groups)
    },
    upsertJobLayer: vi.fn(),
    removeJobLayerById: vi.fn(),
    setWorkflowError: vi.fn(),
    scheduleWorkspacePersist: vi.fn(),
    cleanupUnproducedRunLayers: vi.fn(),
    // 提交路径建组走这里：测试捕获 targets 断言产品标签
    createRunLayerGroup: vi.fn(
      (options: {
        title: string
        targets: Array<{ name: string; productTag: string }>
        memberCatalogIds?: string[]
      }) => {
        const groupId = `grp-submit-${runLayerGroups.length + 1}`
        const memberInstanceIds: string[] = []
        options.targets.forEach((t, i) => {
          const catalogId =
            options.memberCatalogIds?.[i] || `wf-run-${groupId}-${t.productTag.toLowerCase()}`
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
        runLayerGroups.push({
          groupId,
          runId: '',
          title: options.title,
          status: 'computing',
          memberInstanceIds,
          dissolvable: false,
        } as ActiveRunLayerGroup)
        return { groupId, memberInstanceIds, memberCatalogIds: [] }
      },
    ),
    bindRunIdToGroup: vi.fn((groupId: string, runId: string) => {
      const g = runLayerGroups.find((x) => x.groupId === groupId)
      if (g) g.runId = runId
    }),
    attachAlgorithmProductOverlays: vi.fn(async () => 0),

    isLocalSubmitJobId: (jobId: string | null | undefined) =>
      Boolean(jobId?.startsWith('local-submit-')),
    isViewportRefreshStale: vi.fn(() => false),
    isWeatherEngineLayer: vi.fn(() => false),
    resolveBackendLayerId: (catalogId: string) => catalogId,
    ensureRuntimeLayerCatalog: vi.fn(async () => {}),
    getCatalogRunBlockReason: vi.fn(() => null),
    supportsAnalysisWorkflow: vi.fn(() => true),
    isOverlayDisplayOnlyLayer: vi.fn(() => false),
    supportsMapLayerResult: vi.fn(() => true),
    buildWorkflowPayloadForCatalog: vi.fn(() => ({})),
    activateWeatherTileViewport: vi.fn(),

    hydrateWorkspaceFromSnapshot: () => new Map<string, string>(),
    hydrateVectorLayersFromSnapshot: vi.fn(async () => {}),
    reconcileOmegaBlockLayers: vi.fn(),

    ...overrides,
  } as WorkflowRunnerDeps
}

beforeEach(() => {
  vi.clearAllMocks()
  mockBrowserStorage()
  vi.mocked(submitWorkflow).mockResolvedValue({
    run_id: 'run-sub',
    created_at: '2026-01-01T00:00:00Z',
    message: 'accepted',
  } as never)
  vi.mocked(listRecentSucceededRuns).mockResolvedValue([] as never)
})

afterEach(() => {
  vi.restoreAllMocks()
})

// ── ① 提交路径禁用 LEGACY_RESTORE_TAGS ─────────────────────────────────────

describe('提交路径 ensureRestoredRunGroup（source=submit）', () => {
  it('无 manifest/元数据的 run 提交即建组 → 单产出 result，不落 SM/VOD/OMEGA', async () => {
    const deps = makeDeps()
    const runner = createWorkflowRunner(deps)
    await runner.runWorkflowForCatalog('cat-static')

    // 提交成功 → ensureRestoredRunGroup(source:'submit') → createRunLayerGroup
    expect(deps.createRunLayerGroup).toHaveBeenCalledOnce()
    const targets = vi.mocked(deps.createRunLayerGroup).mock.calls[0]![0].targets
    const tags = targets.map((t) => t.productTag)
    expect(tags).toEqual(['result'])
    // 组内只物化 1 个占位成员（旧 bug：SM/VOD/OMEGA 3 个闪现）
    const groups = deps.getRunLayerGroups()
    expect(groups).toHaveLength(1)
    expect(groups[0]!.memberInstanceIds).toHaveLength(1)
    const member = deps
      .getActiveLayers()
      .find((l) => l.instanceId === groups[0]!.memberInstanceIds[0])
    expect(member?.runGroupProductTag).toBe('result')
  })

  it('有 extra.outputs manifest 时提交路径仍按 manifest 标签建组', async () => {
    const deps = makeDeps()
    const catalog = deps.getRuntimeLayerCatalog()
    catalog['cat-seed'] = {
      layer_id: 'cat-seed',
      dataset_key: 'ds-seed',
      display_name: '种子流水线',
      description: '',
      category: 'analysis',
      source_type: 'imported' as never,
      render_type: 'raster' as never,
      supported_map_modes: ['2d'] as never,
      extent: { west: 116, south: 39, east: 117, north: 40 },
      workflow_id: 'wf-seed',
      workflow_definition: { extra: { outputs: ['SM', 'LST'] }, nodes: [] },
    } as LayerDescriptor

    const runner = createWorkflowRunner(deps)
    await runner.runWorkflowForCatalog('cat-seed')

    const targets = vi.mocked(deps.createRunLayerGroup).mock.calls[0]![0].targets
    expect(targets.map((t) => t.productTag).sort()).toEqual(['LST', 'SM'])
  })
})

// ── ② autoAttachProductsForNewLayer 仅当 supportsMapLayerResult 才执行 ─────

describe('autoAttachProductsForNewLayer capability 守卫', () => {
  it('supportsMapLayerResult=false 的静态图层：不查 run、不建组、不 attach', async () => {
    const deps = makeDeps({ supportsMapLayerResult: vi.fn(() => false) })
    const runner = createWorkflowRunner(deps)

    const bound = await runner.autoAttachProductsForNewLayer('cat-aridity-ai')

    expect(bound).toBe(0)
    expect(listRecentSucceededRuns).not.toHaveBeenCalled()
    expect(deps.createRunLayerGroup).not.toHaveBeenCalled()
    expect(deps.attachAlgorithmProductOverlays).not.toHaveBeenCalled()
  })

  it('supportsMapLayerResult=true 时保持原行为（查最近成功 run 并尝试 attach）', async () => {
    const deps = makeDeps({ supportsMapLayerResult: vi.fn(() => true) })
    vi.mocked(listRecentSucceededRuns).mockResolvedValue([
      { run_id: 'run-ok', layer_id: 'cat-fy', command_label: '', created_at: '', status: 'succeeded', result_refs: [] },
    ] as never)
    const runner = createWorkflowRunner(deps)

    await runner.autoAttachProductsForNewLayer('cat-fy')

    expect(listRecentSucceededRuns).toHaveBeenCalledOnce()
    expect(deps.attachAlgorithmProductOverlays).toHaveBeenCalled()
  })
})

// ── ③ reconcileOmegaBlockLayers 孤儿合并保护用户静态层 ─────────────────────

describe('reconcileOmegaBlockLayers 用户静态层保护', () => {
  function makeRunLayersDeps() {
    const activeLayers: ActiveLayer[] = []
    return {
      deps: {
        getActiveLayers: () => activeLayers,
        addLayer: vi.fn(),
        removeLayer: vi.fn(),
        assignLayerAccent: vi.fn(() => ({ accentColor: '#fff', accentGlow: '', chipTone: '' })),
        setSelectedInstanceId: vi.fn(),
        getSidebarView: () => 'active' as const,
        setSidebarView: vi.fn(),
        getMapCenter: () => ({ lng: 116, lat: 39 }),
        getCurrentHour: () => 0,
        forgetTrackedWorkflowRun: vi.fn(),
        rememberTrackedWorkflowRun: vi.fn(),
        isLocalSubmitJobId: vi.fn(() => false),
        scheduleWorkspacePersist: vi.fn(),
        genInstanceId: () => `inst-${Math.random().toString(36).slice(2)}`,
        addImportedRasterLayer: vi.fn(),
      },
      activeLayers,
    }
  }

  function omegaBlockLayer(overrides: Partial<ActiveLayer> = {}): ActiveLayer {
    return {
      instanceId: 'inst-orphan',
      catalogId: 'wf-run-grp-x-omega',
      name: 'OMEGA_BLOCK.mat',
      visible: true,
      opacity: 1,
      order: 0,
      isAdminBoundary: false,
      dataState: 'imported',
      importedRaster: { overlayLayerId: 'ovl-omega', fileName: 'OMEGA_BLOCK.mat' },
      ...overrides,
    } as ActiveLayer
  }

  it('无 run 组归属的用户 OMEGA_BLOCK 静态层：不改名、不摘除、不吞并', () => {
    const { deps, activeLayers } = makeRunLayersDeps()
    // 用户手动导入的 OMEGA_BLOCK（无 runGroupId / runGroupProductTag）
    const userLayer = omegaBlockLayer({ instanceId: 'inst-user' })
    activeLayers.push(userLayer)
    // 组内空占位（若有归属的产物层才应被并入这个占位）
    const placeholder: ActiveLayer = {
      instanceId: 'inst-ph',
      catalogId: 'wf-run-grp-x-omega',
      name: 'ω',
      visible: true,
      opacity: 1,
      order: 1,
      isAdminBoundary: false,
      dataState: 'catalog',
      runGroupId: 'grp-x',
      runGroupProductTag: 'OMEGA',
    } as ActiveLayer
    activeLayers.push(placeholder)

    const slice = createRunLayersSlice(deps as never)
    slice.runLayerGroups.value.push({
      groupId: 'grp-x',
      runId: 'run-x',
      title: '反演组',
      status: 'ready',
      memberInstanceIds: ['inst-ph'],
      dissolvable: false,
    } as ActiveRunLayerGroup)
    slice.reconcileOmegaBlockLayers()

    // 用户静态层原样保留：名字不变、引用不摘、仍在列表
    expect(userLayer.name).toBe('OMEGA_BLOCK.mat')
    expect(userLayer.importedRaster?.overlayLayerId).toBe('ovl-omega')
    expect(activeLayers).toHaveLength(2)
    expect(activeLayers.some((l) => l.instanceId === 'inst-user')).toBe(true)
    // 占位未被灌入用户层数据
    expect(placeholder.importedRaster).toBeUndefined()
  })

  it('有 run 组归属的工作流产物 OMEGA_BLOCK：仍并入组内占位（原语义保留）', () => {
    const { deps, activeLayers } = makeRunLayersDeps()
    // 工作流物化产物层（带 runGroupProductTag）
    const productLayer = omegaBlockLayer({
      instanceId: 'inst-prod',
      runGroupId: 'grp-x',
      runGroupProductTag: 'OMEGA',
    })
    activeLayers.push(productLayer)
    const placeholder: ActiveLayer = {
      instanceId: 'inst-ph',
      catalogId: 'wf-run-grp-x-omega',
      name: 'ω',
      visible: true,
      opacity: 1,
      order: 1,
      isAdminBoundary: false,
      dataState: 'catalog',
      runGroupId: 'grp-x',
      runGroupProductTag: 'OMEGA',
    } as ActiveLayer
    activeLayers.push(placeholder)

    const slice = createRunLayersSlice(deps as never)
    slice.runLayerGroups.value.push({
      groupId: 'grp-x',
      runId: 'run-x',
      title: '反演组',
      status: 'ready',
      memberInstanceIds: ['inst-ph'],
      dissolvable: false,
    } as ActiveRunLayerGroup)
    slice.reconcileOmegaBlockLayers()

    // 产物层数据灌入占位、游离产物层被摘除
    expect(placeholder.importedRaster?.overlayLayerId).toBe('ovl-omega')
    expect(activeLayers.some((l) => l.instanceId === 'inst-prod')).toBe(false)
    expect(activeLayers).toHaveLength(1)
  })
})
