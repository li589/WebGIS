import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/services/analysis-api', () => ({
  fetchAnalysisTools: vi.fn(async () => ({
    layer_id: 'imported-a',
    layer_kind: 'raster',
    items: [
      {
        tool_id: 'stats.histogram',
        title: '直方图',
        description: '',
        category: 'stats',
        input_kinds: ['raster'],
        param_schema: [{ key: 'bins', type: 'integer', title: 'bins', default: 50 }],
        workflow_template_id: 'analysis_histogram',
        outputs: ['chart', 'table'],
        resource_profile: 'standard',
        concurrency_key: 'layer_tool',
        enabled: true,
      },
      {
        tool_id: 'gis.clip',
        title: '裁剪',
        description: '',
        category: 'gis',
        input_kinds: ['raster'],
        param_schema: [],
        workflow_template_id: 'analysis_clip',
        outputs: ['map_layer'],
        resource_profile: 'heavy',
        concurrency_key: 'layer_tool',
        enabled: true,
      },
      {
        tool_id: 'gis.reclassify',
        title: '重分类',
        description: '',
        category: 'gis',
        input_kinds: ['raster'],
        param_schema: [],
        workflow_template_id: 'analysis_reclassify',
        outputs: ['map_layer'],
        resource_profile: 'standard',
        concurrency_key: 'layer_tool',
        enabled: true,
      },
    ],
  })),
  submitAnalysisRun: vi.fn(async ({ tool_id }: { tool_id: string }) => ({
    run_id: `run-${tool_id}`,
    status: 'accepted',
    status_url: '/x',
    events_url: '/y',
    created_at: new Date().toISOString(),
    message: 'ok',
  })),
}))

vi.mock('@/services/runtime-api', () => ({
  cancelWorkflowRun: vi.fn(async () => ({})),
}))

vi.mock('@/stores/layers', () => ({
  useLayersStore: () => ({
    jobLayers: [],
    registerExternalWorkflowRun: vi.fn(async () => undefined),
    currentMapBBox: { west: 1, south: 2, east: 3, north: 4 },
  }),
}))

describe('analysis-runner', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('queues third concurrent tool for same layer', async () => {
    const { useAnalysisRunnerStore } = await import('@/stores/analysis-runner')
    const { submitAnalysisRun } = await import('@/services/analysis-api')
    const store = useAnalysisRunnerStore()
    await store.loadToolsForDisplay({
      catalogId: 'imported-a',
      instanceId: 'i1',
      isImportedRaster: true,
      importedRasterOverlayLayerId: 'imported-a',
    } as never)

    const tools = store.toolsCache!.items
    const display = {
      catalogId: 'imported-a',
      instanceId: 'i1',
      isImportedRaster: true,
      importedRasterOverlayLayerId: 'imported-a',
    } as never

    await store.submitTool({ tool: tools[0], display, params: {} })
    await store.submitTool({ tool: tools[1], display, params: {} })
    await store.submitTool({ tool: tools[2], display, params: {} })

    expect(submitAnalysisRun).toHaveBeenCalledTimes(2)
    expect(store.localQueue.length).toBe(1)
    expect(store.toolStatus('gis.reclassify', 'imported-a')?.phase).toBe('queued')
  })
})
