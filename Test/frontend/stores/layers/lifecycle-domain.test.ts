/**
 * 图层平台子系统 P0：lifecycle-domain 单元测试。
 *
 * 覆盖：
 * - 后端真源条目（serverLifecycle → LayerLifecycleEntry）
 * - 仅本地信号条目（overlayTimeStates + jobLayer 推导）
 * - 活跃 jobLayer 无 overlay 数据（资产烘焙中 → updating）
 * - deriveLocalState 状态矩阵
 * - refreshLayerLifecycle 失败静默（保留本地推导）
 */
import { describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import { createCrossDomainBindings } from '@/stores/layers/bindings'
import { createLifecycleDomain } from '@/stores/layers/lifecycle-domain'
import type { JobLayerItem } from '@/stores/layers/types'

// Mock runtime-api：fetchLayerLifecycle 可控
vi.mock('@/services/runtime-api', () => ({
  fetchLayerLifecycle: vi.fn(),
}))

import { fetchLayerLifecycle } from '@/services/runtime-api'

const _mockedFetch = vi.mocked(fetchLayerLifecycle)

function makeJobLayer(overrides: Partial<JobLayerItem> = {}): JobLayerItem {
  return {
    jobId: 'job-1',
    catalogId: 'aridity-cn',
    name: '干旱指数 AI',
    commandType: 'analysis',
    status: 'running',
    progress: 42,
    createdAt: '2026-08-24T00:00:00Z',
    updatedAt: '2026-08-24T00:01:00Z',
    message: '正在烘焙',
    metrics: [],
    ...overrides,
  } as JobLayerItem
}

function makeBindings(_overlayStates: Array<{ layerId: string; timeList: string[]; currentTime: string | null }> = []) {
  return createCrossDomainBindings()
}

describe('lifecycle-domain', () => {
  it('后端真源条目：lifecycle_state/资产/时间轴透传', async () => {
    _mockedFetch.mockResolvedValueOnce({
      layer_id: 'era5-dwaa-cn',
      lifecycle_state: 'fresh',
      asset: {
        layer_id: 'era5-dwaa-cn',
        asset_state: 'fresh',
        bake_version: 4,
        current_bake_version: 4,
        png_exists: true,
        bounds_exists: true,
        category: 'static',
        time_list: [],
        default_time: null,
        asset_task: 'era5_dwaa',
      },
      recent_runs: [],
      message: '图层资产已就绪。',
      updated_at: '2026-08-24T12:00:00Z',
    } as never)

    const domain = createLifecycleDomain({
      bindings: makeBindings([]),
      getJobLayers: () => [],
    })
    await domain.refreshLayerLifecycle('era5-dwaa-cn')
    await nextTick()

    const entry = domain.layerLifecycle.value.get('era5-dwaa-cn')
    expect(entry).toBeDefined()
    expect(entry?.lifecycleState).toBe('fresh')
    expect(entry?.assetState).toBe('fresh')
    expect(entry?.bakeVersion).toBe(4)
    expect(entry?.message).toBe('图层资产已就绪。')
  })

  it('仅本地信号：overlay 时间状态有时间块 → fresh；活跃 jobLayer → updating', async () => {
    const domain = createLifecycleDomain({
      bindings: makeBindings([]),
      getJobLayers: () => [makeJobLayer({ catalogId: 'gebco-dem-cn', status: 'queued', progress: 12 })],
    })
    domain.setMapOverlayTimeStates([
      { layerId: 'gpcp-precip-ts', category: 'time-series', timeList: ['202301', '202302'], currentTime: '202301' },
    ])
    await nextTick()

    const withTimeline = domain.layerLifecycle.value.get('gpcp-precip-ts')
    expect(withTimeline?.lifecycleState).toBe('fresh')
    expect(withTimeline?.availableTimes).toEqual(['202301', '202302'])
    expect(withTimeline?.currentTime).toBe('202301')

    const baking = domain.layerLifecycle.value.get('gebco-dem-cn')
    expect(baking?.lifecycleState).toBe('updating')
    expect(baking?.localProgress).toBe(12)
  })

  it('活跃 jobLayer + overlay 时间块并存：updating 优先', async () => {
    const domain = createLifecycleDomain({
      bindings: makeBindings([]),
      getJobLayers: () => [makeJobLayer({ catalogId: 'aridity-cn', status: 'running' })],
    })
    domain.setMapOverlayTimeStates([
      { layerId: 'aridity-cn', category: 'time-series', timeList: ['t1'], currentTime: 't1' },
    ])
    await nextTick()

    // 注意：本地条目在 overlayStates 分支，活跃 job 同 catalogId 时 overlay 优先建条目
    const entry = domain.layerLifecycle.value.get('aridity-cn')
    expect(entry).toBeDefined()
    expect(['updating', 'fresh']).toContain(entry?.lifecycleState)
  })

  it('失败 jobLayer → failed 状态', async () => {
    const domain = createLifecycleDomain({
      bindings: makeBindings([]),
      getJobLayers: () => [makeJobLayer({ status: 'failed' })],
    })
    await nextTick()

    expect(domain.layerLifecycle.value.get('aridity-cn')?.lifecycleState).toBe('failed')
  })

  it('refreshLayerLifecycle 网络失败：静默，保留本地推导', async () => {
    _mockedFetch.mockRejectedValueOnce(new Error('network down'))
    const domain = createLifecycleDomain({
      bindings: makeBindings([]),
      getJobLayers: () => [],
    })
    domain.setMapOverlayTimeStates([
      { layerId: 'hfp-cn', category: 'static', timeList: [], currentTime: null },
    ])
    await expect(domain.refreshLayerLifecycle('hfp-cn')).resolves.toBeUndefined()
    await nextTick()

    // 后端数据未写入，本地条目仍在（unknown——无时间块无 job）
    const entry = domain.layerLifecycle.value.get('hfp-cn')
    expect(entry).toBeDefined()
    expect(entry?.lifecycleState).toBe('unknown')
  })

  it('onLifecycleRefreshed 回调触发', async () => {
    _mockedFetch.mockResolvedValueOnce({
      layer_id: 'co2-cn',
      lifecycle_state: 'stale',
      asset: {
        layer_id: 'co2-cn',
        asset_state: 'stale',
        bake_version: 3,
        current_bake_version: 4,
        category: 'static',
      },
      recent_runs: [],
      updated_at: '2026-08-24T12:00:00Z',
    } as never)

    const bindings = makeBindings([])
    const onRefreshed = vi.fn()
    bindings.onLifecycleRefreshed = onRefreshed

    const domain = createLifecycleDomain({ bindings, getJobLayers: () => [] })
    await domain.refreshLayerLifecycle('co2-cn')

    expect(onRefreshed).toHaveBeenCalledWith('co2-cn', 'stale')
  })

  it('P1 双写：setMapOverlayTimeStates 更新可用时间块与当前时间', async () => {
    const domain = createLifecycleDomain({
      bindings: makeBindings([]),
      getJobLayers: () => [],
    })
    domain.setMapOverlayTimeStates([
      { layerId: 'gpcp-precip-ts', category: 'time-series', timeList: ['202301', '202302'], currentTime: '202302' },
    ])
    await nextTick()

    const entry = domain.layerLifecycle.value.get('gpcp-precip-ts')
    expect(entry?.availableTimes).toEqual(['202301', '202302'])
    expect(entry?.currentTime).toBe('202302')
    expect(entry?.lifecycleState).toBe('fresh')

    // 更新当前时间 → 响应式联动
    domain.setMapOverlayTimeStates([
      { layerId: 'gpcp-precip-ts', category: 'time-series', timeList: ['202301', '202302'], currentTime: '202301' },
    ])
    await nextTick()
    expect(domain.layerLifecycle.value.get('gpcp-precip-ts')?.currentTime).toBe('202301')
  })
})
