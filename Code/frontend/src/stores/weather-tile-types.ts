/**
 * Weather tile manager — shared constants & types (P1-1 split).
 */
import type { LngLatBounds, WeatherTileCoords } from '../services/weather-tile-api'
import type { WindGeoJSON } from '../types/map-geo'
import { normalizeWeatherModel, WEATHER_MODEL_BOOTSTRAP } from '../utils/weather-model'
import { useWeatherEngineStore } from './weather-engine'

/** 视口外扩预取圈数：同级邻居提前缓存，减少平移空洞 */
export const PREFETCH_NEIGHBOR_DEPTH = 3
/** 多可见天气层时压缩邻域，把槽位留给各层视口 */
export const PREFETCH_NEIGHBOR_DEPTH_MULTI_LAYER = 1
/** 邻小时预取优先级（仅 viewport，不扩环） */
export const ADJACENT_HOUR_PRIORITY = 3
/** 可见竞争层数达到此阈值时抑制邻小时/深邻域预取 */
export const MULTI_LAYER_PREFETCH_THRESHOLD = 2
/** 预报 hour 合法范围（与后端 Query ge=0,le=47 对齐） */
export const HOUR_MIN = 0
export const HOUR_MAX = 47

/** dataVersion 短窗合并，避免每到一块瓦片就全量重算 */
export const DATA_VERSION_COALESCE_MS = 220
/** pending 过高时暂停 z+1 child prefetch */
export const CHILD_PREFETCH_PENDING_STRESS = 6
export const BACKOFF_429_MS = 5000
/** 429 退避后重试的最大次数，避免无限重试 */
export const MAX_429_RETRIES = 3
/** 503（断路器/服务不可用）退避时间 */
export const BACKOFF_503_MS = 8000
/** 503 重试最大次数 */
export const MAX_503_RETRIES = 3
/** 前端 abort 超时后的退避（后端可能仍在生成，稍后重试可命中缓存） */
export const BACKOFF_TIMEOUT_MS = 4000
/** 超时重试最大次数 */
export const MAX_TIMEOUT_RETRIES = 2
/** 耗尽重试后的软重拉间隔（给断路器恢复时间，避免立刻再撞 503） */
export const SOFT_REQUEUE_MS = 15_000
/** 同一瓦片软重拉上限，防止断路器打开时无限「运行中」 */
export const MAX_SOFT_REQUEUES = 3
/** 视口缺口补洞扫描间隔（秒级，商业观感：缩放后尽快填洞） */
export const GAP_SWEEP_MS = 2_500
/** 限流/断路压力下的补洞间隔 */
export const GAP_SWEEP_STRESSED_MS = 8_000
/** Zoom-out 过渡期补洞间隔（更快填洞） */
export const GAP_SWEEP_ZOOM_CHANGE_MS = 1_000
/** Zoom-out 过渡期 dataVersion 合并窗口（更快触发渲染） */
export const DATA_VERSION_ZOOMOUT_COALESCE_MS = 100
/** Zoom-out 过渡期时长（ms）：在此期间加速补洞/放宽缓存/缩短合并 */
export const ZOOM_OUT_TRANSITION_MS = 3_000

/** 单瓦片缓存条目：SWR 用 fetchedAt，LRU trim 用 lastAccess */
export interface CachedTileEntry {
  geojson: WindGeoJSON
  fetchedAt: number
  lastAccess: number
}

/** 默认气象模型 bootstrap；正式值由天气引擎配置 / 后端 default_model 覆盖。 */
export const DEFAULT_WEATHER_MODEL = WEATHER_MODEL_BOOTSTRAP

/** Resolve tile model: explicit override > weather-engine default_model > bootstrap. */
export function resolveConfiguredWeatherModel(override?: string): string {
  if (override && override.trim()) return normalizeWeatherModel(override)
  try {
    return useWeatherEngineStore().defaultModel
  } catch {
    return WEATHER_MODEL_BOOTSTRAP
  }
}

/**
 * 模型 × 图层 结构性不支持清单：变量在该模型中不存在，数据同步也补不齐
 * （如 ECMWF IFS 不提供 visibility）。与后端 WEATHER_LAYER_SPECS 语义保持一致。
 * 命中时 setViewport 直接短路：不发瓦片请求，按 data-empty 提示。
 */
const UNSUPPORTED_LAYER_MODELS: Record<string, readonly string[]> = {
  visibility: ['ecmwf_ifs025'],
}

/** 图层变量在当前模型下是否结构性不可用（与数据同步状态无关） */
export function isWeatherLayerUnsupportedByModel(layerId: string, model: string): boolean {
  const models = UNSUPPORTED_LAYER_MODELS[layerId]
  return !!models && models.includes(model)
}

export interface TileKey {
  layerId: string
  z: number
  x: number
  y: number
  hour: number
}

export interface TileRequest {
  key: TileKey
  layerId: string
  priority: number
  generation: number
  sequence: number
  controller: AbortController
  /** 是否已被 drainQueue 取出并进入 submitTile；用于取消时区分是否占用并发槽位。 */
  dispatched?: boolean
  /** 429 重试计数 */
  retry429Count?: number
  /** 503 重试计数 */
  retry503Count?: number
  /** 前端超时重试计数 */
  retryTimeoutCount?: number
  /** 该瓦片最早可重试的时间戳（ms）。drainQueue/pickNextRequest 会跳过未到期的瓦片，
   *  确保单个瓦片的退避不被其他 drainQueue 调用绕过。 */
  retryAfter?: number
}

export interface LayerState {
  layerId: string
  generation: number
  visible: boolean
  center: { lng: number; lat: number }
  /** 预算后的瓦片 zoom（入队 / merge 用） */
  zoom: number
  /** 地图原始 zoom；用于判断「仅缩放未改瓦片集合」时仍需通知 overlay 重投影 */
  mapZoom: number
  hour: number
  model: string
  /** Weather provider preference (auto | provider_id); part of tile cache key */
  provider: string
  bbox: LngLatBounds | null
  viewportTiles: WeatherTileCoords[]
  prefetchRing: WeatherTileCoords[]
  tiles: Map<string, CachedTileEntry>
  pending: Map<string, TileRequest>
  /** 最近一次成功合并的 GeoJSON；视口换小时/缩放时暂无可匹配瓦片则沿用，避免闪空 */
  lastMergedGeojson: WindGeoJSON | null
  /** 上一帧合并的 feature 数，用于检测「平移后暂时变稀」并沿用旧帧 */
  lastMergedFeatureCount: number
  /** 最近一次错误类型（null = 无错误）。UI 通过 statusVersion 触发响应式更新。 */
  lastErrorType: WeatherTileErrorType | null
  /** 错误信息（供 UI 展示） */
  lastErrorMessage: string | null
  /**
   * 「无数据」短路标记：记录最近一次 422（主变量全 null）时的 `${model}|${provider}`。
   * 命中后该图层在当前 model/provider 下不再发任何瓦片请求（422 表示变量缺失，
   * 是图层级状态而非单瓦片问题），避免 gap sweep / soft requeue 构成无限重试。
   * model/provider 变化后 scope 自动失配、恢复请求；图层重新激活时显式清除。
   */
  dataEmptyScope: string | null
  /** 最近一次 zoom 变化的时间戳（ms）；zoom-out 过渡期内加速补洞/放宽缓存/缩短合并窗口 */
  lastZoomChangedAt: number
}

export interface LayerTileStats {
  pending: number
  cached: number
  visible: number
}

/** 天气瓦片图层的运行时状态，供 UI 显示加载/错误反馈 */
export type WeatherTileErrorType =
  'circuit-open' | 'rate-limited' | 'workflow-failed' | 'timeout' | 'data-empty' | 'unknown'

export type WeatherWorkflowMappedStatus =
  'running' | 'queued' | 'retry_pending' | 'failed' | 'cancelled' | 'succeeded'

export interface WeatherWorkflowContributionItem {
  catalogId: string
  status: WeatherWorkflowMappedStatus
  message: string
  pending: number
  missingInViewport: number
  cachedInViewport: number
  viewportTotal: number
  errorType: WeatherTileErrorType | null
}

export interface WeatherWorkflowContribution {
  running: number
  queued: number
  retryPending: number
  failed: number
  cancelled: number
  succeeded: number
  items: WeatherWorkflowContributionItem[]
}

export interface WeatherTileLayerStatus {
  /** 图层是否可见且需要瓦片 */
  active: boolean
  /** 视口内已缓存的瓦片数 */
  cachedInViewport: number
  /** 视口内瓦片总数 */
  viewportTotal: number
  /** 视口内尚未缓存的瓦片数 */
  missingInViewport: number
  /** 仍在加载的瓦片数（含退避中；工具栏「运行中」≈ priority=0 pending） */
  pending: number
  /** 是否有图层级视口补洞定时器在跑 */
  gapSweepActive: boolean
  /** 最近一次错误类型（null = 无错误） */
  errorType: WeatherTileErrorType | null
  /** 错误信息（供 UI 展示） */
  errorMessage: string | null
}
