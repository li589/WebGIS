/**
 * NAS 按需出图 API 客户端。
 *
 * 两条取数路径：
 *  1. {@link ensureNasFrame} —— 产品 × 变量 × 某天，写进独立的
 *     `imports/imported-nas-<…>/` 图层（NAS 缓存池，2000 帧上限）。
 *  2. {@link ensureNasLayerFrame} —— 既有图层 × 某天，把单日帧**补进那个图层
 *     自己的目录**（不改该层 meta.json）。时间轴「拖到某天才取数」走这条。
 *
 * 后端不会因为 404 就把图层藏起来：`/overlay-preview?time=` 能不能取到图，
 * 只取决于目录里是否真有 `preview_<tag>.png`。
 */
import { requestJson } from './_http'

/** 4 个 NAS 目录 = 卫星 × 约束口径。 */
export type NasProductKey = 'fy_avg' | 'fy_raw' | 'smap_avg' | 'smap_raw'

/** 3 个变量。 */
export type NasVariableKey = 'SM' | 'VOD' | 'OMEGA'

export type NasFrameRequest = {
  product: NasProductKey
  variable: NasVariableKey
  /** YYYYMMDD */
  date: string
  /** 忽略本地缓存，强制重新从 NAS 取并重绘 */
  force?: boolean
}

export type NasFrameEviction = {
  total_before: number
  total_after: number
  deleted_count: number
}

export type NasFrameResult = {
  layer_id: string
  time_key: string
  /** true = 命中的是本地缓存（没连 NAS） */
  cached: boolean
  source: 'local' | 'nas'
  elapsed_ms: number
  png: string
  bounds: string
  time_list_size?: number | null
  mat_bytes?: number | null
  eviction?: NasFrameEviction | null
  render?: {
    shape?: number[]
    finite_pixels?: number
    vmin?: number | null
    vmax?: number | null
    bounds?: number[]
    png_bytes?: number
  } | null
}

export type NasCacheState = {
  max_frames: number
  target_frames: number
  per_layer_floor: number
  protect_recent_days: number
  total_frames: number
  total_bytes: number
  total_bytes_human: string
  layers: Record<
    string,
    { frames: number; bytes: number; oldest_used: number; oldest_used_human: string }
  >
  oldest_frames: { layer_id: string; tag: string; last_used: string }[]
}

export type NasProductCatalog = {
  products: {
    key: NasProductKey
    source: string
    source_label: string
    constraint: string
  }[]
  variables: {
    key: NasVariableKey
    label: string
    title: string
    palette: string
    vmin: number
    vmax: number
    unit: string
  }[]
  cache: {
    max_frames: number
    target_frames: number
    per_layer_floor: number
    protect_recent_days: number
  }
}

/**
 * 确保「产品 × 变量 × 某天」在本地有一张可显示的图。
 *
 * 后端行为：
 * 1. 本地已有 → 直接返回 `cached: true, source: 'local'`，**不连 NAS**；
 * 2. 本地没有 → 只读拉取那一个 `.mat` → 渲染 PNG + bounds → 写盘；
 * 3. 写盘后若总帧数超过 2000，按 LRU 淘汰到 1800。
 *
 * 超时给到 60s：NAS 隧道实测 ~2 MB/s，单个 .mat 4.3 MB，加渲染约 6~10s。
 */
export async function ensureNasFrame(payload: NasFrameRequest): Promise<NasFrameResult> {
  return requestJson<NasFrameResult>('/nas-ondemand/frame', {
    method: 'POST',
    body: JSON.stringify({
      product: payload.product,
      variable: payload.variable,
      date: payload.date,
      force: payload.force ?? false,
    }),
    timeoutMs: 60_000,
  })
}

/** 查看缓存现状（帧数 / 占用 / 最久未用）。纯读，不连 NAS。 */
export async function fetchNasCacheState(): Promise<NasCacheState> {
  return requestJson<NasCacheState>('/nas-ondemand/cache-state')
}

/** 可选产品与变量清单（含配色与量程口径）。纯读，不连 NAS。 */
export async function fetchNasProductCatalog(): Promise<NasProductCatalog> {
  return requestJson<NasProductCatalog>('/nas-ondemand/products')
}

/** `GET /overlays` 返回的可访问 overlay 图层 ID（用于确认新帧是否已可被发现）。 */
export async function fetchOverlayLayerIds(): Promise<string[]> {
  const data = await requestJson<{ overlay_layer_ids?: string[] }>('/overlays')
  return Array.isArray(data?.overlay_layer_ids) ? data.overlay_layer_ids : []
}

// ── 按需补帧（写进既有图层目录，不改该层 meta） ─────────────────────────────

export type NasOndemandLayer = {
  layer_id: string
  product: NasProductKey
  variable: NasVariableKey
}

export type NasOndemandLayers = {
  layers: NasOndemandLayer[]
  coverage: { start: string; end: string }
}

/**
 * 哪些图层支持「拖时间轴补单日帧」+ 数据覆盖范围。
 *
 * 纯读、不连 NAS。前端据此决定：这次拖动要不要发请求、超出范围就直接拦。
 */
export async function fetchNasOndemandLayers(): Promise<NasOndemandLayers> {
  return requestJson<NasOndemandLayers>('/nas-ondemand/layers', { silent: true })
}

/**
 * 确保「这个既有图层 × 这一天」有图可显示。
 *
 * 行为：
 * 1. 本地已有该日 PNG → 毫秒级返回 `cached: true`，**不连 NAS**；
 * 2. 否则从 NAS 只读取那一个 `.mat` → 渲染成与**该层原成品同画幅**的 PNG
 *    → 写进该层目录（`preview_<tag>.png` + `bounds_<tag>.json`）；
 * 3. **不改该层 meta.json**（time_list / default_time / native_step 全不动），
 *    所以「勾选/添加图层仍然显示原来的长序列」。
 *
 * 超时给到 90s：NAS 隧道实测 ~2 MB/s，单帧 3 MB，加渲染约 5~10s。
 */
export async function ensureNasLayerFrame(payload: {
  layerId: string
  /** YYYYMMDD */
  date: string
  force?: boolean
}): Promise<NasFrameResult> {
  return requestJson<NasFrameResult>('/nas-ondemand/layer-frame', {
    method: 'POST',
    silent: true,
    body: JSON.stringify({
      layer_id: payload.layerId,
      date: payload.date,
      force: payload.force ?? false,
    }),
    timeoutMs: 90_000,
  })
}
