import { describe, expect, it, vi } from 'vitest'

import { createAdminBoundaryModule } from './admin-boundary-module'

describe('admin-boundary-module', () => {
  it('loads boundary assets once and syncs overlay opacity', async () => {
    const sources = new Map<string, unknown>()
    const layers = new Set<string>()
    const setLayoutProperty = vi.fn()
    const setPaintProperty = vi.fn()
    const boundaryModuleData = {
      guangdongCityBoundaries: { type: 'FeatureCollection', features: [] as any[] },
    }
    const loadBoundaryModule = vi.fn(async () => boundaryModuleData) as unknown as NonNullable<
      NonNullable<Parameters<typeof createAdminBoundaryModule>[0]['dependencies']>['loadBoundaryModule']
    >
    const setLoadingLabel = vi.fn()

    const module = createAdminBoundaryModule({
      map: {
        getSource: (id: string) => sources.get(id),
        addSource: (id: string, source: unknown) => {
          sources.set(id, source)
        },
        getLayer: (id: string) => (layers.has(id) ? { id } : undefined),
        addLayer: (layer: { id: string }) => {
          layers.add(layer.id)
        },
        setLayoutProperty,
        setPaintProperty,
      } as any,
      setLoadingLabel,
      dependencies: {
        loadBoundaryModule,
      },
    })

    await module.ensureLayers()
    await module.ensureLayers()
    module.syncOverlay(true, 0.5)

    expect(loadBoundaryModule).toHaveBeenCalledTimes(1)
    expect(setLoadingLabel).toHaveBeenCalledWith('正在载入行政区边界...')
    expect(sources.has('admin-boundaries')).toBe(true)
    expect(sources.has('admin-centers')).toBe(false)
    expect(layers.has('admin-fill')).toBe(true)
    expect(layers.has('admin-line')).toBe(true)
    expect(layers.has('admin-center-points')).toBe(false)
    expect(setLayoutProperty).toHaveBeenCalledWith('admin-fill', 'visibility', 'visible')
    expect(setPaintProperty).toHaveBeenCalledWith('admin-fill', 'fill-opacity', 0.16)
    expect(setPaintProperty).toHaveBeenCalledWith('admin-line', 'line-opacity', 0.41)
    expect(setPaintProperty).not.toHaveBeenCalledWith(
      'admin-center-points',
      'circle-opacity',
      expect.anything(),
    )
  })
})
