/**
 * 从 openapi-typescript 自动生成的 `api-contracts.ts` 中 re-export 常用 schema 为扁平命名。
 *
 * 设计意图：
 *  - 消除前端手写 interface 与后端 Pydantic 模型的重复维护。
 *  - 保留现有导入路径兼容：消费方仍可从 `services/runtime-api` 或本文件导入同名类型。
 *
 * 注意：自动生成的字段可选性与手写版本可能不同（Pydantic 默认值字段在 OpenAPI 中会标记为可选）。
 *       消费方在访问这些字段时需进行 null/undefined 检查。
 */

import type { components } from './api-contracts'

type Schema<K extends keyof components['schemas']> = components['schemas'][K]

// ── 枚举（字符串字面量联合） ───────────────────────────────────────────────

export type ExecutionStatus = Schema<'ExecutionStatus'>
export type WorkflowCommandType = Schema<'WorkflowCommandType'>
export type WorkflowPriority = Schema<'WorkflowPriority'>
export type WorkflowResourceProfile = Schema<'WorkflowResourceProfile'>
export type ResultKind = Schema<'ResultKind'>
export type EventChannel = Schema<'EventChannel'>
export type LogLevel = Schema<'LogLevel'>
export type MapMode = Schema<'MapMode'>
export type LayerSourceType = Schema<'LayerSourceType'>
export type LayerRenderType = Schema<'LayerRenderType'>
export type TimeGranularity = Schema<'TimeGranularity'>

// ── 通用结构 ──────────────────────────────────────────────────────────────

export type BoundingBox = Schema<'BoundingBox'>
export type SpatialFilter = Schema<'SpatialFilter'>
export type TimeRange = Schema<'TimeRange'>
export type ClientIdentity = Schema<'ClientIdentity'>
export type RuntimeMapContext = Schema<'RuntimeMapContext'>
export type RetryPolicy = Schema<'RetryPolicy'>

// ── Workflow 相关 ─────────────────────────────────────────────────────────

export type WorkflowSubmitRequest = Schema<'WorkflowSubmitRequest'>
export type WorkflowAcceptedResponse = Schema<'WorkflowAcceptedResponse'>
export type WorkflowResultReference = Schema<'WorkflowResultReference'>
export type WorkflowEvent = Schema<'WorkflowEvent'>
export type WorkflowEventsResponse = Schema<'WorkflowEventsResponse'>
export type WorkflowAnalysisResultDto = Schema<'WorkflowAnalysisResultDto'>
export type WorkflowProviderResultDto = Schema<'WorkflowProviderResultDto'>
export type WorkflowDownloadResultDto = Schema<'WorkflowDownloadResultDto'>

/**
 * 工作流结果 DTO 联合类型。
 *
 * 后端 OpenAPI 中此联合类型作为 `WorkflowRunStatusResponse.result_dto` 的内联类型出现，
 * 没有独立命名。这里显式声明以供前端多处复用。
 */
export type WorkflowResultDto =
  | WorkflowAnalysisResultDto
  | WorkflowProviderResultDto
  | WorkflowDownloadResultDto
  | Record<string, unknown>

export type WorkflowRunStatusResponse = Schema<'WorkflowRunStatusResponse'>
export type WorkflowRunViewSummaryRow = Schema<'WorkflowRunViewSummaryRow'>
export type WorkflowRunViewResponse = Schema<'WorkflowRunViewResponse'>

// ── Layer catalog 相关 ────────────────────────────────────────────────────

export type LayerDescriptor = Schema<'LayerDescriptor'>
export type LayerCapabilities = Schema<'LayerCapabilities'>
export type OnlineTemporalCapability = Schema<'OnlineTemporalCapability'>
export type LayerStyleHint = Schema<'LayerStyleHint'>
export type LayerPresentation = Schema<'LayerPresentation'>
export type LayerCatalogResponse = Schema<'LayerCatalogResponse'>
export type LayerCategoryDef = Schema<'LayerCategoryDef'>
export type LayerCategoryResponse = Schema<'LayerCategoryResponse'>

// ── 图层平台子系统：资产状态与生命周期（P0，2026-08-24） ───────────────────

export type LayerAssetStateResponse = Schema<'LayerAssetStateResponse'>
export type LayerLifecycleRunSummary = Schema<'LayerLifecycleRunSummary'>
export type LayerLifecycleResponse = Schema<'LayerLifecycleResponse'>

// ── 图层平台子系统：在线源同步（P1，2026-08-25） ─────────────────────────────

export type LayerOnlineSyncRequest = Schema<'LayerOnlineSyncRequest'>
export type LayerOnlineSyncResponse = Schema<'LayerOnlineSyncResponse'>

// ── 图层平台子系统：课题组工作流模板（P1，2026-08-25） ───────────────────────

export type WorkflowTemplateSummary = Schema<'WorkflowTemplateSummary'>
export type WorkflowTemplateListResponse = Schema<'WorkflowTemplateListResponse'>
export type WorkflowTemplateRunRequest = Schema<'WorkflowTemplateRunRequest'>
export type WorkflowTemplateRunResponse = Schema<'WorkflowTemplateRunResponse'>

// ── 图层平台子系统：统一在线源凭证状态（P2-3，2026-08-25） ────────────────────

export type OnlineSourceCredentialStatus = Schema<'OnlineSourceCredentialStatus'>
export type OnlineSourcesResponse = Schema<'OnlineSourcesResponse'>

// ── Weather 相关 ──────────────────────────────────────────────────────────

export type WeatherLayerRenderHint = Schema<'WeatherLayerRenderHint'>
export type WeatherPointCurrent = Schema<'WeatherPointCurrent'>
export type WeatherPointHourlyEntry = Schema<'WeatherPointHourlyEntry'>
export type WeatherPointResponse = Schema<'WeatherPointResponse'>

// ── Config / settings（/config/*）──────────────────────────────────────────

export type ApiKeyItem = Schema<'ApiKeyItem'>
export type ApiKeyUpdateRequest = Schema<'ApiKeyUpdateRequest'>
export type ApiKeyHistoryItem = Schema<'ApiKeyHistoryItem'>
export type ApiKeyHistoryClearResponse = Schema<'ApiKeyHistoryClearResponse'>
export type ApiKeyHistoryDeletedResponse = Schema<'ApiKeyHistoryDeletedResponse'>
export type ApiKeyDeletedResponse = Schema<'ApiKeyDeletedResponse'>
export type ApiKeyToggleRequest = Schema<'ApiKeyToggleRequest'>

export type GeeAccountItem = Schema<'GeeAccountItem'>
export type GeeAccountCreateRequest = Schema<'GeeAccountCreateRequest'>
export type GeeAccountToggleRequest = Schema<'GeeAccountToggleRequest'>
export type GeeAccountDeletedResponse = Schema<'GeeAccountDeletedResponse'>
export type GeeAccountToggleResponse = Schema<'GeeAccountToggleResponse'>
export type GeeRuntimeConfig = Schema<'GeeRuntimeConfig'>

export type GeneralConfig = Schema<'GeneralConfig'>
export type MapAoiPreset = Schema<'MapAoiPreset'>

export type WeatherConfig = Schema<'WeatherConfig'>
export type WeatherSyncCron = Schema<'WeatherSyncCron'>
export type WeatherSupportedModel = Schema<'WeatherSupportedModel'>
export type WeatherModelUpdateRequest = Schema<'WeatherModelUpdateRequest'>
export type WeatherProviderStatus = Schema<'WeatherProviderStatus'>
export type WeatherProviderConfigField = Schema<'WeatherProviderConfigField'>
export type WeatherProviderItem = Schema<'WeatherProviderItem'>
export type WeatherProviderUpdateRequest = Schema<'WeatherProviderUpdateRequest'>
export type WeatherProviderTestResponse = Schema<'WeatherProviderTestResponse'>
export type WeatherProviderToggleRequest = Schema<'WeatherProviderToggleRequest'>
export type WeatherProviderPriorityRequest = Schema<'WeatherProviderPriorityRequest'>
export type WeatherProviderToggleResponse = Schema<'WeatherProviderToggleResponse'>
export type WeatherProviderPriorityResponse = Schema<'WeatherProviderPriorityResponse'>
export type WeatherProviderDeletedResponse = Schema<'WeatherProviderDeletedResponse'>

export type DataSourceConfig = Schema<'DataSourceConfig'>
export type OnlineTileSource = Schema<'OnlineTileSource'>
export type OnlineTileSourceUpsertRequest = Schema<'OnlineTileSourceUpsertRequest'>
export type DataSourcePathsUpdateRequest = Schema<'DataSourcePathsUpdateRequest'>
export type DataSourcePathsUpdateResponse = Schema<'DataSourcePathsUpdateResponse'>
export type DiscoveredDataset = Schema<'DiscoveredDataset'>

// ── 部署配置中心（/config/deployment） ─────────────────────────────────────
export type DeploymentConfigStatus = Schema<'DeploymentConfigStatus'>
export type DeploymentKeyValueStatus = Schema<'DeploymentKeyValueStatus'>
export type DeploymentPreviewDiffItem = Schema<'DeploymentPreviewDiffItem'>
export type DeploymentBackupInfo = Schema<'DeploymentBackupInfo'>
export type DeploymentConfigUpdateRequest = Schema<'DeploymentConfigUpdateRequest'>
export type DeploymentConfigPreviewResponse = Schema<'DeploymentConfigPreviewResponse'>
export type DeploymentConfigUpdateResponse = Schema<'DeploymentConfigUpdateResponse'>
export type DeploymentDataGroup = Schema<'DeploymentDataGroup'>
export type DeploymentRuntimeGroup = Schema<'DeploymentRuntimeGroup'>
export type DeploymentCachesGroup = Schema<'DeploymentCachesGroup'>
export type DeploymentImportsGroup = Schema<'DeploymentImportsGroup'>
export type DeploymentDockerGroup = Schema<'DeploymentDockerGroup'>
export type MinioPublicConfig = Schema<'MinioPublicConfig'>
export type StaticCacheSummary = Schema<'StaticCacheSummary'>
export type PortalCredentialPublic = Schema<'PortalCredentialPublic'>
export type PortalCredentialsMapResponse = Schema<'PortalCredentialsMapResponse'>
export type PortalCredentialUpsertRequest = Schema<'PortalCredentialUpsertRequest'>
export type DataCacheOverview = Schema<'DataCacheOverview'>
export type DataCacheEntry = Schema<'DataCacheEntry'>
export type DataCacheEvictRequest = Schema<'DataCacheEvictRequest'>
export type DataCacheEvictResponse = Schema<'DataCacheEvictResponse'>
export type OpenDataPresetsUpdateRequest = Schema<'OpenDataPresetsUpdateRequest'>
export type OpenDataPresetsUpdateResponse = Schema<'OpenDataPresetsUpdateResponse'>
export type RemoteLayerUrisUpdateRequest = Schema<'RemoteLayerUrisUpdateRequest'>
export type RemoteLayerUrisUpdateResponse = Schema<'RemoteLayerUrisUpdateResponse'>

export type ServiceRestartRequest = Schema<'ServiceRestartRequest'>
export type ServiceRestartResponse = Schema<'ServiceRestartResponse'>

export type AboutInfo = Schema<'AboutInfo'>
export type AboutModule = Schema<'AboutModule'>

export type TestResultResponse = Schema<'TestResultResponse'>
export type ReloadResultResponse = Schema<'ReloadResultResponse'>

export type RemoteStorageProfile = Schema<'RemoteStorageProfile'>
export type RemoteStorageUpsertRequest = Schema<'RemoteStorageUpsertRequest'>
export type RemoteStorageTestResponse = Schema<'RemoteStorageTestResponse'>
export type RemoteStorageHistoryItem = Schema<'RemoteStorageHistoryItem'>
export type RemoteStorageHistoryClearResponse = Schema<'RemoteStorageHistoryClearResponse'>
export type RemoteStorageHistoryDeletedResponse = Schema<'RemoteStorageHistoryDeletedResponse'>
export type RemoteStorageDeletedResponse = Schema<'RemoteStorageDeletedResponse'>
export type RemoteStorageToggleRequest = Schema<'RemoteStorageToggleRequest'>
export type RemoteStorageToggleResponse = Schema<'RemoteStorageToggleResponse'>
export type RemoteStorageTestRequest = Schema<'RemoteStorageTestRequest'>
export type RemoteEntryItem = Schema<'RemoteEntryItem'>
export type RemoteBrowseRequest = Schema<'RemoteBrowseRequest'>
export type RemoteBrowseResponse = Schema<'RemoteBrowseResponse'>
export type RemoteSearchRequest = Schema<'RemoteSearchRequest'>
export type RemoteSearchResponse = Schema<'RemoteSearchResponse'>
export type RemoteFailoverRequest = Schema<'RemoteFailoverRequest'>
export type RemoteFailoverResponse = Schema<'RemoteFailoverResponse'>

// ── 开放门户目录（Phase B） ─────────────────────────────────────────────────

export type PortalCatalogEntry = Schema<'PortalCatalogEntry'>
export type PortalCatalogResponse = Schema<'PortalCatalogResponse'>
export type PortalUpsertRequest = Schema<'PortalUpsertRequest'>
export type PortalTestResponse = Schema<'PortalTestResponse'>
export type PortalSearchResponse = Schema<'PortalSearchResponse'>
export type PortalSearchDatasetItem = Schema<'PortalSearchDatasetItem'>

// ── 可用数据集 / 远程数据源注册表（Phase C） ─────────────────────────────────

export type AvailableDatasetEntry = Schema<'AvailableDatasetEntry'>
export type DatasetUpsertRequest = Schema<'DatasetUpsertRequest'>
export type DatasetRescanResponse = Schema<'DatasetRescanResponse'>
export type RemoteSourceEntry = Schema<'RemoteSourceEntry'>
export type RemoteSourceRefBadge = Schema<'RemoteSourceRefBadge'>
export type RemoteSourceUpsertRequest = Schema<'RemoteSourceUpsertRequest'>
// 注册并添加到图层（原子端点，2026-08-25 P2/Wave 2）
export type RegisterAndAddRequest = Schema<'RegisterAndAddRequest'>
export type RegisterAndAddResponse = Schema<'RegisterAndAddResponse'>
export type WorkflowHint = Schema<'WorkflowHint'>

// ── 远程数据集授权（数据集化改造阶段 1） ─────────────────────────────────────

export type RemoteDatasetGrant = Schema<'RemoteDatasetGrant'>
export type RemoteDatasetGrantUpsertRequest = Schema<'RemoteDatasetGrantUpsertRequest'>
export type RemoteDatasetPolicy = Schema<'RemoteDatasetPolicy'>
export type RemoteDatasetPolicyDataset = Schema<'RemoteDatasetPolicyDataset'>

export type DeletedResponse = Schema<'DeletedResponse'>

export type RuntimeConfigScope = Schema<'RuntimeConfigScope'>
export type RuntimeConfigPatch = Schema<'RuntimeConfigPatch'>
export type RuntimeConfigUpdateRequest = Schema<'RuntimeConfigUpdateRequest'>
export type RuntimeConfigUpdateResponse = Schema<'RuntimeConfigUpdateResponse'>
export type RuntimeConfigSnapshotResponse = Schema<'RuntimeConfigSnapshotResponse'>
export type RuntimeStatusResponse = Schema<'RuntimeStatusResponse'>
export type BackendServiceStatus = Schema<'BackendServiceStatus'>
export type ResourceUsageResponse = Schema<'ResourceUsageResponse'>
export type SystemResourceSnapshot = Schema<'SystemResourceSnapshot'>
export type ProcessResourceSnapshot = Schema<'ProcessResourceSnapshot'>

/** OpenAPI 为 plain string；UI 侧已知取值（与后端 weather provider 注册一致）。 */
export type WeatherProviderType = 'free_api' | 'commercial_api' | 'local_data'
export type WeatherCapability = 'all' | 'point_query' | 'grid_query'
export type CircuitState = 'closed' | 'open' | 'half_open' | 'n/a'
/** 远程存储协议（与后端 ALLOWED_PROTOCOLS 对齐，Phase A 扩展至 11 种）。 */
export type RemoteStorageProtocol =
  | 'sftp'
  | 'ssh'
  | 'smb'
  | 'ftp'
  | 'ftps'
  | 'gs'
  | 'http'
  | 'https'
  | 'filebrowser'
  | 'lan'
  | 'nfs'
/** 双路径回退模式（存 profile extra.fallback_mode）。 */
export type RemoteFallbackMode = 'auto' | 'manual' | 'off'
/** 可用数据集来源。 */
export type DatasetSource = 'manual' | 'scan' | 'algorithm_registry'
/** 远程数据源别名引用类型。 */
export type RemoteSourceKind = 'storage_profile' | 'portal'
