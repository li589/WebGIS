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
  signal?: AbortSignal
  /** 客户端缓存 bust 参数，不参与业务 */
  t?: number
}

const _WEB_MERCATOR_MAX_LAT = 85.0511287798066
const _TILE_KEY_PREFIX = 'weather:tile:'

/** 与后端 tile_key 一致的前端缓存键（不含 model，前端缓存按默认 model 管理）。 */
export function buildTileKey(
  layerId: string,
  z: number,
  x: number,
  y: number,
  hour: number,
): string {
  return `${_TILE_KEY_PREFIX}${layerId}:z${z}:x${x}:y${y}:h${hour}`
}

/** 标准 Web Mercator：经纬度 → z/x/y 瓦片坐标。 */
export function lngLatToTile(lng: number, lat: number, z: number): WeatherTileCoords {
  const n = 2 ** z
  let x = Math.floor(((lng + 180) / 360) * n)
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
 * @param buffer 视口外扩圈数（0 = 仅边界内，1 = 外扩一圈）
 * @returns 主世界瓦片坐标集合（经度已归一化到 [0, n)）
 */
export function tilesInBounds(
  bounds: LngLatBounds,
  z: number,
  buffer = 0,
): WeatherTileCoords[] {
  const clampedZ = Math.max(0, Math.min(12, Math.round(z)))
  const sw = lngLatToTile(bounds.west, bounds.south, clampedZ)
  const ne = lngLatToTile(bounds.east, bounds.north, clampedZ)

  const minX = Math.min(sw.x, ne.x) - buffer
  const maxX = Math.max(sw.x, ne.x) + buffer
  const minY = Math.min(sw.y, ne.y) - buffer
  const maxY = Math.max(sw.y, ne.y) + buffer

  const n = 2 ** clampedZ
  const seen = new Set<string>()
  const tiles: WeatherTileCoords[] = []

  for (let x = minX; x <= maxX; x += 1) {
    // 处理 renderWorldCopies：归一化到主世界 [0, n)
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
 * 项目约束：所有引擎模块统一走 /workflow-runs。
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
 * 直接请求后端 /weather/tiles REST 接口（仅用于调试，前端 tile manager 不再调用）。
 * @deprecated 请使用 submitWeatherTileWorkflow。
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
  if (typeof options.t === 'number') search.set('t', String(options.t))

  const suffix = search.toString() ? `?${search.toString()}` : ''
  const url = resolveApiUrl(`/unified-tiles/${layerId}/${z}/${x}/${y}${suffix}`)

  const response = await fetch(url, {
    signal: options.signal,
  })

  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`Weather tile request failed: ${response.status} ${url}${detail ? ` - ${detail}` : ''}`)
  }

  return (await response.json()) as WindGeoJSON
}
