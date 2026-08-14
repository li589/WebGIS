/**
 * 配置管理 API 调用封装（/config/*、/runtime/config|status）。
 *
 * 类型单一来源：OpenAPI → `types/api-contracts.ts` → `types/api-reexports.ts`。
 * 本文件仅保留 fetch 封装与 re-export，勿手写 DTO。
 */

export type {
  AboutInfo,
  AboutModule,
  ApiKeyDeletedResponse,
  ApiKeyHistoryClearResponse,
  ApiKeyHistoryDeletedResponse,
  ApiKeyHistoryItem,
  ApiKeyItem,
  ApiKeyToggleRequest,
  ApiKeyUpdateRequest,
  AvailableDatasetEntry,
  BackendServiceStatus,
  CircuitState,
  DataCacheEntry,
  DataCacheEvictRequest,
  DataCacheEvictResponse,
  DataCacheOverview,
  DataSourceConfig,
  DataSourcePathsUpdateRequest,
  DataSourcePathsUpdateResponse,
  DatasetRescanResponse,
  DatasetSource,
  DatasetUpsertRequest,
  DeletedResponse,
  DiscoveredDataset,
  GeeAccountCreateRequest,
  GeeAccountDeletedResponse,
  GeeAccountItem,
  GeeAccountToggleRequest,
  GeeAccountToggleResponse,
  GeeRuntimeConfig,
  GeneralConfig,
  MapAoiPreset,
  MinioPublicConfig,
  OpenDataPresetsUpdateRequest,
  OpenDataPresetsUpdateResponse,
  PortalCatalogEntry,
  PortalCatalogResponse,
  PortalCredentialPublic,
  PortalCredentialUpsertRequest,
  PortalCredentialsMapResponse,
  PortalSearchResponse,
  PortalSearchResultItem,
  PortalTestResponse,
  PortalUpsertRequest,
  ReloadResultResponse,
  RemoteBrowseRequest,
  RemoteBrowseResponse,
  RemoteEntryItem,
  RemoteFailoverRequest,
  RemoteFailoverResponse,
  RemoteFallbackMode,
  RemoteLayerUrisUpdateRequest,
  RemoteLayerUrisUpdateResponse,
  RemoteSearchRequest,
  RemoteSearchResponse,
  RemoteSourceEntry,
  RemoteSourceKind,
  RemoteSourceRefBadge,
  RemoteSourceUpsertRequest,
  RemoteStorageDeletedResponse,
  RemoteStorageHistoryClearResponse,
  RemoteStorageHistoryDeletedResponse,
  RemoteStorageHistoryItem,
  RemoteStorageProfile,
  RemoteStorageProtocol,
  RemoteStorageTestRequest,
  RemoteStorageTestResponse,
  RemoteStorageToggleRequest,
  RemoteStorageToggleResponse,
  RemoteStorageUpsertRequest,
  ResourceUsageResponse,
  RuntimeConfigPatch,
  RuntimeConfigScope,
  RuntimeConfigSnapshotResponse,
  RuntimeConfigUpdateRequest,
  RuntimeConfigUpdateResponse,
  RuntimeStatusResponse,
  ServiceRestartRequest,
  ServiceRestartResponse,
  StaticCacheSummary,
  TestResultResponse,
  WeatherCapability,
  WeatherConfig,
  WeatherModelUpdateRequest,
  WeatherProviderConfigField,
  WeatherProviderDeletedResponse,
  WeatherProviderItem,
  WeatherProviderPriorityRequest,
  WeatherProviderPriorityResponse,
  WeatherProviderStatus,
  WeatherProviderTestResponse,
  WeatherProviderToggleRequest,
  WeatherProviderToggleResponse,
  WeatherProviderType,
  WeatherProviderUpdateRequest,
  WeatherSupportedModel,
  WeatherSyncCron,
} from '../types/api-reexports'

import { applyApiFetchDefaults } from './http-credentials'
import { extractErrorDetail, extractRequestId, SessionExpiredError } from './http-errors'
import { handleSessionExpired, isAuthBootstrapPath } from './session-expired'
import { withWriteAuthHeaders } from './backend-auth'
import { resolveApiUrl } from './runtime-api'
import { useLogStore } from '../stores/log'
import type {
  AboutInfo,
  ApiKeyDeletedResponse,
  ApiKeyHistoryClearResponse,
  ApiKeyHistoryDeletedResponse,
  ApiKeyHistoryItem,
  ApiKeyItem,
  ApiKeyToggleRequest,
  ApiKeyUpdateRequest,
  AvailableDatasetEntry,
  DataCacheEvictRequest,
  DataCacheEvictResponse,
  DataCacheOverview,
  DataSourceConfig,
  DataSourcePathsUpdateRequest,
  DataSourcePathsUpdateResponse,
  DatasetRescanResponse,
  DatasetUpsertRequest,
  DeletedResponse,
  GeeAccountCreateRequest,
  GeeAccountDeletedResponse,
  GeeAccountItem,
  GeeAccountToggleRequest,
  GeeAccountToggleResponse,
  GeeRuntimeConfig,
  GeneralConfig,
  OpenDataPresetsUpdateRequest,
  OpenDataPresetsUpdateResponse,
  PortalCatalogEntry,
  PortalCatalogResponse,
  PortalCredentialUpsertRequest,
  PortalCredentialsMapResponse,
  PortalSearchResponse,
  PortalTestResponse,
  PortalUpsertRequest,
  ReloadResultResponse,
  RemoteBrowseRequest,
  RemoteBrowseResponse,
  RemoteFailoverRequest,
  RemoteFailoverResponse,
  RemoteLayerUrisUpdateRequest,
  RemoteLayerUrisUpdateResponse,
  RemoteSearchRequest,
  RemoteSearchResponse,
  RemoteSourceEntry,
  RemoteSourceUpsertRequest,
  RemoteStorageDeletedResponse,
  RemoteStorageHistoryClearResponse,
  RemoteStorageHistoryDeletedResponse,
  RemoteStorageHistoryItem,
  RemoteStorageProfile,
  RemoteStorageTestRequest,
  RemoteStorageTestResponse,
  RemoteStorageToggleRequest,
  RemoteStorageToggleResponse,
  RemoteStorageUpsertRequest,
  ResourceUsageResponse,
  RuntimeConfigPatch,
  RuntimeConfigSnapshotResponse,
  RuntimeConfigUpdateRequest,
  RuntimeConfigUpdateResponse,
  RuntimeStatusResponse,
  ServiceRestartRequest,
  ServiceRestartResponse,
  TestResultResponse,
  WeatherConfig,
  WeatherModelUpdateRequest,
  WeatherProviderDeletedResponse,
  WeatherProviderItem,
  WeatherProviderPriorityRequest,
  WeatherProviderPriorityResponse,
  WeatherProviderTestResponse,
  WeatherProviderToggleRequest,
  WeatherProviderToggleResponse,
  WeatherProviderUpdateRequest,
} from '../types/api-reexports'

async function settingsFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const url = resolveApiUrl(path)
  const method = (init?.method ?? 'GET').toUpperCase()
  let headers: Record<string, string> = {
    ...(init?.headers as Record<string, string> | undefined),
  }
  if (method !== 'GET' && method !== 'HEAD' && init?.body != null) {
    headers['Content-Type'] = headers['Content-Type'] ?? 'application/json'
  }
  headers = withWriteAuthHeaders(headers, method, true)

  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), 15_000)
  try {
    const response = await fetch(
      url,
      applyApiFetchDefaults({
        ...init,
        headers,
        signal: init?.signal ?? controller.signal,
      }),
    )
    if (!response.ok) {
      let errorBody: unknown = null
      let errorDetail = ''
      try {
        errorBody = await response.json()
        errorDetail = extractErrorDetail(errorBody)
      } catch {
        errorDetail = await response.text().catch(() => '')
      }
      const requestId = extractRequestId(errorBody)
      const detailSuffix = requestId ? ` (request_id=${requestId})` : ''

      if (response.status === 401 && !isAuthBootstrapPath(path)) {
        try {
          useLogStore().logOperation('api-error', `未授权：${path}`, errorDetail)
        } catch {
          /* pinia unavailable in tests */
        }
        handleSessionExpired(path)
        throw new SessionExpiredError(path)
      }

      try {
        useLogStore().logOperation(
          'api-error',
          `设置 API 失败 ${response.status}`,
          `${path}${detailSuffix} — ${errorDetail.slice(0, 200)}`,
        )
      } catch {
        /* pinia unavailable in tests */
      }

      throw new Error(
        `Settings API failed: ${response.status} ${path}${errorDetail ? ` — ${errorDetail.slice(0, 200)}` : ''}`,
      )
    }
    return response.json() as Promise<T>
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error(`Settings API timeout: ${path}`, { cause: err })
    }
    if (err instanceof TypeError) {
      throw new Error(
        `Settings API unreachable: ${path}（请确认后端已启动，开发环境 Vite 需代理 /config）`,
        { cause: err },
      )
    }
    throw err
  } finally {
    window.clearTimeout(timeoutId)
  }
}

export function fetchGeneralConfig(): Promise<GeneralConfig> {
  return settingsFetch('/config/general')
}

export function fetchApiKeys(): Promise<ApiKeyItem[]> {
  return settingsFetch('/config/api-keys')
}

export function updateApiKey(keyName: string, request: ApiKeyUpdateRequest): Promise<ApiKeyItem> {
  return settingsFetch(`/config/api-keys/${encodeURIComponent(keyName)}`, {
    method: 'PUT',
    body: JSON.stringify(request),
  })
}

export function deleteApiKey(keyName: string): Promise<ApiKeyDeletedResponse> {
  return settingsFetch(`/config/api-keys/${encodeURIComponent(keyName)}`, {
    method: 'DELETE',
  })
}

export function testApiKey(keyName: string): Promise<TestResultResponse> {
  return settingsFetch(`/config/api-keys/${encodeURIComponent(keyName)}/test`, {
    method: 'POST',
  })
}

export function toggleApiKey(keyName: string, enabled: boolean): Promise<ApiKeyItem> {
  return settingsFetch(`/config/api-keys/${encodeURIComponent(keyName)}/toggle`, {
    method: 'PUT',
    body: JSON.stringify({ enabled } satisfies ApiKeyToggleRequest),
  })
}

export function fetchApiKeyHistory(keyName: string): Promise<ApiKeyHistoryItem[]> {
  return settingsFetch(`/config/api-keys/${encodeURIComponent(keyName)}/history`)
}

export function restoreApiKeyHistory(keyName: string, historyId: number): Promise<ApiKeyItem> {
  return settingsFetch(
    `/config/api-keys/${encodeURIComponent(keyName)}/history/${historyId}/restore`,
    { method: 'POST' },
  )
}

export function deleteApiKeyHistoryEntry(
  keyName: string,
  historyId: number,
): Promise<ApiKeyHistoryDeletedResponse> {
  return settingsFetch(`/config/api-keys/${encodeURIComponent(keyName)}/history/${historyId}`, {
    method: 'DELETE',
  })
}

export function clearApiKeyHistory(keyName: string): Promise<ApiKeyHistoryClearResponse> {
  return settingsFetch(`/config/api-keys/${encodeURIComponent(keyName)}/history`, {
    method: 'DELETE',
  })
}

export function fetchGeeAccounts(): Promise<GeeAccountItem[]> {
  return settingsFetch('/config/gee/accounts')
}

export function createGeeAccount(request: GeeAccountCreateRequest): Promise<GeeAccountItem> {
  return settingsFetch('/config/gee/accounts', {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

export function deleteGeeAccount(accountId: string): Promise<GeeAccountDeletedResponse> {
  return settingsFetch(`/config/gee/accounts/${encodeURIComponent(accountId)}`, {
    method: 'DELETE',
  })
}

export function testGeeAccount(accountId: string): Promise<TestResultResponse> {
  return settingsFetch(`/config/gee/accounts/${encodeURIComponent(accountId)}/test`, {
    method: 'POST',
  })
}

export function toggleGeeAccount(
  accountId: string,
  enabled: boolean,
): Promise<GeeAccountToggleResponse> {
  return settingsFetch(`/config/gee/accounts/${encodeURIComponent(accountId)}/toggle`, {
    method: 'PUT',
    body: JSON.stringify({ enabled } satisfies GeeAccountToggleRequest),
  })
}

export function reloadGeeAccounts(): Promise<ReloadResultResponse> {
  return settingsFetch('/config/gee/accounts/reload', {
    method: 'POST',
  })
}

export function fetchGeeRuntimeConfig(): Promise<GeeRuntimeConfig> {
  return settingsFetch('/config/gee/runtime')
}

export function fetchWeatherConfig(): Promise<WeatherConfig> {
  return settingsFetch('/config/weather')
}

export function updateWeatherDefaultModel(defaultModel: string): Promise<WeatherConfig> {
  return settingsFetch('/config/weather/model', {
    method: 'PUT',
    body: JSON.stringify({ default_model: defaultModel } satisfies WeatherModelUpdateRequest),
  })
}

export function fetchWeatherProviders(includeDisabled = true): Promise<WeatherProviderItem[]> {
  const query = includeDisabled ? '' : '?include_disabled=false'
  return settingsFetch(`/config/weather/providers${query}`)
}

export function fetchWeatherProvider(providerId: string): Promise<WeatherProviderItem> {
  return settingsFetch(`/config/weather/providers/${encodeURIComponent(providerId)}`)
}

export function updateWeatherProvider(
  providerId: string,
  request: WeatherProviderUpdateRequest,
): Promise<WeatherProviderItem> {
  return settingsFetch(`/config/weather/providers/${encodeURIComponent(providerId)}`, {
    method: 'PUT',
    body: JSON.stringify(request),
  })
}

export function testWeatherProvider(providerId: string): Promise<WeatherProviderTestResponse> {
  return settingsFetch(`/config/weather/providers/${encodeURIComponent(providerId)}/test`, {
    method: 'POST',
  })
}

export function toggleWeatherProvider(
  providerId: string,
  enabled: boolean,
): Promise<WeatherProviderToggleResponse> {
  return settingsFetch(`/config/weather/providers/${encodeURIComponent(providerId)}/toggle`, {
    method: 'PUT',
    body: JSON.stringify({ enabled } satisfies WeatherProviderToggleRequest),
  })
}

export function setWeatherProviderPriority(
  providerId: string,
  priority: number,
): Promise<WeatherProviderPriorityResponse> {
  return settingsFetch(`/config/weather/providers/${encodeURIComponent(providerId)}/priority`, {
    method: 'PUT',
    body: JSON.stringify({ priority } satisfies WeatherProviderPriorityRequest),
  })
}

export function deleteWeatherProvider(providerId: string): Promise<WeatherProviderDeletedResponse> {
  return settingsFetch(`/config/weather/providers/${encodeURIComponent(providerId)}`, {
    method: 'DELETE',
  })
}

export function fetchDataSourceConfig(): Promise<DataSourceConfig> {
  return settingsFetch('/config/data-source')
}

export function updateDataSourcePaths(
  payload: DataSourcePathsUpdateRequest,
): Promise<DataSourcePathsUpdateResponse> {
  return settingsFetch('/config/data-source/paths', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function restartBackendService(
  payload?: ServiceRestartRequest,
): Promise<ServiceRestartResponse> {
  return settingsFetch('/config/service/restart', {
    method: 'POST',
    body: JSON.stringify(payload ?? {}),
  })
}

export async function waitForBackendHealthy(options?: {
  timeoutMs?: number
  intervalMs?: number
}): Promise<boolean> {
  const timeoutMs = options?.timeoutMs ?? 120_000
  const intervalMs = options?.intervalMs ?? 2000
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    try {
      const res = await fetch(resolveApiUrl('/health'), { method: 'GET', cache: 'no-store' })
      if (res.ok) return true
    } catch {
      // still restarting
    }
    await new Promise((r) => setTimeout(r, intervalMs))
  }
  return false
}

export function fetchDataCacheOverview(): Promise<DataCacheOverview> {
  return settingsFetch('/config/data-cache/overview')
}

export function evictDataCache(
  payload: DataCacheEvictRequest = {},
): Promise<DataCacheEvictResponse> {
  return settingsFetch('/config/data-cache/evict', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateOpenDataPresets(
  open_data_presets: Record<string, string>,
): Promise<OpenDataPresetsUpdateResponse> {
  return settingsFetch('/config/data-source/open-data-presets', {
    method: 'PUT',
    body: JSON.stringify({ open_data_presets } satisfies OpenDataPresetsUpdateRequest),
  })
}

export function upsertPortalCredential(
  portalId: string,
  payload: PortalCredentialUpsertRequest,
): Promise<PortalCredentialsMapResponse> {
  return settingsFetch(`/config/data-source/portal-credentials/${encodeURIComponent(portalId)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function deletePortalCredential(portalId: string): Promise<PortalCredentialsMapResponse> {
  return settingsFetch(`/config/data-source/portal-credentials/${encodeURIComponent(portalId)}`, {
    method: 'DELETE',
  })
}

export function updateRemoteLayerUris(
  remote_layer_data_uris: RemoteLayerUrisUpdateRequest['remote_layer_data_uris'],
): Promise<RemoteLayerUrisUpdateResponse> {
  return settingsFetch('/config/data-source/remote-layer-uris', {
    method: 'PUT',
    body: JSON.stringify({ remote_layer_data_uris }),
  })
}

export function fetchRemoteStorageProfiles(
  includeDisabled = true,
): Promise<RemoteStorageProfile[]> {
  return settingsFetch(`/config/remote-storage?include_disabled=${includeDisabled}`)
}

export function upsertRemoteStorageProfile(
  profileId: string,
  request: RemoteStorageUpsertRequest,
): Promise<RemoteStorageProfile> {
  return settingsFetch(`/config/remote-storage/${encodeURIComponent(profileId)}`, {
    method: 'PUT',
    body: JSON.stringify(request),
  })
}

export function deleteRemoteStorageProfile(
  profileId: string,
): Promise<RemoteStorageDeletedResponse> {
  return settingsFetch(`/config/remote-storage/${encodeURIComponent(profileId)}`, {
    method: 'DELETE',
  })
}

export function toggleRemoteStorageProfile(
  profileId: string,
  enabled: boolean,
): Promise<RemoteStorageToggleResponse> {
  return settingsFetch(`/config/remote-storage/${encodeURIComponent(profileId)}/toggle`, {
    method: 'PUT',
    body: JSON.stringify({ enabled } satisfies RemoteStorageToggleRequest),
  })
}

export function testRemoteStorageProfile(
  profileId: string,
  uri?: string | null,
): Promise<RemoteStorageTestResponse> {
  return settingsFetch(`/config/remote-storage/${encodeURIComponent(profileId)}/test`, {
    method: 'POST',
    body: JSON.stringify({ uri: uri ?? null } satisfies RemoteStorageTestRequest),
  })
}

export function fetchRemoteStorageHistory(profileId: string): Promise<RemoteStorageHistoryItem[]> {
  return settingsFetch(`/config/remote-storage/${encodeURIComponent(profileId)}/history`)
}

export function restoreRemoteStorageHistory(
  profileId: string,
  historyId: number,
): Promise<RemoteStorageProfile> {
  return settingsFetch(
    `/config/remote-storage/${encodeURIComponent(profileId)}/history/${historyId}/restore`,
    { method: 'POST' },
  )
}

export function deleteRemoteStorageHistoryEntry(
  profileId: string,
  historyId: number,
): Promise<RemoteStorageHistoryDeletedResponse> {
  return settingsFetch(
    `/config/remote-storage/${encodeURIComponent(profileId)}/history/${historyId}`,
    { method: 'DELETE' },
  )
}

export function clearRemoteStorageHistory(
  profileId: string,
): Promise<RemoteStorageHistoryClearResponse> {
  return settingsFetch(`/config/remote-storage/${encodeURIComponent(profileId)}/history`, {
    method: 'DELETE',
  })
}

/** 单条 Profile（脱敏回显，编辑表单填充用）。 */
export function fetchRemoteStorageProfile(profileId: string): Promise<RemoteStorageProfile> {
  return settingsFetch(`/config/remote-storage/${encodeURIComponent(profileId)}`)
}

/** 浏览远端目录（read 权限；filebrowser/sftp/smb/lan 等协议分发在后端）。 */
export function browseRemoteStorage(
  profileId: string,
  path: string,
): Promise<RemoteBrowseResponse> {
  return settingsFetch(`/config/remote-storage/${encodeURIComponent(profileId)}/browse`, {
    method: 'POST',
    body: JSON.stringify({ path } satisfies RemoteBrowseRequest),
  })
}

/** 远端名称搜索（filebrowser 原生 / 文件系统类受限 glob / 门户按能力）。 */
export function searchRemoteStorage(
  profileId: string,
  query: string,
  maxResults = 200,
): Promise<RemoteSearchResponse> {
  return settingsFetch(`/config/remote-storage/${encodeURIComponent(profileId)}/search`, {
    method: 'POST',
    body: JSON.stringify({ query, max_results: maxResults } satisfies RemoteSearchRequest),
  })
}

/** 手动切换主/备访问路径。 */
export function failoverRemoteStorage(
  profileId: string,
  target: RemoteFailoverRequest['target'],
): Promise<RemoteFailoverResponse> {
  return settingsFetch(`/config/remote-storage/${encodeURIComponent(profileId)}/failover`, {
    method: 'POST',
    body: JSON.stringify({ target } satisfies RemoteFailoverRequest),
  })
}

// ── 开放门户目录 ────────────────────────────────────────────────────────────

export function fetchPortalCatalog(): Promise<PortalCatalogResponse> {
  return settingsFetch('/config/portals')
}

/** 自定义门户创建/更新；builtin 门户仅 base_url/alt_url 覆盖生效。 */
export function upsertPortal(
  portalId: string,
  payload: PortalUpsertRequest,
): Promise<PortalCatalogEntry> {
  return settingsFetch(`/config/portals/${encodeURIComponent(portalId)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function deletePortal(portalId: string): Promise<DeletedResponse> {
  return settingsFetch(`/config/portals/${encodeURIComponent(portalId)}`, {
    method: 'DELETE',
  })
}

export function testPortal(portalId: string): Promise<PortalTestResponse> {
  return settingsFetch(`/config/portals/${encodeURIComponent(portalId)}/test`, {
    method: 'POST',
  })
}

/** 门户在线检索（仅 search_capability != none 的门户，如 CMR）。 */
export function searchPortal(
  portalId: string,
  query: string,
  pageSize = 20,
): Promise<PortalSearchResponse> {
  const qs = new URLSearchParams({ q: query, page_size: String(pageSize) })
  return settingsFetch(`/config/portals/${encodeURIComponent(portalId)}/search?${qs}`)
}

// ── 可用数据集注册表 ────────────────────────────────────────────────────────

export function fetchAvailableDatasets(includeDisabled = true): Promise<AvailableDatasetEntry[]> {
  return settingsFetch(`/config/data-source/datasets?include_disabled=${includeDisabled}`)
}

export function upsertAvailableDataset(
  datasetId: string,
  payload: DatasetUpsertRequest,
): Promise<AvailableDatasetEntry> {
  return settingsFetch(`/config/data-source/datasets/${encodeURIComponent(datasetId)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function deleteAvailableDataset(datasetId: string): Promise<DeletedResponse> {
  return settingsFetch(`/config/data-source/datasets/${encodeURIComponent(datasetId)}`, {
    method: 'DELETE',
  })
}

export function rescanAvailableDatasets(): Promise<DatasetRescanResponse> {
  return settingsFetch('/config/data-source/datasets/rescan', { method: 'POST' })
}

// ── 可访问远程数据源（别名注册表） ──────────────────────────────────────────

export function fetchRemoteSources(): Promise<RemoteSourceEntry[]> {
  return settingsFetch('/config/remote-sources')
}

export function upsertRemoteSource(
  remoteSourceId: string,
  payload: RemoteSourceUpsertRequest,
): Promise<RemoteSourceEntry> {
  return settingsFetch(`/config/remote-sources/${encodeURIComponent(remoteSourceId)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function deleteRemoteSource(remoteSourceId: string): Promise<DeletedResponse> {
  return settingsFetch(`/config/remote-sources/${encodeURIComponent(remoteSourceId)}`, {
    method: 'DELETE',
  })
}

export function fetchAboutInfo(): Promise<AboutInfo> {
  return settingsFetch('/config/about')
}

export function fetchRuntimeConfig(): Promise<RuntimeConfigSnapshotResponse> {
  return settingsFetch('/runtime/config')
}

export function fetchRuntimeStatus(): Promise<RuntimeStatusResponse> {
  return settingsFetch('/runtime/status')
}

export function fetchRuntimeResources(): Promise<ResourceUsageResponse> {
  return settingsFetch('/runtime/resources')
}

export async function updateRuntimeConfig(
  items: RuntimeConfigPatch[],
): Promise<RuntimeConfigUpdateResponse> {
  const body: RuntimeConfigUpdateRequest = {
    items,
    client: { client_id: 'web', page: 'settings-ui' },
  }
  return settingsFetch('/runtime/config', {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}
