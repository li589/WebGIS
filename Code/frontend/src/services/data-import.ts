/**
 * 主界面本地数据导入：文件分类、矢量解析、栅格上传（带写鉴权）。
 */
import { getBackendWriteApiKey, withWriteAuthHeaders } from './backend-auth'
import { resolveApiUrl } from './_http'
import type { CRSOption } from '@/services/crs'

export const MAX_RASTER_UPLOAD_BYTES = 100 * 1024 * 1024
export const MAX_CLIENT_FILE_BYTES = 80 * 1024 * 1024

export type ImportKind = 'vector' | 'csv' | 'raster' | 'unknown'

export interface ParsedVectorImport {
  geojson: GeoJSON.FeatureCollection
  layerCount: number
  multiLayerNote: string
}

export interface RasterImportResult {
  layer_id: string
  bounds?: [number, number, number, number]
  /** 后端检测到的源 CRS（如 'EPSG:32650'）；Phase 1 CRS 模块新增字段 */
  source_crs?: string
  /** 后端建议的 CRS（同 source_crs 或兜底建议）；用于弹窗默认选项 */
  suggested_crs?: string
  /** 非 WGS84 等价系时为 true，前端需弹窗让用户确认 */
  needs_confirm?: boolean
  /** 检测备注（如 'rasterio_crs' / 'bounds_heuristic' 等） */
  detection_notes?: string
}

const VECTOR_EXTS = new Set(['shp', 'zip', 'geojson', 'json'])
const CSV_EXTS = new Set(['csv'])
const RASTER_EXTS = new Set(['tif', 'tiff'])

export function fileExtension(name: string): string {
  const parts = name.toLowerCase().split('.')
  return parts.length > 1 ? (parts.pop() ?? '') : ''
}

export function classifyImportFile(file: File): ImportKind {
  const ext = fileExtension(file.name)
  if (VECTOR_EXTS.has(ext)) return 'vector'
  if (CSV_EXTS.has(ext)) return 'csv'
  if (RASTER_EXTS.has(ext)) return 'raster'
  return 'unknown'
}

export function validateImportFile(file: File, kind: ImportKind): void {
  if (!file || file.size <= 0) {
    throw new Error('文件为空或无效')
  }
  if (kind === 'unknown') {
    throw new Error(
      `不支持的文件格式: ${file.name}（支持 .shp/.zip/.geojson/.json/.csv/.tif/.tiff）`,
    )
  }
  if (kind === 'raster' && file.size > MAX_RASTER_UPLOAD_BYTES) {
    throw new Error(`栅格超过上限 ${MAX_RASTER_UPLOAD_BYTES / (1024 * 1024)} MiB`)
  }
  if ((kind === 'vector' || kind === 'csv') && file.size > MAX_CLIENT_FILE_BYTES) {
    throw new Error(`文件过大（>${MAX_CLIENT_FILE_BYTES / (1024 * 1024)} MiB），请先裁剪或拆分`)
  }
}

export function normalizeShpResult(result: unknown): {
  geojson: GeoJSON.FeatureCollection
  layerCount: number
} {
  if (Array.isArray(result)) {
    const collections = result.filter((item): item is GeoJSON.FeatureCollection =>
      Boolean(item && typeof item === 'object' && Array.isArray((item as GeoJSON.FeatureCollection).features)),
    )
    if (collections.length === 0) {
      throw new Error('ZIP/SHP 解析后未找到有效图层')
    }
    return {
      layerCount: collections.length,
      geojson: {
        type: 'FeatureCollection',
        features: collections.flatMap((c) => c.features),
      },
    }
  }
  if (result && typeof result === 'object' && Array.isArray((result as GeoJSON.FeatureCollection).features)) {
    return { layerCount: 1, geojson: result as GeoJSON.FeatureCollection }
  }
  if (result && typeof result === 'object') {
    const collections = Object.entries(result as Record<string, unknown>)
      .filter(([key, value]) =>
        !key.endsWith('_null')
        && Boolean(value && typeof value === 'object' && Array.isArray((value as GeoJSON.FeatureCollection).features)),
      )
      .map(([, value]) => value as GeoJSON.FeatureCollection)
    if (collections.length === 0) {
      throw new Error('ZIP/SHP 解析后未找到有效图层')
    }
    return {
      layerCount: collections.length,
      geojson: {
        type: 'FeatureCollection',
        features: collections.flatMap((c) => c.features),
      },
    }
  }
  throw new Error('无法识别的 SHP 解析结果')
}

export async function parseVectorFile(file: File): Promise<ParsedVectorImport> {
  validateImportFile(file, 'vector')
  const ext = fileExtension(file.name)
  let geojson: GeoJSON.FeatureCollection
  let layerCount = 1

  if (ext === 'geojson' || ext === 'json') {
    const text = await file.text()
    const parsed = JSON.parse(text) as GeoJSON.FeatureCollection | GeoJSON.Feature | GeoJSON.Geometry
    if (parsed && typeof parsed === 'object' && (parsed as GeoJSON.FeatureCollection).type === 'FeatureCollection') {
      geojson = parsed as GeoJSON.FeatureCollection
    } else if (parsed && typeof parsed === 'object' && (parsed as GeoJSON.Feature).type === 'Feature') {
      geojson = { type: 'FeatureCollection', features: [parsed as GeoJSON.Feature] }
    } else if (parsed && typeof parsed === 'object' && 'type' in parsed) {
      geojson = {
        type: 'FeatureCollection',
        features: [{ type: 'Feature', properties: {}, geometry: parsed as GeoJSON.Geometry }],
      }
    } else {
      throw new Error('GeoJSON 格式无效')
    }
  } else if (ext === 'shp' || ext === 'zip') {
    const arrayBuffer = await file.arrayBuffer()
    const shpjs = (await import('shpjs')).default
    const result = await shpjs(arrayBuffer)
    const normalized = normalizeShpResult(result)
    geojson = normalized.geojson
    layerCount = normalized.layerCount
  } else {
    throw new Error(`不支持的矢量格式: .${ext}`)
  }

  if (!geojson.features || !Array.isArray(geojson.features)) {
    throw new Error('文件解析后未找到有效的 features 数组')
  }
  if (geojson.features.length === 0) {
    throw new Error('文件中没有要素')
  }

  const multiLayerNote = layerCount > 1
    ? `已合并 ZIP 内 ${layerCount} 个图层，`
    : ''

  return { geojson, layerCount, multiLayerNote }
}

function parseErrorDetail(status: number, text: string): string {
  try {
    const body = JSON.parse(text) as { detail?: unknown; user_message?: string; error?: string }
    const detail = body.user_message || body.error || body.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((d) => (typeof d === 'object' && d && 'msg' in d ? String((d as { msg: unknown }).msg) : String(d)))
        .join('; ')
    }
  } catch {
    /* use raw */
  }
  return text || `HTTP ${status}`
}

export function uploadRasterFile(
  file: File,
  options?: {
    onProgress?: (ratio: number) => void
    signal?: AbortSignal
  },
): Promise<RasterImportResult> {
  validateImportFile(file, 'raster')

  const key = getBackendWriteApiKey()
  if (!key && import.meta.env.PROD) {
    return Promise.reject(new Error('未配置后端写密钥，请先在「设置 → API Key」填写后端认证 Key'))
  }

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', resolveApiUrl('/import/raster'))
    const headers = withWriteAuthHeaders({}, 'POST')
    for (const [k, v] of Object.entries(headers)) {
      xhr.setRequestHeader(k, v)
    }

    xhr.upload.onprogress = (ev) => {
      if (!ev.lengthComputable || !options?.onProgress) return
      options.onProgress(Math.min(1, ev.loaded / Math.max(1, ev.total)))
    }

    xhr.onload = () => {
      const text = xhr.responseText ?? ''
      if (xhr.status < 200 || xhr.status >= 300) {
        const detail = parseErrorDetail(xhr.status, text)
        if (xhr.status === 401 || xhr.status === 403) {
          reject(new Error(`鉴权失败（${xhr.status}）：请在设置中配置正确的后端认证 Key。${detail}`))
          return
        }
        reject(new Error(detail))
        return
      }
      try {
        const data = JSON.parse(text) as RasterImportResult
        if (!data.layer_id) {
          reject(new Error('后端未返回 layer_id'))
          return
        }
        resolve(data)
      } catch {
        reject(new Error('后端响应不是有效 JSON'))
      }
    }

    xhr.onerror = () => reject(new Error('网络错误，栅格上传失败'))
    xhr.onabort = () => reject(new Error('上传已取消'))

    if (options?.signal) {
      if (options.signal.aborted) {
        xhr.abort()
        return
      }
      options.signal.addEventListener('abort', () => xhr.abort(), { once: true })
    }

    const formData = new FormData()
    formData.append('file', file)
    xhr.send(formData)
  })
}

export async function deleteImportedRaster(layerId: string): Promise<void> {
  const headers = withWriteAuthHeaders({ 'Content-Type': 'application/json' }, 'DELETE')
  const resp = await fetch(resolveApiUrl(`/import/raster/${encodeURIComponent(layerId)}`), {
    method: 'DELETE',
    headers,
  })
  if (resp.status === 404) return
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new Error(parseErrorDetail(resp.status, text))
  }
}

// ── Phase 1 CRS 模块：13 项 CRS 选项 / 确认重投影 / 批量点转换 ───────────

/** GET /import/crs-options — 获取 13 项 CRS 下拉选项 */
export async function fetchCrsOptions(): Promise<{ count: number; items: CRSOption[] }> {
  const resp = await fetch(resolveApiUrl('/import/crs-options'))
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new Error(parseErrorDetail(resp.status, text))
  }
  return resp.json() as Promise<{ count: number; items: CRSOption[] }>
}

/** POST /import/raster/confirm — 提交确认的源 CRS + 偏移，后端重投影到 WGS84 并返回新 bounds */
export async function confirmRasterImport(params: {
  layerId: string
  sourceCrs: string
  lngOffset: number
  latOffset: number
}): Promise<{
  layer_id: string
  source_crs: string
  target_crs: string
  applied_offset: [number, number]
  bounds: [number, number, number, number]
}> {
  const headers = withWriteAuthHeaders({ 'Content-Type': 'application/json' }, 'POST')
  const resp = await fetch(resolveApiUrl('/import/raster/confirm'), {
    method: 'POST',
    headers,
    body: JSON.stringify({
      layer_id: params.layerId,
      source_crs: params.sourceCrs,
      lng_offset: params.lngOffset,
      lat_offset: params.latOffset,
    }),
  })
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new Error(parseErrorDetail(resp.status, text))
  }
  return resp.json() as Promise<{
    layer_id: string
    source_crs: string
    target_crs: string
    applied_offset: [number, number]
    bounds: [number, number, number, number]
  }>
}

/** POST /import/transform-point — 批量点转换（CSV/POI 提交时用） */
export async function transformPointBatch(params: {
  points: Array<[number, number]>
  sourceCrs: string
  targetCrs: string
  lngOffset?: number
  latOffset?: number
}): Promise<{ count: number; points: Array<[number, number]> }> {
  const headers = withWriteAuthHeaders({ 'Content-Type': 'application/json' }, 'POST')
  const resp = await fetch(resolveApiUrl('/import/transform-point'), {
    method: 'POST',
    headers,
    body: JSON.stringify({
      points: params.points,
      source_crs: params.sourceCrs,
      target_crs: params.targetCrs,
      lng_offset: params.lngOffset ?? 0,
      lat_offset: params.latOffset ?? 0,
    }),
  })
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new Error(parseErrorDetail(resp.status, text))
  }
  return resp.json() as Promise<{ count: number; points: Array<[number, number]> }>
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}
