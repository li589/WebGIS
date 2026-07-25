import { describe, expect, it } from 'vitest'

import { classifyDataFile, fileExtension } from '../data-manager/core/api'
import { DATA_COPY } from './data'
import { basemapProviderShort } from './basemap'

describe('data-io classify', () => {
  it('classifies vector / raster / document extensions', () => {
    expect(classifyDataFile(new File([], 'a.shp'))).toBe('vector')
    expect(classifyDataFile(new File([], 'a.dbf'))).toBe('vector')
    expect(classifyDataFile(new File([], 'a.sbn'))).toBe('vector')
    expect(classifyDataFile(new File([], 'a.sbx'))).toBe('vector')
    expect(classifyDataFile(new File([], 'a.zip'))).toBe('vector')
    expect(classifyDataFile(new File([], 'a.tif'))).toBe('raster')
    expect(classifyDataFile(new File([], 'a.nc'))).toBe('raster')
    expect(classifyDataFile(new File([], 'a.mat'))).toBe('raster')
    expect(classifyDataFile(new File([], 'a.csv'))).toBe('document')
    expect(classifyDataFile(new File([], 'a.xlsx'))).toBe('document')
    expect(classifyDataFile(new File([], 'a.txt'))).toBe('document')
    expect(classifyDataFile(new File([], 'a.bin'))).toBe('unknown')
    expect(classifyDataFile(new File([], 'evil.exe'))).toBe('unknown')
    expect(classifyDataFile(new File([], 'x.py'))).toBe('unknown')
  })

  it('parses extension', () => {
    expect(fileExtension('Foo.Bar.SHP')).toBe('shp')
  })
})

describe('data copy + terrain pill shorts', () => {
  it('keeps 数据 menu labels', () => {
    expect(DATA_COPY.menuLabel).toBe('数据')
    expect(DATA_COPY.import).toBe('导入')
    expect(DATA_COPY.export).toBe('导出')
    expect(DATA_COPY.workspaceTitle).toBe('数据工作台')
    expect(DATA_COPY.wsAttributes).toBe('属性表')
    expect(DATA_COPY.wsJobs).toBe('作业')
  })

  it('disambiguates terrain Esri pills', () => {
    expect(basemapProviderShort('esri-terrain', 'Esri')).toBe('Esri图')
    expect(basemapProviderShort('esri-hillshade', 'Esri')).toBe('Esri晕')
    expect(basemapProviderShort('opentopo-terrain', 'OpenTopo')).toBe('OTM')
    expect(basemapProviderShort('tianditu-ter', 'Tianditu')).toBe('天地')
  })
})
