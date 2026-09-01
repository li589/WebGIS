import { describe, expect, it } from 'vitest'
import { buildGroupContextMenu, buildLayerContextMenu } from '@/components/layer-sidebar/layer-context-menu'
import { resolveLayerContextCapabilities } from '@/components/layer-sidebar/layer-context-menu-capabilities'
import type { ActiveLayerDisplay } from '@/stores/layers/types'

function baseDisplay(overrides: Partial<ActiveLayerDisplay> = {}): ActiveLayerDisplay {
  return {
    instanceId: 'inst-1',
    catalogId: 'cat-weather',
    name: 'Test Layer',
    category: 'weather',
    description: '',
    engine: 'weather',
    supportsTime: true,
    runReadiness: 'ready',
    runReadinessSummary: '',
    summary: '',
    metricLabel: '',
    metricValue: '',
    trendLabel: '',
    statusLabel: '',
    updateLabel: '',
    sourceLabel: '',
    confidenceLabel: '',
    accentColor: '#fff',
    accentGlow: 'rgba(0,0,0,0.1)',
    chipTone: 'rgba(0,0,0,0.1)',
    availabilityState: 'ready',
    availabilityLabel: '',
    availabilityDescription: '',
    observationTimeLabel: '',
    missingFieldsLabel: '',
    hotspots: [],
    isAdminBoundary: false,
    isImported: false,
    isImportedRaster: false,
    visible: true,
    opacity: 1,
    order: 1,
    ...overrides,
  }
}

function flatIds(groups: ReturnType<typeof buildLayerContextMenu>) {
  return groups.flatMap((g) => g.items.map((i) => i.id))
}

describe('buildLayerContextMenu', () => {
  it('catalog algorithm layer gets runWorkflow when canRunWorkflow', () => {
    const groups = buildLayerContextMenu({
      visible: true,
      isAdminBoundary: false,
      isImported: false,
      isImportedRaster: false,
      hasJobReport: false,
      canRunWorkflow: true,
    })
    const ids = flatIds(groups)
    expect(ids).toContain('zoom')
    expect(ids).toContain('openStyle')
    expect(ids).toContain('runWorkflow')
    expect(ids).not.toContain('exportGeoJson')
    expect(ids).not.toContain('retryWeatherTiles')
  })

  it('weather layer gets retry tiles, not runWorkflow', () => {
    const groups = buildLayerContextMenu({
      visible: true,
      isAdminBoundary: false,
      isImported: false,
      isImportedRaster: false,
      hasJobReport: false,
      canRunWorkflow: false,
      canRetryWeatherTiles: true,
    })
    const ids = flatIds(groups)
    expect(ids).toContain('retryWeatherTiles')
    expect(ids).not.toContain('runWorkflow')
    expect(ids).not.toContain('runWorkflowNoCache')
  })

  it('weather data-empty gets trigger sync', () => {
    const groups = buildLayerContextMenu({
      visible: true,
      isAdminBoundary: false,
      isImported: false,
      isImportedRaster: false,
      hasJobReport: false,
      canRunWorkflow: false,
      canRetryWeatherTiles: true,
      canTriggerWeatherSync: true,
    })
    const ids = flatIds(groups)
    expect(ids).toContain('triggerWeatherSync')
  })

  it('imported vector gets attributes, exports, no viewDetails in view group', () => {
    const groups = buildLayerContextMenu({
      visible: true,
      isAdminBoundary: false,
      isImported: true,
      isImportedRaster: false,
      hasJobReport: false,
      canRunWorkflow: false,
      showViewDetailsInViewGroup: false,
    })
    const viewGroup = groups.find((g) => g.id === 'view')
    const viewIds = viewGroup?.items.map((i) => i.id) ?? []
    expect(viewIds).not.toContain('viewDetails')
    const ids = flatIds(groups)
    expect(ids).toContain('openAttributes')
    expect(ids).not.toContain('editGeometry')
    expect(ids).toContain('exportGeoJson')
    expect(ids).toContain('openExportPanel')
    expect(ids).not.toContain('runWorkflow')
  })

  it('polygon imported vector can edit geometry', () => {
    const groups = buildLayerContextMenu({
      visible: true,
      isAdminBoundary: false,
      isImported: true,
      isImportedRaster: false,
      hasJobReport: false,
      canRunWorkflow: false,
      canEditGeometry: true,
      showViewDetailsInViewGroup: false,
    })
    const ids = flatIds(groups)
    expect(ids).toContain('editGeometry')
  })

  it('imported raster panel-only export has no duplicate format shortcuts', () => {
    const groups = buildLayerContextMenu({
      visible: false,
      isAdminBoundary: false,
      isImported: false,
      isImportedRaster: true,
      hasJobReport: false,
      canRunWorkflow: false,
      rasterExportPanelOnly: true,
      showViewDetailsInViewGroup: false,
    })
    const ids = flatIds(groups)
    expect(ids).toContain('openExportPanel')
    expect(ids).not.toContain('exportPng')
    expect(ids).not.toContain('exportTif')
    expect(ids).not.toContain('exportNc')
    expect(ids).not.toContain('exportMat')
    const toggle = groups.flatMap((g) => g.items).find((i) => i.id === 'toggleVisible')
    expect(toggle?.label).toContain('显示')
  })

  it('draw draft disables vector exports', () => {
    const groups = buildLayerContextMenu({
      visible: true,
      isAdminBoundary: false,
      isImported: true,
      isImportedRaster: false,
      hasJobReport: false,
      canRunWorkflow: false,
      isDrawDraft: true,
      showViewDetailsInViewGroup: false,
    })
    const exports = groups
      .flatMap((g) => g.items)
      .filter((i) => i.id.startsWith('export') || i.id === 'openExportPanel')
    expect(exports.length).toBeGreaterThan(0)
    expect(exports.every((i) => i.disabled)).toBe(true)
    expect(exports[0]?.label).toContain('需先保存')
  })

  it('export pending placeholder shows disabled export item', () => {
    const groups = buildLayerContextMenu({
      visible: true,
      isAdminBoundary: false,
      isImported: false,
      isImportedRaster: false,
      isExportPending: true,
      hasJobReport: false,
      canRunWorkflow: false,
    })
    const pending = groups.flatMap((g) => g.items).find((i) => i.id === 'exportPending')
    expect(pending?.disabled).toBe(true)
  })

  it('job report item when hasJobReport', () => {
    const groups = buildLayerContextMenu({
      visible: true,
      isAdminBoundary: false,
      isImported: false,
      isImportedRaster: false,
      hasJobReport: true,
      canRunWorkflow: false,
    })
    const ids = flatIds(groups)
    expect(ids).toContain('viewReport')
    expect(ids).not.toContain('dissolveGroup')
  })

  it('admin boundary still gets openStyle for opacity in analysis panel', () => {
    const groups = buildLayerContextMenu({
      visible: true,
      isAdminBoundary: true,
      isImported: false,
      isImportedRaster: false,
      hasJobReport: false,
      canRunWorkflow: false,
    })
    const ids = flatIds(groups)
    expect(ids).toContain('openStyle')
  })
})

describe('resolveLayerContextCapabilities', () => {
  const noopWeather = () => false
  const alwaysTrue = () => true

  it('weather layer excludes runWorkflow and enables retry', () => {
    const caps = resolveLayerContextCapabilities({
      layer: baseDisplay({ catalogId: 'weather-temp-2m' }),
      raw: undefined,
      isWeatherLayer: () => true,
      supportsAnalysisWorkflow: alwaysTrue,
      isOverlayDisplayOnlyLayer: () => false,
      canRunCatalog: alwaysTrue,
    })
    expect(caps.canRunWorkflow).toBe(false)
    expect(caps.canRetryWeatherTiles).toBe(true)
  })

  it('overlay-only static layer can run workflow bake', () => {
    const caps = resolveLayerContextCapabilities({
      layer: baseDisplay({ catalogId: 'overlay-static' }),
      raw: undefined,
      isWeatherLayer: noopWeather,
      supportsAnalysisWorkflow: () => false,
      isOverlayDisplayOnlyLayer: alwaysTrue,
      canRunCatalog: alwaysTrue,
    })
    expect(caps.canRunWorkflow).toBe(true)
  })

  it('draw draft marks exports disabled', () => {
    const caps = resolveLayerContextCapabilities({
      layer: baseDisplay({
        catalogId: 'draw-draft-abc',
        isImported: true,
      }),
      raw: {
        instanceId: 'inst-1',
        catalogId: 'draw-draft-abc',
        name: 'draft',
        visible: true,
        opacity: 1,
        order: 1,
        isAdminBoundary: false,
      },
      isWeatherLayer: noopWeather,
      supportsAnalysisWorkflow: () => false,
      isOverlayDisplayOnlyLayer: () => false,
      canRunCatalog: alwaysTrue,
    })
    expect(caps.isDrawDraft).toBe(true)
    expect(caps.showViewDetailsInViewGroup).toBe(false)
  })
})

describe('buildGroupContextMenu', () => {
  it('exposes dissolve/remove/toggle and disables dissolve while computing', () => {
    const groups = buildGroupContextMenu({
      dissolvable: false,
      computing: true,
      anyVisible: true,
    })
    const items = groups.flatMap((g) => g.items)
    const ids = items.map((i) => i.id)
    expect(ids).toEqual(['toggleGroupVisible', 'dissolveGroup', 'removeGroup'])
    expect(items.find((i) => i.id === 'dissolveGroup')?.disabled).toBe(true)
  })
})
