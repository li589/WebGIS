/**
 * 图层平台 P1 / 鉴权：ACL 资源目录服务测试。
 *
 * 覆盖：后端目录汇聚（图层/分组/工作流映射、工作流跨端点去重）、
 * 数据源静态清单、部分端点失败时的静态兜底。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const requestJsonMock = vi.hoisted(() => vi.fn())

vi.mock('@/services/_http', () => ({
  requestJson: requestJsonMock,
}))

import {
  fetchPermissionResourceCatalog,
  KNOWN_DATA_SOURCES,
} from '@/services/permission-resources'

function mockEndpoint(url: string, data: unknown) {
  requestJsonMock.mockImplementation(async (u: string) => {
    if (u === url) return data
    throw new Error(`unexpected url: ${u}`)
  })
}

beforeEach(() => {
  requestJsonMock.mockReset()
})

describe('fetchPermissionResourceCatalog：后端目录汇聚', () => {
  it('映射图层（display_name + category hint）、分组（自建/种子标注）、工作流（跨端点去重）', async () => {
    requestJsonMock.mockImplementation(async (url: string) => {
      switch (url) {
        case '/layers':
          return {
            items: [
              { layer_id: 'wind-field', display_name: '风场（10m）', category: 'weather' },
              { layer_id: 'smap-omega', display_name: 'SMAP 反演 ω', category: 'research-group' },
            ],
          }
        case '/layers/categories':
          return {
            items: [
              { id: 'weather', name: '在线天气', is_custom: false },
              { id: 'lab-custom', name: '课题组专用', is_custom: true },
            ],
          }
        case '/algorithm/workflows':
          return { body: { workflows: [{ name: 'smap-soil-inversion', description: 'SMAP 反演' }] } }
        case '/provider/workflows':
          return {
            body: {
              workflows: [
                { name: 'smap-soil-inversion', description: 'SMAP 反演' },
                { name: 'provider-only', description: '仅 provider 注册' },
              ],
            },
          }
        default:
          throw new Error(`unexpected url: ${url}`)
      }
    })

    const catalog = await fetchPermissionResourceCatalog()

    expect(catalog.layers).toEqual([
      { id: 'wind-field', label: '风场（10m）', hint: 'weather' },
      { id: 'smap-omega', label: 'SMAP 反演 ω', hint: 'research-group' },
    ])
    expect(catalog.layerGroups).toEqual([
      { id: 'weather', label: '在线天气', hint: '种子分组' },
      { id: 'lab-custom', label: '课题组专用', hint: '自建分组' },
    ])
    // 跨 algorithm/provider 端点去重
    expect(catalog.workflows.map((w) => w.id)).toEqual(['smap-soil-inversion', 'provider-only'])
    // 数据源无列表端点：静态清单
    expect(catalog.dataSources).toBe(KNOWN_DATA_SOURCES)
    expect(catalog.dataSources.some((d) => d.id === 'open-meteo-local')).toBe(true)
  })

  it('图层目录为空时回落静态图层清单', async () => {
    requestJsonMock.mockImplementation(async (url: string) => {
      if (url === '/layers') return { items: [] }
      if (url === '/layers/categories') return { items: [] }
      throw new Error(`unexpected url: ${url}`)
    })
    const catalog = await fetchPermissionResourceCatalog()
    expect(catalog.layers.length).toBeGreaterThan(0)
    expect(catalog.workflows.length).toBeGreaterThan(0)
  })

  it('端点全部失败时不抛异常（各类别回落兜底）', async () => {
    requestJsonMock.mockRejectedValue(new Error('backend down'))
    const catalog = await fetchPermissionResourceCatalog()
    expect(catalog.layers.length).toBeGreaterThan(0)
    expect(catalog.layerGroups).toEqual([])
    expect(catalog.workflows.length).toBeGreaterThan(0)
    expect(catalog.dataSources).toBe(KNOWN_DATA_SOURCES)
  })
})
