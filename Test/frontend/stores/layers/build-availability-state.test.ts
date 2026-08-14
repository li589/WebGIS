import { describe, expect, it } from 'vitest'
import { buildAvailabilityState } from '@/stores/layers/catalog-builders'
import type { ActiveLayer, JobLayerItem, RuntimeLayerLibraryItem } from '@/stores/layers/types'

function baseItem(overrides: Partial<RuntimeLayerLibraryItem> = {}): RuntimeLayerLibraryItem {
  return {
    catalogId: 'research-demo',
    name: '演示层',
    category: 'research-group',
    description: 'desc',
    metricLabel: '指标',
    metricUnit: '',
    metricPrecision: 1,
    updateLabel: '日更',
    sourceLabel: '源',
    accentColor: '#5ad5ff',
    accentGlow: 'rgba(90,213,255,0.3)',
    chipTone: 'rgba(90,213,255,0.16)',
    sources: [],
    runReadiness: 'ready',
    runReadinessSummary: null,
    runReadinessNotes: [],
    backendStatus: 'ready',
    engine: 'python_provider',
    sourceType: null,
    renderType: null,
    workflowName: null,
    ...overrides,
  }
}

function baseLayer(overrides: Partial<ActiveLayer> = {}): ActiveLayer {
  return {
    instanceId: 'inst-1',
    catalogId: 'research-demo',
    visible: true,
    opacity: 1,
    order: 0,
    isAdminBoundary: false,
    dataState: 'catalog',
    ...overrides,
  }
}

describe('buildAvailabilityState', () => {
  it('catalog layer without job shows 待运行', () => {
    const result = buildAvailabilityState(baseLayer(), baseItem())
    expect(result.label).toBe('待运行')
    expect(result.state).toBe('empty')
  })

  it('weather engine layer without job never shows 待运行', () => {
    const result = buildAvailabilityState(
      baseLayer({ catalogId: 'wind-field' }),
      baseItem({
        catalogId: 'wind-field',
        engine: 'weatherengine',
        category: 'weather',
      }),
    )
    expect(result.label).not.toBe('待运行')
    expect(result.label).toBe('可查看')
    expect(result.state).toBe('partial')
  })

  it('dataState real without job shows 等待结果 not 待运行', () => {
    const result = buildAvailabilityState(baseLayer({ dataState: 'real' }), baseItem())
    expect(result.label).toBe('等待结果')
    expect(result.state).toBe('partial')
  })

  it('imported raster without job shows 完整数据', () => {
    const result = buildAvailabilityState(
      baseLayer({
        catalogId: 'imported-abc',
        dataState: 'imported',
        importedRaster: {
          overlayLayerId: 'imported-abc',
          bounds: [0, 0, 1, 1],
        },
      }),
      baseItem({ catalogId: 'imported-abc' }),
    )
    expect(result.label).toBe('完整数据')
    expect(result.state).toBe('ready')
  })

  it('running job uses short 运行中 label', () => {
    const job: JobLayerItem = {
      jobId: 'run-1',
      name: '分析',
      commandType: 'analysis',
      catalogId: 'research-demo',
      status: 'running',
      progress: 35,
      message: '服务层正在执行真实工作流。',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    }
    const result = buildAvailabilityState(baseLayer(), baseItem(), job)
    expect(result.label).toBe('运行中')
  })
})
