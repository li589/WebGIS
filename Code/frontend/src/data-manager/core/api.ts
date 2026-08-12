/**
 * 后端统一数据导入/导出 API（分块上传 + 矢量/栅格/文档 + 导出）。
 */
import { getBackendWriteApiKey, withWriteAuthHeaders } from './backend-auth'
import { applyApiFetchDefaults } from '../../services/http-credentials'
import { resolveApiUrl } from './_http'

export const MAX_UPLOAD_BYTES = 512 * 1024 * 1024
export const CHUNK_SIZE = 2 * 1024 * 1024
/** Manifest 模式默认分块（与后端 resumable DEFAULT_CHUNK_SIZE 对齐） */
export const RESUMABLE_CHUNK_SIZE = 4 * 1024 * 1024
const CHUNK_MAX_RETRIES = 4
const CHUNK_RETRY_BASE_MS = 400
const RESUMABLE_CONCURRENCY = 4

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
    throw new Error('未配置写权限：请登录或联系管理员获取 API Token')
  }
  return fetch(resolveApiUrl(path), applyApiFetchDefaults({ ...init, headers }))
}

async function sha256Hex(file: File, signal?: AbortSignal): Promise<string> {
  if (typeof crypto === 'undefined' || !crypto.subtle) {
    throw new Error('当前环境不支持 WebCrypto SHA-256')
  }
  const buf = await file.arrayBuffer()
  if (signal?.aborted) throw new Error('上传已取消')
  const digest = await crypto.subtle.digest('SHA-256', buf)
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

async function postIndexedChunkWithRetry(
  uploadId: string,
  file: File,
  chunkIndex: number,
  chunkSize: number,
  totalSize: number,
  signal?: AbortSignal,
): Promise<void> {
  const start = chunkIndex * chunkSize
  const end = Math.min(start + chunkSize, totalSize)
  let lastError: Error | null = null
  for (let attempt = 0; attempt <= CHUNK_MAX_RETRIES; attempt++) {
    if (signal?.aborted) throw new Error('上传已取消')
    try {
      const form = new FormData()
      form.append('file', file.slice(start, end), file.name)
      const resp = await writeFetch(
        `/import/upload/${encodeURIComponent(uploadId)}/chunk/${chunkIndex}`,
        { method: 'POST', body: form, signal },
      )
      if (resp.ok) return
      const detail = parseErrorDetail(resp.status, await resp.text())
      lastError = new Error(detail)
      if (!isRetryableUploadError(resp.status) || attempt === CHUNK_MAX_RETRIES) {
        throw lastError
      }
    } catch (err) {
      if (signal?.aborted) throw new Error('上传已取消', { cause: err })
      if (err === lastError) throw err
      lastError = err instanceof Error ? err : new Error(String(err))
      const networkLike =
        lastError.name === 'TypeError' ||
        /network|fetch|Failed to fetch|timeout|aborted/i.test(lastError.message)
      if (!networkLike || attempt === CHUNK_MAX_RETRIES) throw lastError
    }
    await sleep(CHUNK_RETRY_BASE_MS * 2 ** attempt + Math.floor(Math.random() * 200), signal)
  }
  throw lastError ?? new Error(`分块 ${chunkIndex} 上传失败`)
}

async function runPool<T>(
  items: T[],
  concurrency: number,
  worker: (item: T) => Promise<void>,
  signal?: AbortSignal,
): Promise<void> {
  let cursor = 0
  const runners = Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (cursor < items.length) {
      if (signal?.aborted) throw new Error('上传已取消')
      const idx = cursor++
      const item = items[idx]
      if (item === undefined) return
      await worker(item)
    }
  })
  await Promise.all(runners)
}

/**
 * Manifest 断点续传上传：SHA-256 → 并行分块 → 缺块续传 → complete 校验。
 */
export async function chunkedUpload(
  file: File,
  options?: {
    onProgress?: (ratio: number) => void
    /** 进度阶段文案：校验 SHA-256 / 块续传 / 合并校验 */
    onPhase?: (phase: string) => void
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

  const fingerprint = `${file.name}|${file.size}|${file.lastModified}`
  const resumeKey = `cgda:upload-resume:${fingerprint}`
  let resumeUploadId: string | null = null
  try {
    const raw = localStorage.getItem(resumeKey)
    if (raw) {
      const parsed = JSON.parse(raw) as { upload_id?: string; mode?: string }
      if (parsed.mode === 'manifest' && parsed.upload_id) {
        resumeUploadId = parsed.upload_id
      }
    }
  } catch {
    resumeUploadId = null
  }

  options?.onProgress?.(0.02)
  // 超大文件避免整文件 ArrayBuffer OOM；服务端仍可无 SHA 完成（未提供则跳过校验）
  const HASH_LIMIT = 128 * 1024 * 1024
  options?.onPhase?.(file.size <= HASH_LIMIT ? '校验 SHA-256' : '跳过 SHA-256（文件过大）')
  const sha256 = file.size <= HASH_LIMIT ? await sha256Hex(file, options?.signal) : null

  let uploadId = ''
  let chunkSize = RESUMABLE_CHUNK_SIZE
  let totalChunks = Math.ceil(file.size / chunkSize)
  let missing: number[] = []

  if (resumeUploadId) {
    try {
      const stResp = await writeFetch(
        `/import/upload/${encodeURIComponent(resumeUploadId)}/status`,
        { signal: options?.signal },
      )
      if (stResp.ok) {
        const st = (await stResp.json()) as {
          mode?: string
          complete?: boolean
          chunk_size?: number
          total_chunks?: number
          missing_chunks?: number[]
          size?: number
          filename?: string
        }
        if (st.mode === 'manifest' && !st.complete && Number(st.size) === file.size) {
          uploadId = resumeUploadId
          chunkSize = Number(st.chunk_size) || chunkSize
          totalChunks = Number(st.total_chunks) || totalChunks
          missing = Array.isArray(st.missing_chunks) ? [...st.missing_chunks] : []
        }
      }
    } catch {
      /* fall through to new init */
    }
  }

  if (!uploadId) {
    const initResp = await writeFetch('/import/upload/resumable/init', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        filename: file.name,
        size: file.size,
        content_type: file.type || null,
        chunk_size: chunkSize,
        sha256,
      }),
      signal: options?.signal,
    })
    if (!initResp.ok) {
      throw new Error(parseErrorDetail(initResp.status, await initResp.text()))
    }
    const initData = (await initResp.json()) as {
      upload_id: string
      chunk_size: number
      total_chunks: number
    }
    uploadId = initData.upload_id
    chunkSize = initData.chunk_size
    totalChunks = initData.total_chunks
    missing = Array.from({ length: totalChunks }, (_, i) => i)
  }

  options?.onUploadId?.(uploadId)
  try {
    localStorage.setItem(resumeKey, JSON.stringify({ upload_id: uploadId, mode: 'manifest' }))
  } catch {
    /* ignore */
  }

  options?.onPhase?.(
    resumeUploadId && uploadId === resumeUploadId
      ? `块续传（缺 ${missing.length}/${totalChunks}）`
      : `块上传（${totalChunks} 块）`,
  )
  let completedChunks = totalChunks - missing.length
  const bumpProgress = () => {
    options?.onProgress?.(Math.min(0.95, completedChunks / Math.max(1, totalChunks)))
  }
  bumpProgress()

  const toUpload = [...missing]
  await runPool(
    toUpload,
    RESUMABLE_CONCURRENCY,
    async (chunkIndex) => {
      await postIndexedChunkWithRetry(
        uploadId,
        file,
        chunkIndex,
        chunkSize,
        file.size,
        options?.signal,
      )
      completedChunks += 1
      bumpProgress()
    },
    options?.signal,
  )

  // 最终核对缺失块
  const stResp = await writeFetch(`/import/upload/${encodeURIComponent(uploadId)}/status`, {
    signal: options?.signal,
  })
  if (stResp.ok) {
    const st = (await stResp.json()) as { missing_chunks?: number[] }
    const stillMissing = Array.isArray(st.missing_chunks) ? st.missing_chunks : []
    if (stillMissing.length) {
      await runPool(
        stillMissing,
        RESUMABLE_CONCURRENCY,
        async (chunkIndex) => {
          await postIndexedChunkWithRetry(
            uploadId,
            file,
            chunkIndex,
            chunkSize,
            file.size,
            options?.signal,
          )
        },
        options?.signal,
      )
    }
  }

  options?.onPhase?.('合并并校验 SHA-256')
  options?.onProgress?.(0.97)
  let completeResp: Response | null = null
  let lastCompleteErr: Error | null = null
  for (let attempt = 0; attempt <= CHUNK_MAX_RETRIES; attempt++) {
    if (options?.signal?.aborted) throw new Error('上传已取消')
    try {
      completeResp = await writeFetch('/import/upload/resumable/complete', {
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
    if (!isRetryableUploadError(completeResp.status) || attempt === CHUNK_MAX_RETRIES) {
      throw lastCompleteErr
    }
    await sleep(CHUNK_RETRY_BASE_MS * 2 ** attempt, options?.signal)
  }
  if (!completeResp?.ok) {
    throw lastCompleteErr ?? new Error('完成上传失败')
  }
  try {
    localStorage.removeItem(resumeKey)
  } catch {
    /* ignore */
  }
  options?.onProgress?.(1)
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
    field_sanitization?: {
      changes?: Array<{ original: string; sanitized: string; reason: string }>
    }
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

export type ExportBBoxPayload = {
  west: number
  south: number
  east: number
  north: number
  crs?: string
}

export type ExportRequestOptions = {
  encoding?: string
  time?: string | null
  times?: string[] | null
  bbox?: ExportBBoxPayload | null
  outputCrs?: string | null
  fields?: string[] | null
}

export async function exportBatchLayers(
  layerIds: string[],
  format: string,
  encodingOrOpts: string | ExportRequestOptions = 'auto',
): Promise<{ job_id?: string; blob?: Blob }> {
  const opts: ExportRequestOptions =
    typeof encodingOrOpts === 'string' ? { encoding: encodingOrOpts } : encodingOrOpts
  const payload: Record<string, unknown> = {
    layer_ids: layerIds,
    format,
    encoding: opts.encoding || 'auto',
  }
  if (opts.times?.length) payload.times = opts.times
  else if (opts.time) payload.time = opts.time
  if (opts.bbox) payload.bbox = { crs: 'EPSG:4326', ...opts.bbox }
  if (opts.outputCrs) payload.output_crs = opts.outputCrs
  if (opts.fields?.length) payload.fields = opts.fields
  const resp = await writeFetch('/export/batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
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
    guessed_temporal?: {
      kind?: string
      time_list?: string[]
      default_time?: string
      native_step?: string
      label?: string
    } | null
    variables: Array<{
      id: string
      name: string
      shape?: number[] | null
      dtype?: string | null
      fill_value?: number | null
      suggested_grid_preset?: string | null
      needs_transpose?: boolean
      axis_hint?: string | null
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
    suggested_needs_transpose?: boolean
    suggested_crs?: string | null
    file_meta?: Record<string, string>
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
  /** auto | as_is | transpose — MATLAB v7.3 颠倒维默认 auto */
  axisOrder?: 'auto' | 'as_is' | 'transpose'
  /** True → axis_order=transpose；与 axisOrder 二选一优先 swapXy */
  swapXy?: boolean | null
  /** overwrite 覆盖同名 / rename 另存 / error 冲突报错 */
  conflictPolicy?: 'overwrite' | 'rename' | 'error'
  /** auto | static | point | range */
  temporalMode?: 'auto' | 'static' | 'point' | 'range'
  timeLabel?: string | null
  timeStart?: string | null
  timeEnd?: string | null
  nativeStep?: string | null
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
      axis_order: params.axisOrder ?? 'auto',
      swap_xy: params.swapXy ?? null,
      conflict_policy: params.conflictPolicy ?? 'overwrite',
      temporal_mode: params.temporalMode ?? 'auto',
      time_label: params.timeLabel ?? null,
      time_start: params.timeStart ?? null,
      time_end: params.timeEnd ?? null,
      native_step: params.nativeStep ?? null,
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
      time_list?: string[]
      default_time?: string | null
      native_step?: string | null
      follow_policy?: string | null
      temporal_kind?: string | null
      temporal_source?: string | null
      replaced?: boolean
      auto_confirm_error?: string
    }>
    bounds?: [number, number, number, number]
    source_crs?: string
    suggested_crs?: string
    needs_confirm?: boolean
    detection_notes?: string
    count?: number
    time_list?: string[]
    default_time?: string | null
    native_step?: string | null
    follow_policy?: string | null
    temporal_kind?: string | null
    temporal_source?: string | null
    replaced?: boolean
  }>
}

export async function detectRasterInvalidValues(params: {
  uploadId: string
  variableId: string
}): Promise<{
  suggested_invalid_values: number[]
  sentinels?: Array<{ value: number; count?: number; frequency?: number }>
  has_inf?: boolean
  fill_value?: number | null
  missing_value?: number | null
  [key: string]: unknown
}> {
  const resp = await writeFetch('/import/raster/detect-invalid', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      upload_id: params.uploadId,
      variable_id: params.variableId,
    }),
  })
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json()
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
  source_encoding?: string | null
  encoding_note?: string | null
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
  /** null/undefined=自动检测；true/false=强制 */
  swapXy?: boolean | null
}) {
  const resp = await writeFetch(`/import/document/${encodeURIComponent(params.sessionId)}/commit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      x_field: params.xField,
      y_field: params.yField,
      source_crs: params.sourceCrs ?? 'EPSG:4326',
      target_crs: params.targetCrs ?? 'EPSG:4326',
      swap_xy: params.swapXy === undefined ? null : params.swapXy,
    }),
  })
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json() as Promise<{
    layer_id: string
    feature_count: number
    preview_geojson: GeoJSON.FeatureCollection
    source_name: string
    point_count: number
    xy_swap_applied?: boolean
    xy_swap_note?: string
    field_sanitization?: {
      changes?: Array<{ original: string; sanitized: string; reason: string }>
    }
  }>
}

export async function exportImportedLayer(
  layerId: string,
  format: string,
  encodingOrOpts: string | ExportRequestOptions = 'auto',
  time?: string | null,
  times?: string[] | null,
): Promise<Blob> {
  const opts: ExportRequestOptions =
    typeof encodingOrOpts === 'string' ? { encoding: encodingOrOpts, time, times } : encodingOrOpts
  const payload: Record<string, unknown> = {
    layer_id: layerId,
    format,
    encoding: opts.encoding || 'auto',
  }
  if (opts.times?.length) {
    payload.times = opts.times
  } else if (opts.time) {
    payload.time = opts.time
  }
  if (opts.bbox) payload.bbox = { crs: 'EPSG:4326', ...opts.bbox }
  if (opts.outputCrs) payload.output_crs = opts.outputCrs
  if (opts.fields?.length) payload.fields = opts.fields
  const resp = await writeFetch('/export/layer', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
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

/** 更新导入图层显示名（写入后端 meta.display_name） */
export async function renameImportedLayerDisplayName(layerId: string, displayName: string) {
  const resp = await writeFetch(`/import/layers/${encodeURIComponent(layerId)}/display-name`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ display_name: displayName }),
  })
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json() as Promise<{ layer_id: string; display_name: string; kind?: string }>
}

export async function deleteImportedLayer(layerId: string): Promise<void> {
  const resp = await writeFetch(`/import/layers/${encodeURIComponent(layerId)}`, {
    method: 'DELETE',
  })
  if (!resp.ok && resp.status !== 404) {
    throw new Error(parseErrorDetail(resp.status, await resp.text()))
  }
}

export interface ImportQuotaInfo {
  ok: boolean
  used_bytes: number
  ephemeral_bytes: number
  limit_bytes: number
  free_bytes: number
  soft_reserve_bytes: number
  used_ratio: number
  imports_dir: string
}

export async function fetchImportQuota(): Promise<ImportQuotaInfo> {
  const resp = await writeFetch('/import/quota')
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json() as Promise<ImportQuotaInfo>
}

export async function reclaimImportSpace(): Promise<{
  ok: boolean
  reclaimed_bytes: number
}> {
  const resp = await writeFetch('/import/quota/reclaim', { method: 'POST' })
  if (!resp.ok) throw new Error(parseErrorDetail(resp.status, await resp.text()))
  return resp.json()
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
