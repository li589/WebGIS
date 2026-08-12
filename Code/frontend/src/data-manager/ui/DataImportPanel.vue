<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { DATA_COPY } from '../../ui-copy'
import AppSelect from '../../components/ui/AppSelect.vue'
import {
  applyDocumentOps,
  chunkedUpload,
  classifyDataFile,
  commitDocumentSession,
  commitRasterUpload,
  discardUpload,
  fileExtension,
  formatBytes,
  importVectorByUploads,
  inspectRasterUpload,
  openDocumentUpload,
  waitForImportJob,
  type DocumentSession,
} from '../core/api'
import { confirmRasterImport } from '../core/api'
import { describeShapefileReadiness, groupVectorFiles } from '../core/vector-groups'
import {
  focusImportedLayer,
  registerImportedRasterLayer,
  registerImportedVectorLayer,
} from '../adapters/layers'
import { useLayersStore } from '../../stores/layers'
import { useLogStore } from '../../stores/log'
import RasterImportConfirmDialog from './RasterImportConfirmDialog.vue'
import ScienceRasterImportDialog, {
  type GridPreset,
  type ScienceRasterCommitPayload,
  type ScienceVariable,
} from './ScienceRasterImportDialog.vue'
import { validateOverlayBounds } from '../../components/map/overlay-image-module'
import { openDataWorkspace, setUploadProgress, showToast } from '../core/workspace-store'
import {
  buildImportTemporalPayload,
  guessTimeLabelFromFilename,
  type ImportTemporalMode,
} from '../../utils/import-temporal'
import type { TemporalFollowPolicy } from '../../utils/temporal-interval'

const props = defineProps<{
  initialTab?: 'vector' | 'raster' | 'document'
  initialFiles?: File[]
  /** 嵌入数据工作台时不渲染全屏遮罩 */
  embedded?: boolean
}>()

const emit = defineEmits<{ close: [] }>()

const layersStore = useLayersStore()
const logStore = useLogStore()

const activeTab = ref<'vector' | 'raster' | 'document'>(props.initialTab ?? 'vector')
const busy = ref(false)
const progress = ref<number | null>(null)
const statusMsg = ref('')
const errorMsg = ref('')
const uploadAbort = ref<AbortController | null>(null)
const activeUploadId = ref<string | null>(null)

const vectorFiles = ref<File[]>([])
const rasterFiles = ref<File[]>([])
const rasterFile = ref<File | null>(null)
const rasterUploadId = ref<string | null>(null)
const rasterVariables = ref<ScienceVariable[]>([])
const selectedVariable = ref('')
const timeIndex = ref(0)
const needsVariable = ref(false)
const scienceDialogOpen = ref(false)
const scienceFormat = ref('')
const scienceGridPresets = ref<GridPreset[]>([])
const scienceSuggestedPreset = ref<string | null>(null)
const scienceSuggestedCrs = ref<string | null>(null)
const scienceSuggestedNeedsTranspose = ref(false)
const scienceCommitOpts = ref<ScienceRasterCommitPayload | null>(null)
const documentQueue = ref<File[]>([])
const documentSession = ref<DocumentSession | null>(null)
const xField = ref('')
const yField = ref('')
/** auto | force | keep — 映射到 swap_xy null/true/false */
const docSwapXyMode = ref<'auto' | 'force' | 'keep'>('auto')
const sourceCrs = ref('EPSG:4326')

/** 栅格时间语义：自动猜文件名 / 静态 / 时间点 / 时间段 */
const temporalMode = ref<ImportTemporalMode>('auto')
const temporalPoint = ref('')
const temporalStart = ref('')
const temporalEnd = ref('')
const temporalNativeStep = ref('')

const temporalPreview = computed(() => {
  const sample = rasterFile.value?.name || rasterFiles.value[0]?.name || ''
  return buildImportTemporalPayload({
    mode: temporalMode.value,
    fileName: sample,
    timePoint: temporalPoint.value,
    timeStart: temporalStart.value,
    timeEnd: temporalEnd.value,
    nativeStep: temporalNativeStep.value || undefined,
  })
})

watch(
  () => rasterFiles.value.map((f) => f.name).join('|'),
  () => {
    const name = rasterFiles.value[0]?.name
    if (!name || temporalMode.value !== 'auto') return
    const g = guessTimeLabelFromFilename(name)
    if (g?.kind === 'point') {
      temporalPoint.value = g.label
      temporalNativeStep.value = g.nativeStep
    } else if (g?.kind === 'range') {
      const [a, b] = g.label.split('_')
      temporalStart.value = a || ''
      temporalEnd.value = b || ''
      temporalNativeStep.value = g.nativeStep
    }
  },
)
const opRenameFrom = ref('')
const opRenameTo = ref('')
const opFilterField = ref('')
const opFilterContains = ref('')
const opFindField = ref('')
const opFind = ref('')
const opReplace = ref('')
const opSplitField = ref('')
const opSplitSep = ref(',')
const opSplitInto = ref('')

const pendingRasterConfirm = ref<{
  layerId: string
  fileName: string
  detectionResult: {
    layer_id: string
    source_crs?: string
    suggested_crs?: string
    needs_confirm?: boolean
    detection_notes?: string
    bounds?: [number, number, number, number]
  }
} | null>(null)

const tabs = [
  { id: 'vector' as const, label: DATA_COPY.tabVector, hint: DATA_COPY.vectorHint },
  { id: 'raster' as const, label: DATA_COPY.tabRaster, hint: DATA_COPY.rasterHint },
  { id: 'document' as const, label: DATA_COPY.tabDocument, hint: DATA_COPY.documentHint },
]

const documentColumns = computed(() => documentSession.value?.columns ?? [])
const documentRows = computed(() => documentSession.value?.rows ?? [])

onMounted(() => {
  if (!props.initialFiles?.length) return
  const files = props.initialFiles
  const kinds = new Set(files.map((f) => classifyDataFile(f)))
  if (kinds.has('document')) {
    activeTab.value = 'document'
    documentQueue.value = files.filter((f) => classifyDataFile(f) === 'document')
    if (documentQueue.value[0]) void startDocument(documentQueue.value[0]!)
  } else if (kinds.has('raster')) {
    activeTab.value = 'raster'
    rasterFiles.value = files.filter((f) => classifyDataFile(f) === 'raster')
  } else if (kinds.has('vector')) {
    activeTab.value = 'vector'
    vectorFiles.value = files.filter((f) => classifyDataFile(f) === 'vector')
  }
})

/** 将选中文件拆成独立导入组：每个 zip/geojson 一组；同 stem 的 shp+sidecar 一组 — 见 vector-groups.ts */

const vectorSidecarStatus = computed(() => describeShapefileReadiness(vectorFiles.value))

function setStatus(msg: string, isError = false) {
  statusMsg.value = isError ? '' : msg
  errorMsg.value = isError ? msg : ''
}

function beginUploadSession() {
  uploadAbort.value?.abort()
  const ac = new AbortController()
  uploadAbort.value = ac
  activeUploadId.value = null
  return ac
}

async function cancelUpload() {
  uploadAbort.value?.abort()
  const id = activeUploadId.value
  activeUploadId.value = null
  if (id) {
    try {
      await discardUpload(id)
    } catch {
      /* ignore */
    }
  }
  busy.value = false
  progress.value = null
  setUploadProgress(null)
  setStatus('已取消上传')
}

function uploadOpts(onProgress: (r: number) => void) {
  const ac = beginUploadSession()
  return {
    signal: ac.signal,
    onProgress: (r: number) => {
      onProgress(r)
      setUploadProgress(r)
    },
    onPhase: (phase: string) => {
      setStatus(`${DATA_COPY.uploading} · ${phase}`)
    },
    onUploadId: (id: string) => {
      activeUploadId.value = id
    },
  }
}

function onVectorPick(e: Event) {
  const input = e.target as HTMLInputElement
  vectorFiles.value = Array.from(input.files ?? [])
  input.value = ''
}

async function importOneVectorGroup(files: File[], groupIndex: number, groupTotal: number) {
  const uploadIds: string[] = []
  // 跳过无法分类的附属文件，避免整组失败（主文件仍校验）
  const uploadable = files.filter((f) => classifyDataFile(f) === 'vector')
  if (!uploadable.length) {
    throw new Error('没有可上传的矢量文件')
  }
  for (let i = 0; i < uploadable.length; i++) {
    const file = uploadable[i]!
    const up = await chunkedUpload(file, {
      ...uploadOpts((r) => {
        const base = groupIndex / groupTotal
        const slice = 1 / groupTotal
        progress.value = base + (slice * (i + r)) / uploadable.length
      }),
    })
    uploadIds.push(up.upload_id)
  }
  setStatus(`${DATA_COPY.processing}（${groupIndex + 1}/${groupTotal}）`)
  let result = await importVectorByUploads(
    uploadIds,
    uploadable.find((f) => fileExtension(f.name) === 'shp')?.name ?? uploadable[0]?.name,
  )
  if (result.async && result.job_id) {
    const job = await waitForImportJob(result.job_id, {
      onProgress: (p) => {
        progress.value = (groupIndex + p) / groupTotal
      },
    })
    result = { async: false, ...(job.result as typeof result) }
  }
  const preview =
    (result.preview_geojson as GeoJSON.FeatureCollection | undefined) ??
    ({ type: 'FeatureCollection', features: [] } as GeoJSON.FeatureCollection)
  const displayName =
    (typeof result.source_name === 'string' && result.source_name) ||
    uploadable.find((f) => fileExtension(f.name) === 'shp')?.name ||
    uploadable[0]!.name
  const layer = await registerImportedVectorLayer(displayName, preview, {
    backendLayerId: result.layer_id,
    featureCount: result.feature_count,
    truncated: Boolean(result.truncated),
  })
  focusImportedLayer(layer.instanceId)
  const changes = result.field_sanitization?.changes
  if (Array.isArray(changes) && changes.length) {
    const sample = changes
      .slice(0, 3)
      .map((c) => `${c.original}→${c.sanitized}`)
      .join('；')
    showToast(`字段名已规范化 ${changes.length} 项：${sample}${changes.length > 3 ? '…' : ''}`)
  }
  return { ...result, instanceId: layer.instanceId }
}

async function runVectorImport() {
  if (!vectorFiles.value.length) {
    setStatus('请先选择矢量文件', true)
    return
  }
  const readiness = describeShapefileReadiness(vectorFiles.value)
  if (!readiness.ok) {
    setStatus(readiness.errors[0] || 'SHP 附属文件不完整', true)
    return
  }
  const groups = groupVectorFiles(vectorFiles.value)
  if (!groups.length) {
    setStatus('未识别到可导入的矢量文件', true)
    return
  }
  busy.value = true
  progress.value = 0
  setStatus(DATA_COPY.uploading)
  let ok = 0
  const errors: string[] = []
  try {
    for (let g = 0; g < groups.length; g++) {
      try {
        await importOneVectorGroup(groups[g]!, g, groups.length)
        ok += 1
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err)
        errors.push(msg)
      }
    }
    if (ok && !errors.length) {
      setStatus(`已导入 ${ok} 个矢量图层`)
      vectorFiles.value = []
      const last = [...layersStore.activeLayers].reverse().find((l) => l.importedVector)
      if (last) {
        focusImportedLayer(last.instanceId)
        openDataWorkspace({ tab: 'attributes', layerInstanceId: last.instanceId })
        if (last.importedVector?.truncated) {
          showToast(`已导入（地图为预览截断）；属性表走服务端分页，可在详情中加载完整数据`)
        } else {
          showToast(`已导入 ${ok} 个矢量图层，已加入图层管理器`)
        }
      } else {
        showToast(`已导入 ${ok} 个矢量图层`)
      }
    } else if (ok) {
      setStatus(`成功 ${ok} 个，失败 ${errors.length}：${errors[0]}`, true)
    } else {
      setStatus(errors[0] || '矢量导入失败', true)
    }
    if (ok) logStore.logOperation('import-vector-success', `矢量导入 ${ok} 层`)
    if (errors.length)
      logStore.logOperation('import-vector-fail', '部分矢量导入失败', errors.join('; '))
  } finally {
    busy.value = false
    progress.value = null
    setUploadProgress(null)
  }
}

async function runRasterBatch() {
  if (busy.value) return
  if (!rasterFiles.value.length) {
    setStatus('请先选择栅格文件', true)
    return
  }
  // 多文件且无需变量选择时可批量；含科学格式时逐个 inspect
  const queue = [...rasterFiles.value]
  busy.value = true
  progress.value = 0
  let ok = 0
  const errors: string[] = []
  try {
    for (let i = 0; i < queue.length; i++) {
      const file = queue[i]!
      setStatus(`${DATA_COPY.uploading}（${i + 1}/${queue.length}） ${file.name}`)
      try {
        const up = await chunkedUpload(file, {
          ...uploadOpts((r) => {
            progress.value = (i + r) / queue.length
          }),
        })
        rasterUploadId.value = up.upload_id
        rasterFile.value = file
        const info = await inspectRasterUpload(up.upload_id)
        needsVariable.value = Boolean(info.needs_variable_select)
        rasterVariables.value = (info.variables || []) as ScienceVariable[]
        selectedVariable.value = rasterVariables.value[0]?.id ?? ''
        scienceFormat.value = info.format || ''
        scienceGridPresets.value = (info.grid_presets || []) as GridPreset[]
        scienceSuggestedPreset.value = info.suggested_grid_preset ?? null
        scienceSuggestedCrs.value = info.suggested_crs ?? null
        scienceSuggestedNeedsTranspose.value = Boolean(info.suggested_needs_transpose)
        if (needsVariable.value) {
          // 需要用户配置变量/CRS/无效值：打开科学导入对话框
          rasterFiles.value = queue.slice(i)
          scienceDialogOpen.value = true
          setStatus(`已解析 ${info.format}（${file.name}），请配置后确认导入`)
          progress.value = null
          return
        }
        await commitRaster({ resumeQueue: false })
        ok += 1
        rasterFiles.value = rasterFiles.value.filter((f) => f.name !== file.name)
      } catch (err) {
        errors.push(`${file.name}: ${err instanceof Error ? err.message : String(err)}`)
      }
    }
    rasterFiles.value = []
    if (ok && !errors.length) setStatus(`已导入 ${ok} 个栅格图层`)
    else if (ok) setStatus(`成功 ${ok} 个，失败 ${errors.length}：${errors[0]}`, true)
    else setStatus(errors[0] || '栅格导入失败', true)
  } finally {
    busy.value = false
    if (!needsVariable.value) progress.value = null
  }
}

async function startRaster(file: File) {
  rasterFiles.value = [file]
  await runRasterBatch()
}

function onRasterPick(e: Event) {
  const input = e.target as HTMLInputElement
  rasterFiles.value = Array.from(input.files ?? [])
  input.value = ''
  if (rasterFiles.value.length === 1) void startRaster(rasterFiles.value[0]!)
}

async function startDocument(file: File) {
  busy.value = true
  progress.value = 0
  setStatus(DATA_COPY.uploading)
  try {
    const up = await chunkedUpload(file, {
      ...uploadOpts((r) => {
        progress.value = r
      }),
    })
    setStatus(DATA_COPY.processing)
    const session = await openDocumentUpload(up.upload_id)
    documentSession.value = session
    guessXy(session.columns)
    setStatus(`文档已打开：${session.row_count} 行 / ${session.columns.length} 列`)
    documentQueue.value = documentQueue.value.filter((f) => f !== file)
  } catch (err) {
    setStatus(err instanceof Error ? err.message : String(err), true)
  } finally {
    busy.value = false
    progress.value = null
  }
}

function onDocumentPick(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  if (!files.length) return
  documentQueue.value = files
  void startDocument(files[0]!)
}

async function onScienceRasterConfirm(payload: ScienceRasterCommitPayload) {
  scienceCommitOpts.value = payload
  selectedVariable.value = payload.variableIds[0] ?? ''
  timeIndex.value = payload.timeIndex
  if (payload.temporalMode) temporalMode.value = payload.temporalMode
  if (payload.timePoint != null) temporalPoint.value = payload.timePoint
  if (payload.timeStart != null) temporalStart.value = payload.timeStart
  if (payload.timeEnd != null) temporalEnd.value = payload.timeEnd
  if (payload.nativeStep != null) temporalNativeStep.value = payload.nativeStep
  scienceDialogOpen.value = false
  await commitRaster({ resumeQueue: true })
}

function resolveTemporalCommitFields(fileName: string) {
  const fromSci = scienceCommitOpts.value
  const mode = (fromSci?.temporalMode || temporalMode.value) as ImportTemporalMode
  const built = buildImportTemporalPayload({
    mode,
    fileName,
    timePoint: fromSci?.timePoint ?? temporalPoint.value,
    timeStart: fromSci?.timeStart ?? temporalStart.value,
    timeEnd: fromSci?.timeEnd ?? temporalEnd.value,
    nativeStep: (fromSci?.nativeStep ?? temporalNativeStep.value) || undefined,
  })
  if ((mode === 'point' || mode === 'range') && !built.preview) {
    throw new Error(mode === 'point' ? '请填写有效时间点（YYYYMMDD）' : '请填写有效起止日期')
  }
  return built
}

function temporalOptionsFromResult(lr: {
  time_list?: string[]
  native_step?: string | null
  follow_policy?: string | null
}): {
  nativeStep?: string | null
  timeList?: string[]
  followPolicy?: TemporalFollowPolicy
} {
  const timeList = Array.isArray(lr.time_list) ? lr.time_list.map(String) : []
  if (!timeList.length) return {}
  return {
    timeList,
    nativeStep: lr.native_step || (timeList[0]?.includes('_') ? '8d' : '1d'),
    followPolicy: (lr.follow_policy as TemporalFollowPolicy) || 'containing',
  }
}

function onScienceRasterCancel() {
  scienceDialogOpen.value = false
  scienceCommitOpts.value = null
  setStatus('已取消科学栅格导入')
}

async function commitRaster(opts?: { resumeQueue?: boolean }) {
  if (!rasterUploadId.value || !rasterFile.value) return
  const resumeQueue = opts?.resumeQueue !== false
  busy.value = true
  setStatus(DATA_COPY.processing)
  try {
    const sci = scienceCommitOpts.value
    const temporal = resolveTemporalCommitFields(rasterFile.value.name)
    let data = await commitRasterUpload({
      uploadId: rasterUploadId.value,
      variableId: needsVariable.value ? selectedVariable.value : null,
      variableIds: sci?.variableIds,
      timeIndex: sci?.timeIndex ?? timeIndex.value,
      sourceName: rasterFile.value.name,
      sourceCrs: sci?.sourceCrs,
      gridPreset: sci?.gridPreset,
      bounds: sci?.bounds,
      invalidValues: sci?.invalidValues,
      nodata: sci?.nodata ?? null,
      autoConfirm: sci?.autoConfirm !== false,
      axisOrder: sci?.axisOrder ?? 'auto',
      conflictPolicy: sci?.conflictPolicy ?? 'overwrite',
      temporalMode: temporal.temporalMode,
      timeLabel: temporal.timeLabel ?? null,
      timeStart: temporal.timeStart ?? null,
      timeEnd: temporal.timeEnd ?? null,
      nativeStep: temporal.nativeStep ?? null,
    })

    if (data.async && data.job_id) {
      setStatus('大文件异步导入中…')
      const job = await waitForImportJob(data.job_id, {
        onProgress: (p) => {
          progress.value = typeof p === 'number' ? p : progress.value
        },
      })
      data = { ...(job.result || {}), async: false } as typeof data
    }

    const layerResults =
      Array.isArray(data.layers) && data.layers.length
        ? data.layers
        : data.layer_id
          ? [
              {
                layer_id: data.layer_id,
                bounds: data.bounds,
                source_crs: data.source_crs,
                needs_confirm: data.needs_confirm,
                detection_notes: data.detection_notes,
                auto_confirm_error: (data as { auto_confirm_error?: string }).auto_confirm_error,
                variable_id: selectedVariable.value,
                time_list: data.time_list,
                native_step: data.native_step,
                follow_policy: data.follow_policy,
              },
            ]
          : []

    if (!layerResults.length) {
      throw new Error('导入未返回图层结果')
    }

    let lastInstanceId: string | null = null
    for (const lr of layerResults) {
      const boundsCheck = validateOverlayBounds(lr.bounds)
      if (lr.needs_confirm || !boundsCheck.ok) {
        pendingRasterConfirm.value = {
          layerId: lr.layer_id,
          fileName: `${rasterFile.value.name}${lr.variable_id ? ` · ${lr.variable_id}` : ''}`,
          detectionResult: {
            layer_id: lr.layer_id,
            source_crs: lr.source_crs ?? sci?.sourceCrs,
            suggested_crs: sci?.sourceCrs ?? lr.source_crs,
            needs_confirm: true,
            detection_notes:
              (typeof (lr as { auto_confirm_error?: string }).auto_confirm_error === 'string'
                ? `自动重投影未完成：${(lr as { auto_confirm_error?: string }).auto_confirm_error}；`
                : '') +
              (lr.detection_notes ||
                (!boundsCheck.ok ? `范围无法直接显示：${boundsCheck.reason}` : '') ||
                ''),
            bounds: lr.bounds,
          },
        }
        setStatus('请确认坐标系')
        // 多图层时若仍有一层需确认，先停在第一层确认；其余层若已 auto_confirm 则已注册
        break
      }
      const layer = await registerImportedRasterLayer(
        `${rasterFile.value.name}${lr.variable_id ? `:${lr.variable_id}` : ''}`,
        lr.layer_id,
        lr.bounds,
        {
          sourceCrs: lr.source_crs ?? sci?.sourceCrs,
          ...temporalOptionsFromResult({
            time_list: lr.time_list ?? data.time_list,
            native_step: lr.native_step ?? data.native_step,
            follow_policy: lr.follow_policy ?? data.follow_policy,
          }),
        },
      )
      lastInstanceId = layer.instanceId
      focusImportedLayer(layer.instanceId)
    }

    if (!pendingRasterConfirm.value) {
      if (lastInstanceId) {
        openDataWorkspace({ tab: 'details', layerInstanceId: lastInstanceId })
      }
      setStatus(
        `${(data as { replaced?: boolean }).replaced || layerResults.some((l) => (l as { replaced?: boolean }).replaced) ? '已覆盖同名并导入' : '栅格已导入'}：${rasterFile.value.name}（${layerResults.length} 层）`,
      )
      const doneName = rasterFile.value.name
      rasterFile.value = null
      rasterUploadId.value = null
      needsVariable.value = false
      scienceCommitOpts.value = null
      scienceDialogOpen.value = false
      rasterFiles.value = rasterFiles.value.filter((f) => f.name !== doneName)
      if (resumeQueue && rasterFiles.value.length) {
        void runRasterBatch()
        return
      }
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    setStatus(msg, true)
  } finally {
    busy.value = false
  }
}

async function onRasterConfirm(payload: {
  sourceCrs: string
  lngOffset: number
  latOffset: number
}) {
  const pending = pendingRasterConfirm.value
  if (!pending) return
  busy.value = true
  try {
    const result = await confirmRasterImport({
      layerId: pending.layerId,
      sourceCrs: payload.sourceCrs,
      lngOffset: payload.lngOffset,
      latOffset: payload.latOffset,
    })
    const layer = await registerImportedRasterLayer(
      pending.fileName,
      pending.layerId,
      result.bounds,
      {
        sourceCrs: payload.sourceCrs,
        lngOffset: payload.lngOffset,
        latOffset: payload.latOffset,
        ...temporalOptionsFromResult({
          time_list: (result as { time_list?: string[] }).time_list,
          native_step: (result as { native_step?: string | null }).native_step,
          follow_policy: (result as { follow_policy?: string | null }).follow_policy,
        }),
      },
    )
    focusImportedLayer(layer.instanceId)
    openDataWorkspace({ tab: 'details', layerInstanceId: layer.instanceId })
    setStatus(`栅格已导入：${pending.fileName}`)
    const doneName = pending.fileName
    pendingRasterConfirm.value = null
    rasterFile.value = null
    rasterUploadId.value = null
    needsVariable.value = false
    rasterFiles.value = rasterFiles.value.filter((f) => f.name !== doneName)
    if (rasterFiles.value.length) {
      void runRasterBatch()
      return
    }
  } catch (err) {
    setStatus(err instanceof Error ? err.message : String(err), true)
  } finally {
    busy.value = false
  }
}

function skipRasterConfirm() {
  const pending = pendingRasterConfirm.value
  if (!pending) return
  void onRasterConfirm({
    sourceCrs: pending.detectionResult.suggested_crs || 'EPSG:4326',
    lngOffset: 0,
    latOffset: 0,
  })
}

function guessXy(columns: string[]) {
  const lower = columns.map((c) => c.toLowerCase())
  const xIdx = lower.findIndex((c) => ['lon', 'lng', 'longitude', 'x', '经度'].includes(c))
  const yIdx = lower.findIndex((c) => ['lat', 'latitude', 'y', '纬度'].includes(c))
  xField.value = xIdx >= 0 ? columns[xIdx]! : columns[0] || ''
  yField.value = yIdx >= 0 ? columns[yIdx]! : columns[1] || columns[0] || ''
}

async function applyOps() {
  if (!documentSession.value) return
  const ops: Array<Record<string, unknown>> = []
  if (opRenameFrom.value && opRenameTo.value) {
    ops.push({ op: 'rename', from: opRenameFrom.value, to: opRenameTo.value })
  }
  if (opFilterField.value && opFilterContains.value) {
    ops.push({
      op: 'filter',
      field: opFilterField.value,
      contains: opFilterContains.value,
    })
  }
  if (opFindField.value && opFind.value !== '') {
    ops.push({
      op: 'find_replace',
      field: opFindField.value,
      find: opFind.value,
      replace: opReplace.value,
    })
  }
  if (opSplitField.value && opSplitInto.value) {
    ops.push({
      op: 'split',
      field: opSplitField.value,
      separator: opSplitSep.value || ',',
      into: opSplitInto.value
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
    })
  }
  if (!ops.length) {
    setStatus('请先填写至少一项表操作', true)
    return
  }
  busy.value = true
  try {
    documentSession.value = await applyDocumentOps(documentSession.value.session_id, ops)
    guessXy(documentSession.value.columns)
    setStatus('表操作已应用')
  } catch (err) {
    setStatus(err instanceof Error ? err.message : String(err), true)
  } finally {
    busy.value = false
  }
}

async function commitDocument() {
  if (!documentSession.value) return
  if (!xField.value || !yField.value) {
    setStatus('请选择 XY 列', true)
    return
  }
  busy.value = true
  setStatus(DATA_COPY.processing)
  try {
    const swapXy =
      docSwapXyMode.value === 'force' ? true : docSwapXyMode.value === 'keep' ? false : null
    const result = await commitDocumentSession({
      sessionId: documentSession.value.session_id,
      xField: xField.value,
      yField: yField.value,
      sourceCrs: sourceCrs.value,
      swapXy,
    })
    const layer = await registerImportedVectorLayer(
      result.source_name || documentSession.value.source_name || 'document',
      result.preview_geojson,
      {
        backendLayerId: result.layer_id,
        featureCount: result.feature_count ?? result.point_count,
      },
    )
    focusImportedLayer(layer.instanceId)
    openDataWorkspace({ tab: 'attributes', layerInstanceId: layer.instanceId })
    const notes: string[] = [`已导入 ${result.point_count} 个点`]
    if (result.xy_swap_applied) {
      notes.push(result.xy_swap_note || '已自动交换 XY')
    } else if (result.xy_swap_note) {
      notes.push(result.xy_swap_note)
    }
    const fieldChanges = result.field_sanitization?.changes
    if (Array.isArray(fieldChanges) && fieldChanges.length) {
      notes.push(`字段规范化 ${fieldChanges.length} 项`)
      showToast(
        `字段名已规范化：${fieldChanges
          .slice(0, 3)
          .map((c) => `${c.original}→${c.sanitized}`)
          .join('；')}`,
      )
    }
    setStatus(notes.join('；'))
    documentSession.value = null
    docSwapXyMode.value = 'auto'
    if (documentQueue.value.length) {
      void startDocument(documentQueue.value[0]!)
    }
  } catch (err) {
    setStatus(err instanceof Error ? err.message : String(err), true)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div
    :class="embedded ? 'import-embedded-root' : 'data-panel-overlay'"
    @click.self="!embedded && emit('close')"
  >
    <div
      class="data-panel"
      :class="{ 'as-embedded': embedded }"
      role="region"
      :aria-label="DATA_COPY.importTitle"
    >
      <header v-if="!embedded" class="data-panel-header">
        <span class="header-title">{{ DATA_COPY.importTitle }}</span>
        <button class="close-btn" type="button" :title="DATA_COPY.close" @click="emit('close')">
          ✕
        </button>
      </header>

      <nav class="data-tabs" role="tablist">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          type="button"
          class="data-tab"
          :class="{ active: activeTab === tab.id }"
          role="tab"
          @click="activeTab = tab.id"
        >
          {{ tab.label }}
        </button>
      </nav>

      <p class="tab-hint">{{ tabs.find((t) => t.id === activeTab)?.hint }}</p>

      <div class="data-panel-body">
        <section v-if="activeTab === 'vector'" class="tab-section">
          <p class="tip">{{ DATA_COPY.vectorSidecarTip }}</p>
          <label class="file-btn">
            {{ DATA_COPY.upload }}
            <input
              type="file"
              multiple
              accept=".shp,.dbf,.shx,.prj,.cpg,.sbn,.sbx,.zip,.rar,.geojson,.json"
              hidden
              @change="onVectorPick"
            />
          </label>
          <ul v-if="vectorFiles.length" class="file-list">
            <li v-for="f in vectorFiles" :key="f.name + f.size">
              {{ f.name }} · {{ formatBytes(f.size) }}
            </li>
          </ul>
          <ul v-if="vectorSidecarStatus.lines.length" class="sidecar-status">
            <li
              v-for="(line, idx) in vectorSidecarStatus.lines"
              :key="idx"
              :class="{ bad: line.startsWith('✗') || line.startsWith('⚠') }"
            >
              {{ line }}
            </li>
          </ul>
          <p v-if="vectorSidecarStatus.errors.length" class="sidecar-warn">
            {{ vectorSidecarStatus.errors[0] }}
          </p>
          <button
            class="primary-btn"
            type="button"
            :disabled="busy || !vectorFiles.length || !vectorSidecarStatus.ok"
            @click="runVectorImport"
          >
            {{ DATA_COPY.commit }}
          </button>
        </section>

        <section v-else-if="activeTab === 'raster'" class="tab-section">
          <label class="file-btn">
            {{ DATA_COPY.upload }}
            <input
              type="file"
              multiple
              accept=".tif,.tiff,.nc,.hdf,.h5,.he5,.mat"
              hidden
              @change="onRasterPick"
            />
          </label>
          <ul v-if="rasterFiles.length" class="file-list">
            <li v-for="f in rasterFiles" :key="f.name">{{ f.name }} · {{ formatBytes(f.size) }}</li>
          </ul>

          <div v-if="rasterFiles.length" class="temporal-block">
            <p class="tip">数据时间（可从文件名自动识别，也可手动指定）</p>
            <div class="temporal-modes">
              <label><input v-model="temporalMode" type="radio" value="auto" /> 自动识别</label>
              <label><input v-model="temporalMode" type="radio" value="static" /> 静态</label>
              <label><input v-model="temporalMode" type="radio" value="point" /> 时间点</label>
              <label><input v-model="temporalMode" type="radio" value="range" /> 时间段</label>
            </div>
            <div v-if="temporalMode === 'point'" class="temporal-fields">
              <label>
                日期
                <input v-model="temporalPoint" type="text" placeholder="YYYYMMDD 或 YYYY-MM-DD" />
              </label>
              <label>
                步长
                <input v-model="temporalNativeStep" type="text" placeholder="1d" />
              </label>
            </div>
            <div v-else-if="temporalMode === 'range'" class="temporal-fields">
              <label>
                起
                <input v-model="temporalStart" type="text" placeholder="YYYYMMDD" />
              </label>
              <label>
                止
                <input v-model="temporalEnd" type="text" placeholder="YYYYMMDD" />
              </label>
              <label>
                步长
                <input v-model="temporalNativeStep" type="text" placeholder="8d" />
              </label>
            </div>
            <p v-if="temporalPreview.preview" class="temporal-preview">
              将写入：{{ temporalPreview.preview.kind }} · {{ temporalPreview.preview.label
              }}{{
                temporalPreview.preview.nativeStep ? ` · ${temporalPreview.preview.nativeStep}` : ''
              }}
            </p>
          </div>

          <button
            v-if="rasterFiles.length > 1 || (rasterFiles.length === 1 && !needsVariable)"
            class="primary-btn"
            type="button"
            :disabled="busy || !rasterFiles.length"
            @click="runRasterBatch"
          >
            {{ DATA_COPY.batchImport }}
          </button>
          <p v-if="rasterFile && needsVariable" class="file-line">
            当前：{{ rasterFile.name }} · {{ formatBytes(rasterFile.size) }}
          </p>
          <div v-if="needsVariable && rasterVariables.length" class="var-block">
            <p class="tip">
              已解析科学栅格（{{
                scienceFormat || 'mat/nc/hdf'
              }}），请在配置对话框中选择变量、坐标系与无效值后再导入。
            </p>
            <button
              class="primary-btn"
              type="button"
              :disabled="busy"
              @click="scienceDialogOpen = true"
            >
              打开导入配置
            </button>
          </div>
        </section>

        <section v-else class="tab-section">
          <label class="file-btn">
            {{ DATA_COPY.upload }}
            <input
              type="file"
              multiple
              accept=".csv,.xlsx,.xls,.txt"
              hidden
              @change="onDocumentPick"
            />
          </label>
          <p v-if="documentQueue.length" class="tip">
            队列剩余 {{ documentQueue.length }} 个文档（当前导入完成后自动打开下一个）
          </p>

          <template v-if="documentSession">
            <div class="ops-grid">
              <label>
                {{ DATA_COPY.renameFrom }}
                <AppSelect
                  v-model="opRenameFrom"
                  :options="[
                    { label: '—', value: '' },
                    ...documentColumns.map((c) => ({ label: c, value: c })),
                  ]"
                />
              </label>
              <label>
                {{ DATA_COPY.renameTo }}
                <input v-model="opRenameTo" type="text" />
              </label>
              <label>
                {{ DATA_COPY.filterField }}
                <AppSelect
                  v-model="opFilterField"
                  :options="[
                    { label: '—', value: '' },
                    ...documentColumns.map((c) => ({ label: c, value: c })),
                  ]"
                />
              </label>
              <label>
                {{ DATA_COPY.filterContains }}
                <input v-model="opFilterContains" type="text" />
              </label>
              <label>
                {{ DATA_COPY.findReplaceField }}
                <AppSelect
                  v-model="opFindField"
                  :options="[
                    { label: '—', value: '' },
                    ...documentColumns.map((c) => ({ label: c, value: c })),
                  ]"
                />
              </label>
              <label>
                {{ DATA_COPY.findText }}
                <input v-model="opFind" type="text" />
              </label>
              <label>
                {{ DATA_COPY.replaceText }}
                <input v-model="opReplace" type="text" />
              </label>
              <label>
                {{ DATA_COPY.splitField }}
                <AppSelect
                  v-model="opSplitField"
                  :options="[
                    { label: '—', value: '' },
                    ...documentColumns.map((c) => ({ label: c, value: c })),
                  ]"
                />
              </label>
              <label>
                {{ DATA_COPY.splitSep }}
                <input v-model="opSplitSep" type="text" />
              </label>
              <label>
                {{ DATA_COPY.splitInto }}
                <input v-model="opSplitInto" type="text" placeholder="col_a,col_b" />
              </label>
            </div>
            <button class="secondary-btn" type="button" :disabled="busy" @click="applyOps">
              {{ DATA_COPY.applyOps }}
            </button>

            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th v-for="c in documentColumns" :key="c">{{ c }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, idx) in documentRows.slice(0, 80)" :key="idx">
                    <td v-for="c in documentColumns" :key="c">{{ row[c] }}</td>
                  </tr>
                </tbody>
              </table>
              <p class="table-meta">
                预览 {{ Math.min(80, documentRows.length) }} / {{ documentSession.row_count }} 行
                <span v-if="documentSession.truncated">（已截断）</span>
              </p>
            </div>

            <div class="commit-row">
              <label>
                {{ DATA_COPY.xField }}
                <AppSelect
                  v-model="xField"
                  :options="documentColumns.map((c) => ({ label: c, value: c }))"
                />
              </label>
              <label>
                {{ DATA_COPY.yField }}
                <AppSelect
                  v-model="yField"
                  :options="documentColumns.map((c) => ({ label: c, value: c }))"
                />
              </label>
              <label>
                {{ DATA_COPY.sourceCrs }}
                <input v-model="sourceCrs" type="text" />
              </label>
              <label>
                交换 XY
                <AppSelect
                  v-model="docSwapXyMode"
                  :options="[
                    { label: '自动检测', value: 'auto' },
                    { label: '强制交换', value: 'force' },
                    { label: '保持不交换', value: 'keep' },
                  ]"
                />
              </label>
              <button class="primary-btn" type="button" :disabled="busy" @click="commitDocument">
                {{ DATA_COPY.commit }}
              </button>
            </div>
            <p class="table-meta">
              地理 CRS 下若经纬度列颠倒，可选用「自动检测」或「强制交换」。Excel
              为二进制格式，不适用文本编码探测。
            </p>
          </template>
        </section>
      </div>

      <footer class="data-panel-footer">
        <div v-if="progress != null" class="progress-bar">
          <div class="progress-fill" :style="{ width: `${Math.round(progress * 100)}%` }" />
        </div>
        <div class="footer-row">
          <div class="footer-msgs">
            <p v-if="errorMsg" class="msg error">{{ errorMsg }}</p>
            <p v-else-if="statusMsg" class="msg">{{ statusMsg }}</p>
            <p v-else-if="busy" class="msg">{{ DATA_COPY.processing }}</p>
          </div>
          <button
            v-if="busy && activeUploadId"
            class="secondary-btn"
            type="button"
            @click="cancelUpload"
          >
            {{ DATA_COPY.cancelUpload }}
          </button>
        </div>
      </footer>
    </div>

    <ScienceRasterImportDialog
      :visible="scienceDialogOpen"
      :file-name="rasterFile?.name || ''"
      :format="scienceFormat"
      :upload-id="rasterUploadId"
      :variables="rasterVariables"
      :grid-presets="scienceGridPresets"
      :suggested-grid-preset="scienceSuggestedPreset"
      :suggested-crs="scienceSuggestedCrs"
      :suggested-needs-transpose="scienceSuggestedNeedsTranspose"
      :importing="busy"
      @confirm="onScienceRasterConfirm"
      @cancel="onScienceRasterCancel"
    />

    <RasterImportConfirmDialog
      v-if="pendingRasterConfirm"
      :visible="true"
      :file-name="pendingRasterConfirm.fileName"
      :detection-result="pendingRasterConfirm.detectionResult"
      :importing="busy"
      @confirm="onRasterConfirm"
      @cancel="pendingRasterConfirm = null"
      @skip="skipRasterConfirm"
    />
  </div>
</template>

<style scoped>
.import-embedded-root {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
}
.data-panel.as-embedded {
  width: 100%;
  max-height: none;
  height: 100%;
  border: none;
  box-shadow: none;
  background: transparent;
  border-radius: 0;
}
.footer-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}
.footer-msgs {
  min-width: 0;
  flex: 1 1 auto;
}
.data-panel-overlay {
  position: fixed;
  inset: 0;
  z-index: 10040;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 3.5vh 1rem 2vh;
  overflow: auto;
  background: rgba(4, 10, 18, 0.55);
}
.data-panel {
  width: min(42rem, calc(100vw - 2rem));
  max-height: min(70vh, 34rem);
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  border-radius: 0.7rem;
  background: rgba(8, 17, 31, 0.98);
  border: 1px solid var(--border-default);
  box-shadow: 0 18px 48px rgba(1, 8, 16, 0.45);
  color: var(--text-primary);
}
.data-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
  flex-shrink: 0;
  padding: 0.62rem 0.8rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.1);
}
.header-title {
  font-size: var(--font-size-caption);
  font-weight: 600;
}
.close-btn {
  flex: none;
  width: 1.7rem;
  height: 1.7rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(136, 192, 255, 0.22);
  border-radius: 0.38rem;
  background: rgba(4, 12, 23, 0.72);
  color: var(--text-primary);
  cursor: pointer;
  font-size: var(--font-size-caption);
  line-height: 1;
}
.close-btn:hover {
  border-color: rgba(90, 213, 255, 0.4);
  color: var(--accent);
}
.data-tabs {
  display: flex;
  gap: 0.3rem;
  flex-shrink: 0;
  padding: 0.48rem 0.8rem 0;
}
.data-tab {
  border: 1px solid rgba(136, 192, 255, 0.12);
  border-radius: 0.42rem;
  padding: 0.28rem 0.62rem;
  background: var(--surface-sunken);
  color: var(--text-secondary);
  cursor: pointer;
  font: inherit;
  font-size: var(--font-size-caption);
}
.data-tab.active {
  color: var(--accent);
  border-color: rgba(90, 213, 255, 0.35);
  background: rgba(10, 132, 255, 0.16);
}
.tab-hint {
  flex-shrink: 0;
  margin: 0.36rem 0.8rem 0;
  font-size: var(--font-size-caption);
  color: #6a8094;
  line-height: 1.4;
}
.data-panel-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 0.55rem 0.8rem 0.35rem;
}
.tab-section {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.tip,
.file-line,
.table-meta {
  margin: 0;
  font-size: var(--font-size-caption);
  color: #8aa0b4;
}
.file-btn,
.primary-btn,
.secondary-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: fit-content;
  border-radius: 0.42rem;
  padding: 0.36rem 0.72rem;
  font: inherit;
  font-size: var(--font-size-caption);
  cursor: pointer;
}
.file-btn,
.secondary-btn {
  border: 1px solid rgba(136, 192, 255, 0.18);
  background: rgba(4, 12, 23, 0.55);
  color: #c5d8ea;
}
.primary-btn {
  border: 1px solid rgba(90, 213, 255, 0.35);
  background: rgba(10, 132, 255, 0.22);
  color: #a8e8ff;
}
.primary-btn:disabled,
.secondary-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.file-list {
  margin: 0;
  padding-left: 1rem;
  font-size: var(--font-size-caption);
  color: #b7c9da;
}
.temporal-block {
  margin: 0.45rem 0 0.55rem;
  padding: 0.5rem 0.55rem;
  border-radius: 0.42rem;
  border: 1px solid rgba(136, 192, 255, 0.12);
  background: rgba(4, 12, 23, 0.42);
}
.temporal-modes {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem 0.8rem;
  margin: 0.3rem 0 0.35rem;
  font-size: var(--font-size-caption);
  color: #c5d7ea;
}
.temporal-modes label {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  cursor: pointer;
}
.temporal-fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(7.2rem, 1fr));
  gap: 0.35rem;
}
.temporal-fields label {
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
  font-size: var(--font-size-caption);
  color: #8aa0b4;
}
.temporal-fields input {
  border: 1px solid rgba(136, 192, 255, 0.18);
  border-radius: 0.35rem;
  background: rgba(2, 10, 18, 0.7);
  color: var(--text-primary);
  padding: 0.26rem 0.38rem;
  font: inherit;
  font-size: var(--font-size-caption);
}
.temporal-preview {
  margin: 0.35rem 0 0;
  font-size: var(--font-size-caption);
  color: #7eb8e0;
}
.sidecar-status {
  margin: 0;
  padding: 0.35rem 0.55rem;
  list-style: none;
  border: 1px solid rgba(136, 192, 255, 0.12);
  border-radius: 0.4rem;
  background: rgba(4, 12, 23, 0.45);
  font-size: var(--font-size-caption);
  color: #9ec4e0;
  font-family: ui-monospace, Consolas, monospace;
}
.sidecar-status .bad {
  color: #ffb0b0;
}
.sidecar-warn {
  margin: 0;
  font-size: var(--font-size-caption);
  color: #ffd166;
  line-height: 1.35;
}
.ops-grid,
.commit-row,
.var-block {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(9.5rem, 1fr));
  gap: 0.4rem;
}
label {
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
  font-size: var(--font-size-caption);
  color: #8aa0b4;
}
input,
select {
  border: 1px solid rgba(136, 192, 255, 0.14);
  border-radius: 0.34rem;
  padding: 0.28rem 0.4rem;
  background: rgba(4, 12, 23, 0.7);
  color: var(--text-primary);
  font: inherit;
  font-size: var(--font-size-caption);
}
.table-wrap {
  overflow: auto;
  max-height: 10rem;
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: 0.4rem;
}
table {
  border-collapse: collapse;
  width: max-content;
  min-width: 100%;
  font-size: var(--font-size-caption);
}
th,
td {
  border-bottom: 1px solid var(--border-subtle);
  padding: 0.22rem 0.4rem;
  text-align: left;
  white-space: nowrap;
}
th {
  position: sticky;
  top: 0;
  background: rgba(10, 20, 34, 0.98);
  color: #9ec4e0;
}
.data-panel-footer {
  flex-shrink: 0;
  padding: 0.45rem 0.8rem 0.6rem;
  border-top: 1px solid rgba(136, 192, 255, 0.1);
}
.progress-bar {
  height: 0.28rem;
  border-radius: 999px;
  background: rgba(136, 192, 255, 0.12);
  overflow: hidden;
  margin-bottom: 0.35rem;
}
.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #0a84ff, var(--accent));
}
.msg {
  margin: 0;
  font-size: var(--font-size-caption);
  color: #9ec4e0;
}
.msg.error {
  color: #ffb0b0;
}
</style>
