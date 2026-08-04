// ─── Layer category & source ─────────────────────────────────────────────────

export interface LayerCategory {
  id: string
  name: string
  icon: string
  accentColor: string
  chipTone: string
}

export interface LayerSource {
  id: string
  name: string
  description: string
  /** URL 模板，{x}/{y}/{z} 占位符，可包含参数如 {time} */
  urlTemplate: string
  /** 附加 URL 参数 */
  urlParams?: Record<string, string>
  /** 需要认证 (API Key) */
  needsAuth: boolean
  /** 需要后端坐标转换 */
  needsBackendTransform: boolean
  /** 坐标系 */
  coordSys: 'EPSG:3857' | 'EPSG:4326' | 'GCJ-02' | 'BD-09'
  /** 数据更新频率描述 */
  updateFrequency: string
  attribution?: string
}

// ─── Layer catalog item (图层库条目) ─────────────────────────────────────────

export interface LayerCatalogItem {
  /** 唯一标识，与后端 layer_id 对齐 */
  catalogId: string
  name: string
  category: string
  /** 课题组数据二级分类: '模型输入' | '模型输出' | '辅助数据' */
  subCategory?: '模型输入' | '模型输出' | '辅助数据'
  metricLabel: string
  metricUnit: string
  metricPrecision: number
  updateLabel: string
  sourceLabel: string
  accentColor: string
  accentGlow: string
  chipTone: string
  /** 可选数据源列表，为空则使用默认源 */
  sources: LayerSource[]
  /** 是否内置行政区边界图层 */
  isAdminBoundary?: boolean
  // ── 课题组数据集元数据扩展（Phase 1：扩展和细化）────────────────────────────
  /** 数据归属（课题组成员 / Lab / 留空表示外部公开数据）；与 NAS 顶级目录对齐 */
  dataOwner?: string
  /** 时间覆盖范围的人类可读描述，如 '2023-01' / '2018-2020' / 'doy 017-030' */
  temporalCoverage?: string
  /** 数据源引用（DOI / URL / 官方页面），用于学术溯源 */
  sourceReference?: string
}

export interface RuntimeLayerLibraryItem extends LayerCatalogItem {
  description: string
  engine?: string | null
  sourceType?: string | null
  renderType?: string | null
  workflowName?: string | null
  runReadiness: string
  runReadinessSummary?: string | null
  runReadinessNotes: string[]
  backendStatus?: string | null
  defaultVisible?: boolean
  supportsTime?: boolean
}

// ─── Job layer item (作业生产数据) ───────────────────────────────────────────

export type JobStatus =
  'running' | 'succeeded' | 'failed' | 'queued' | 'cancelled' | 'retry_pending'

// ─── Workflow summary (全局工作流状态汇总) ──────────────────────────────────

export interface WorkflowSummary {
  total: number
  running: number
  queued: number
  succeeded: number
  failed: number
  cancelled: number
  retryPending: number
  /** 整体状态：idle | active | succeeded | failed | mixed */
  overall: 'idle' | 'active' | 'succeeded' | 'failed' | 'mixed'
  /** 用于按钮配色的状态键 */
  tone: 'idle' | 'active' | 'success' | 'warning' | 'error'
  hasError: boolean
}

import type {
  WeatherLayerRenderHint,
  WorkflowResultDto,
  WorkflowRunViewResponse,
} from '../../types/api-reexports'

export type { WeatherLayerRenderHint }

export interface JobLayerMapAssets {
  geojsonUrl?: string
  geojsonData?: Record<string, unknown>
  cogUrl?: string
  cogPreviewUrl?: string
  cogBbox?: {
    west: number
    south: number
    east: number
    north: number
    crs?: string
  }
  /** 后端 imported overlay id（算法产品提交后） */
  overlayLayerId?: string
  /** 产品标签（SM / VOD / OMEGA 等） */
  productTag?: string
}

export interface JobLayerMapLayerPayload {
  renderHint?: WeatherLayerRenderHint
  pointFeature?: Record<string, unknown>
  layerAssets?: JobLayerMapAssets
}

/** 节点级进度信息 */
export interface NodeProgress {
  /** 节点 ID */
  nodeId: string
  /** 节点显示名 */
  nodeLabel: string
  /** 阶段: "download" | "preprocess" | "inversion" | "output" */
  stage: string
  /** 进度 0-100 */
  progress: number
  /** 当前消息 */
  message?: string
  /** 产物路径列表 */
  artifacts?: string[]
  /** 最近一次 node_progress 事件时间（ISO） */
  updatedAt?: string
  /** chunk/pixel/block 细粒度进度（算法反演等长任务） */
  detail?: {
    chunksDone?: number
    chunksTotal?: number
    pixelsDone?: number
    pixelsTotal?: number
    phase?: string
    blocksDone?: number
    blocksTotal?: number
    dateStart?: string
    dateEnd?: string
    blockIdx?: number
    blockDir?: string
    timeKey?: string
    tileId?: string
    chunkId?: string
    blockId?: string
    productTag?: string
    moduleName?: string
  }
}

export interface JobLayerItem {
  /** 作业 ID (run_id) */
  jobId: string
  /** 作业标签/名称 */
  name: string
  /** 关联的图层目录 ID（用于面板列表展示与重试/取消操作） */
  catalogId?: string
  commandType: string
  status: JobStatus
  /** 0-100 */
  progress: number
  createdAt: string
  updatedAt: string
  message: string
  /** 简要指标 */
  metrics?: Array<{ label: string; value: string }>
  /** 报告文本摘要 */
  reportSummary?: string
  /** 统一结果视图 */
  resultDto?: WorkflowResultDto
  /** UI 视图模型 */
  resultView?: WorkflowRunViewResponse
  /** 结果引用链接 */
  resultUrl?: string
  /** map_layer 产物中的附加地图资产 */
  mapLayerPayload?: JobLayerMapLayerPayload
  /** 原始诊断信息 */
  diagnostics?: string[]
  /** 面向 UI 的诊断摘要 */
  diagnosticNotes?: string[]
  /** 最近一次已消费的事件游标 */
  lastEventId?: string
  /** 最近一次事件时间 */
  lastEventAt?: string
  /** 最近的增量事件消息，用于运行中展示持续产出 */
  eventMessages?: string[]
  /** 节点级进度（下载/预处理/反演各阶段） */
  nodeProgress?: NodeProgress[]
  /** 运行中 incremental materialize 已同步的时间片/图层数 */
  progressiveOverlayCount?: number
  /** incremental materialize 最近一次错误（用户可见摘要） */
  progressiveOverlayError?: string
  /** incremental materialize 最近一次成功时间（ISO） */
  progressiveOverlayAt?: string
  /** 若为重试运行，指向原 run_id */
  retryOfRunId?: string
}

// ─── Active layer (已添加图层) ────────────────────────────────────────────────

/** Active TOC 中的工作流计算组（与 library 的 output.group 文案无关） */
export interface ActiveRunLayerGroup {
  groupId: string
  runId: string
  title: string
  status: 'computing' | 'ready' | 'failed' | 'cancelled'
  memberInstanceIds: string[]
  /** succeeded 且成员均可显示，或 failed/cancelled 时可拆 */
  dissolvable: boolean
  sourceLayerId?: string
  workflowId?: string
  progress?: number
  message?: string
}

export interface ActiveLayer {
  /** 实例 ID (uuid)，用于列表 key 和唯一性 */
  instanceId: string
  catalogId: string
  /** 显示名覆盖（导入图层等无 catalog 条目时使用） */
  name?: string
  /** 是否可见 */
  visible: boolean
  /** 透明度 0-1 */
  opacity: number
  /** 叠加顺序，数字越大越在上层 */
  order: number
  /** 是否为行政区边界图层 */
  isAdminBoundary: boolean
  /** 若来自作业，则关联作业信息 */
  jobLayer?: JobLayerItem
  /** 本地导入的矢量数据 */
  importedVector?: import('./imported-vector').ImportedVectorPayload
  /** 本地导入的栅格（后端 overlay_layer_id） */
  importedRaster?: import('./imported-raster').ImportedRasterPayload
  /** 数据状态：catalog | real | imported */
  dataState: 'catalog' | 'real' | 'imported'
  /** 用户自定义配色方案覆盖（覆盖默认 renderHint.palette） */
  paletteOverride?: string | null
  /** 实例级强调色（侧栏区分 / 时间轴主色） */
  accentColor?: string
  accentGlow?: string
  chipTone?: string
  /** 所属计算组（工作流运行占位） */
  runGroupId?: string
  /** 组内产品标签（SM / VOD / result…） */
  runGroupProductTag?: string
  /** 计算中禁止单独拖出组 */
  runGroupLocked?: boolean
}

// ─── Layer sidebar view mode ──────────────────────────────────────────────────

export type LayerSidebarView = 'empty' | 'library' | 'active'

// ─── Derived types ────────────────────────────────────────────────────────────

export type AvailabilityState = 'empty' | 'partial' | 'ready'

export interface LayerHotspot {
  id: string
  name: string
  lng: number
  lat: number
  value: string
}

export interface ActiveLayerDisplay {
  instanceId: string
  catalogId: string
  name: string
  category: string
  subCategory?: '模型输入' | '模型输出' | '辅助数据'
  description?: string
  engine?: string | null
  supportsTime?: boolean
  runReadiness?: string
  runReadinessSummary?: string | null
  summary: string
  metricLabel: string
  metricValue: string
  trendLabel: string
  statusLabel: string
  updateLabel: string
  sourceLabel: string
  confidenceLabel: string
  accentColor: string
  accentGlow: string
  chipTone: string
  availabilityState: AvailabilityState
  availabilityLabel: string
  availabilityDescription: string
  observationTimeLabel: string
  missingFieldsLabel: string
  hotspots: LayerHotspot[]
  isAdminBoundary: boolean
  /** 是否为本地导入矢量图层 */
  isImported: boolean
  /** 是否为本地导入栅格图层 */
  isImportedRaster: boolean
  jobLayer?: JobLayerItem
  visible: boolean
  opacity: number
  order: number
  dataState: 'catalog' | 'real' | 'imported'
  /** 天气图层默认渲染提示（tile manager 路径下使用） */
  renderHint?: WeatherLayerRenderHint
  /** 用户自定义配色方案覆盖 */
  paletteOverride?: string | null
  /** 导入矢量元信息（仅 isImported） */
  importedGeometryType?: string
  importedFeatureCount?: number
  /** 导入矢量的后端 layer_id（用于 /export/layer） */
  importedVectorBackendLayerId?: string
  /** 导入栅格元信息（仅 isImportedRaster） */
  importedRasterBounds?: [number, number, number, number]
  /** 导入栅格源 CRS */
  importedRasterSourceCrs?: string
  /** 导入栅格原生时间步（如 8d） */
  importedRasterNativeStep?: string
  /** 导入栅格当前生效区间标签 */
  importedRasterEffectiveTime?: string
  /** 导入栅格可用时刻/块数量 */
  importedRasterTimeCount?: number
  /** 导入文件名 */
  importedFileName?: string
  /** 导入矢量样式（仅 isImported） */
  importedVectorStyle?: {
    color?: string
    width?: number
    radius?: number
    fillOpacity?: number
  }
  /** 导入数据包围盒（矢量 / 栅格） */
  importedBounds?: [number, number, number, number]
  /** 计算组 */
  runGroupId?: string
  runGroupProductTag?: string
  runGroupLocked?: boolean
}
