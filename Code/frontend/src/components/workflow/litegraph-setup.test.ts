import { describe, expect, it } from 'vitest'
import {
  checkConnectionValid,
  getPortTypeLabel,
  mapParamTypeToPortType,
  resolveNodeEngine,
  suggestConnectorsForPortType,
} from './litegraph-setup'

describe('litegraph connection helpers', () => {
  it('allows identical port types', () => {
    expect(checkConnectionValid('value:time_range', 'value:time_range')).toBe(true)
    expect(checkConnectionValid('geometry:bbox', 'geometry:bbox')).toBe(true)
  })

  it('allows data generic with data subtypes only', () => {
    expect(checkConnectionValid('data', 'data:raster')).toBe(true)
    expect(checkConnectionValid('data:mat', 'data')).toBe(true)
    expect(checkConnectionValid('data', 'value:number')).toBe(false)
    expect(checkConnectionValid('geometry:bbox', 'data')).toBe(false)
  })

  it('rejects mismatched value/geometry types', () => {
    expect(checkConnectionValid('value:time_range', 'value:number')).toBe(false)
    expect(checkConnectionValid('geometry:bbox', 'value:time_range')).toBe(false)
  })

  it('maps params to connectable port types', () => {
    expect(mapParamTypeToPortType('number')).toBe('value:number')
    expect(mapParamTypeToPortType('boolean')).toBe('value:boolean')
    expect(mapParamTypeToPortType('string')).toBe('value:string')
    expect(mapParamTypeToPortType('enum')).toBe('value:string')
  })

  it('suggests connectors for common ports', () => {
    expect(suggestConnectorsForPortType('value:time_range')).toContain('data/time_range')
    expect(suggestConnectorsForPortType('geometry:bbox')).toEqual(
      expect.arrayContaining(['data/bbox', 'data/map_viewport']),
    )
    expect(getPortTypeLabel('geometry:bbox')).toContain('bbox')
  })

  it('resolves module/* as python_provider engine', () => {
    expect(resolveNodeEngine('module/smap_daily')).toBe('python_provider')
    expect(resolveNodeEngine('module/ndvi_daily', 'python_provider')).toBe('python_provider')
    expect(resolveNodeEngine('data/bbox', 'common')).toBe('common')
  })
})
