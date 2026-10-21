import { ref } from 'vue'
import { defineStore } from 'pinia'

import {
  fetchGeneralConfig,
  fetchApiKeys,
  updateApiKey,
  deleteApiKey,
  testApiKey,
  toggleApiKey,
  fetchApiKeyHistory,
  restoreApiKeyHistory,
  deleteApiKeyHistoryEntry,
  clearApiKeyHistory,
  fetchGeeAccounts,
  createGeeAccount,
  deleteGeeAccount,
  testGeeAccount,
  toggleGeeAccount,
  reloadGeeAccounts,
  fetchGeeRuntimeConfig,
  fetchWeatherConfig,
  updateWeatherDefaultModel,
  fetchWeatherProviders,
  updateWeatherProvider,
  testWeatherProvider,
  toggleWeatherProvider,
  setWeatherProviderPriority,
  deleteWeatherProvider,
  fetchOnlineTileSources,
  upsertOnlineTileSource,
  deleteOnlineTileSource,
  fetchDataSourceConfig,
  fetchAboutInfo,
  updateRuntimeConfig,
  fetchRemoteStorageProfiles,
  fetchPortalCatalog,
  upsertPortal,
  deletePortal,
  testPortal,
  fetchAvailableDatasets,
  upsertAvailableDataset,
  deleteAvailableDataset,
  rescanAvailableDatasets,
  fetchRemoteSources,
  upsertRemoteSource,
  deleteRemoteSource,
  toggleRemoteSourceAccessMode as _toggleRemoteSourceAccessModeApi,
  upsertRemoteStorageProfile,
  deleteRemoteStorageProfile,
  toggleRemoteStorageProfile,
  testRemoteStorageProfile,
  fetchRemoteStorageHistory,
  restoreRemoteStorageHistory,
  deleteRemoteStorageHistoryEntry,
  clearRemoteStorageHistory,
  type ApiKeyItem,
  type ApiKeyUpdateRequest,
  type ApiKeyHistoryItem,
  type GeeAccountItem,
  type GeeAccountCreateRequest,
  type GeeRuntimeConfig,
  type WeatherConfig,
  type WeatherProviderItem,
  type WeatherProviderUpdateRequest,
  type WeatherProviderTestResponse,
  type OnlineTileSource,
  type OnlineTileSourceUpsertRequest,
  type GeneralConfig,
  type DataSourceConfig,
  type AboutInfo,
  type TestResultResponse,
  type RuntimeConfigPatch,
  type RemoteStorageProfile,
  type RemoteStorageUpsertRequest,
  type RemoteStorageTestResponse,
  type RemoteStorageHistoryItem,
  type PortalCatalogEntry,
  type PortalTestResponse,
  type PortalUpsertRequest,
  type AvailableDatasetEntry,
  type DatasetUpsertRequest,
  type DatasetRescanResponse,
  type RemoteSourceEntry,
  type RemoteSourceUpsertRequest,
} from '../services/settings-api'
import { hydrateMapDefaults } from '../services/map-defaults'
import { ApiRequestError, SessionExpiredError } from '../services/http-errors'
import { safeLog } from './log'
import { useAuthStore } from './auth'

/**
 * 401 / 403 属「确定性拒绝」：同一身份重试必然还是失败。
 * 识别出来只是为了不再重试（重试只会让日志多一条、并拖慢面板打开）。
 */
function isAuthDenied(err: unknown): boolean {
  if (err instanceof ApiRequestError) return err.status === 401 || err.status === 403
  if (err instanceof SessionExpiredError) return true
  return false
}

type LoaderName =
  | 'general'
  | 'api-keys'
  | 'gee-accounts'
  | 'gee-runtime'
  | 'weather'
  | 'weather-providers'
  | 'data-source'
  | 'remote-storage'
  | 'portals'
  | 'datasets'
  | 'remote-sources'
  | 'online-tile-sources'
  | 'about'

const LOADER_LABELS: Record<LoaderName, string> = {
  general: '常规设置',
  'api-keys': 'API Key',
  'gee-accounts': 'GEE 账户',
  'gee-runtime': 'GEE 运行时',
  weather: '天气引擎',
  'weather-providers': '天气源',
  'data-source': '数据源',
  'remote-storage': '远程与存储',
  portals: '开放门户',
  datasets: '可用数据集',
  'remote-sources': '远程数据源',
  'online-tile-sources': '在线瓦片源',
  about: '关于',
}

type SettledResult<T> = {
  name: LoaderName
  value?: T
  error?: string
  /** 401 / 403：确定性拒绝，调用方不应重试 */
  authDenied?: boolean
}

async function settled<T>(name: LoaderName, fn: () => Promise<T>): Promise<SettledResult<T>> {
  try {
    return { name, value: await fn() }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    console.warn(`[settings] load ${name} failed:`, message)
    safeLog('client-error', `配置加载失败: ${name}`, message, 'warn')
    return { name, error: message, authDenied: isAuthDenied(err) }
  }
}

export const useSettingsStore = defineStore('settings', () => {
  const apiKeys = ref<ApiKeyItem[]>([])
  const apiKeyHistory = ref<Record<string, ApiKeyHistoryItem[]>>({})
  const geeAccounts = ref<GeeAccountItem[]>([])
  const geeRuntimeConfig = ref<GeeRuntimeConfig | null>(null)
  const weatherConfig = ref<WeatherConfig | null>(null)
  const weatherProviders = ref<WeatherProviderItem[]>([])
  const generalConfig = ref<GeneralConfig | null>(null)
  const dataSourceConfig = ref<DataSourceConfig | null>(null)
  const remoteStorageProfiles = ref<RemoteStorageProfile[]>([])
  const remoteStorageHistory = ref<Record<string, RemoteStorageHistoryItem[]>>({})
  const portalCatalog = ref<PortalCatalogEntry[]>([])
  const availableDatasets = ref<AvailableDatasetEntry[]>([])
  const remoteSourceRegistry = ref<RemoteSourceEntry[]>([])
  const onlineTileSources = ref<OnlineTileSource[]>([])
  const aboutInfo = ref<AboutInfo | null>(null)
  const loading = ref(false)
  /** 致命错误：核心配置不可用，界面阻断 */
  const error = ref<string | null>(null)
  /** 部分失败提示：不阻断已成功分区 */
  const partialError = ref<string | null>(null)
  const failedLoaders = ref<LoaderName[]>([])

  async function loadAll(options?: { quiet?: boolean }) {
    const authStore = useAuthStore()
    /**
     * 受限登录态（demo 游客，见 auth.isRestrictedRole）：后端对系统配置读取一律 403。
     * 那就**干脆不发**这些必然失败的私有接口，只保留公开的「关于」—— 避免
     * 「必然 403 → 自动重试 → 每次失败再写一条前端日志」把日志刷满。
     *
     * ⚠️ 权限没有任何变化：界面依旧读不到系统配置（只是不再明知故问）。
     * 无鉴权部署下 isRestrictedRole 恒为 false，此分支不生效。
     */
    const restricted = authStore.isRestrictedRole

    // quiet：已有数据时后台刷新，不挡面板内容区（避免二次打开白等）
    const quiet = Boolean(options?.quiet && generalConfig.value)
    if (!quiet) {
      loading.value = true
    }
    error.value = null
    partialError.value = null
    failedLoaders.value = []

    // 关键路径先返回：常规配置拿到即可解除整页 spinner。
    // 数据源扫描等慢接口放第二批，避免拖住整个设置面板。
    const criticalBatch = (): Promise<SettledResult<unknown>[]> =>
      restricted
        ? Promise.all([settled('about', fetchAboutInfo)])
        : Promise.all([
            settled('general', fetchGeneralConfig),
            settled('api-keys', fetchApiKeys),
            settled('about', fetchAboutInfo),
          ])

    const deferredBatch = (): Promise<SettledResult<unknown>[]> =>
      restricted
        ? Promise.resolve([])
        : Promise.all([
            settled('gee-accounts', fetchGeeAccounts),
            settled('gee-runtime', fetchGeeRuntimeConfig),
            settled('weather', fetchWeatherConfig),
            settled('weather-providers', fetchWeatherProviders),
            settled('data-source', fetchDataSourceConfig),
            settled('remote-storage', fetchRemoteStorageProfiles),
            settled('portals', async () => (await fetchPortalCatalog()).portals ?? []),
            settled('datasets', () => fetchAvailableDatasets(true)),
            settled('remote-sources', fetchRemoteSources),
            settled('online-tile-sources', fetchOnlineTileSources),
          ])

    const applyResult = (r: Awaited<ReturnType<typeof settled>>) => {
      if (r.value === undefined) return
      switch (r.name) {
        case 'general': {
          const general = r.value as GeneralConfig | null
          generalConfig.value = general
          if (general) {
            hydrateMapDefaults({
              longitude: general.map_default_longitude,
              latitude: general.map_default_latitude,
              zoom: general.map_default_zoom,
              tileSource: general.map_default_tile_source,
              aoiPresets: general.map_aoi_presets,
            })
          }
          break
        }
        case 'api-keys':
          apiKeys.value = r.value as ApiKeyItem[]
          break
        case 'gee-accounts':
          geeAccounts.value = r.value as GeeAccountItem[]
          break
        case 'gee-runtime':
          geeRuntimeConfig.value = r.value as GeeRuntimeConfig
          break
        case 'weather':
          weatherConfig.value = r.value as WeatherConfig
          break
        case 'weather-providers':
          weatherProviders.value = r.value as WeatherProviderItem[]
          break
        case 'data-source':
          dataSourceConfig.value = r.value as DataSourceConfig
          break
        case 'remote-storage':
          remoteStorageProfiles.value = r.value as RemoteStorageProfile[]
          break
        case 'portals':
          portalCatalog.value = r.value as PortalCatalogEntry[]
          break
        case 'datasets':
          availableDatasets.value = r.value as AvailableDatasetEntry[]
          break
        case 'remote-sources':
          remoteSourceRegistry.value = r.value as RemoteSourceEntry[]
          break
        case 'online-tile-sources':
          onlineTileSources.value = r.value as OnlineTileSource[]
          break
        case 'about':
          aboutInfo.value = r.value as AboutInfo
          break
      }
    }

    let critical: SettledResult<unknown>[] = await criticalBatch()
    // 401 / 403 不重试：同一身份再问一次还是 403，只会多留一条日志
    const criticalFailed = critical.filter((r) => r.error && !r.authDenied)
    if (criticalFailed.length > 0) {
      await new Promise((resolve) => window.setTimeout(resolve, quiet ? 120 : 250))
      const retryMap = new Map<LoaderName, Awaited<ReturnType<typeof settled>>>()
      await Promise.all(
        criticalFailed.map(async (item) => {
          const loader = {
            general: () => settled('general', fetchGeneralConfig),
            'api-keys': () => settled('api-keys', fetchApiKeys),
            about: () => settled('about', fetchAboutInfo),
          }[item.name as 'general' | 'api-keys' | 'about']
          if (loader) retryMap.set(item.name, await loader())
        }),
      )
      critical = critical.map((r) => retryMap.get(r.name) ?? r) as typeof critical
    }
    for (const r of critical) applyResult(r)

    // 常规配置已就绪：立刻放开内容区，其余分区后台继续
    if (generalConfig.value) {
      loading.value = false
    }

    let deferred: SettledResult<unknown>[] = await deferredBatch()
    // 同上：401 / 403 不重试
    const deferredFailed = deferred.filter((r) => r.error && !r.authDenied)
    if (deferredFailed.length > 0) {
      await new Promise((resolve) => window.setTimeout(resolve, quiet ? 120 : 250))
      const retryMap = new Map<LoaderName, Awaited<ReturnType<typeof settled>>>()
      await Promise.all(
        deferredFailed.map(async (item) => {
          const loader = {
            'gee-accounts': () => settled('gee-accounts', fetchGeeAccounts),
            'gee-runtime': () => settled('gee-runtime', fetchGeeRuntimeConfig),
            weather: () => settled('weather', fetchWeatherConfig),
            'weather-providers': () => settled('weather-providers', fetchWeatherProviders),
            'data-source': () => settled('data-source', fetchDataSourceConfig),
            'remote-storage': () => settled('remote-storage', fetchRemoteStorageProfiles),
            portals: async () =>
              settled('portals', async () => (await fetchPortalCatalog()).portals ?? []),
            datasets: () => settled('datasets', () => fetchAvailableDatasets(true)),
            'remote-sources': () => settled('remote-sources', fetchRemoteSources),
          }[item.name as Exclude<LoaderName, 'general' | 'api-keys' | 'about'>]
          if (loader) retryMap.set(item.name, await loader())
        }),
      )
      deferred = deferred.map((r) => retryMap.get(r.name) ?? r) as typeof deferred
    }
    for (const r of deferred) applyResult(r)

    const results = [...critical, ...deferred]
    const failures = results.filter((r) => r.error)
    failedLoaders.value = failures.map((f) => f.name)
    if (failures.length > 0) {
      const labels = failures.map((f) => LOADER_LABELS[f.name]).join('、')
      partialError.value = `部分配置加载失败：${labels}。可重试或先查看其它分区。`
    }

    // 受限登录态下我们本就没请求 general（读了也必然 403），此时 generalConfig
    // 为空是预期结果，不能据此判定「连不上配置服务」——否则会误报整页错误。
    if (!restricted && !generalConfig.value) {
      error.value =
        failures.find((f) => f.name === 'general')?.error ??
        '无法连接配置服务（请确认后端已启动，且 Vite 已代理 /config）'
    }

    loading.value = false
  }

  // ── API Key ──────────────────────────────────────────────────────────────

  async function loadApiKeys() {
    /**
     * 受限登录态（demo 游客）：后端 `require_config_read_access` 把「敏感配置读取」
     * 等同于可写角色（admin / standard），demo 一律 403
     * （2026-10-20 起 detail 改为只读语义的
     *  「This account is not allowed to view system configuration.」，
     *  原先借用写接口文案「Demo account cannot perform write operations.」，
     *  把「无权查看」说成「不能写」，日志里极易误导）。
     *
     * 前端原先只有 `loadAll()` 做了跳过，但顶部工具栏 `ModeToolbar` 挂载时会单独
     * 调一次本函数，于是 demo 每次进页面都必然 403、每次都往日志面板写一条
     * 「设置 API 失败 403 /config/api-keys」。
     *
     * ⚠️ 权限没有任何变化：界面依旧读不到密钥（只是不再明知故问）。
     * 无鉴权部署下 isRestrictedRole 恒为 false，此分支不生效。
     */
    if (useAuthStore().isRestrictedRole) {
      apiKeys.value = []
      return
    }
    apiKeys.value = await fetchApiKeys()
  }

  async function saveApiKey(keyName: string, request: ApiKeyUpdateRequest) {
    const updated = await updateApiKey(keyName, request)
    await loadApiKeys()
    return updated
  }

  async function removeApiKey(keyName: string) {
    await deleteApiKey(keyName)
    await loadApiKeys()
  }

  async function runApiKeyTest(keyName: string): Promise<TestResultResponse> {
    const result = await testApiKey(keyName)
    await loadApiKeys()
    return result
  }

  async function toggleApiKeyEnabled(keyName: string, enabled: boolean) {
    await toggleApiKey(keyName, enabled)
    await loadApiKeys()
  }

  async function loadApiKeyHistory(keyName: string) {
    apiKeyHistory.value = {
      ...apiKeyHistory.value,
      [keyName]: await fetchApiKeyHistory(keyName),
    }
  }

  async function restoreApiKeyFromHistory(keyName: string, historyId: number) {
    const updated = await restoreApiKeyHistory(keyName, historyId)
    await loadApiKeys()
    await loadApiKeyHistory(keyName)
    return updated
  }

  async function removeApiKeyHistoryEntry(keyName: string, historyId: number) {
    await deleteApiKeyHistoryEntry(keyName, historyId)
    await loadApiKeyHistory(keyName)
  }

  async function clearApiKeyHistoryFor(keyName: string) {
    await clearApiKeyHistory(keyName)
    await loadApiKeyHistory(keyName)
  }

  /** Effective basemap key available for tile proxy (enabled + has value). */
  function isBasemapApiKeyAvailable(keyName: string): boolean {
    const item = apiKeys.value.find((k) => k.key_name === keyName)
    if (!item) return false
    const hasValue = item.has_value ?? Boolean(item.masked_value)
    return Boolean(item.enabled && hasValue)
  }

  // ── GEE 账户 ─────────────────────────────────────────────────────────────

  async function loadGeeAccounts() {
    geeAccounts.value = await fetchGeeAccounts()
  }

  async function addGeeAccount(request: GeeAccountCreateRequest) {
    const created = await createGeeAccount(request)
    await loadGeeAccounts()
    return created
  }

  async function removeGeeAccount(accountId: string) {
    await deleteGeeAccount(accountId)
    await loadGeeAccounts()
  }

  async function runGeeAccountTest(accountId: string): Promise<TestResultResponse> {
    const result = await testGeeAccount(accountId)
    await loadGeeAccounts()
    return result
  }

  async function toggleGeeAccountEnabled(accountId: string, enabled: boolean) {
    await toggleGeeAccount(accountId, enabled)
    await loadGeeAccounts()
  }

  async function reloadGeePool() {
    return await reloadGeeAccounts()
  }

  // ── 天气源 Provider ─────────────────────────────────────────────────────

  async function loadWeatherProviders() {
    weatherProviders.value = await fetchWeatherProviders()
  }

  /**
   * 刷新 Provider 列表，但失败时不抛出错误。
   * 用于操作成功后的后台刷新：操作本身已成功，刷新失败不应让用户误以为操作失败。
   * 返回是否刷新成功。
   */
  async function _refreshProvidersSilently(): Promise<boolean> {
    try {
      weatherProviders.value = await fetchWeatherProviders()
      return true
    } catch (err) {
      console.warn(
        '[settings] refresh weather providers failed (operation may have succeeded):',
        err,
      )
      safeLog(
        'client-error',
        '天气 Provider 刷新失败',
        err instanceof Error ? err.message : String(err),
        'warn',
      )
      return false
    }
  }

  async function saveWeatherProvider(providerId: string, request: WeatherProviderUpdateRequest) {
    const updated = await updateWeatherProvider(providerId, request)
    await _refreshProvidersSilently()
    return updated
  }

  async function runWeatherProviderTest(providerId: string): Promise<WeatherProviderTestResponse> {
    const result = await testWeatherProvider(providerId)
    await _refreshProvidersSilently()
    return result
  }

  async function toggleWeatherProviderEnabled(providerId: string, enabled: boolean) {
    await toggleWeatherProvider(providerId, enabled)
    await _refreshProvidersSilently()
  }

  async function updateWeatherProviderPriority(providerId: string, priority: number) {
    await setWeatherProviderPriority(providerId, priority)
    await _refreshProvidersSilently()
  }

  async function removeWeatherProvider(providerId: string) {
    await deleteWeatherProvider(providerId)
    await _refreshProvidersSilently()
  }

  // ── 远程存储 ─────────────────────────────────────────────────────────────

  async function loadRemoteStorageProfiles() {
    remoteStorageProfiles.value = await fetchRemoteStorageProfiles()
  }

  async function saveRemoteStorageProfile(profileId: string, request: RemoteStorageUpsertRequest) {
    const updated = await upsertRemoteStorageProfile(profileId, request)
    await loadRemoteStorageProfiles()
    return updated
  }

  async function removeRemoteStorageProfile(profileId: string) {
    await deleteRemoteStorageProfile(profileId)
    await loadRemoteStorageProfiles()
  }

  async function toggleRemoteStorageProfileEnabled(profileId: string, enabled: boolean) {
    await toggleRemoteStorageProfile(profileId, enabled)
    await loadRemoteStorageProfiles()
  }

  async function runRemoteStorageTest(
    profileId: string,
    uri?: string | null,
  ): Promise<RemoteStorageTestResponse> {
    const result = await testRemoteStorageProfile(profileId, uri)
    await loadRemoteStorageProfiles()
    return result
  }

  async function loadRemoteStorageHistory(profileId: string) {
    remoteStorageHistory.value = {
      ...remoteStorageHistory.value,
      [profileId]: await fetchRemoteStorageHistory(profileId),
    }
  }

  async function restoreRemoteStorageFromHistory(profileId: string, historyId: number) {
    const updated = await restoreRemoteStorageHistory(profileId, historyId)
    await loadRemoteStorageProfiles()
    await loadRemoteStorageHistory(profileId)
    return updated
  }

  async function removeRemoteStorageHistoryEntry(profileId: string, historyId: number) {
    await deleteRemoteStorageHistoryEntry(profileId, historyId)
    await loadRemoteStorageHistory(profileId)
  }

  async function clearRemoteStorageHistoryFor(profileId: string) {
    await clearRemoteStorageHistory(profileId)
    await loadRemoteStorageHistory(profileId)
  }

  // ── 开放门户 ─────────────────────────────────────────────────────────────

  async function loadPortalCatalog() {
    const res = await fetchPortalCatalog()
    portalCatalog.value = res.portals ?? []
  }

  async function savePortal(portalId: string, request: PortalUpsertRequest) {
    const updated = await upsertPortal(portalId, request)
    await loadPortalCatalog()
    return updated
  }

  async function removePortal(portalId: string) {
    await deletePortal(portalId)
    await loadPortalCatalog()
  }

  async function runPortalTest(portalId: string): Promise<PortalTestResponse> {
    const result = await testPortal(portalId)
    await loadPortalCatalog()
    return result
  }

  // ── 可用数据集 ───────────────────────────────────────────────────────────

  async function loadAvailableDatasets(includeDisabled = true) {
    availableDatasets.value = await fetchAvailableDatasets(includeDisabled)
  }

  async function saveAvailableDataset(datasetId: string | null, request: DatasetUpsertRequest) {
    const updated = await upsertAvailableDataset(datasetId || 'new', request)
    await loadAvailableDatasets()
    return updated
  }

  async function removeAvailableDataset(datasetId: string) {
    await deleteAvailableDataset(datasetId)
    await loadAvailableDatasets()
  }

  async function runDatasetRescan(): Promise<DatasetRescanResponse> {
    const result = await rescanAvailableDatasets()
    await loadAvailableDatasets()
    return result
  }

  // ── 可访问远程数据源 ─────────────────────────────────────────────────────

  async function loadRemoteSources() {
    remoteSourceRegistry.value = await fetchRemoteSources()
  }

  async function saveRemoteSource(remoteSourceId: string, request: RemoteSourceUpsertRequest) {
    const updated = await upsertRemoteSource(remoteSourceId, request)
    await loadRemoteSources()
    return updated
  }

  async function removeRemoteSource(remoteSourceId: string) {
    await deleteRemoteSource(remoteSourceId)
    await loadRemoteSources()
  }

  /** Phase 4：切换远程数据源的访问模式（legacy ↔ site_compatible） */
  async function toggleRemoteSourceAccessMode(
    remoteSourceId: string,
    accessMode: 'legacy' | 'site_compatible',
  ) {
    await _toggleRemoteSourceAccessModeApi(remoteSourceId, accessMode)
    await loadRemoteSources()
  }

  async function loadOnlineTileSources() {
    onlineTileSources.value = await fetchOnlineTileSources()
  }

  async function saveOnlineTileSource(sourceId: string, request: OnlineTileSourceUpsertRequest) {
    const updated = await upsertOnlineTileSource(sourceId, request)
    await loadOnlineTileSources()
    return updated
  }

  async function removeOnlineTileSource(sourceId: string) {
    await deleteOnlineTileSource(sourceId)
    await loadOnlineTileSources()
  }

  async function saveWeatherDefaultModel(defaultModel: string) {
    const updated = await updateWeatherDefaultModel(defaultModel)
    weatherConfig.value = { ...(weatherConfig.value ?? ({} as WeatherConfig)), ...updated }
    return updated
  }

  /**
   * 重新拉取天气引擎公开配置（含 effective cache_ttl_seconds）
   *
   * ⚠️ 2026-10-21：这里**也必须**做受限登录态判断。
   * `loadAll()` 早就跳过 `/config/weather` 了，但 `useWeatherCoverage`（Dashboard
   * 挂载时）会直接调 `weatherEngine.ensureLoaded()` → 本函数，绕过了 loadAll 的
   * 过滤，于是 demo 每次进主界面都必然打一条
   * 「设置 API 失败 403 /config/weather」。
   *
   * 拒绝时返回 null、不发请求：调用方 `ensureLoaded` 会把 loaded 置 true，
   * `defaultModel` 走 WEATHER_MODEL_BOOTSTRAP 兜底，界面照常可用
   * （/weather/coverage 与 /weather/sync/overview 都是公开读接口，不受影响）。
   * 无鉴权部署下 isRestrictedRole 恒为 false，此分支不生效。
   */
  async function reloadWeatherConfig() {
    if (useAuthStore().isRestrictedRole) {
      return weatherConfig.value
    }
    weatherConfig.value = await fetchWeatherConfig()
    return weatherConfig.value
  }

  async function saveRuntimeConfig(patch: RuntimeConfigPatch | RuntimeConfigPatch[]) {
    const items = Array.isArray(patch) ? patch : [patch]
    const updated = await updateRuntimeConfig(items)
    return updated
  }

  return {
    apiKeys,
    apiKeyHistory,
    geeAccounts,
    geeRuntimeConfig,
    weatherConfig,
    weatherProviders,
    generalConfig,
    dataSourceConfig,
    remoteStorageProfiles,
    remoteStorageHistory,
    portalCatalog,
    aboutInfo,
    loading,
    error,
    partialError,
    failedLoaders,
    loadAll,
    loadApiKeys,
    saveApiKey,
    removeApiKey,
    runApiKeyTest,
    toggleApiKeyEnabled,
    loadApiKeyHistory,
    restoreApiKeyFromHistory,
    removeApiKeyHistoryEntry,
    clearApiKeyHistoryFor,
    isBasemapApiKeyAvailable,
    loadGeeAccounts,
    addGeeAccount,
    removeGeeAccount,
    runGeeAccountTest,
    toggleGeeAccountEnabled,
    reloadGeePool,
    loadWeatherProviders,
    saveWeatherProvider,
    runWeatherProviderTest,
    toggleWeatherProviderEnabled,
    updateWeatherProviderPriority,
    removeWeatherProvider,
    saveWeatherDefaultModel,
    reloadWeatherConfig,
    saveRuntimeConfig,
    loadRemoteStorageProfiles,
    saveRemoteStorageProfile,
    removeRemoteStorageProfile,
    toggleRemoteStorageProfileEnabled,
    runRemoteStorageTest,
    loadRemoteStorageHistory,
    restoreRemoteStorageFromHistory,
    removeRemoteStorageHistoryEntry,
    clearRemoteStorageHistoryFor,
    loadPortalCatalog,
    savePortal,
    removePortal,
    runPortalTest,
    availableDatasets,
    loadAvailableDatasets,
    onlineTileSources,
    loadOnlineTileSources,
    saveOnlineTileSource,
    removeOnlineTileSource,
    remoteSourceRegistry,
    saveAvailableDataset,
    removeAvailableDataset,
    runDatasetRescan,
    loadRemoteSources,
    saveRemoteSource,
    removeRemoteSource,
    toggleRemoteSourceAccessMode,
  }
})
