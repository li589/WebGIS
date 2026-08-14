import { describe, expect, it } from 'vitest'
import { buildGroupContextMenu, buildLayerContextMenu } from '@/components/layer-sidebar/layer-context-menu'

describe('buildLayerContextMenu', () => {
  it('weather-like layer gets zoom, openStyle, order, remove', () => {
    const groups = buildLayerContextMenu({
      visible: true,
      isAdminBoundary: false,
      isImported: false,
      isImportedRaster: false,
      hasJobReport: false,
      canRunWorkflow: true,
    })
    const ids = groups.flatMap((g) => g.items.map((i) => i.id))
    expect(ids).toContain('zoom')
    expect(ids).toContain('openStyle')
    expect(ids).not.toContain('symbology' as never)
    expect(ids).toContain('bringToFront')
    expect(ids).toContain('runWorkflow')
    expect(ids).toContain('remove')
    expect(ids).not.toContain('exportGeoJson')
  })

  it('imported vector gets attributes, exports, shp, and export panel', () => {
    const groups = buildLayerContextMenu({
      visible: true,
      isAdminBoundary: false,
      isImported: true,
      isImportedRaster: false,
      hasJobReport: false,
      canRunWorkflow: false,
    })
    const ids = groups.flatMap((g) => g.items.map((i) => i.id))
    expect(ids).toContain('openAttributes')
    expect(ids).toContain('exportGeoJson')
    expect(ids).toContain('exportCsv')
    expect(ids).toContain('exportShp')
    expect(ids).toContain('openExportPanel')
    expect(ids.filter((id) => id === 'openStyle')).toHaveLength(1)
    expect(ids).not.toContain('runWorkflow')
  })

  it('imported raster gets tif/nc/mat/png and export panel', () => {
    const groups = buildLayerContextMenu({
      visible: false,
      isAdminBoundary: false,
      isImported: false,
      isImportedRaster: true,
      hasJobReport: false,
      canRunWorkflow: false,
    })
    const ids = groups.flatMap((g) => g.items.map((i) => i.id))
    expect(ids).toContain('exportPng')
    expect(ids).toContain('exportTif')
    expect(ids).toContain('exportNc')
    expect(ids).toContain('exportMat')
    expect(ids).toContain('openExportPanel')
    expect(ids).toContain('toggleVisible')
    expect(ids).toContain('openStyle')
    const toggle = groups.flatMap((g) => g.items).find((i) => i.id === 'toggleVisible')
    expect(toggle?.label).toContain('显示')
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

  it('admin boundary still gets openStyle for opacity in analysis panel', () => {
    const groups = buildLayerContextMenu({
      visible: true,
      isAdminBoundary: true,
      isImported: false,
      isImportedRaster: false,
      hasJobReport: false,
      canRunWorkflow: false,
    })
    const ids = groups.flatMap((g) => g.items.map((i) => i.id))
    expect(ids).toContain('openStyle')
    expect(ids).not.toContain('symbology' as never)
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
    const ids = groups.flatMap((g) => g.items.map((i) => i.id))
    expect(ids).toContain('viewReport')
  })

  it('dissolveGroup when canDissolveGroup', () => {
    const groups = buildLayerContextMenu({
      visible: true,
      isAdminBoundary: false,
      isImported: false,
      isImportedRaster: true,
      hasJobReport: false,
      canRunWorkflow: false,
      canDissolveGroup: true,
    })
    const ids = groups.flatMap((g) => g.items.map((i) => i.id))
    expect(ids).toContain('dissolveGroup')
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
