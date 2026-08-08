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
  BackendServiceStatus,
  CircuitState,
  DataCacheEntry,
  DataCacheEvictRequest,
  DataCacheEvictResponse,
  DataCacheOverview,
  DataSourceConfig,
  DataSourcePathsUpdateRequest,
  DataSourcePathsUpdateResponse,
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
  PortalCredentialPublic,
  PortalCredentialUpsertRequest,
  PortalCredentialsMapResponse,
  ReloadResult,
  ReloadResultResponse,
  RemoteLayerUrisUpdateRequest,
  RemoteLayerUrisUpdateResponse,
  RemoteStorageDeletedResponse,
  RemoteStorageHistoryClearResponse,
  RemoteStorageHistoryDeletedResponse,
  RemoteStorageHistoryItem,
  RemoteStorageProfile,
  RemoteStorageProtocol,
  RemoteStorageTestRequest,
  RemoteStorageTestResponse,
  RemoteStorageTestResult,
  RemoteStorageToggleRequest,
  RemoteStorageToggleResponse,
  RemoteStorageUpsertRequest,
  RuntimeConfigPatch,
  RuntimeConfigScope,
  RuntimeConfigSnapshotResponse,
  RuntimeConfigUpdateRequest,
  RuntimeConfigUpdateResponse,
  RuntimeStatusResponse,
  ServiceRestartRequest,
  ServiceRestartResponse,
  StaticCacheSummary,
  TestResult,
  TestResultResponse,
  WeatherCapability,
  WeatherConfig,
  WeatherModelUpdateRequest,
  WeatherProviderConfigField,
  WeatherProviderConfigSchema,
  WeatherProviderDeletedResponse,
  WeatherProviderItem,
  WeatherProviderPriorityRequest,
  WeatherProviderPriorityResponse,
  WeatherProviderStatus,
  WeatherProviderTestResponse,
  WeatherProviderTestResult,
  WeatherProviderToggleRequest,
  WeatherProviderToggleResponse,
  WeatherProviderType,
  WeatherProviderUpdateRequest,
  WeatherSupportedModel,
  WeatherSyncCron,
} from '../types/api-reexports'

import { withWriteAuthHeaders } from './backend-auth'
import { resolveApiUrl } from './runtime-api'
import type {
  AboutInfo,
  ApiKeyDeletedResponse,
  ApiKeyHistoryClearResponse,
  ApiKeyHistoryDeletedResponse,
  ApiKeyHistoryItem,
  ApiKeyItem,
  ApiKeyToggleRequest,
  ApiKeyUpdateRequest,
  DataCacheEvictRequest,
  DataCacheEvictResponse,
  DataCacheOverview,
  DataSourceConfig,
  DataSourcePathsUpdateRequest,
  DataSourcePathsUpdateResponse,
  GeeAccountCreateRequest,
  GeeAccountDeletedResponse,
  GeeAccountItem,
  GeeAccountToggleRequest,
  GeeAccountToggleResponse,
  GeeRuntimeConfig,
  GeneralConfig,
  OpenDataPresetsUpdateRequest,
  OpenDataPresetsUpdateResponse,
  PortalCredentialUpsertRequest,
  PortalCredentialsMapResponse,
  ReloadResult,
  RemoteLayerUrisUpdateRequest,
  RemoteLayerUrisUpdateResponse,
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
  RuntimeConfigPatch,
  RuntimeConfigSnapshotResponse,
  RuntimeConfigUpdateRequest,
  RuntimeConfigUpdateResponse,
  RuntimeStatusResponse,
  ServiceRestartRequest,
  ServiceRestartResponse,
  TestResult,
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
    const response = await fetch(url, {
      ...init,
      headers,
      signal: init?.signal ?? controller.signal,
    })
    if (!response.ok) {
      const detail = await response.text().catch(() => '')
      throw new Error(
        `Settings API failed: ${response.status} ${path}${detail ? ` — ${detail.slice(0, 200)}` : ''}`,
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

export function testApiKey(keyName: string): Promise<TestResult> {
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

export function testGeeAccount(accountId: string): Promise<TestResult> {
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

export function reloadGeeAccounts(): Promise<ReloadResult> {
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

export function fetchAboutInfo(): Promise<AboutInfo> {
  return settingsFetch('/config/about')
}

export function fetchRuntimeConfig(): Promise<RuntimeConfigSnapshotResponse> {
  return settingsFetch('/runtime/config')
}

export function fetchRuntimeStatus(): Promise<RuntimeStatusResponse> {
  return settingsFetch('/runtime/status')
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
