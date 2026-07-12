/**
 * 从 openapi-typescript 自动生成的 `api-contracts.ts` 中 re-export 常用 schema 为扁平命名。
 *
 * 设计意图：
 *  - 消除前端手写 interface 与后端 Pydantic 模型的重复维护。
 *  - 保留现有导入路径兼容：消费方仍可从 `services/runtime-api` 或本文件导入同名类型。
 *  - 历史 `Runtime*` 前缀名通过别名映射到后端真实 schema 名（如 `RuntimeLayerDescriptor` → `LayerDescriptor`）。
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
// 历史 `Runtime*` 前缀名通过别名映射到后端真实 schema 名，保持向后兼容。

export type LayerDescriptor = Schema<'LayerDescriptor'>
export type LayerCapabilities = Schema<'LayerCapabilities'>
export type LayerStyleHint = Schema<'LayerStyleHint'>
export type LayerCatalogResponse = Schema<'LayerCatalogResponse'>

/** @deprecated 请使用 `LayerDescriptor`。保留别名以兼容现有导入。 */
export type RuntimeLayerDescriptor = LayerDescriptor
/** @deprecated 请使用 `LayerCapabilities`。保留别名以兼容现有导入。 */
export type RuntimeLayerCapabilities = LayerCapabilities
/** @deprecated 请使用 `LayerStyleHint`。保留别名以兼容现有导入。 */
export type RuntimeLayerStyleHint = LayerStyleHint
/** @deprecated 请使用 `LayerCatalogResponse`。保留别名以兼容现有导入。 */
export type RuntimeLayerCatalogResponse = LayerCatalogResponse

// ── Weather 相关 ──────────────────────────────────────────────────────────

export type WeatherLayerRenderHint = Schema<'WeatherLayerRenderHint'>
export type WeatherPointCurrent = Schema<'WeatherPointCurrent'>
export type WeatherPointHourlyEntry = Schema<'WeatherPointHourlyEntry'>
export type WeatherPointResponse = Schema<'WeatherPointResponse'>
