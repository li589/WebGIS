import { describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useAnalysisRunnerStore } from '@/stores/analysis-runner'
import type { AnalysisToolDescriptor } from '@/services/analysis-api'

function makeTool(): AnalysisToolDescriptor {
  return {
    tool_id: 'gis.zonal_stats',
    title: '分区统计',
    description: '',
    category: 'gis',
    input_kinds: ['raster'],
    param_schema: [],
    workflow_template_id: 'analysis_zonal_stats',
    outputs: ['table', 'chart'],
    resource_profile: 'standard',
    concurrency_key: 'layer_tool',
    enabled: true,
  }
}

function makeDisplay(overrides: Record<string, unknown> = {}) {
  return {
    instanceId: 'i1',
    catalogId: 'cat-raster',
    name: '栅格',
    isImportedRaster: true,
    importedRasterOverlayLayerId: 'ov-raster',
    dataState: 'real',
    ...overrides,
  } as never
}

describe('analysis-runner buildSubmitBody', () => {
  it('overlay 与 zones 矢量/栅格字段映射正确', () => {
    setActivePinia(createPinia())
    const runner = useAnalysisRunnerStore()
    const body = runner.buildSubmitBody({
      tool: makeTool(),
      display: makeDisplay(),
      params: {
        statistic: 'mean',
        zones_imported_vector_layer_id: 'vec-backend-9',
        zones_overlay_layer_id: 'ov-zones',
      },
      mapPoint: null,
      bbox: null,
    })
    expect(body.overlay_layer_id).toBe('ov-raster')
    expect(body.zones_overlay_layer_id).toBe('ov-zones')
    expect(body.params?.zones_imported_vector_layer_id).toBe('vec-backend-9')
    expect(body.params?.zones_overlay_layer_id).toBeUndefined()
  })

  it('catalog 层 overlay 回落 catalogId', () => {
    setActivePinia(createPinia())
    const runner = useAnalysisRunnerStore()
    const body = runner.buildSubmitBody({
      tool: makeTool(),
      display: makeDisplay({
        isImportedRaster: false,
        importedRasterOverlayLayerId: undefined,
        dataState: 'catalog',
        catalogId: 'method-omega-sf',
      }),
      params: {},
      mapPoint: null,
      bbox: null,
    })
    expect(body.overlay_layer_id).toBe('method-omega-sf')
  })
})
