/**
 * 天气瓦片 API 与坐标工具。
 *
 * 提供标准 Web Mercator z/x/y 瓦片请求和坐标转换，供 weather-tile-manager 使用。
 */
import type { Map as MaplibreMap } from 'maplibre-gl'
import type { WindGeoJSON } from '../components/map/types'
import { resolveApiUrl, submitWorkflow } from './runtime-api'
import type { WorkflowSubmitRequest } from './runtime-api'

export interface WeatherTileCoords {
  z: number
  x: number
  y: number
}

export interface LngLatBounds {
  west: number
  south: number
  east: number
  north: number
}

export interface FetchWeatherTileOptions {
  hour?: number
  model?: string
  /** Weather provider id; omit or 'auto' for registry priority */
  provider?: string
  signal?: AbortSignal
  /** 客户端缓存 bust 参数，不参与业务 */
  t?: number
}

const _WEB_MERCATOR_MAX_LAT = 85.0511287798066
const _TILE_KEY_PREFIX = 'weather:tile:'

function normalizeProviderPart(provider?: string): string {
  const p = (provider ?? 'auto').trim()
  if (!p || p.toLowerCase() === 'default') return 'auto'
  return p.replace(/\//g, '_').replace(/:/g, '_')
}

/** 与后端 tile_key 对齐的前端缓存键（含 model + provider，避免换源脏缓存）。 */
export function buildTileKey(
  layerId: string,
  z: number,
  x: number,
  y: number,
  hour: number,
  model = 'best_match',
  provider = 'auto',
): string {
  const modelPart = model.replace(/\//g, '_').replace(/:/g, '_')
  const providerPart = normalizeProviderPart(provider)
  return `${_TILE_KEY_PREFIX}${layerId}:z${z}:x${x}:y${y}:h${hour}:m${modelPart}:p${providerPart}`
}

/** 标准 Web Mercator：经纬度 → z/x/y 瓦片坐标。 */
export function lngLatToTile(lng: number, lat: number, z: number): WeatherTileCoords {
  const n = 2 ** z
  const x = Math.floor(((lng + 180) / 360) * n)
  // 纬度 clamp 到 Web Mercator 有效范围
  const clampedLat = Math.max(-_WEB_MERCATOR_MAX_LAT, Math.min(_WEB_MERCATOR_MAX_LAT, lat))
  const latRad = (clampedLat * Math.PI) / 180
  const y = Math.floor(
    ((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) * n,
  )
  return {
    z,
    x: Math.max(0, Math.min(n - 1, x)),
    y: Math.max(0, Math.min(n - 1, y)),
  }
}

/** 标准 Web Mercator：瓦片 z/x/y → EPSG:4326 bbox。 */
export function tileToLngLatBounds(z: number, x: number, y: number): LngLatBounds {
  const n = 2 ** z
  const west = (x / n) * 360 - 180
  const east = ((x + 1) / n) * 360 - 180

  function tileYToLat(yTile: number): number {
    const latRad = Math.atan(Math.sinh(Math.PI * (1 - (2 * yTile) / n)))
    return (latRad * 180) / Math.PI
  }

  const north = tileYToLat(y)
  const south = tileYToLat(y + 1)
  return { west, south, east, north }
}

/**
 * 获取指定经纬度边界内的所有瓦片坐标。
 *
 * 反子午线穿越处理：
 * 主数据流（buildMapViewportSnapshot → store → weather-tile-manager）已通过
 * normalizeLngBounds 将跨 ±180° 的 bbox 转为 `east += 360` 短路径形式
 *（如 west=170, east=185），此时 `east - west ≤ 180`，下方 `> 180` 块不触发。
 * 函数仍通过 `((x % n) + n) % n` 归一化正确处理跨子午线瓦片索引。
 *
 * 下方 `> 180` 块为向后兼容保留：若旧式 swap 形式（west=-175, east=170，
 * 跨度 345°）的 bbox 被直接传入，仍能正确转为短路径。当前主数据流不会
 * 产生此形式，但保留以防直接调用方（如 tilesInViewport）传入原始 MapLibre bounds。
 *
 * @param buffer 视口外扩圈数（0 = 仅边界内，1 = 外扩一圈）
 * @returns 主世界瓦片坐标集合（经度已归一化到 [0, n)）
 */
export function tilesInBounds(
  bounds: LngLatBounds,
  z: number,
  buffer = 0,
): WeatherTileCoords[] {
  const clampedZ = Math.max(0, Math.min(12, Math.round(z)))
  const n = 2 ** clampedZ

  // 向后兼容：旧式 swap 形式（east - west > 180°）转为短路径
  let westLng = bounds.west
  let eastLng = bounds.east
  if (eastLng - westLng > 180) {
    westLng = bounds.east
    eastLng = bounds.west + 360
  }

  // 手动计算瓦片 x 坐标（不 clamp，允许 > n 以处理穿越后的回绕）
  const westTileX = Math.floor(((westLng + 180) / 360) * n)
  const eastTileX = Math.floor(((eastLng + 180) / 360) * n)

  // y 坐标使用 lngLatToTile 确保 Web Mercator 投影正确
  const southTileY = lngLatToTile(0, bounds.south, clampedZ).y
  const northTileY = lngLatToTile(0, bounds.north, clampedZ).y

  const minX = Math.min(westTileX, eastTileX) - buffer
  const maxX = Math.max(westTileX, eastTileX) + buffer
  const minY = Math.min(southTileY, northTileY) - buffer
  const maxY = Math.max(southTileY, northTileY) + buffer

  const seen = new Set<string>()
  const tiles: WeatherTileCoords[] = []

  for (let x = minX; x <= maxX; x += 1) {
    // 归一化到主世界 [0, n)
    const normalizedX = ((x % n) + n) % n
    for (let y = minY; y <= maxY; y += 1) {
      if (y < 0 || y >= n) continue
      const key = `${clampedZ}:${normalizedX}:${y}`
      if (seen.has(key)) continue
      seen.add(key)
      tiles.push({ z: clampedZ, x: normalizedX, y })
    }
  }

  return tiles
}

/**
 * 获取当前视口内的所有瓦片坐标。
 *
 * @param buffer 视口外扩圈数（0 = 仅视口内，1 = 外扩一圈）
 * @returns 主世界瓦片坐标集合（经度已归一化到 [0, n)）
 */
export function tilesInViewport(map: MaplibreMap, buffer = 0): WeatherTileCoords[] {
  const z = Math.max(0, Math.min(12, Math.round(map.getZoom())))
  const bounds = map.getBounds()
  return tilesInBounds(
    {
      west: bounds.getWest(),
      south: bounds.getSouth(),
      east: bounds.getEast(),
      north: bounds.getNorth(),
    },
    z,
    buffer,
  )
}

export interface SubmitWeatherTileWorkflowOptions {
  hour?: number
  model?: string
  signal?: AbortSignal
}

/**
 * 提交单个天气瓦片的 workflow 渲染任务。
 * 仅用于显式扩展 DAG / 调试；视口热路径请使用 fetchWeatherTile。
 * 显式 tile workflow 计入后端 weather_tile 容量池（max_active_weather_tile_runs）。
 */
export async function submitWeatherTileWorkflow(
  layerId: string,
  z: number,
  x: number,
  y: number,
  options: SubmitWeatherTileWorkflowOptions = {},
): Promise<{ runId: string }> {
  const workflowId = `weather-tile-${layerId}-z${z}-x${x}-y${y}-h${options.hour ?? 0}`
  const payload: WorkflowSubmitRequest = {
    command_type: 'analysis',
    layer_id: layerId,
    priority: 'normal',
    resource_profile: 'standard',
    realtime_preferred: false,
    requested_outputs: ['json'],
    parameters: { hour: options.hour ?? 0 },
    weather_request: {
      workflow_id: workflowId,
      workflow: {
        workflow_id: workflowId,
        nodes: [
          {
            node_id: 'tile-render',
            node_type: 'weather_tile_render',
            params: {
              layer_id: layerId,
              z,
              x,
              y,
              hour: options.hour ?? 0,
              model: options.model,
            },
          },
        ],
        edges: [],
      },
    },
  }
  const resp = await submitWorkflow(payload)
  return { runId: resp.run_id }
}

/**
 * 天气瓦片请求超时（毫秒）。
 * 后端热路径可能经历：tile 信号量排队 + API 槽位等待(≤30s) + urlopen(≤30s) + 429 退避，
 * 25s 前端中止会误判为永久失败并清空图层；放宽到 75s 与后端最坏排队对齐。
 */
const TILE_FETCH_TIMEOUT_MS = 75_000

/**
 * 视口热路径：直接请求 GET /weather/tiles/{layer}/{z}/{x}/{y}。
 * 由 WeatherTileService 负责缓存与网格生成；不占用 workflow-runs 业务容量池。
 *
 * 内置超时，避免后端排队或 Open-Meteo API 慢时前端并发槽位被无限占用。
 * 超时抛出 Error（message 含 "timeout"），与外部 AbortSignal 取消区分。
 */
export async function fetchWeatherTile(
  layerId: string,
  z: number,
  x: number,
  y: number,
  options: FetchWeatherTileOptions = {},
): Promise<WindGeoJSON> {
  const search = new URLSearchParams()
  if (typeof options.hour === 'number') search.set('hour', String(options.hour))
  if (options.model) search.set('model', options.model)
  if (options.provider && options.provider !== 'auto') search.set('provider', options.provider)
  if (typeof options.t === 'number') search.set('t', String(options.t))

  const suffix = search.toString() ? `?${search.toString()}` : ''
  const url = resolveApiUrl(`/weather/tiles/${layerId}/${z}/${x}/${y}${suffix}`)

  // 组合外部 signal 和超时 signal，任一触发都会 abort fetch
  const timeoutController = new AbortController()
  const timeoutId = setTimeout(() => timeoutController.abort(), TILE_FETCH_TIMEOUT_MS)
  const externalSignal = options.signal

  // 外部 abort 传播到 timeoutController，保持错误类型一致
  if (externalSignal) {
    if (externalSignal.aborted) {
      clearTimeout(timeoutId)
      timeoutController.abort(externalSignal.reason)
    } else {
      externalSignal.addEventListener('abort', () => timeoutController.abort(externalSignal.reason), { once: true })
    }
  }

  try {
    const response = await fetch(url, { signal: timeoutController.signal })

    if (!response.ok) {
      const detail = await response.text().catch(() => '')
      throw new Error(`Weather tile request failed: ${response.status} ${url}${detail ? ` - ${detail}` : ''}`)
    }

    return (await response.json()) as WindGeoJSON
  } catch (err) {
    // 区分超时和外部取消：超时时 externalSignal 未 abort，但 timeoutController 已 abort
    if (err instanceof DOMException && err.name === 'AbortError' && !externalSignal?.aborted) {
      throw new Error(`Weather tile request timeout after ${TILE_FETCH_TIMEOUT_MS / 1000}s: ${url}`, { cause: err })
    }
    throw err
  } finally {
    clearTimeout(timeoutId)
  }
}
