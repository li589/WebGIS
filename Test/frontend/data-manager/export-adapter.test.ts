import { beforeEach, describe, expect, it, vi } from 'vitest'

const exportImportedLayer = vi.fn()
const exportBatchLayers = vi.fn()
const downloadBlob = vi.fn()

vi.mock('@/data-manager/core/api', () => ({
  exportImportedLayer: (...args: unknown[]) => exportImportedLayer(...args),
  exportBatchLayers: (...args: unknown[]) => exportBatchLayers(...args),
  downloadBlob: (...args: unknown[]) => downloadBlob(...args),
  waitForImportJob: vi.fn(),
}))

vi.mock('@/services/http-credentials', () => ({
  applyApiFetchDefaults: (init: RequestInit) => init,
}))
vi.mock('@/services/_http', () => ({
  resolveApiUrl: (u: string) => u,
}))
vi.mock('@/services/backend-auth', () => ({
  withWriteAuthHeaders: (h: HeadersInit) => h,
}))

import { exportLayer, exportLayersBatch } from '@/data-manager/adapters/export'

describe('export adapter options', () => {
  beforeEach(() => {
    exportImportedLayer.mockReset()
    exportBatchLayers.mockReset()
    downloadBlob.mockReset()
    exportImportedLayer.mockResolvedValue(new Blob(['x'], { type: 'image/tiff' }))
    exportBatchLayers.mockResolvedValue({ blob: new Blob(['z'], { type: 'application/zip' }) })
  })

  it('passes bbox/outputCrs/fields/time to single export', async () => {
    await exportLayer(
      {
        name: 'SM',
        catalogId: 'imported-a',
        importedRaster: { overlayLayerId: 'imported-a', timeList: ['t1'] },
      } as never,
      'tif',
      {
        time: 't1',
        bbox: { west: 1, south: 2, east: 3, north: 4, crs: 'EPSG:4326' },
        outputCrs: 'EPSG:3857',
        fields: ['a'],
      },
    )
    expect(exportImportedLayer).toHaveBeenCalledWith(
      'imported-a',
      'tif',
      expect.objectContaining({
        time: 't1',
        bbox: expect.objectContaining({ west: 1, east: 3 }),
        outputCrs: 'EPSG:3857',
        fields: ['a'],
      }),
    )
    expect(downloadBlob).toHaveBeenCalled()
  })

  it('rejects unsaved draw-draft layers with a save-first hint', async () => {
    await expect(
      exportLayer(
        { name: '绘制图层', catalogId: 'draw-draft-x', importedVector: { geojson: { type: 'FeatureCollection', features: [] } } } as never,
        'geojson',
      ),
    ).rejects.toThrow('尚未保存')
    expect(exportImportedLayer).not.toHaveBeenCalled()
    expect(downloadBlob).not.toHaveBeenCalled()
  })

  it('passes times to batch export', async () => {
    await exportLayersBatch(
      [
        {
          name: 'A',
          catalogId: 'imported-a',
          importedRaster: { overlayLayerId: 'imported-a' },
        } as never,
        {
          name: 'B',
          catalogId: 'imported-b',
          importedRaster: { overlayLayerId: 'imported-b' },
        } as never,
      ],
      'tif',
      undefined,
      { times: ['t1', 't2'], encoding: 'auto' },
    )
    expect(exportBatchLayers).toHaveBeenCalledWith(
      ['imported-a', 'imported-b'],
      'tif',
      expect.objectContaining({ times: ['t1', 't2'] }),
    )
  })
})
