import { describe, expect, it } from 'vitest'
import { buildLayerContextMenu } from './layer-context-menu'

describe('buildLayerContextMenu', () => {
  it('weather-like layer gets zoom, symbology, order, remove', () => {
    const groups = buildLayerContextMenu({
      visible: true,
      isAdminBoundary: false,
      isImported: false,
      isImportedRaster: false,
      hasJobReport: false,
      canRunWorkflow: true,
      hasColorSymbology: true,
    })
    const ids = groups.flatMap((g) => g.items.map((i) => i.id))
    expect(ids).toContain('zoom')
    expect(ids).toContain('symbology')
    expect(ids).toContain('bringToFront')
    expect(ids).toContain('runWorkflow')
    expect(ids).toContain('remove')
    expect(ids).not.toContain('exportGeoJson')
  })

  it('imported vector gets attributes and exports', () => {
    const groups = buildLayerContextMenu({
      visible: true,
      isAdminBoundary: false,
      isImported: true,
      isImportedRaster: false,
      hasJobReport: false,
      canRunWorkflow: false,
      hasColorSymbology: false,
    })
    const ids = groups.flatMap((g) => g.items.map((i) => i.id))
    expect(ids).toContain('openAttributes')
    expect(ids).toContain('exportGeoJson')
    expect(ids).toContain('exportCsv')
    expect(ids).toContain('openStyle')
    expect(ids).not.toContain('runWorkflow')
  })

  it('imported raster gets png/tif export', () => {
    const groups = buildLayerContextMenu({
      visible: false,
      isAdminBoundary: false,
      isImported: false,
      isImportedRaster: true,
      hasJobReport: false,
      canRunWorkflow: false,
      hasColorSymbology: true,
    })
    const ids = groups.flatMap((g) => g.items.map((i) => i.id))
    expect(ids).toContain('exportPng')
    expect(ids).toContain('exportTif')
    expect(ids).toContain('toggleVisible')
    const toggle = groups.flatMap((g) => g.items).find((i) => i.id === 'toggleVisible')
    expect(toggle?.label).toContain('显示')
  })

  it('admin boundary skips symbology', () => {
    const groups = buildLayerContextMenu({
      visible: true,
      isAdminBoundary: true,
      isImported: false,
      isImportedRaster: false,
      hasJobReport: false,
      canRunWorkflow: false,
      hasColorSymbology: false,
    })
    const ids = groups.flatMap((g) => g.items.map((i) => i.id))
    expect(ids).not.toContain('symbology')
  })

  it('job report item when hasJobReport', () => {
    const groups = buildLayerContextMenu({
      visible: true,
      isAdminBoundary: false,
      isImported: false,
      isImportedRaster: false,
      hasJobReport: true,
      canRunWorkflow: false,
      hasColorSymbology: true,
    })
    const ids = groups.flatMap((g) => g.items.map((i) => i.id))
    expect(ids).toContain('viewReport')
  })
})
