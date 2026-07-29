/**
 * 后端统一数据导入/导出 API（分块上传 + 矢量/栅格/文档 + 导出）。
 */
import { getBackendWriteApiKey, withWriteAuthHeaders } from './backend-auth'
import { resolveApiUrl } from './_http'

export const MAX_UPLOAD_BYTES = 512 * 1024 * 1024
export const CHUNK_SIZE = 2 * 1024 * 1024
const CHUNK_MAX_RETRIES = 4
const CHUNK_RETRY_BASE_MS = 400

export type DataImportKind = 'vector' | 'raster' | 'document' | 'unknown'

/** 与后端 upload_validation.ALLOWED_EXTENSIONS 矢量侧对齐（含 ArcGIS 空间索引附属） */
const VECTOR_EXTS = new Set([
  'shp',
  'zip',
  'rar',
  'geojson',
  'json',
  'dbf',
  'shx',
  'prj',
  'cpg',
  'sbn',
  'sbx',
  'qix',
])
const RASTER_EXTS = new Set(['tif', 'tiff', 'nc', 'hdf', 'h5', 'he5', 'mat'])
const DOCUMENT_EXTS = new Set(['csv', 'xlsx', 'xls', 'txt'])
const DENIED_EXTS = new Set([
  'exe',
  'dll',
  'so',
  'bat',
  'cmd',
  'ps1',
  'sh',
  'py',
  'js',
  'mjs',
  'vbs',
  'jar',
  'msi',
  'scr',
  'php',
])

export function fileExtension(name: string): string {
  const parts = name.toLowerCase().split('.')
  return parts.length > 1 ? (parts.pop() ?? '') : ''
}

export function classifyDataFile(file: File): DataImportKind {
  const ext = fileExtension(file.name)
  if (DENIED_EXTS.has(ext)) return 'unknown'
  if (DOCUMENT_EXTS.has(ext)) return 'document'
  if (RASTER_EXTS.has(ext)) return 'raster'
  if (VECTOR_EXTS.has(ext)) return 'vector'
  return 'unknown'
}

function parseErrorDetail(status: number, text: string): string {
  try {
    const body = JSON.parse(text) as { detail?: unknown; user_message?: string; error?: string }
    const detail = body.user_message || body.error || body.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((d) =>
          typeof d === 'object' && d && 'msg' in d
            ? String((d as { msg: unknown }).msg)
            : String(d),
        )
        .join('; ')
    }
  } catch {
    /* raw */
  }
  return text || `HTTP ${status}`
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new Error('上传已取消'))
      return
    }
    const t = setTimeout(resolve, ms)
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(t)
        reject(new Error('上传已取消'))
      },
      { once: true },
    )
  })
}

function isRetryableUploadError(status: number): boolean {
  return status === 408 || status === 429 || status >= 500
}

async function writeFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method || 'GET').toUpperCase()
  const headers = withWriteAuthHeaders(
    { ...(init.headers as Record<string, string> | undefined) },
    method,
  )
  const key = getBackendWriteApiKey()
  if (!key && import.meta.env.PROD) {
    throw new Error('未配置后端写密钥，请先在「设置 → API Key」填写后端认证 Key')
  }
  return fetch(resolveApiUrl(path), { ...init, headers })
}

async function postChunkWithRetry(
  uploadId: string,
  file: File,
  offset: number,
  end: number,
  signal?: AbortSignal,
): Promise<number> {
  let lastError: Error | null = null
  for (let attempt = 0; attempt <= CHUNK_MAX_RETRIES; attempt++) {
    if (signal?.aborted) throw new Error('上传已取消')
    try {
      const blob = file.slice(offset, end)
      const form = new FormData()
      form.append('file', blob, file.name)
      form.append('offset', String(offset))
      const chunkResp = await writeFetch(`/import/upload/${encodeURIComponent(uploadId)}/chunk`, {
        method: 'POST',
        body: form,
        signal,
      })
      if (chunkResp.ok) {
        const data = (await chunkResp.json()) as { received?: number }
        return typeof data.received === 'number' ? data.received : end
      }
      const detail = parseErrorDetail(chunkResp.status, await chunkResp.text())
      // 偏移不匹配：可能上次已写入，尝试用服务端 received 续传
      if (chunkResp.status === 400 && /偏移不匹配|期望/.test(detail)) {
        const m = detail.match(/期望\s*(\d+)/)
        if (m) {
          const expected = Number(m[1])
          if (Number.isFinite(expected) && expected > offset) {
            return expected
          }
        }
      }
      lastError = new Error(detail)
      if (!isRetryableUploadError(chunkResp.status) || attempt === CHUNK_MAX_RETRIES) {
        throw lastError
      }
    } catch (err) {
      if (signal?.aborted) {
        throw new Error('上传已取消', { cause: err })
      }
      // 业务错误（已在上方 throw 的 lastError）不可再吞掉重试
      if (err === lastError) throw err
      lastError = err instanceof Error ? err : new Error(String(err))
      const networkLike =
        lastError.name === 'TypeError' ||
        /network|fetch|Failed to fetch|timeout|aborted/i.test(lastError.message)
      if (!networkLike || attempt === CHUNK_MAX_RETRIES) throw lastError
    }
    const delay = CHUNK_RETRY_BASE_MS * 2 ** attempt + Math.floor(Math.random() * 200)
    await sleep(delay, signal)
  }
  throw lastError ?? new Error('分块上传失败')
}

export async function chunkedUpload(
  file: File,
  options?: {
    onProgress?: (ratio: number) => void
    signal?: AbortSignal
    onUploadId?: (uploadId: string) => void
  },
): Promise<{ upload_id: string; filename: string; size: number }> {
  if (file.size <= 0) throw new Error('文件为空')
  if (file.size > MAX_UPLOAD_BYTES) {
    throw new Error(`文件超过上限 ${MAX_UPLOAD_BYTES / (1024 * 1024)} MiB`)
  }
  const ext = fileExtension(file.name)
  if (DENIED_EXTS.has(ext)) {
    throw new Error(`拒绝上传可执行/脚本类型: .${ext}`)
  }
  if (classifyDataFile(file) === 'unknown') {
    throw new Error(`不支持的文件类型: ${file.name}`)
  }

  const initResp = await writeFetch('/import/upload/init', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      filename: file.name,
      size: file.size,
      content_type: file.type || null,
    }),
    signal: options?.signal,
  })
  if (!initResp.ok) {
    throw new Error(parseErrorDetail(initResp.status, await initResp.text()))
  }
  const initData = (await initResp.json()) as { upload_id: string; chunk_size_hint?: number }
  const uploadId = initData.upload_id
  options?.onUploadId?.(uploadId)
  const chunkSize = initData.chunk_size_hint || CHUNK_SIZE

  let offset = 0
  while (offset < file.size) {
    if (options?.signal?.aborted) throw new Error('上传已取消')
    const end = Math.min(offset + chunkSize, file.size)
    const received = await postChunkWithRetry(uploadId, file, offset, end, options?.signal)
    offset = Math.max(received, end)
    options?.onProgress?.(Math.min(1, offset / file.size))
  }

  let completeResp: Response | null = null
  let lastCompleteErr: Error | null = null
  for (let attempt = 0; attempt <= CHUNK_MAX_RETRIES; attempt++) {
    if (options?.signal?.aborted) throw new Error('上传已取消')
    try {
      completeResp = await writeFetch('/import/upload/complete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ upload_id: uploadId }),
        signal: options?.signal,
      })
    } catch (err) {
      if (options?.signal?.aborted) {
        throw new Error('上传已取消', { cause: err })
      }
      lastCompleteErr = err instanceof Error ? err : new Error(String(err))
      const networkLike =
        lastCompleteErr.name === 'TypeError' ||
        /network|fetch|Failed to fetch|timeout|aborted/i.test(lastCompleteErr.message)
      if (!networkLike || attempt === CHUNK_MAX_RETRIES) throw lastCompleteErr
      await sleep(CHUNK_RETRY_BASE_MS * 2 ** attempt, options?.signal)
      continue
    }
    if (completeResp.ok) break
    const detail = parseErrorDetail(completeResp.status, await completeResp.text())
    lastCompleteErr = new Error(detail)
    // 400/404 等业务错误不可重试：complete 失败时服务端可能已 discard staging，
    // 再试会变成「上传会话不存在」，掩盖真实原因（如魔数不匹配）。
    if (!isRetryableUploadError(completeResp.status) || attempt === CHUNK_MAX_RETRIES) {
      throw lastCompleteErr
    }
    await sleep(CHUNK_RETRY_BASE_MS * 2 ** attempt, options?.signal)
  }
  if (!completeResp?.ok) {
    throw lastCompleteErr ?? new Error('完成上传失败')
  }
  return (await completeResp.json()) as { upload_id: string; filename: string; size: number }
}

export async function importVectorByUploads(uploadIds: string[], sourceName?: string) {
  const resp = await writeFetch('/import/vector', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ upload_ids: uploadIds, source_name: sourceName ?? null }),
  })
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json() as Promise<{
    async?: boolean
    job_id?: string
    layer_id?: string
    feature_count?: number
    preview_geojson?: GeoJSON.FeatureCollection
    source_name?: string
    truncated?: boolean
  }>
}

export async function importVectorMultipart(files: File[]) {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  const resp = await writeFetch('/import/vector/multipart', { method: 'POST', body: form })
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json() as Promise<{
    layer_id: string
    feature_count: number
    preview_geojson: GeoJSON.FeatureCollection
    source_name: string
  }>
}

export async function waitForImportJob(
  jobId: string,
  options?: {
    intervalMs?: number
    timeoutMs?: number
    onProgress?: (p: number, message?: string) => void
  },
) {
  const interval = options?.intervalMs ?? 800
  const timeout = options?.timeoutMs ?? 10 * 60_000
  const started = Date.now()
  while (Date.now() - started < timeout) {
    const job = await fetchImportJob(jobId)
    options?.onProgress?.(Number(job.progress) || 0, job.message)
    if (job.status === 'succeeded') return job
    if (job.status === 'failed' || job.status === 'cancelled') {
      throw new Error(job.error || (job.status === 'cancelled' ? '任务已取消' : '导入任务失败'))
    }
    await new Promise((r) => setTimeout(r, interval))
  }
  throw new Error('导入任务超时')
}

export async function fetchImportJob(jobId: string) {
  const resp = await writeFetch(`/import/jobs/${encodeURIComponent(jobId)}`)
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json() as Promise<{
    status: string
    progress: number
    message?: string
    error?: string | null
    result?: Record<string, unknown>
    download_url?: string
  }>
}

export async function listImportJobs(limit = 20) {
  const resp = await writeFetch(`/import/jobs?limit=${limit}`)
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json() as Promise<{
    items: Array<{
      job_id: string
      kind: string
      status: string
      progress: number
      message?: string
      error?: string | null
      created_at?: string
    }>
  }>
}

export async function cancelImportJob(jobId: string) {
  const resp = await writeFetch(`/import/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: 'POST',
  })
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json() as Promise<{ job_id: string; status: string }>
}

export async function importBatch(
  uploadGroups: Array<{ kind: string; upload_ids: string[]; source_name?: string }>,
) {
  const resp = await writeFetch('/import/batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ groups: uploadGroups }),
  })
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json() as Promise<{ batch_id: string; job_ids: string[] }>
}

export async function exportBatchLayers(
  layerIds: string[],
  format: string,
  encoding: string = 'auto',
): Promise<{ job_id?: string; blob?: Blob }> {
  const resp = await writeFetch('/export/batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ layer_ids: layerIds, format, encoding }),
  })
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  const ct = resp.headers.get('content-type') || ''
  if (ct.includes('application/json')) {
    return resp.json() as Promise<{ job_id?: string }>
  }
  return { blob: await resp.blob() }
}

export async function inspectRasterUpload(uploadId: string) {
  const resp = await writeFetch('/import/raster/inspect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ upload_id: uploadId }),
  })
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json() as Promise<{
    upload_id: string
    filename: string
    format: string
    needs_variable_select: boolean
    variables: Array<{
      id: string
      name: string
      shape?: number[] | null
      dtype?: string | null
      fill_value?: number | null
    }>
    grid_presets?: Array<{
      id: string
      label: string
      crs?: string | null
      cols?: number | null
      rows?: number | null
      resolution?: number | null
      bounds?: [number, number, number, number] | null
      category?: string | null
    }>
    suggested_grid_preset?: string | null
    suggested_crs?: string | null
  }>
}

export async function commitRasterUpload(params: {
  uploadId: string
  variableId?: string | null
  variableIds?: string[]
  timeIndex?: number
  sourceName?: string
  sourceCrs?: string | null
  gridPreset?: string | null
  bounds?: [number, number, number, number] | null
  invalidValues?: number[]
  nodata?: number | null
  autoConfirm?: boolean
  lngOffset?: number
  latOffset?: number
  asyncMode?: boolean
}) {
  const resp = await writeFetch('/import/raster/commit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      upload_id: params.uploadId,
      variable_id: params.variableId ?? null,
      variable_ids: params.variableIds ?? [],
      time_index: params.timeIndex ?? 0,
      source_name: params.sourceName ?? null,
      source_crs: params.sourceCrs ?? null,
      grid_preset: params.gridPreset ?? null,
      bounds: params.bounds ?? null,
      invalid_values: params.invalidValues ?? [],
      nodata: params.nodata ?? null,
      auto_confirm: params.autoConfirm !== false,
      lng_offset: params.lngOffset ?? 0,
      lat_offset: params.latOffset ?? 0,
      async_mode: params.asyncMode ?? false,
    }),
  })
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json() as Promise<{
    async?: boolean
    job_id?: string
    layer_id?: string
    layers?: Array<{
      layer_id: string
      bounds?: [number, number, number, number]
      source_crs?: string
      needs_confirm?: boolean
      variable_id?: string
      detection_notes?: string
    }>
    bounds?: [number, number, number, number]
    source_crs?: string
    suggested_crs?: string
    needs_confirm?: boolean
    detection_notes?: string
    count?: number
  }>
}

export async function openDocumentUpload(uploadId: string) {
  const resp = await writeFetch('/import/document', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ upload_id: uploadId }),
  })
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json() as Promise<DocumentSession>
}

export async function openDocumentMultipart(file: File) {
  const form = new FormData()
  form.append('file', file)
  const resp = await writeFetch('/import/document/multipart', { method: 'POST', body: form })
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json() as Promise<DocumentSession>
}

export interface DocumentSession {
  session_id: string
  source_name?: string
  columns: string[]
  row_count: number
  preview_row_count: number
  truncated: boolean
  rows: Array<Record<string, string>>
}

export async function applyDocumentOps(sessionId: string, ops: Array<Record<string, unknown>>) {
  const resp = await writeFetch(`/import/document/${encodeURIComponent(sessionId)}/ops`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ops }),
  })
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json() as Promise<DocumentSession>
}

export async function commitDocumentSession(params: {
  sessionId: string
  xField: string
  yField: string
  sourceCrs?: string
  targetCrs?: string
}) {
  const resp = await writeFetch(`/import/document/${encodeURIComponent(params.sessionId)}/commit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      x_field: params.xField,
      y_field: params.yField,
      source_crs: params.sourceCrs ?? 'EPSG:4326',
      target_crs: params.targetCrs ?? 'EPSG:4326',
    }),
  })
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json() as Promise<{
    layer_id: string
    feature_count: number
    preview_geojson: GeoJSON.FeatureCollection
    source_name: string
    point_count: number
  }>
}

export async function exportImportedLayer(
  layerId: string,
  format: string,
  encoding: string = 'auto',
): Promise<Blob> {
  const resp = await writeFetch('/export/layer', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ layer_id: layerId, format, encoding }),
  })
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.blob()
}

export type ExportEncodingOption = { id: string; label: string }

export async function fetchExportEncodings(): Promise<ExportEncodingOption[]> {
  const resp = await writeFetch('/export/encodings')
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  const data = (await resp.json()) as { encodings?: ExportEncodingOption[] }
  return Array.isArray(data.encodings) ? data.encodings : []
}

export async function discardUpload(uploadId: string): Promise<void> {
  const resp = await writeFetch(`/import/upload/${encodeURIComponent(uploadId)}`, {
    method: 'DELETE',
  })
  if (!resp.ok && resp.status !== 404) {
    throw new Error(parseErrorDetail(resp.status, await resp.text()))
  }
}

export async function fetchImportedLayerMeta(layerId: string) {
  const resp = await writeFetch(`/import/layers/${encodeURIComponent(layerId)}/meta`)
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json() as Promise<{
    layer_id: string
    kind?: string
    source_name?: string
    feature_count?: number
    fields?: string[]
    geometry_types?: string[]
    truncated?: boolean
    source_encoding?: unknown
    encoding_strict?: unknown
    encoding_sources?: unknown
    [key: string]: unknown
  }>
}

export async function fetchImportedLayerGeojson(layerId: string, preview = true) {
  const q = preview ? 'true' : 'false'
  const resp = await writeFetch(
    `/import/layers/${encodeURIComponent(layerId)}/geojson?preview=${q}`,
  )
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json() as Promise<GeoJSON.FeatureCollection>
}

export async function fetchImportedLayerFeatures(
  layerId: string,
  params?: {
    limit?: number
    offset?: number
    field?: string
    contains?: string
    sort?: string
    where?: string
  },
) {
  const sp = new URLSearchParams()
  if (params?.limit != null) sp.set('limit', String(params.limit))
  if (params?.offset != null) sp.set('offset', String(params.offset))
  if (params?.field) sp.set('field', params.field)
  if (params?.contains != null) sp.set('contains', params.contains)
  if (params?.sort) sp.set('sort', params.sort)
  if (params?.where) sp.set('where', params.where)
  const qs = sp.toString()
  const resp = await writeFetch(
    `/import/layers/${encodeURIComponent(layerId)}/features${qs ? `?${qs}` : ''}`,
  )
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json() as Promise<{
    layer_id: string
    total: number
    offset: number
    limit: number
    features: GeoJSON.Feature[]
    indexes?: number[]
    fields?: string[]
  }>
}

export async function patchFeatureAttribute(
  layerId: string,
  featureIndex: number,
  field: string,
  value: unknown,
) {
  const resp = await writeFetch(
    `/import/layers/${encodeURIComponent(layerId)}/features/${featureIndex}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ field, value }),
    },
  )
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json() as Promise<{ layer_id: string; feature_index: number }>
}

export async function batchSetFeatureAttribute(
  layerId: string,
  featureIndexes: number[],
  field: string,
  value: unknown,
) {
  const resp = await writeFetch(`/import/layers/${encodeURIComponent(layerId)}/features/batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ indexes: featureIndexes, field, value }),
  })
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json() as Promise<{ layer_id: string; updated: number }>
}

export async function addLayerField(layerId: string, name: string, defaultValue: unknown = '') {
  const resp = await writeFetch(`/import/layers/${encodeURIComponent(layerId)}/fields`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, default: defaultValue }),
  })
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json() as Promise<{ layer_id: string; fields: string[] }>
}

export async function deleteLayerField(layerId: string, name: string) {
  const resp = await writeFetch(
    `/import/layers/${encodeURIComponent(layerId)}/fields/${encodeURIComponent(name)}`,
    { method: 'DELETE' },
  )
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json() as Promise<{ layer_id: string; fields: string[] }>
}

/** CRS 确认：转发 legacy 服务（保持行为） */
export { confirmRasterImport, fetchCrsOptions } from '../../services/data-import'

export async function renameImportedLayerField(layerId: string, oldName: string, newName: string) {
  const resp = await writeFetch(`/import/layers/${encodeURIComponent(layerId)}/rename-field`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ old_name: oldName, new_name: newName }),
  })
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json() as Promise<{
    layer_id: string
    feature_count?: number
    fields?: string[]
    preview_geojson?: GeoJSON.FeatureCollection
  }>
}

export async function deleteImportedLayer(layerId: string): Promise<void> {
  const resp = await writeFetch(`/import/layers/${encodeURIComponent(layerId)}`, {
    method: 'DELETE',
  })
  if (!resp.ok && resp.status !== 404) {
    throw new Error(parseErrorDetail(resp.status, await resp.text()))
  }
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}
