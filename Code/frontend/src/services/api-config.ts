/**
 * Unified integration config registry.
 *
 * This file acts as the single structured entry for:
 * - basemap provider definitions
 * - external data-source APIs
 * - GEE multi-account credential metadata
 *
 * Sensitive values must stay in backend-managed secret stores. Frontend only
 * keeps references so provider URLs, keys, certificates, and future upstream
 * integrations can be updated in one normalized place.
 */

import { getMapDefaults } from './map-defaults'
import { withWriteAuthHeaders } from './backend-auth'
import { applyApiFetchDefaults } from './http-credentials'
import { resolveApiUrl } from './runtime-api'

export type IntegrationDomain = 'basemap' | 'data-source' | 'gee' | 'credential' | 'certificate'
export type IntegrationEnv = 'local' | 'dev' | 'staging' | 'prod'
export type AuthMode = 'none' | 'api-key' | 'bearer' | 'service-account' | 'certificate'
export type SecretBackend = 'env' | 'vault' | 'backend-runtime' | 'manual' | 'config-api-keys'
export type BasemapStyle = 'none' | 'street' | 'satellite' | 'dark' | 'terrain'
export type TileSourceId =
  | 'none'
  | 'esri-street'
  | 'esri-imagery'
  | 'esri-terrain'
  | 'esri-hillshade'
  | 'esri-dark'
  | 'osm-standard'
  | 'osm-hot'
  | 'opentopo-terrain'
  | 'carto-dark'
  | 'bing-road'
  | 'bing-aerial'
  | 'bing-dark'
  | 'gaode-street'
  | 'gaode-satellite'
  | 'tianditu-vec'
  | 'tianditu-img'
  | 'tianditu-cva'
  | 'tianditu-ter'
  | 'baidu-street'
  | 'baidu-satellite'

export interface ConfigReference {
  id: string
  backend: SecretBackend
  key: string
  description?: string
}

export interface EndpointConfig {
  id: string
  label: string
  url: string
  authMode: AuthMode
  enabled: boolean
  timeoutMs?: number
  headers?: Record<string, string>
  secretRef?: ConfigReference
  certificateRef?: ConfigReference
  metadata?: Record<string, unknown>
}

export interface BasemapEndpointConfig extends EndpointConfig {
  sourceId: TileSourceId
  style: BasemapStyle
  attribution?: string
  tileSize?: number
  saturation: number
  brightness: number
  contrast: number
  isStandard: boolean
  needsBackendTransform: boolean
}

export interface BasemapProviderConfig {
  id: string
  label: string
  provider: string
  routePrefix?: string
  coordinateSystem?: string
  endpoints: BasemapEndpointConfig[]
  metadata?: Record<string, unknown>
}

export interface ExternalApiConfig {
  id: string
  label: string
  domain: Exclude<IntegrationDomain, 'gee' | 'credential' | 'certificate'>
  capabilities: string[]
  endpoints: EndpointConfig[]
  metadata?: Record<string, unknown>
}

export interface GeeAccountConfig {
  id: string
  label: string
  accountEmail?: string
  projectId?: string
  enabled: boolean
  credentialRef?: ConfigReference
  certificateRef?: ConfigReference
  metadata?: Record<string, unknown>
}

export interface GeeIntegrationConfig {
  enabled: boolean
  environment: IntegrationEnv
  moduleRoot?: string
  credentialsStoreRef?: ConfigReference
  encryptionKeyRef?: ConfigReference
  accounts: GeeAccountConfig[]
  metadata?: Record<string, unknown>
}

export interface UnifiedIntegrationConfig {
  version: string
  updatedAt: string
  basemaps: BasemapProviderConfig[]
  externalApis: ExternalApiConfig[]
  gee: GeeIntegrationConfig
}

export interface RuntimeApiProviderResponse {
  provider?: string
  name?: string
  endpoint?: {
    url?: string
    requires_auth?: boolean
    rate_limit?: number | null
    timeout?: number
    retry_count?: number
    capabilities?: string[]
  }
  /** Backend never returns plaintext keys; only configuration flags. */
  api_key_configured?: boolean
  api_key_source?: 'env' | 'db' | 'metadata' | 'none' | string
  /** Capabilities actually invoked on hot paths (may be narrower than endpoint.capabilities). */
  wired_in_hot_path?: string[]
  hot_path_notes?: string
  enabled?: boolean
  priority?: number
  metadata?: Record<string, unknown>
  /** @deprecated Backend no longer returns plaintext; kept for stale client cache only. */
  api_key?: never
}

export interface GeeParallelConfigResponse {
  max_parallel_exports: number
  max_parallel_uploads: number
  max_parallel_downloads: number
  account_cooldown_seconds: number
  max_tasks_per_account: number
}

export interface GeeConfigResponse {
  enabled: boolean
  parallel_config: GeeParallelConfigResponse
  storage_backend: string
  local_storage_root: string
  credentials_encryption_enabled: boolean
  api_account_management_enabled: boolean
}

export interface GeeTaskLimitResponse {
  max_concurrent: number
  active: number
  available: number
}

export interface GeeStatusResponse {
  enabled: boolean
  gee_available: boolean
  concurrency_stats: {
    active_exports: number
    active_uploads: number
    active_downloads: number
    active_accounts: number
    queued_tasks: number
  }
  task_limits: {
    export: GeeTaskLimitResponse
    upload: GeeTaskLimitResponse
    download: GeeTaskLimitResponse
  }
}

export interface GeeEnvironmentResponse {
  gee_enabled: boolean
  gee_module_root: string
  gee_storage_backend: string
  gee_local_storage_root: string
  gee_credentials_encryption_key_set: boolean
  gee_credentials_db_path: string
  gee_api_account_management_enabled: boolean
}

export interface TileSourceConfig {
  id: TileSourceId
  label: string
  provider: string
  style: BasemapStyle
  urlTemplate: string
  attribution?: string
  tileSize?: number
  saturation: number
  brightness: number
  contrast: number
  isStandard: boolean
  needsBackendTransform: boolean
  authMode: AuthMode
  secretRef?: ConfigReference
  certificateRef?: ConfigReference
  /** 可选注记/叠加瓦片（如天地图 vec + cva） */
  overlayUrlTemplate?: string
}

// P3-A（2026-08-24）数据/逻辑分离：四个配置数据块（底图 provider/外部
// API/GEE 集成/统一模板，原 486 行）外置到 api-config.data.json。JSON 由
// Tools 内提取生成（值与原 TS 常量运行时等价）；类型仍以本文件接口为准。
// 敏感值（key/凭证）依旧只存后端 secret store，前端仅保留引用。
import apiConfigData from './api-config.data.json'

const _data = apiConfigData as {
  basemapProviders: BasemapProviderConfig[]
  externalApis: ExternalApiConfig[]
  geeIntegration: GeeIntegrationConfig
  unifiedTemplate: UnifiedIntegrationConfig
}

export const BASEMAP_PROVIDER_CONFIGS: BasemapProviderConfig[] = _data.basemapProviders
export const EXTERNAL_API_CONFIGS: ExternalApiConfig[] = _data.externalApis
export const GEE_INTEGRATION_CONFIG: GeeIntegrationConfig = _data.geeIntegration
export const UNIFIED_INTEGRATION_CONFIG_TEMPLATE: UnifiedIntegrationConfig =
  _data.unifiedTemplate

export const TILE_SOURCES: TileSourceConfig[] = BASEMAP_PROVIDER_CONFIGS.flatMap((provider) =>
  provider.endpoints
    .filter((endpoint) => endpoint.enabled)
    .map((endpoint) => ({
      id: endpoint.sourceId,
      label: endpoint.label,
      provider:
        typeof endpoint.metadata?.providerLabel === 'string'
          ? endpoint.metadata.providerLabel
          : provider.provider,
      style: endpoint.style,
      urlTemplate: endpoint.url,
      attribution: endpoint.attribution,
      tileSize: endpoint.tileSize,
      saturation: endpoint.saturation,
      brightness: endpoint.brightness,
      contrast: endpoint.contrast,
      isStandard: endpoint.isStandard,
      needsBackendTransform: endpoint.needsBackendTransform,
      authMode: endpoint.authMode,
      secretRef: endpoint.secretRef,
      certificateRef: endpoint.certificateRef,
      overlayUrlTemplate:
        typeof endpoint.metadata?.overlayUrl === 'string'
          ? endpoint.metadata.overlayUrl
          : undefined,
    })),
)

export const TILE_SOURCE_MAP = new Map<TileSourceId, TileSourceConfig>(
  TILE_SOURCES.map((source) => [source.id, source]),
)

export const TILE_SOURCES_BY_STYLE = new Map<BasemapStyle, TileSourceConfig[]>()
for (const source of TILE_SOURCES) {
  const existing = TILE_SOURCES_BY_STYLE.get(source.style)
  if (existing) {
    existing.push(source)
  } else {
    TILE_SOURCES_BY_STYLE.set(source.style, [source])
  }
}

/**
 * 同风格展示优先级：高德 → Bing → 其余（验收默认与第二选项）。
 * 未列出的 id 保持相对顺序排在后面。
 */
const BASEMAP_STYLE_PRIORITY: Partial<Record<BasemapStyle, readonly string[]>> = {
  street: ['gaode-street', 'bing-road'],
  satellite: ['gaode-satellite', 'bing-aerial'],
  dark: ['bing-dark'],
  // 免 Key 优先；天地图地形需 Key，排后
  terrain: ['esri-terrain', 'esri-hillshade', 'opentopo-terrain', 'tianditu-ter'],
}

function sortBasemapSourcesInPlace(sources: TileSourceConfig[], style: BasemapStyle): void {
  const priority = BASEMAP_STYLE_PRIORITY[style]
  if (!priority?.length) return
  const rank = new Map(priority.map((id, i) => [id, i]))
  const decorated = sources.map((s, i) => ({ s, i }))
  decorated.sort((a, b) => {
    const ra = rank.get(a.s.id) ?? priority.length + a.i
    const rb = rank.get(b.s.id) ?? priority.length + b.i
    return ra - rb
  })
  for (let i = 0; i < decorated.length; i++) sources[i] = decorated[i].s
}

for (const [style, sources] of TILE_SOURCES_BY_STYLE) {
  sortBasemapSourcesInPlace(sources, style)
}

export function getDefaultTileSource(): TileSourceId {
  // 运行时可由 /config/general.map_default_tile_source 覆盖（见 map-defaults）
  const id = normalizeTileSourceId(getMapDefaults().tileSource)
  if (TILE_SOURCE_MAP.has(id)) return id
  return 'gaode-street'
}

/** 旧版误把 cva 注记当街道；持久化 id 迁移到 vec。 */
export function normalizeTileSourceId(sourceId: string): TileSourceId {
  if (sourceId === 'tianditu-cva') return 'tianditu-vec'
  if (TILE_SOURCE_MAP.has(sourceId as TileSourceId)) return sourceId as TileSourceId
  return 'gaode-street'
}

export function needsBackendProxy(sourceId: TileSourceId): boolean {
  return TILE_SOURCE_MAP.get(sourceId)?.needsBackendTransform ?? false
}

export function getTileUrl(sourceId: TileSourceId): string {
  return TILE_SOURCE_MAP.get(sourceId)?.urlTemplate ?? ''
}

export function getProxyRequiredSources(): TileSourceConfig[] {
  return TILE_SOURCES.filter((source) => source.needsBackendTransform)
}

export function getDirectAccessSources(): TileSourceConfig[] {
  return TILE_SOURCES.filter((source) => !source.needsBackendTransform && source.id !== 'none')
}

export function getSourcesByStyle(style: BasemapStyle): TileSourceConfig[] {
  return TILE_SOURCES_BY_STYLE.get(style) ?? []
}

/**
 * 底图 provider 熔断后的故障转移候选：同风格组内按既有展示优先级排序，
 * 排除自身与冷却中的 provider（按 provider 标签与 sourceId 双重排除，
 * 因为熔断归因既可能是 provider 标签也可能是代理 sourceId）。
 */
export function getFailoverCandidates(
  currentSourceId: TileSourceId,
  excludeProviders: ReadonlySet<string>,
): TileSourceId[] {
  const current = TILE_SOURCE_MAP.get(currentSourceId)
  if (!current) return []
  const group = TILE_SOURCES_BY_STYLE.get(current.style) ?? []
  return group
    .filter(
      (source) =>
        source.id !== currentSourceId &&
        source.isStandard &&
        !excludeProviders.has(source.provider) &&
        !excludeProviders.has(source.id),
    )
    .map((source) => source.id)
}

export function isSourceAvailable(sourceId: TileSourceId): boolean {
  return sourceId !== 'none' && TILE_SOURCE_MAP.has(sourceId)
}

/** Backend tile proxy currently requires these keys before serving tiles. */
export const REQUIRED_BASEMAP_API_KEYS = new Set(['tianditu', 'baidu'])

export function tileSourceRequiresApiKey(source: TileSourceConfig): boolean {
  const key = source.secretRef?.key
  return Boolean(key && REQUIRED_BASEMAP_API_KEYS.has(key))
}

export function isTileSourceUsable(
  source: TileSourceConfig,
  isKeyAvailable: (keyName: string) => boolean,
): boolean {
  if (!tileSourceRequiresApiKey(source)) return true
  return isKeyAvailable(source.secretRef!.key)
}

export function listEnabledBasemapProviders(config: UnifiedIntegrationConfig) {
  return config.basemaps.filter((provider) =>
    provider.endpoints.some((endpoint) => endpoint.enabled),
  )
}

export function listEnabledBasemapSources(config: UnifiedIntegrationConfig) {
  return config.basemaps.flatMap((provider) =>
    provider.endpoints.filter((endpoint) => endpoint.enabled).map((endpoint) => endpoint.sourceId),
  )
}

export function listEnabledExternalApis(config: UnifiedIntegrationConfig) {
  return config.externalApis.filter((api) => api.endpoints.some((endpoint) => endpoint.enabled))
}

export function listEnabledGeeAccounts(config: UnifiedIntegrationConfig) {
  return config.gee.accounts.filter((account) => account.enabled)
}

function cloneUnifiedIntegrationConfig(source: UnifiedIntegrationConfig): UnifiedIntegrationConfig {
  return JSON.parse(JSON.stringify(source)) as UnifiedIntegrationConfig
}

async function requestConfigJson<T>(
  path: string,
  init?: RequestInit & { timeoutMs?: number },
): Promise<T> {
  const { timeoutMs, ...restInit } = init ?? {}
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs ?? 15000)

  try {
    const method = (restInit.method ?? 'GET').toString()
    const response = await fetch(
      resolveApiUrl(path),
      applyApiFetchDefaults({
        ...restInit,
        headers: withWriteAuthHeaders(
          {
            'Content-Type': 'application/json',
            ...(restInit.headers as Record<string, string> | undefined),
          },
          method,
          true,
        ),
        signal: restInit.signal ?? controller.signal,
      }),
    )

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status} ${path}`)
    }

    return (await response.json()) as T
  } finally {
    window.clearTimeout(timeoutId)
  }
}

function hasApiCredential(runtimeConfig: RuntimeApiProviderResponse) {
  if (runtimeConfig.api_key_configured === true) {
    return true
  }
  if (runtimeConfig.api_key_source && runtimeConfig.api_key_source !== 'none') {
    return true
  }
  const metadata = runtimeConfig.metadata
  if (
    metadata &&
    typeof metadata.credentials_path === 'string' &&
    metadata.credentials_path.trim().length > 0
  ) {
    return true
  }
  return false
}

function normalizeRuntimeApiProviderEntries(
  payload: unknown,
): Array<{ providerId: string; config: RuntimeApiProviderResponse }> {
  if (!payload || typeof payload !== 'object') {
    return []
  }

  return Object.entries(payload as Record<string, unknown>).flatMap(([providerId, value]) => {
    if (!value || typeof value !== 'object') {
      return []
    }
    return [{ providerId, config: value as RuntimeApiProviderResponse }]
  })
}

function attachRuntimeProviderMetadata(
  target: { metadata?: Record<string, unknown> },
  providerId: string,
  runtimeConfig: RuntimeApiProviderResponse,
) {
  target.metadata = {
    ...(target.metadata ?? {}),
    runtimeProviderId: providerId,
    runtimeProviderName: runtimeConfig.name ?? providerId,
    runtimeEnabled: runtimeConfig.enabled ?? true,
    runtimePriority: runtimeConfig.priority ?? null,
    runtimeEndpointUrl: runtimeConfig.endpoint?.url ?? null,
    runtimeRequiresAuth: runtimeConfig.endpoint?.requires_auth ?? false,
    runtimeCapabilities: runtimeConfig.endpoint?.capabilities ?? [],
    runtimeRateLimit: runtimeConfig.endpoint?.rate_limit ?? null,
    runtimeTimeoutSeconds: runtimeConfig.endpoint?.timeout ?? null,
    runtimeRetryCount: runtimeConfig.endpoint?.retry_count ?? null,
    runtimeAuthConfigured: hasApiCredential(runtimeConfig),
    runtimeApiKeySource: runtimeConfig.api_key_source ?? 'none',
    runtimeWiredInHotPath: runtimeConfig.wired_in_hot_path ?? [],
    runtimeHotPathNotes: runtimeConfig.hot_path_notes ?? null,
    runtimeSourceMetadata: runtimeConfig.metadata ?? {},
  }
}

function mergeRuntimeApiConfigs(
  baseConfig: UnifiedIntegrationConfig,
  runtimeConfigs: Array<{ providerId: string; config: RuntimeApiProviderResponse }>,
) {
  for (const { providerId, config } of runtimeConfigs) {
    const basemapProvider = baseConfig.basemaps.find((item) => item.id === providerId)
    if (basemapProvider) {
      attachRuntimeProviderMetadata(basemapProvider, providerId, config)
      for (const endpoint of basemapProvider.endpoints) {
        endpoint.enabled = config.enabled ?? endpoint.enabled
        endpoint.metadata = {
          ...(endpoint.metadata ?? {}),
          runtimeProviderId: providerId,
          runtimeEnabled: config.enabled ?? true,
          runtimeAuthConfigured: hasApiCredential(config),
          upstreamBaseUrl: config.endpoint?.url ?? null,
        }
      }
      continue
    }

    const externalApi = baseConfig.externalApis.find((item) => item.id === providerId)
    if (externalApi) {
      attachRuntimeProviderMetadata(externalApi, providerId, config)
      for (const endpoint of externalApi.endpoints) {
        endpoint.enabled = config.enabled ?? endpoint.enabled
        if (config.endpoint?.url) {
          endpoint.url = config.endpoint.url
        }
        endpoint.metadata = {
          ...(endpoint.metadata ?? {}),
          runtimeProviderId: providerId,
          runtimeEnabled: config.enabled ?? true,
          runtimeAuthConfigured: hasApiCredential(config),
        }
      }
    }
  }
}

function mergeGeeRuntimeSnapshot(
  baseConfig: UnifiedIntegrationConfig,
  geeConfig?: GeeConfigResponse,
  geeStatus?: GeeStatusResponse,
  geeEnvironment?: GeeEnvironmentResponse,
) {
  const gee = baseConfig.gee

  if (geeConfig) {
    gee.enabled = geeConfig.enabled
    gee.metadata = {
      ...(gee.metadata ?? {}),
      storageBackend: geeConfig.storage_backend,
      localStorageRoot: geeConfig.local_storage_root,
      credentialsEncryptionEnabled: geeConfig.credentials_encryption_enabled,
      apiAccountManagementEnabled: geeConfig.api_account_management_enabled,
      parallelConfig: geeConfig.parallel_config,
    }
  }

  if (geeEnvironment) {
    gee.enabled = geeEnvironment.gee_enabled
    gee.moduleRoot = geeEnvironment.gee_module_root || gee.moduleRoot
    gee.metadata = {
      ...(gee.metadata ?? {}),
      storageBackend: geeEnvironment.gee_storage_backend,
      localStorageRoot: geeEnvironment.gee_local_storage_root,
      credentialsEncryptionKeySet: geeEnvironment.gee_credentials_encryption_key_set,
      apiAccountManagementEnabled: geeEnvironment.gee_api_account_management_enabled,
      runtimeResolvedCredentialsDbPath: geeEnvironment.gee_credentials_db_path,
    }
  }

  if (geeStatus) {
    gee.metadata = {
      ...(gee.metadata ?? {}),
      geeAvailable: geeStatus.gee_available,
      concurrencyStats: geeStatus.concurrency_stats,
      taskLimits: geeStatus.task_limits,
    }
  }
}

export async function loadUnifiedIntegrationConfig(): Promise<UnifiedIntegrationConfig> {
  const baseConfig = cloneUnifiedIntegrationConfig(UNIFIED_INTEGRATION_CONFIG_TEMPLATE)

  const [runtimeApiConfigsResult, geeConfigResult, geeStatusResult, geeEnvironmentResult] =
    await Promise.allSettled([
      requestConfigJson<Record<string, RuntimeApiProviderResponse>>('/runtime/api-config'),
      requestConfigJson<GeeConfigResponse>('/gee/config'),
      requestConfigJson<GeeStatusResponse>('/gee/config/status'),
      requestConfigJson<GeeEnvironmentResponse>('/gee/config/environment'),
    ])

  if (runtimeApiConfigsResult.status === 'fulfilled') {
    mergeRuntimeApiConfigs(
      baseConfig,
      normalizeRuntimeApiProviderEntries(runtimeApiConfigsResult.value),
    )
  }

  mergeGeeRuntimeSnapshot(
    baseConfig,
    geeConfigResult.status === 'fulfilled' ? geeConfigResult.value : undefined,
    geeStatusResult.status === 'fulfilled' ? geeStatusResult.value : undefined,
    geeEnvironmentResult.status === 'fulfilled' ? geeEnvironmentResult.value : undefined,
  )

  baseConfig.updatedAt = new Date().toISOString()
  return baseConfig
}

export async function loadUnifiedIntegrationConfigSafe() {
  try {
    return await loadUnifiedIntegrationConfig()
  } catch {
    return cloneUnifiedIntegrationConfig(UNIFIED_INTEGRATION_CONFIG_TEMPLATE)
  }
}
