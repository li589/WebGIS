import { describe, expect, it } from 'vitest'

import {
  activeLayerHasReadableRaster,
  buildToolRunContext,
  inferToolInputRequirement,
  layerHasReadableRaster,
  resolveRasterOverlayId,
  resolveRasterOverlayIdFromActiveLayer,
  resolveVectorBackendId,
} from '@/components/info-panel/tools/tool-layer-capabilities'
import type { AnalysisToolDescriptor } from '@/services/analysis-api'

function makeDisplay(overrides: Record<string, unknown> = {}) {
  return {
    instanceId: 'i1',
    catalogId: 'catalog-omega',
    name: '测试',
    isImported: false,
    isImportedRaster: false,
    dataState: 'catalog',
    ...overrides,
  } as never
}

function makeTool(overrides: Partial<AnalysisToolDescriptor> = {}): AnalysisToolDescriptor {
  return {
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
    ...overrides,
  }
}

describe('resolveRasterOverlayId', () => {
  it('优先 importedRasterOverlayLayerId', () => {
    expect(resolveRasterOverlayId(makeDisplay({ importedRasterOverlayLayerId: 'ov-1' }))).toBe(
      'ov-1',
    )
  })

  it('catalog/real 层回落 catalogId', () => {
    expect(resolveRasterOverlayId(makeDisplay({ dataState: 'catalog', catalogId: 'c1' }))).toBe(
      'c1',
    )
    expect(resolveRasterOverlayId(makeDisplay({ dataState: 'real', catalogId: 'c2' }))).toBe('c2')
  })

  it('无栅格能力时返回 null', () => {
    expect(
      resolveRasterOverlayId(makeDisplay({ dataState: 'placeholder', catalogId: 'x' })),
    ).toBeNull()
  })
})

describe('layerHasReadableRaster', () => {
  it('导入栅格与 catalog 层均可分析', () => {
    expect(layerHasReadableRaster(makeDisplay({ isImportedRaster: true }))).toBe(true)
    expect(layerHasReadableRaster(makeDisplay({ dataState: 'catalog' }))).toBe(true)
  })

  it('导入矢量 / 行政区不算栅格', () => {
    expect(
      layerHasReadableRaster(
        makeDisplay({
          isImported: true,
          dataState: 'real',
          importedVectorBackendLayerId: 'v1',
        }),
      ),
    ).toBe(false)
    expect(resolveRasterOverlayId(makeDisplay({ isImported: true, dataState: 'real' }))).toBeNull()
    expect(layerHasReadableRaster(makeDisplay({ isAdminBoundary: true, dataState: 'real' }))).toBe(
      false,
    )
  })
})

describe('activeLayerHasReadableRaster / resolveRasterOverlayIdFromActiveLayer', () => {
  it('与 display 层口径一致', () => {
    const layer = {
      visible: true,
      catalogId: 'cat-1',
      dataState: 'catalog',
    }
    expect(activeLayerHasReadableRaster(layer)).toBe(true)
    expect(resolveRasterOverlayIdFromActiveLayer(layer)).toBe('cat-1')
  })

  it('矢量 active layer 不计入栅格列表', () => {
    expect(
      resolveRasterOverlayIdFromActiveLayer({
        catalogId: 'vec-1',
        dataState: 'real',
        isImported: true,
        importedVectorBackendLayerId: 'vb',
      }),
    ).toBeNull()
  })
})

describe('resolveVectorBackendId', () => {
  it('读取 importedVectorBackendLayerId', () => {
    expect(
      resolveVectorBackendId(
        makeDisplay({ isImported: true, importedVectorBackendLayerId: 'vec-backend-1' }),
      ),
    ).toBe('vec-backend-1')
  })
})

describe('inferToolInputRequirement', () => {
  it('从 input_kinds 推导 raster/vector/point', () => {
    expect(inferToolInputRequirement(makeTool({ input_kinds: ['raster'] }))).toMatchObject({
      needsRaster: true,
      needsVector: false,
    })
    expect(
      inferToolInputRequirement(makeTool({ tool_id: 'gis.buffer', input_kinds: ['vector', 'point'] })),
    ).toMatchObject({ needsPoint: true })
    expect(
      inferToolInputRequirement(makeTool({ tool_id: 'gis.clip', input_kinds: ['raster'] })),
    ).toMatchObject({ needsMapBBox: true })
  })
})

describe('buildToolRunContext', () => {
  it('组装运行上下文', () => {
    const ctx = buildToolRunContext(makeDisplay(), { lng: 1, lat: 2 }, true)
    expect(ctx.selectedMapPoint).toEqual({ lng: 1, lat: 2 })
    expect(ctx.hasMapBBox).toBe(true)
  })
})
