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

import { resolveApiUrl } from './runtime-api'

export type IntegrationDomain = 'basemap' | 'data-source' | 'gee' | 'credential' | 'certificate'
export type IntegrationEnv = 'local' | 'dev' | 'staging' | 'prod'
export type AuthMode = 'none' | 'api-key' | 'bearer' | 'service-account' | 'certificate'
export type SecretBackend = 'env' | 'vault' | 'backend-runtime' | 'manual'
export type BasemapStyle = 'none' | 'street' | 'satellite' | 'dark' | 'terrain'
export type TileSourceId =
  | 'none'
  | 'esri-street'
  | 'esri-imagery'
  | 'esri-terrain'
  | 'esri-dark'
  | 'esri-light'
  | 'osm-standard'
  | 'osm-hot'
  | 'carto-dark'
  | 'bing-road'
  | 'bing-aerial'
  | 'bing-dark'
  | 'gaode-street'
  | 'gaode-satellite'
  | 'tianditu-img'
  | 'tianditu-cva'
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
  api_key?: string | null
  enabled?: boolean
  priority?: number
  metadata?: Record<string, unknown>
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
}

export const BASEMAP_PROVIDER_CONFIGS: BasemapProviderConfig[] = [
  {
    id: 'none',
    label: 'Blank Basemap',
    provider: 'None',
    coordinateSystem: 'EPSG:3857',
    endpoints: [
      {
        id: 'blank',
        sourceId: 'none',
        label: '空白',
        url: '',
        authMode: 'none',
        enabled: true,
        style: 'none',
        saturation: 0,
        brightness: 0,
        contrast: 0,
        isStandard: true,
        needsBackendTransform: false,
      },
    ],
  },
  {
    id: 'esri',
    label: 'Esri Basemaps',
    provider: 'Esri',
    routePrefix: '/tiles',
    coordinateSystem: 'EPSG:3857',
    endpoints: [
      {
        id: 'street',
        sourceId: 'esri-street',
        label: 'Esri 世界街道',
        url: '/tiles/esri-street/{z}/{x}/{y}',
        authMode: 'none',
        enabled: true,
        style: 'street',
        attribution: 'Esri',
        tileSize: 256,
        saturation: -0.08,
        brightness: 0.02,
        contrast: 0.08,
        isStandard: true,
        needsBackendTransform: false,
      },
      {
        id: 'imagery',
        sourceId: 'esri-imagery',
        label: 'Esri 世界影像',
        url: '/tiles/esri-imagery/{z}/{x}/{y}',
        authMode: 'none',
        enabled: true,
        style: 'satellite',
        attribution: 'Esri',
        tileSize: 256,
        saturation: 0.04,
        brightness: 0.03,
        contrast: 0.1,
        isStandard: true,
        needsBackendTransform: false,
      },
      {
        id: 'terrain',
        sourceId: 'esri-terrain',
        label: 'Esri 地形',
        url: '/tiles/esri-terrain/{z}/{x}/{y}',
        authMode: 'none',
        enabled: true,
        style: 'terrain',
        attribution: 'Esri',
        tileSize: 256,
        saturation: -0.1,
        brightness: 0.02,
        contrast: 0.12,
        isStandard: true,
        needsBackendTransform: false,
      },
      {
        id: 'dark',
        sourceId: 'esri-dark',
        label: 'Esri 深色',
        url: '/tiles/esri-dark/{z}/{x}/{y}',
        authMode: 'none',
        enabled: true,
        style: 'dark',
        attribution: 'Esri',
        tileSize: 256,
        saturation: -0.15,
        brightness: -0.05,
        contrast: 0.12,
        isStandard: true,
        needsBackendTransform: false,
      },
      {
        id: 'light',
        sourceId: 'esri-light',
        label: 'Esri 浅色',
        url: '/tiles/esri-light/{z}/{x}/{y}',
        authMode: 'none',
        enabled: true,
        style: 'street',
        attribution: 'Esri',
        tileSize: 256,
        saturation: -0.05,
        brightness: 0.02,
        contrast: 0.08,
        isStandard: true,
        needsBackendTransform: false,
      },
    ],
  },
  {
    id: 'osm',
    label: 'OSM Basemaps',
    provider: 'OSM',
    routePrefix: '/tiles',
    coordinateSystem: 'EPSG:3857',
    endpoints: [
      {
        id: 'standard',
        sourceId: 'osm-standard',
        label: 'OSM 标准',
        url: '/tiles/osm-standard/{z}/{x}/{y}',
        authMode: 'none',
        enabled: true,
        style: 'street',
        attribution: '© OpenStreetMap contributors',
        tileSize: 256,
        saturation: 0,
        brightness: 0,
        contrast: 0.02,
        isStandard: true,
        needsBackendTransform: false,
      },
      {
        id: 'hot',
        sourceId: 'osm-hot',
        label: 'OSM 人道主义',
        url: '/tiles/osm-hot/{z}/{x}/{y}',
        authMode: 'none',
        enabled: true,
        style: 'street',
        attribution: '© OpenStreetMap contributors',
        tileSize: 256,
        saturation: -0.05,
        brightness: 0,
        contrast: 0.05,
        isStandard: true,
        needsBackendTransform: false,
        metadata: { providerLabel: 'OSM-FR' },
      },
    ],
  },
  {
    id: 'carto',
    label: 'CARTO Basemaps',
    provider: 'CARTO',
    routePrefix: '/tiles',
    coordinateSystem: 'EPSG:3857',
    endpoints: [
      {
        id: 'dark',
        sourceId: 'carto-dark',
        label: 'CARTO 深色',
        url: '/tiles/carto-dark/{z}/{x}/{y}',
        authMode: 'none',
        enabled: true,
        style: 'dark',
        attribution: 'CARTO',
        tileSize: 256,
        saturation: -0.2,
        brightness: -0.04,
        contrast: 0.16,
        isStandard: true,
        needsBackendTransform: false,
      },
    ],
  },
  {
    id: 'bing',
    label: 'Bing Basemaps',
    provider: 'Bing',
    routePrefix: '/tiles',
    coordinateSystem: 'EPSG:3857',
    endpoints: [
      {
        id: 'road',
        sourceId: 'bing-road',
        label: 'Bing 道路',
        url: '/tiles/bing-road/{z}/{x}/{y}',
        authMode: 'api-key',
        enabled: true,
        style: 'street',
        attribution: '© Microsoft Bing',
        tileSize: 256,
        saturation: -0.02,
        brightness: 0.01,
        contrast: 0.05,
        isStandard: true,
        needsBackendTransform: true,
        secretRef: { id: 'bing-maps-key', backend: 'backend-runtime', key: 'BING_MAPS_KEY' },
      },
      {
        id: 'aerial',
        sourceId: 'bing-aerial',
        label: 'Bing 航空',
        url: '/tiles/bing-aerial/{z}/{x}/{y}',
        authMode: 'api-key',
        enabled: true,
        style: 'satellite',
        attribution: '© Microsoft Bing',
        tileSize: 256,
        saturation: 0.02,
        brightness: 0.02,
        contrast: 0.08,
        isStandard: true,
        needsBackendTransform: true,
        secretRef: { id: 'bing-maps-key', backend: 'backend-runtime', key: 'BING_MAPS_KEY' },
      },
      {
        id: 'dark',
        sourceId: 'bing-dark',
        label: 'Bing 深色',
        url: '/tiles/bing-dark/{z}/{x}/{y}',
        authMode: 'api-key',
        enabled: true,
        style: 'dark',
        attribution: '© Microsoft Bing',
        tileSize: 256,
        saturation: -0.1,
        brightness: -0.04,
        contrast: 0.12,
        isStandard: true,
        needsBackendTransform: true,
        secretRef: { id: 'bing-maps-key', backend: 'backend-runtime', key: 'BING_MAPS_KEY' },
      },
    ],
  },
  {
    id: 'gaode',
    label: 'Gaode Basemaps',
    provider: 'AutoNavi',
    routePrefix: '/tiles',
    coordinateSystem: 'GCJ-02',
    endpoints: [
      {
        id: 'street',
        sourceId: 'gaode-street',
        label: '高德街道',
        url: '/tiles/gaode-street/{z}/{x}/{y}',
        authMode: 'api-key',
        enabled: true,
        style: 'street',
        attribution: '© 高德地图',
        tileSize: 256,
        saturation: 0,
        brightness: 0,
        contrast: 0.05,
        isStandard: true,
        needsBackendTransform: true,
        secretRef: { id: 'gaode-key', backend: 'backend-runtime', key: 'GAODE_API_KEY' },
      },
      {
        id: 'satellite',
        sourceId: 'gaode-satellite',
        label: '高德卫星',
        url: '/tiles/gaode-satellite/{z}/{x}/{y}',
        authMode: 'api-key',
        enabled: true,
        style: 'satellite',
        attribution: '© 高德影像',
        tileSize: 256,
        saturation: 0.02,
        brightness: 0.02,
        contrast: 0.08,
        isStandard: true,
        needsBackendTransform: true,
        secretRef: { id: 'gaode-key', backend: 'backend-runtime', key: 'GAODE_API_KEY' },
      },
    ],
  },
  {
    id: 'tianditu',
    label: 'Tianditu Basemaps',
    provider: 'Tianditu',
    routePrefix: '/tiles',
    coordinateSystem: 'EPSG:3857',
    endpoints: [
      {
        id: 'imagery',
        sourceId: 'tianditu-img',
        label: '天地图影像',
        url: '/tiles/tianditu-img/{z}/{x}/{y}',
        authMode: 'api-key',
        enabled: true,
        style: 'satellite',
        attribution: '© 天地图',
        tileSize: 256,
        saturation: 0.02,
        brightness: 0.02,
        contrast: 0.08,
        isStandard: true,
        needsBackendTransform: true,
        secretRef: { id: 'tianditu-token', backend: 'backend-runtime', key: 'TIANDITU_TOKEN' },
      },
      {
        id: 'annotation',
        sourceId: 'tianditu-cva',
        label: '天地图标注',
        url: '/tiles/tianditu-cva/{z}/{x}/{y}',
        authMode: 'api-key',
        enabled: true,
        style: 'street',
        attribution: '© 天地图',
        tileSize: 256,
        saturation: 0,
        brightness: 0,
        contrast: 0.02,
        isStandard: true,
        needsBackendTransform: true,
        secretRef: { id: 'tianditu-token', backend: 'backend-runtime', key: 'TIANDITU_TOKEN' },
      },
    ],
  },
  {
    id: 'baidu',
    label: 'Baidu Basemaps',
    provider: 'Baidu',
    routePrefix: '/tiles',
    coordinateSystem: 'BD-09',
    endpoints: [
      {
        id: 'street',
        sourceId: 'baidu-street',
        label: '百度街道',
        url: '/tiles/baidu-street/{z}/{x}/{y}',
        authMode: 'api-key',
        enabled: true,
        style: 'street',
        attribution: '© 百度地图',
        tileSize: 256,
        saturation: 0,
        brightness: 0,
        contrast: 0.05,
        isStandard: true,
        needsBackendTransform: true,
        secretRef: { id: 'baidu-map-ak', backend: 'backend-runtime', key: 'BAIDU_MAP_AK' },
      },
      {
        id: 'satellite',
        sourceId: 'baidu-satellite',
        label: '百度卫星',
        url: '/tiles/baidu-satellite/{z}/{x}/{y}',
        authMode: 'api-key',
        enabled: true,
        style: 'satellite',
        attribution: '© 百度影像',
        tileSize: 256,
        saturation: 0.02,
        brightness: 0.02,
        contrast: 0.08,
        isStandard: true,
        needsBackendTransform: true,
        secretRef: { id: 'baidu-map-ak', backend: 'backend-runtime', key: 'BAIDU_MAP_AK' },
      },
    ],
  },
]

export const EXTERNAL_API_CONFIGS: ExternalApiConfig[] = [
  {
    id: 'open-meteo',
    label: 'Open-Meteo',
    domain: 'data-source',
    capabilities: ['weather', 'forecast'],
    endpoints: [
      {
        id: 'forecast',
        label: 'Forecast API',
        url: 'https://api.open-meteo.com/v1/forecast',
        authMode: 'none',
        enabled: true,
        timeoutMs: 30000,
      },
    ],
  },
  {
    id: 'basemap-proxy',
    label: 'Basemap Proxy',
    domain: 'basemap',
    capabilities: ['tile-proxy', 'coord-transform'],
    endpoints: [
      {
        id: 'tiles',
        label: 'Tile Proxy',
        url: '/tiles/{provider}/{z}/{x}/{y}',
        authMode: 'none',
        enabled: true,
      },
    ],
  },
]

export const GEE_INTEGRATION_CONFIG: GeeIntegrationConfig = {
  enabled: true,
  environment: 'dev',
  moduleRoot: 'backend-managed',
  credentialsStoreRef: {
    id: 'gee-credentials-db',
    backend: 'backend-runtime',
    key: 'GEE_CREDENTIALS_DB_PATH',
  },
  encryptionKeyRef: {
    id: 'gee-credentials-key',
    backend: 'backend-runtime',
    key: 'GEE_CREDENTIALS_ENCRYPTION_KEY',
  },
  accounts: [
    {
      id: 'gee-account-template',
      label: 'GEE Account Template',
      enabled: false,
      credentialRef: {
        id: 'gee-service-account-json',
        backend: 'vault',
        key: 'GEE_SERVICE_ACCOUNT_JSON',
      },
    },
  ],
}

export const UNIFIED_INTEGRATION_CONFIG_TEMPLATE: UnifiedIntegrationConfig = {
  version: '0.2.0',
  updatedAt: '2026-07-09T00:00:00Z',
  basemaps: BASEMAP_PROVIDER_CONFIGS,
  externalApis: EXTERNAL_API_CONFIGS,
  gee: GEE_INTEGRATION_CONFIG,
}

export const TILE_SOURCES: TileSourceConfig[] = BASEMAP_PROVIDER_CONFIGS.flatMap((provider) =>
  provider.endpoints
    .filter((endpoint) => endpoint.enabled)
    .map((endpoint) => ({
      id: endpoint.sourceId,
      label: endpoint.label,
      provider: typeof endpoint.metadata?.providerLabel === 'string'
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

export function getDefaultTileSource(): TileSourceId {
  return 'esri-street'
}

export function isSourceAvailable(sourceId: TileSourceId): boolean {
  return sourceId !== 'none' && TILE_SOURCE_MAP.has(sourceId)
}

export function listEnabledBasemapProviders(config: UnifiedIntegrationConfig) {
  return config.basemaps.filter((provider) => provider.endpoints.some((endpoint) => endpoint.enabled))
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

async function requestConfigJson<T>(path: string, init?: RequestInit & { timeoutMs?: number }): Promise<T> {
  const { timeoutMs, ...restInit } = init ?? {}
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs ?? 15000)

  try {
    const response = await fetch(resolveApiUrl(path), {
      ...restInit,
      headers: {
        'Content-Type': 'application/json',
        ...(restInit.headers as Record<string, string> | undefined),
      },
      signal: restInit.signal ?? controller.signal,
    })

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status} ${path}`)
    }

    return (await response.json()) as T
  } finally {
    window.clearTimeout(timeoutId)
  }
}

function hasApiCredential(apiKey: string | null | undefined, metadata?: Record<string, unknown>) {
  if (typeof apiKey === 'string' && apiKey.trim().length > 0) {
    return true
  }
  if (metadata && typeof metadata.credentials_path === 'string' && metadata.credentials_path.trim().length > 0) {
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
    runtimeAuthConfigured: hasApiCredential(runtimeConfig.api_key, runtimeConfig.metadata),
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
          runtimeAuthConfigured: hasApiCredential(config.api_key, config.metadata),
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
          runtimeAuthConfigured: hasApiCredential(config.api_key, config.metadata),
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

  const [runtimeApiConfigsResult, geeConfigResult, geeStatusResult, geeEnvironmentResult] = await Promise.allSettled([
    requestConfigJson<Record<string, RuntimeApiProviderResponse>>('/runtime/api-config'),
    requestConfigJson<GeeConfigResponse>('/gee/config'),
    requestConfigJson<GeeStatusResponse>('/gee/config/status'),
    requestConfigJson<GeeEnvironmentResponse>('/gee/config/environment'),
  ])

  if (runtimeApiConfigsResult.status === 'fulfilled') {
    mergeRuntimeApiConfigs(baseConfig, normalizeRuntimeApiProviderEntries(runtimeApiConfigsResult.value))
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
