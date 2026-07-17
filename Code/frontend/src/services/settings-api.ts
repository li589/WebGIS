/**
 * 配置管理 API 调用封装。
 *
 * 对应后端 /config/* 端点，使用 resolveApiUrl + fetch 与 runtime-api.ts 风格一致。
 * 请求 DTO 与 `shared/contracts/config_contracts.py` / OpenAPI 对齐；后续应改走 gen:types re-export。
 */

// ── 类型定义 ──────────────────────────────────────────────────────────────────

export interface ApiKeyItem {
  key_name: string
  display_name: string
  description: string | null
  masked_value: string
  enabled: boolean
  /** db = persisted, env = env fallback only, none = unset */
  source?: 'db' | 'env' | 'none' | string
  /** Whether a value exists (masked or effective) */
  has_value?: boolean
  created_at: string | null
  updated_at: string | null
  last_tested_at: string | null
  last_test_status: string | null
}

export interface ApiKeyUpdateRequest {
  key_value: string
  display_name?: string | null
  description?: string | null
  enabled?: boolean
  history_label?: string | null
}

export interface ApiKeyHistoryItem {
  id: number
  key_name: string
  masked_value: string
  label: string | null
  created_at: string
  superseded_at: string
  source: string
}

export interface GeeAccountItem {
  account_id: string
  display_name: string | null
  project_id: string | null
  account_type: string
  enabled: boolean
  created_at: string
  updated_at: string
  last_tested_at: string | null
  last_test_status: string | null
}

export interface GeeAccountCreateRequest {
  account_id: string
  service_account_json: Record<string, unknown>
  display_name?: string | null
}

export interface GeeRuntimeConfig {
  gee_enabled: boolean
  max_parallel_exports: number
  max_parallel_uploads: number
  max_parallel_downloads: number
  account_cooldown_seconds: number
  storage_backend: string
  local_storage_root: string
  api_account_management_enabled: boolean
  credentials_encryption_enabled: boolean
}

export interface WeatherConfig {
  default_model: string
  cache_ttl_seconds: number
  refresh_forecast_hours: number
  schedule_enabled: boolean
  default_latitude: number
  default_longitude: number
  default_place_name: string
  max_active_weather_tile_runs: number
}

// ── 天气源 Provider 类型 ────────────────────────────────────────────────────

export type WeatherProviderType = 'free_api' | 'commercial_api' | 'local_data'
export type WeatherCapability = 'all' | 'point_query' | 'grid_query'
export type CircuitState = 'closed' | 'open' | 'half_open' | 'n/a'

export interface WeatherProviderStatus {
  healthy: boolean
  circuit_state: CircuitState
  last_error: string | null
  daily_quota: number | null
  daily_used: number | null
  daily_remaining: number | null
  cache_hits: number
  cache_misses: number
  metadata: Record<string, unknown>
}

export interface WeatherProviderConfigSchema {
  key: string
  label: string
  field_type: string
  required: boolean
  default: string | number | boolean | null
  description: string | null
  options: string[]
  placeholder: string | null
}

export interface WeatherProviderItem {
  provider_id: string
  display_name: string
  provider_type: WeatherProviderType
  version: string
  description: string
  homepage_url: string | null
  requires_api_key: boolean
  supported_capabilities: WeatherCapability[]
  priority: number
  enabled: boolean
  status: WeatherProviderStatus
  config_schema: WeatherProviderConfigSchema[]
  current_config: Record<string, unknown>
  persisted_config: Record<string, unknown> | null
  last_tested_at: string | null
  last_test_status: string | null
  is_builtin: boolean
}

export interface WeatherProviderUpdateRequest {
  enabled?: boolean
  priority?: number
  config?: Record<string, unknown>
}

export interface WeatherProviderTestResult {
  provider_id: string
  success: boolean
  message: string
  tested_at: string
}

export interface GeneralConfig {
  environment: string
  host: string
  port: number
  service_name: string
  data_root: string
  output_root: string
  cache_dir: string
  log_dir: string
  log_level: string
  max_active_runs: number
  max_requested_outputs: number
  redis_url: string
  storage_backend: string
  reload: boolean
}

export interface DataSourceConfig {
  storage_backend: string
  data_root: string
  output_root: string
  download_source_root: string
  download_real_fetch_enabled: boolean
  tile_proxy_enabled: boolean
  tile_proxy_cache_ttl_seconds: number
  minio: {
    endpoint: string
    bucket: string
    secure: boolean
  } | null
}

export interface AboutModule {
  name: string
  description: string
}

export interface AboutInfo {
  project_name: string
  version: string
  description: string
  tech_stack: string[]
  modules: AboutModule[]
  architecture_summary: string
}

export interface TestResult {
  success: boolean
  message: string
}

export interface ReloadResult {
  success: boolean
  account_count: number
  message: string
}

// ── API 函数 ──────────────────────────────────────────────────────────────────

import { resolveApiUrl } from './runtime-api'
import { withWriteAuthHeaders } from './backend-auth'

async function settingsFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const url = resolveApiUrl(path)
  const method = (init?.method ?? 'GET').toUpperCase()
  let headers: Record<string, string> = {
    ...(init?.headers as Record<string, string> | undefined),
  }
  // 仅在有 JSON body 的写请求上设置 Content-Type，避免部分代理对 GET 敏感
  if (method !== 'GET' && method !== 'HEAD' && init?.body != null) {
    headers['Content-Type'] = headers['Content-Type'] ?? 'application/json'
  }
  headers = withWriteAuthHeaders(headers, method)

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
      throw new Error(`Settings API timeout: ${path}`)
    }
    if (err instanceof TypeError) {
      throw new Error(
        `Settings API unreachable: ${path}（请确认后端已启动，开发环境 Vite 需代理 /config）`,
      )
    }
    throw err
  } finally {
    window.clearTimeout(timeoutId)
  }
}

// 常规配置
export function fetchGeneralConfig(): Promise<GeneralConfig> {
  return settingsFetch('/config/general')
}

// API Key
export function fetchApiKeys(): Promise<ApiKeyItem[]> {
  return settingsFetch('/config/api-keys')
}

export function updateApiKey(keyName: string, request: ApiKeyUpdateRequest): Promise<ApiKeyItem> {
  return settingsFetch(`/config/api-keys/${encodeURIComponent(keyName)}`, {
    method: 'PUT',
    body: JSON.stringify(request),
  })
}

export function deleteApiKey(keyName: string): Promise<{ deleted: boolean }> {
  return settingsFetch(`/config/api-keys/${encodeURIComponent(keyName)}`, {
    method: 'DELETE',
  })
}

export function testApiKey(keyName: string): Promise<TestResult> {
  return settingsFetch(`/config/api-keys/${encodeURIComponent(keyName)}/test`, {
    method: 'POST',
  })
}

export function toggleApiKey(keyName: string, enabled: boolean): Promise<{ key_name: string; enabled: boolean }> {
  return settingsFetch(`/config/api-keys/${encodeURIComponent(keyName)}/toggle`, {
    method: 'PUT',
    body: JSON.stringify({ enabled }),
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
): Promise<{ deleted: boolean }> {
  return settingsFetch(
    `/config/api-keys/${encodeURIComponent(keyName)}/history/${historyId}`,
    { method: 'DELETE' },
  )
}

export function clearApiKeyHistory(keyName: string): Promise<{ key_name: string; deleted: number }> {
  return settingsFetch(`/config/api-keys/${encodeURIComponent(keyName)}/history`, {
    method: 'DELETE',
  })
}

// GEE 账户
export function fetchGeeAccounts(): Promise<GeeAccountItem[]> {
  return settingsFetch('/config/gee/accounts')
}

export function createGeeAccount(request: GeeAccountCreateRequest): Promise<GeeAccountItem> {
  return settingsFetch('/config/gee/accounts', {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

export function deleteGeeAccount(accountId: string): Promise<{ deleted: boolean }> {
  return settingsFetch(`/config/gee/accounts/${encodeURIComponent(accountId)}`, {
    method: 'DELETE',
  })
}

export function testGeeAccount(accountId: string): Promise<TestResult> {
  return settingsFetch(`/config/gee/accounts/${encodeURIComponent(accountId)}/test`, {
    method: 'POST',
  })
}

export function toggleGeeAccount(accountId: string, enabled: boolean): Promise<{ account_id: string; enabled: boolean }> {
  return settingsFetch(`/config/gee/accounts/${encodeURIComponent(accountId)}/toggle`, {
    method: 'PUT',
    body: JSON.stringify({ enabled }),
  })
}

export function reloadGeeAccounts(): Promise<ReloadResult> {
  return settingsFetch('/config/gee/accounts/reload', {
    method: 'POST',
  })
}

// GEE 运行时配置
export function fetchGeeRuntimeConfig(): Promise<GeeRuntimeConfig> {
  return settingsFetch('/config/gee/runtime')
}

// 天气配置
export function fetchWeatherConfig(): Promise<WeatherConfig> {
  return settingsFetch('/config/weather')
}

// 天气源 Provider 管理
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

export function testWeatherProvider(providerId: string): Promise<WeatherProviderTestResult> {
  return settingsFetch(`/config/weather/providers/${encodeURIComponent(providerId)}/test`, {
    method: 'POST',
  })
}

export function toggleWeatherProvider(
  providerId: string,
  enabled: boolean,
): Promise<{ provider_id: string; enabled: boolean }> {
  return settingsFetch(`/config/weather/providers/${encodeURIComponent(providerId)}/toggle`, {
    method: 'PUT',
    body: JSON.stringify({ enabled }),
  })
}

export function setWeatherProviderPriority(
  providerId: string,
  priority: number,
): Promise<{ provider_id: string; priority: number }> {
  return settingsFetch(`/config/weather/providers/${encodeURIComponent(providerId)}/priority`, {
    method: 'PUT',
    body: JSON.stringify({ priority }),
  })
}

export function deleteWeatherProvider(providerId: string): Promise<{ deleted: boolean }> {
  return settingsFetch(`/config/weather/providers/${encodeURIComponent(providerId)}`, {
    method: 'DELETE',
  })
}

// 数据源配置
export function fetchDataSourceConfig(): Promise<DataSourceConfig> {
  return settingsFetch('/config/data-source')
}

// 远程存储凭证
export type RemoteStorageProtocol = 'sftp' | 'smb' | 'ftp' | 'ftps' | 'gs'

export interface RemoteStorageProfile {
  profile_id: string
  protocol: RemoteStorageProtocol | string
  host: string
  port: number | null
  username: string | null
  has_secret: boolean
  has_private_key: boolean
  domain: string | null
  extra: Record<string, unknown>
  display_name: string
  enabled: boolean
  created_at: string
  updated_at: string
  last_tested_at: string | null
  last_test_status: string | null
}

export interface RemoteStorageUpsertRequest {
  protocol: string
  host?: string
  port?: number | null
  username?: string | null
  secret?: string | null
  private_key_pem?: string | null
  domain?: string | null
  /** null/omit preserves existing; {} clears protocol extras */
  extra?: Record<string, unknown> | null
  display_name?: string | null
  /** null/omit preserves existing enabled flag */
  enabled?: boolean | null
}

export interface RemoteStorageTestResult {
  profile_id: string
  success: boolean
  message: string
  tested_at: string
}

export function fetchRemoteStorageProfiles(includeDisabled = true): Promise<RemoteStorageProfile[]> {
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

export function deleteRemoteStorageProfile(profileId: string): Promise<{ deleted: boolean }> {
  return settingsFetch(`/config/remote-storage/${encodeURIComponent(profileId)}`, {
    method: 'DELETE',
  })
}

export function toggleRemoteStorageProfile(
  profileId: string,
  enabled: boolean,
): Promise<{ profile_id: string; enabled: boolean }> {
  return settingsFetch(`/config/remote-storage/${encodeURIComponent(profileId)}/toggle`, {
    method: 'PUT',
    body: JSON.stringify({ enabled }),
  })
}

export function testRemoteStorageProfile(
  profileId: string,
  uri?: string | null,
): Promise<RemoteStorageTestResult> {
  return settingsFetch(`/config/remote-storage/${encodeURIComponent(profileId)}/test`, {
    method: 'POST',
    body: JSON.stringify({ uri: uri ?? null }),
  })
}

export interface RemoteStorageHistoryItem {
  id: number
  profile_id: string
  masked_secret: string
  has_private_key: boolean
  label: string | null
  created_at: string
  superseded_at: string
  source: string
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
): Promise<{ deleted: boolean }> {
  return settingsFetch(
    `/config/remote-storage/${encodeURIComponent(profileId)}/history/${historyId}`,
    { method: 'DELETE' },
  )
}

export function clearRemoteStorageHistory(
  profileId: string,
): Promise<{ profile_id: string; deleted: number }> {
  return settingsFetch(`/config/remote-storage/${encodeURIComponent(profileId)}/history`, {
    method: 'DELETE',
  })
}

// 关于
export function fetchAboutInfo(): Promise<AboutInfo> {
  return settingsFetch('/config/about')
}
