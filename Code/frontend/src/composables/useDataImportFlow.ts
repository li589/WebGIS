/**
 * Shared import flow for toolbar menu + map drag-drop.
 */
import { ref } from 'vue'
import { useLayersStore } from '../stores/layers'
import { useLogStore } from '../stores/log'
import {
  classifyImportFile,
  confirmRasterImport,
  deleteImportedRaster,
  formatBytes,
  parseVectorFile,
  uploadRasterFile,
  validateImportFile,
  type RasterImportResult,
} from '../services/data-import'

const csvFile = ref<File | null>(null)
const importing = ref(false)
const importMsg = ref('')
const importError = ref(false)
const uploadProgress = ref<number | null>(null)
const dropActive = ref(false)

/** 当 /import/raster 返回 needs_confirm=true 时，暂存检测结果以触发 RasterImportConfirmDialog */
const pendingRasterConfirm = ref<{
  layerId: string
  fileName: string
  detectionResult: RasterImportResult
} | null>(null)

let toastTimer: ReturnType<typeof setTimeout> | null = null

function showToast(message: string, isError = false, ms = 4200) {
  importMsg.value = message
  importError.value = isError
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    importMsg.value = ''
    importError.value = false
    toastTimer = null
  }, ms)
}

export function useDataImportFlow() {
  const layersStore = useLayersStore()
  const logStore = useLogStore()

  async function importVectorFile(file: File) {
    importing.value = true
    uploadProgress.value = null
    showToast(`正在解析矢量: ${file.name}…`, false, 60_000)
    try {
      const { geojson, multiLayerNote } = await parseVectorFile(file)
      layersStore.addImportedVectorLayer(file.name, geojson)
      showToast(
        `${multiLayerNote}已导入 ${geojson.features.length} 个要素（${formatBytes(file.size)}）`,
      )
      logStore.logOperation(
        'import-vector-success',
        `矢量导入成功: ${file.name}`,
        `要素数: ${geojson.features.length}`,
      )
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      showToast(`导入失败: ${msg}`, true)
      logStore.logOperation('import-vector-fail', `矢量导入失败: ${file.name}`, msg)
    } finally {
      importing.value = false
    }
  }

  function openCsvDialog(file: File) {
    try {
      validateImportFile(file, 'csv')
      csvFile.value = file
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      showToast(`导入失败: ${msg}`, true)
      logStore.logOperation('import-csv-fail', `CSV 打开失败: ${file.name}`, msg)
    }
  }

  function closeCsvDialog() {
    csvFile.value = null
  }

  function confirmCsvImport(geojson: GeoJSON.FeatureCollection, name: string) {
    layersStore.addImportedVectorLayer(name, geojson)
    csvFile.value = null
    showToast(`CSV 已导入 ${geojson.features.length} 个点`)
    logStore.logOperation(
      'import-csv-success',
      `CSV 导入成功: ${name}`,
      `要素数: ${geojson.features.length}`,
    )
  }

  async function importRasterFile(file: File) {
    importing.value = true
    uploadProgress.value = 0
    showToast(`正在上传栅格: ${file.name}…`, false, 120_000)
    try {
      const data = await uploadRasterFile(file, {
        onProgress: (ratio) => {
          uploadProgress.value = ratio
          showToast(`上传中 ${Math.round(ratio * 100)}% · ${file.name}`, false, 120_000)
        },
      })

      // CRS 确认分流：
      // - needs_confirm=false（WGS84 等价系）：直接加入图层列表
      // - needs_confirm=true（非 WGS84 等价系）：暂存到 pendingRasterConfirm 触发弹窗
      if (data.needs_confirm) {
        pendingRasterConfirm.value = {
          layerId: data.layer_id,
          fileName: file.name,
          detectionResult: data,
        }
        showToast(`栅格已上传，请确认坐标系：${file.name}`, false, 120_000)
        logStore.logOperation(
          'import-raster-pending',
          `栅格等待 CRS 确认: ${file.name}`,
          `Layer ID: ${data.layer_id}, source_crs: ${data.source_crs ?? '?'}`,
        )
      } else {
        layersStore.addImportedRasterLayer(file.name, data.layer_id, data.bounds, {
          sourceCrs: data.source_crs,
        })
        showToast(`栅格已导入图层列表（${formatBytes(file.size)}）`)
        logStore.logOperation(
          'import-raster-success',
          `栅格导入成功: ${file.name}`,
          `Layer ID: ${data.layer_id}, crs: ${data.source_crs ?? 'EPSG:4326'}`,
        )
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      showToast(`导入失败: ${msg}`, true, 6000)
      logStore.logOperation('import-raster-fail', `栅格导入失败: ${file.name}`, msg)
    } finally {
      importing.value = false
      uploadProgress.value = null
    }
  }

  /** 用户在 RasterImportConfirmDialog 点击「确认转换」 */
  async function confirmRasterCrs(payload: {
    sourceCrs: string
    lngOffset: number
    latOffset: number
  }) {
    const pending = pendingRasterConfirm.value
    if (!pending) return
    const { layerId, fileName } = pending
    importing.value = true
    try {
      const result = await confirmRasterImport({
        layerId,
        sourceCrs: payload.sourceCrs,
        lngOffset: payload.lngOffset,
        latOffset: payload.latOffset,
      })
      layersStore.addImportedRasterLayer(fileName, layerId, result.bounds, {
        sourceCrs: payload.sourceCrs,
        lngOffset: payload.lngOffset,
        latOffset: payload.latOffset,
      })
      showToast(`栅格已重投影并导入：${fileName}`)
      logStore.logOperation(
        'import-raster-success',
        `栅格确认导入成功: ${fileName}`,
        `Layer ID: ${layerId}, source: ${payload.sourceCrs} → WGS84, offset: (${payload.lngOffset}, ${payload.latOffset})`,
      )
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      showToast(`CRS 确认失败：${msg}`, true, 6000)
      logStore.logOperation('import-raster-confirm-fail', `栅格 CRS 确认失败: ${fileName}`, msg)
      // 失败时清理后端临时文件
      await deleteImportedRaster(layerId).catch(() => {})
    } finally {
      pendingRasterConfirm.value = null
      importing.value = false
    }
  }

  /** 用户在 RasterImportConfirmDialog 点击「跳过（用建议值）」 */
  async function skipRasterConfirm() {
    const pending = pendingRasterConfirm.value
    if (!pending) return
    const { layerId, fileName, detectionResult } = pending
    const suggestedCrs = detectionResult.suggested_crs ?? 'EPSG:4326'
    importing.value = true
    try {
      const result = await confirmRasterImport({
        layerId,
        sourceCrs: suggestedCrs,
        lngOffset: 0,
        latOffset: 0,
      })
      layersStore.addImportedRasterLayer(fileName, layerId, result.bounds, {
        sourceCrs: suggestedCrs,
      })
      showToast(`栅格已用建议 CRS 导入：${fileName}`)
      logStore.logOperation(
        'import-raster-success',
        `栅格跳过确认导入成功: ${fileName}`,
        `Layer ID: ${layerId}, used suggested CRS: ${suggestedCrs}`,
      )
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      showToast(`CRS 确认失败：${msg}`, true, 6000)
      logStore.logOperation('import-raster-confirm-fail', `栅格 CRS 跳过失败: ${fileName}`, msg)
      await deleteImportedRaster(layerId).catch(() => {})
    } finally {
      pendingRasterConfirm.value = null
      importing.value = false
    }
  }

  /** 用户在 RasterImportConfirmDialog 点击「取消」 */
  async function cancelRasterConfirm() {
    // 守卫：confirmRasterCrs / skipRasterConfirm 的 await 进行中时禁止取消，
    // 否则 cancel 删除后端文件 → confirm 的 await 返回 → 用 stale layerId 注册 overlay → 死链。
    // Dialog 层已通过 :disabled="importing" 禁用按钮，此处为双重防御。
    if (importing.value) return
    const pending = pendingRasterConfirm.value
    if (!pending) return
    const { layerId, fileName } = pending
    // 清理后端临时文件
    await deleteImportedRaster(layerId).catch(() => {})
    pendingRasterConfirm.value = null
    showToast(`已取消栅格导入：${fileName}`)
    logStore.logOperation(
      'import-raster-cancel',
      `栅格导入已取消: ${fileName}`,
      `Layer ID: ${layerId} 已清理`,
    )
  }

  async function processFiles(fileList: FileList | File[] | null | undefined) {
    const files = Array.from(fileList ?? []).filter(Boolean)
    if (!files.length) return

    for (const file of files) {
      const kind = classifyImportFile(file)
      if (kind === 'vector') {
        await importVectorFile(file)
      } else if (kind === 'csv') {
        openCsvDialog(file)
        break
      } else if (kind === 'raster') {
        await importRasterFile(file)
      } else {
        showToast(`跳过不支持的文件: ${file.name}`, true)
        logStore.logOperation('import-skip', `跳过: ${file.name}`, 'unsupported')
      }
    }
  }

  return {
    csvFile,
    importing,
    importMsg,
    importError,
    uploadProgress,
    dropActive,
    pendingRasterConfirm,
    showToast,
    importVectorFile,
    openCsvDialog,
    closeCsvDialog,
    confirmCsvImport,
    importRasterFile,
    confirmRasterCrs,
    skipRasterConfirm,
    cancelRasterConfirm,
    processFiles,
  }
}
