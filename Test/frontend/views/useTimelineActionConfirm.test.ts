/**
 * useTimelineActionConfirm — coverage_gap → recovery → 切换在线重跑 / 计划会话升级
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { computed, nextTick, ref } from 'vue'

vi.mock('../../../Code/frontend/src/services/workflow-definition-api', () => ({
  fetchWorkflowDefinition: vi.fn(async () => ({
    workflow_id: 'omega_sf_fenkuai_fy_online',
    nodes: [{ id: 1, type: 'download/fy_download', title: 'fy', pos: [0, 0], properties: { orbit_mode: 'MWRID' } }],
  })),
  fetchWorkflowDefinitions: vi.fn(async () => []),
}))

import { useTimelineActionBannerStore } from '../../../Code/frontend/src/stores/timeline-action-banner'
import { useOnlinePlanSessionStore } from '../../../Code/frontend/src/stores/online-plan-session'
import { useTimelineActionConfirm } from '../../../Code/frontend/src/views/dashboard/useTimelineActionConfirm'

function makeDeps(overrides: Record<string, unknown> = {}) {
  const jobLayers = ref<
    Array<{
      jobId: string
      catalogId: string
      status: string
      message?: string
      failureCategory?: string
      diagnostics?: string[]
    }>
  >([])

  const setWorkflowVariantPreference = vi.fn()
  const runWorkflowForCatalog = vi.fn(async () => 'run-1')
  const interruptWorkflowForCatalog = vi.fn()
  const cancelWorkflowRunForJob = vi.fn(async () => undefined)
  const getWorkflowVariantPreference = vi.fn(() => undefined as 'online' | 'local' | undefined)
  const getCatalogRunBlockReason = vi.fn(() => null as string | null)
  const resolveEffectiveDescriptor = vi.fn((id: string) => {
    if (id.startsWith('method-')) {
      return {
        module_name: 'omega_sf_fenkuai',
        workflow_variants: {
          online: { workflow_id: 'omega_sf_fenkuai_fy_online' },
          local: { workflow_id: 'omega_sf_fenkuai_fy_single' },
        },
      }
    }
    return { module_name: 'fy_daily' }
  })

  const workspace = {
    activeLayers: ref([]),
    layerLibrary: ref([]),
    isWeatherEngineLayer: () => false,
    supportsAnalysisWorkflow: () => true,
    getOnlineTemporalConfig: () => ({ native_step: '1d' }),
    resolveEffectiveDescriptor,
    resolveBackendLayerId: (id: string) => id,
    getCatalogRunBlockReason,
  }

  const workflowRun = {
    jobLayers,
    hasReusableProductsForTime: vi.fn(async () => false),
    autoAttachProductsForNewLayer: vi.fn(async () => 0),
    interruptWorkflowForCatalog,
    cancelWorkflowRunForJob,
    runWorkflowForCatalog,
    setWorkflowVariantPreference,
    getWorkflowVariantPreference,
  }

  const uiStore = {
    unifiedTimeLock: false,
    rememberLayerTime: vi.fn(),
  }

  return {
    workspace: workspace as never,
    workflowRun: workflowRun as never,
    uiStore: uiStore as never,
    selectedCatalogId: computed(() => 'method-fy-omega-doy-dynamic'),
    currentDate: ref(new Date('2025-12-03T00:00:00Z')),
    currentHour: ref(0),
    activeLayerGranularity: computed(() => 'day' as const),
    isPlaying: ref(false),
    logOperation: vi.fn(),
    _spies: {
      jobLayers,
      setWorkflowVariantPreference,
      runWorkflowForCatalog,
      getCatalogRunBlockReason,
      getWorkflowVariantPreference,
      resolveEffectiveDescriptor,
    },
    ...overrides,
  }
}

describe('useTimelineActionConfirm coverage recovery', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
  })

  it('shows recovery (not 10s notice) on coverage_gap when online variant exists', async () => {
    const deps = makeDeps()
    useTimelineActionConfirm(deps)
    const banner = useTimelineActionBannerStore()

    // watch 跳过 prevJoined===''；先写入 running 再 failed，模拟真实轮询
    deps._spies.jobLayers.value = [
      {
        jobId: 'run-1',
        catalogId: 'method-fy-omega-doy-dynamic',
        status: 'running',
        message: '执行中',
      },
    ]
    await nextTick()
    deps._spies.jobLayers.value = [
      {
        jobId: 'run-1',
        catalogId: 'method-fy-omega-doy-dynamic',
        status: 'failed',
        message: 'error_code=coverage_gap 零交集',
        failureCategory: 'coverage_gap',
        diagnostics: ['failure_category=coverage_gap'],
      },
    ]
    await nextTick()

    expect(banner.hasRecovery).toBe(true)
    expect(banner.recovery?.offers).toEqual(['switch_online', 'open_plan'])
    expect(banner.hasNotice).toBe(false)
  })

  it('escalates to plan session on 3rd coverage_gap (L1)', async () => {
    const deps = makeDeps()
    useTimelineActionConfirm(deps)
    const banner = useTimelineActionBannerStore()
    const plan = useOnlinePlanSessionStore()

    async function failOnce(jobId: string, catalogId: string) {
      deps._spies.jobLayers.value = [
        { jobId, catalogId, status: 'running', message: 'go' },
      ]
      await nextTick()
      deps._spies.jobLayers.value = [
        {
          jobId,
          catalogId,
          status: 'failed',
          message: `error_code=coverage_gap ${jobId}`,
          failureCategory: 'coverage_gap',
        },
      ]
      await nextTick()
      // allow async ensureTab (param load)
      await vi.runAllTimersAsync()
      await nextTick()
    }

    const cid = 'method-fy-omega-doy-dynamic'
    await failOnce('r1', cid)
    expect(plan.getFailCount(cid)).toBe(1)
    expect(plan.hasPending).toBe(false)
    expect(banner.recovery?.offers).toContain('switch_online')

    await failOnce('r2', cid)
    expect(plan.getFailCount(cid)).toBe(2)
    expect(plan.hasPending).toBe(false)

    // 第 3 次：勿 runAllTimers（会立刻吃掉 10s notice）；只冲刷 async ensureTab
    deps._spies.jobLayers.value = [{ jobId: 'r3', catalogId: cid, status: 'running', message: 'go' }]
    await nextTick()
    deps._spies.jobLayers.value = [
      {
        jobId: 'r3',
        catalogId: cid,
        status: 'failed',
        message: 'error_code=coverage_gap r3',
        failureCategory: 'coverage_gap',
      },
    ]
    await nextTick()
    await Promise.resolve()
    await nextTick()
    await Promise.resolve()
    await nextTick()

    expect(plan.getFailCount(cid)).toBe(3)
    expect(plan.tabs.some((t) => t.catalogId === cid)).toBe(true)
    expect(plan.status).toBe('open')
    // L1：直接开面板，不再叠 recovery / notice（避免被 backdrop 挡住）
    expect(banner.hasRecovery).toBe(false)
    expect(banner.hasNotice).toBe(false)
  })

  it('multi-catalog each at 3 fails creates two chips', async () => {
    const deps = makeDeps()
    deps._spies.resolveEffectiveDescriptor.mockImplementation((id: string) => ({
      module_name: 'omega_sf_fenkuai',
      workflow_variants: {
        online: { workflow_id: 'omega_sf_fenkuai_fy_online' },
        local: { workflow_id: 'omega_sf_fenkuai_fy_single' },
      },
      display_name: id,
    }))
    useTimelineActionConfirm(deps)
    const plan = useOnlinePlanSessionStore()

    async function tripleFail(catalogId: string) {
      for (let i = 0; i < 3; i++) {
        const jobId = `${catalogId}-${i}`
        deps._spies.jobLayers.value = [{ jobId, catalogId, status: 'running' }]
        await nextTick()
        deps._spies.jobLayers.value = [
          {
            jobId,
            catalogId,
            status: 'failed',
            message: 'error_code=coverage_gap',
            failureCategory: 'coverage_gap',
          },
        ]
        await nextTick()
        await vi.runAllTimersAsync()
        await nextTick()
      }
    }

    await tripleFail('method-a')
    await tripleFail('method-b')
    expect(plan.tabs.map((t) => t.catalogId).sort()).toEqual(['method-a', 'method-b'])
    plan.setActiveCatalog('method-a')
    expect(plan.activeCatalogId).toBe('method-a')
  })

  it('falls back to notice when layer has no online variant', async () => {
    const deps = makeDeps()
    deps._spies.resolveEffectiveDescriptor.mockImplementation(() => ({
      module_name: 'fy_daily',
    }))
    useTimelineActionConfirm(deps)
    const banner = useTimelineActionBannerStore()

    deps._spies.jobLayers.value = [
      {
        jobId: 'run-2',
        catalogId: 'ref-fy-tb-202512-mwri',
        status: 'running',
      },
    ]
    await nextTick()
    deps._spies.jobLayers.value = [
      {
        jobId: 'run-2',
        catalogId: 'ref-fy-tb-202512-mwri',
        status: 'failed',
        message: 'error_code=coverage_gap',
        failureCategory: 'coverage_gap',
      },
    ]
    await nextTick()

    expect(banner.hasRecovery).toBe(false)
    expect(banner.hasNotice).toBe(true)
  })

  it('handleSwitchOnlineRerun sets preference and submits online variant', async () => {
    const deps = makeDeps()
    const api = useTimelineActionConfirm(deps)
    const banner = useTimelineActionBannerStore()

    banner.showRecovery({
      catalogId: 'method-fy-omega-doy-dynamic',
      message: 'error_code=coverage_gap',
      timeKey: '2025-12-03',
      offers: ['switch_online'],
    })

    await api.handleSwitchOnlineRerun()

    expect(deps._spies.setWorkflowVariantPreference).toHaveBeenCalledWith(
      'method-fy-omega-doy-dynamic',
      'online',
      { pinned: true },
    )
    expect(deps._spies.runWorkflowForCatalog).toHaveBeenCalledWith(
      'method-fy-omega-doy-dynamic',
      expect.objectContaining({
        workflowVariant: 'online',
      }),
    )
    expect(banner.hasRecovery).toBe(false)
  })

  it('blocks switch-online when catalog run readiness is blocked', async () => {
    const deps = makeDeps()
    deps._spies.getCatalogRunBlockReason.mockReturnValue('在线凭据未配置')
    const api = useTimelineActionConfirm(deps)
    const banner = useTimelineActionBannerStore()

    banner.showRecovery({
      catalogId: 'method-fy-omega-doy-dynamic',
      message: 'error_code=coverage_gap',
      offers: ['switch_online'],
    })

    await api.handleSwitchOnlineRerun()

    expect(deps._spies.runWorkflowForCatalog).not.toHaveBeenCalled()
    expect(banner.hasNotice).toBe(true)
    expect(banner.notice?.message).toContain('在线凭据')
  })
})
