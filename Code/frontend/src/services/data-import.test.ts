import { describe, expect, it } from 'vitest'
import {
  classifyImportFile,
  fileExtension,
  normalizeShpResult,
  validateImportFile,
} from './data-import'

describe('data-import helpers', () => {
  it('classifies common extensions', () => {
    expect(classifyImportFile(new File([], 'a.geojson'))).toBe('vector')
    expect(classifyImportFile(new File([], 'b.ZIP'))).toBe('vector')
    expect(classifyImportFile(new File([], 'c.csv'))).toBe('csv')
    expect(classifyImportFile(new File([], 'd.tif'))).toBe('raster')
    expect(classifyImportFile(new File([], 'e.docx'))).toBe('unknown')
  })

  it('validates empty and oversized files', () => {
    expect(() => validateImportFile(new File([], 'x.geojson'), 'vector')).toThrow(/空/)
    const big = new File([new Uint8Array(10)], 'big.tif')
    Object.defineProperty(big, 'size', { value: 200 * 1024 * 1024 })
    expect(() => validateImportFile(big, 'raster')).toThrow(/上限/)
  })

  it('normalizes shp.js array / object results', () => {
    const fc = {
      type: 'FeatureCollection',
      features: [
        { type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [1, 2] } },
      ],
    } as GeoJSON.FeatureCollection
    expect(normalizeShpResult(fc).layerCount).toBe(1)
    expect(normalizeShpResult([fc, fc]).layerCount).toBe(2)
    expect(normalizeShpResult([fc, fc]).geojson.features).toHaveLength(2)
    expect(normalizeShpResult({ layer_a: fc, layer_b: fc }).layerCount).toBe(2)
  })

  it('reads extension', () => {
    expect(fileExtension('Foo.Bar.TIF')).toBe('tif')
  })
})
