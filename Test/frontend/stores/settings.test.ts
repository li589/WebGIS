/**
 * W3.4d：settings store 测试。
 *
 * 覆盖 loadAll 两批加载与重试、分区状态归位、错误分级（error vs partialError）、
 * 各域 CRUD 动作（API Key / GEE / 天气源 / 远程存储 / 门户 / 数据集 / 远程数据源）、
 * isBasemapApiKeyAvailable、weatherConfig 合并与 runtime patch。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/services/settings-api', () => {
  const api = {
    fetchGeneralConfig: vi.fn(),
    fetchApiKeys: vi.fn(),
    updateApiKey: vi.fn(),
    deleteApiKey: vi.fn(),
    testApiKey: vi.fn(),
    toggleApiKey: vi.fn(),
    fetchApiKeyHistory: vi.fn(),
    restoreApiKeyHistory: vi.fn(),
    deleteApiKeyHistoryEntry: vi.fn(),
    clearApiKeyHistory: vi.fn(),
    fetchGeeAccounts: vi.fn(),
    createGeeAccount: vi.fn(),
    deleteGeeAccount: vi.fn(),
    testGeeAccount: vi.fn(),
    toggleGeeAccount: vi.fn(),
    reloadGeeAccounts: vi.fn(),
    fetchGeeRuntimeConfig: vi.fn(),
    fetchWeatherConfig: vi.fn(),
    updateWeatherDefaultModel: vi.fn(),
    fetchWeatherProviders: vi.fn(),
    updateWeatherProvider: vi.fn(),
    testWeatherProvider: vi.fn(),
    toggleWeatherProvider: vi.fn(),
    setWeatherProviderPriority: vi.fn(),
    deleteWeatherProvider: vi.fn(),
    fetchDataSourceConfig: vi.fn(),
    fetchOnlineTileSources: vi.fn(),
    fetchAboutInfo: vi.fn(),
    updateRuntimeConfig: vi.fn(),
    fetchRemoteStorageProfiles: vi.fn(),
    fetchPortalCatalog: vi.fn(),
    upsertPortal: vi.fn(),
    deletePortal: vi.fn(),
    testPortal: vi.fn(),
    fetchAvailableDatasets: vi.fn(),
    upsertAvailableDataset: vi.fn(),
    deleteAvailableDataset: vi.fn(),
    rescanAvailableDatasets: vi.fn(),
    fetchRemoteSources: vi.fn(),
    upsertRemoteSource: vi.fn(),
    deleteRemoteSource: vi.fn(),
    upsertRemoteStorageProfile: vi.fn(),
    deleteRemoteStorageProfile: vi.fn(),
    toggleRemoteStorageProfile: vi.fn(),
    testRemoteStorageProfile: vi.fn(),
    fetchRemoteStorageHistory: vi.fn(),
    restoreRemoteStorageHistory: vi.fn(),
    deleteRemoteStorageHistoryEntry: vi.fn(),
    clearRemoteStorageHistory: vi.fn(),
  }
  return api
})

vi.mock('@/services/map-defaults', () => ({
  hydrateMapDefaults: vi.fn(),
}))

vi.mock('@/stores/log', () => ({
  safeLog: vi.fn(),
  useLogStore: () => ({ entries: [], push: vi.fn() }),
}))

import * as settingsApi from '@/services/settings-api'
import { hydrateMapDefaults } from '@/services/map-defaults'
import { useSettingsStore } from '@/stores/settings'

const api = vi.mocked(settingsApi)

function mockAllResolve() {
  api.fetchGeneralConfig.mockResolvedValue({
    map_default_longitude: 116,
    map_default_latitude: 39,
    map_default_zoom: 5,
    map_default_tile_source: 'tianditu-vec',
    map_aoi_presets: [],
  } as never)
  api.fetchApiKeys.mockResolvedValue([{ key_name: 'tianditu', enabled: true, has_value: true }] as never)
  api.fetchAboutInfo.mockResolvedValue({ version: '1.0' } as never)
  api.fetchGeeAccounts.mockResolvedValue([{ account_id: 'g1' }] as never)
  api.fetchGeeRuntimeConfig.mockResolvedValue({ available: true } as never)
  api.fetchWeatherConfig.mockResolvedValue({ default_model: 'best_match' } as never)
  api.fetchWeatherProviders.mockResolvedValue([{ provider_id: 'p1' }] as never)
  api.fetchDataSourceConfig.mockResolvedValue({ data_root: 'I:/test' } as never)
  api.fetchOnlineTileSources.mockResolvedValue([] as never)
  api.fetchRemoteStorageProfiles.mockResolvedValue([{ profile_id: 'r1' }] as never)
  api.fetchPortalCatalog.mockResolvedValue({ portals: [{ portal_id: 'po1' }] } as never)
  api.fetchAvailableDatasets.mockResolvedValue([{ dataset_id: 'd1' }] as never)
  api.fetchRemoteSources.mockResolvedValue([{ source_id: 's1' }] as never)
}

beforeEach(() => {
  vi.clearAllMocks()
  setActivePinia(createPinia())
  // settings.ts 的重试退避使用 window.setTimeout；node 环境下补齐 window
  vi.stubGlobal('window', { setTimeout })
  mockAllResolve()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('loadAll', () => {
  it('全量成功：分区状态归位、hydrateMapDefaults 被调用、无错误', async () => {
    const store = useSettingsStore()
    await store.loadAll()
    expect(store.generalConfig).toMatchObject({ map_default_zoom: 5 })
    expect(store.apiKeys).toHaveLength(1)
    expect(store.aboutInfo).toMatchObject({ version: '1.0' })
    expect(store.geeAccounts).toHaveLength(1)
    expect(store.weatherProviders).toHaveLength(1)
    expect(store.dataSourceConfig).toMatchObject({ data_root: 'I:/test' })
    expect(store.remoteStorageProfiles).toHaveLength(1)
    expect(store.portalCatalog).toHaveLength(1)
    expect(store.availableDatasets).toHaveLength(1)
    expect(store.remoteSourceRegistry).toHaveLength(1)
    expect(store.loading).toBe(false)
    expect(store.error).toBeNull()
    expect(store.partialError).toBeNull()
    expect(store.failedLoaders).toEqual([])
    expect(hydrateMapDefaults).toHaveBeenCalledWith(expect.objectContaining({ zoom: 5 }))
  })

  it('关键批失败一次后重试成功：不产生用户可见错误', async () => {
    api.fetchGeneralConfig
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValue({ map_default_zoom: 4 } as never)
    const store = useSettingsStore()
    await store.loadAll()
    expect(store.generalConfig).toMatchObject({ map_default_zoom: 4 })
    expect(store.error).toBeNull()
    expect(store.partialError).toBeNull()
  })

  it('关键批持续失败：error 阻断 + failedLoaders 记录', async () => {
    api.fetchGeneralConfig.mockRejectedValue(new Error('backend down'))
    const store = useSettingsStore()
    await store.loadAll()
    expect(store.error).toBe('backend down')
    expect(store.failedLoaders).toContain('general')
    expect(store.loading).toBe(false)
  })

  it('延迟批部分失败：partialError 不阻断 + 中文标签拼接', async () => {
    api.fetchWeatherProviders.mockRejectedValue(new Error('x'))
    api.fetchRemoteSources.mockRejectedValue(new Error('y'))
    const store = useSettingsStore()
    await store.loadAll()
    expect(store.error).toBeNull()
    expect(store.partialError).toContain('天气源')
    expect(store.partialError).toContain('远程数据源')
    expect(store.failedLoaders).toEqual(
      expect.arrayContaining(['weather-providers', 'remote-sources']),
    )
  })

  it('quiet 模式：已有 general 时不重置 loading', async () => {
    const store = useSettingsStore()
    await store.loadAll()
    store.loading = false
    await store.loadAll({ quiet: true })
    expect(store.loading).toBe(false)
    expect(api.fetchGeneralConfig).toHaveBeenCalled()
  })

  it('general 缺失且关键批无 general 失败：error 给出连接指引', async () => {
    api.fetchGeneralConfig.mockResolvedValue(null as never)
    const store = useSettingsStore()
    await store.loadAll()
    expect(store.error).toContain('无法连接配置服务')
  })
})

describe('API Key 域', () => {
  it('save/remove/toggle/test 都会重载列表', async () => {
    const store = useSettingsStore()
    await store.saveApiKey('tianditu', { masked_value: '***' } as never)
    expect(api.updateApiKey).toHaveBeenCalledWith('tianditu', { masked_value: '***' })
    expect(api.fetchApiKeys).toHaveBeenCalled()

    await store.removeApiKey('tianditu')
    expect(api.deleteApiKey).toHaveBeenCalledWith('tianditu')

    await store.runApiKeyTest('tianditu')
    expect(api.testApiKey).toHaveBeenCalledWith('tianditu')

    await store.toggleApiKeyEnabled('tianditu', false)
    expect(api.toggleApiKey).toHaveBeenCalledWith('tianditu', false)
  })

  it('历史记录按 keyName 归档、恢复/删除/清空联动刷新', async () => {
    api.fetchApiKeyHistory.mockResolvedValue([{ history_id: 7 }] as never)
    api.restoreApiKeyHistory.mockResolvedValue({ key_name: 'k' } as never)
    const store = useSettingsStore()
    await store.loadApiKeyHistory('k')
    expect(store.apiKeyHistory['k']).toHaveLength(1)

    await store.restoreApiKeyFromHistory('k', 7)
    expect(api.restoreApiKeyHistory).toHaveBeenCalledWith('k', 7)

    await store.removeApiKeyHistoryEntry('k', 7)
    expect(api.deleteApiKeyHistoryEntry).toHaveBeenCalledWith('k', 7)

    await store.clearApiKeyHistoryFor('k')
    expect(api.clearApiKeyHistory).toHaveBeenCalledWith('k')
  })

  it('isBasemapApiKeyAvailable：enabled+has_value / masked 回退 / 缺失或禁用', async () => {
    api.fetchApiKeys.mockResolvedValue([
      { key_name: 'a', enabled: true, has_value: true },
      { key_name: 'b', enabled: true, masked_value: 'ab***' },
      { key_name: 'c', enabled: false, has_value: true },
    ] as never)
    const store = useSettingsStore()
    await store.loadApiKeys()
    expect(store.isBasemapApiKeyAvailable('a')).toBe(true)
    expect(store.isBasemapApiKeyAvailable('b')).toBe(true)
    expect(store.isBasemapApiKeyAvailable('c')).toBe(false)
    expect(store.isBasemapApiKeyAvailable('missing')).toBe(false)
  })
})

describe('GEE 域', () => {
  it('add/remove/test/toggle/reload 联动', async () => {
    api.createGeeAccount.mockResolvedValue({ account_id: 'g2' } as never)
    api.testGeeAccount.mockResolvedValue({ ok: true } as never)
    api.reloadGeeAccounts.mockResolvedValue({ reloaded: 2 } as never)
    const store = useSettingsStore()
    await store.addGeeAccount({ label: 'x' } as never)
    expect(api.createGeeAccount).toHaveBeenCalled()
    await store.removeGeeAccount('g1')
    expect(api.deleteGeeAccount).toHaveBeenCalledWith('g1')
    await store.runGeeAccountTest('g1')
    expect(api.testGeeAccount).toHaveBeenCalledWith('g1')
    await store.toggleGeeAccountEnabled('g1', false)
    expect(api.toggleGeeAccount).toHaveBeenCalledWith('g1', false)
    await expect(store.reloadGeePool()).resolves.toEqual({ reloaded: 2 })
  })
})

describe('天气源域', () => {
  it('save/test/toggle/priority/remove 后台刷新失败不抛错', async () => {
    api.updateWeatherProvider.mockResolvedValue({ provider_id: 'p1' } as never)
    api.testWeatherProvider.mockResolvedValue({ ok: true } as never)
    api.fetchWeatherProviders
      .mockResolvedValueOnce([{ provider_id: 'p1' }] as never)
      .mockRejectedValueOnce(new Error('refresh failed'))
    const store = useSettingsStore()
    await expect(store.saveWeatherProvider('p1', { label: 'x' } as never)).resolves.toBeDefined()
    // 刷新失败被吞掉，列表保持旧值
    await expect(store.runWeatherProviderTest('p1')).resolves.toBeDefined()
    await expect(store.toggleWeatherProviderEnabled('p1', true)).resolves.toBeUndefined()
    await expect(store.updateWeatherProviderPriority('p1', 2)).resolves.toBeUndefined()
    await expect(store.removeWeatherProvider('p1')).resolves.toBeUndefined()
    expect(api.deleteWeatherProvider).toHaveBeenCalledWith('p1')
  })

  it('saveWeatherDefaultModel 合并现有 weatherConfig', async () => {
    api.updateWeatherDefaultModel.mockResolvedValue({ default_model: 'ecmwf_ifs025' } as never)
    const store = useSettingsStore()
    await store.loadAll()
    await store.saveWeatherDefaultModel('ecmwf_ifs025')
    expect(store.weatherConfig).toMatchObject({ default_model: 'ecmwf_ifs025' })
  })

  it('reloadWeatherConfig 重新拉取并返回', async () => {
    api.fetchWeatherConfig.mockResolvedValue({ default_model: 'gfs_global' } as never)
    const store = useSettingsStore()
    await expect(store.reloadWeatherConfig()).resolves.toMatchObject({
      default_model: 'gfs_global',
    })
  })

  it('saveRuntimeConfig 支持单条与数组', async () => {
    api.updateRuntimeConfig.mockResolvedValue([] as never)
    const store = useSettingsStore()
    await store.saveRuntimeConfig({ key: 'a', value: '1' } as never)
    expect(api.updateRuntimeConfig).toHaveBeenCalledWith([{ key: 'a', value: '1' }])
    await store.saveRuntimeConfig([
      { key: 'a', value: '1' } as never,
      { key: 'b', value: '2' } as never,
    ])
    expect(api.updateRuntimeConfig).toHaveBeenLastCalledWith([
      { key: 'a', value: '1' },
      { key: 'b', value: '2' },
    ])
  })
})

describe('远程存储域', () => {
  it('save/remove/toggle/test 与历史记录联动', async () => {
    api.upsertRemoteStorageProfile.mockResolvedValue({ profile_id: 'r1' } as never)
    api.testRemoteStorageProfile.mockResolvedValue({ ok: true } as never)
    api.fetchRemoteStorageHistory.mockResolvedValue([{ history_id: 3 }] as never)
    api.restoreRemoteStorageHistory.mockResolvedValue({ profile_id: 'r1' } as never)
    const store = useSettingsStore()
    await store.saveRemoteStorageProfile('r1', { label: 'l' } as never)
    expect(api.upsertRemoteStorageProfile).toHaveBeenCalledWith('r1', { label: 'l' })
    await store.removeRemoteStorageProfile('r1')
    expect(api.deleteRemoteStorageProfile).toHaveBeenCalledWith('r1')
    await store.toggleRemoteStorageProfileEnabled('r1', false)
    expect(api.toggleRemoteStorageProfile).toHaveBeenCalledWith('r1', false)
    await store.runRemoteStorageTest('r1', 's3://x')
    expect(api.testRemoteStorageProfile).toHaveBeenCalledWith('r1', 's3://x')
    await store.loadRemoteStorageHistory('r1')
    expect(store.remoteStorageHistory['r1']).toHaveLength(1)
    await store.restoreRemoteStorageFromHistory('r1', 3)
    expect(api.restoreRemoteStorageHistory).toHaveBeenCalledWith('r1', 3)
    await store.removeRemoteStorageHistoryEntry('r1', 3)
    expect(api.deleteRemoteStorageHistoryEntry).toHaveBeenCalledWith('r1', 3)
    await store.clearRemoteStorageHistoryFor('r1')
    expect(api.clearRemoteStorageHistory).toHaveBeenCalledWith('r1')
  })
})

describe('门户 / 数据集 / 远程数据源域', () => {
  it('门户 save/remove/test 后重载目录', async () => {
    api.upsertPortal.mockResolvedValue({ portal_id: 'po1' } as never)
    api.testPortal.mockResolvedValue({ ok: true } as never)
    const store = useSettingsStore()
    await store.savePortal('po1', { name: 'n' } as never)
    expect(api.upsertPortal).toHaveBeenCalledWith('po1', { name: 'n' })
    await store.removePortal('po1')
    expect(api.deletePortal).toHaveBeenCalledWith('po1')
    await store.runPortalTest('po1')
    expect(api.testPortal).toHaveBeenCalledWith('po1')
    expect(store.portalCatalog).toHaveLength(1)
  })

  it('数据集：null id 走 new、rescan 返回结果', async () => {
    api.upsertAvailableDataset.mockResolvedValue({ dataset_id: 'd2' } as never)
    api.rescanAvailableDatasets.mockResolvedValue({ scanned: 3 } as never)
    const store = useSettingsStore()
    await store.saveAvailableDataset(null, { name: 'x' } as never)
    expect(api.upsertAvailableDataset).toHaveBeenCalledWith('new', { name: 'x' })
    await store.removeAvailableDataset('d1')
    expect(api.deleteAvailableDataset).toHaveBeenCalledWith('d1')
    await expect(store.runDatasetRescan()).resolves.toEqual({ scanned: 3 })
    await store.loadAvailableDatasets(false)
    expect(api.fetchAvailableDatasets).toHaveBeenCalledWith(false)
  })

  it('远程数据源 save/remove 联动', async () => {
    api.upsertRemoteSource.mockResolvedValue({ source_id: 's1' } as never)
    const store = useSettingsStore()
    await store.saveRemoteSource('s1', { label: 'l' } as never)
    expect(api.upsertRemoteSource).toHaveBeenCalledWith('s1', { label: 'l' })
    await store.removeRemoteSource('s1')
    expect(api.deleteRemoteSource).toHaveBeenCalledWith('s1')
  })
})
