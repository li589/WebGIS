/**
 * 统一图层导出入口（侧栏 / InfoPanel / 导出面板共用）。
 */
import type { ActiveLayer } from '../../stores/layers/types'
import { resolveApiUrl } from '../../services/_http'
import { withWriteAuthHeaders } from '../../services/backend-auth'
import { downloadBlob, exportImportedLayer, exportBatchLayers, waitForImportJob } from '../core/api'
import {
  exportFeatureCollectionAsCsv,
  exportFeatureCollectionAsGeoJson,
} from '../../stores/layers/imported-vector'

export type ExportFormat =
  'geojson' | 'csv' | 'shp-zip' | 'tif' | 'png' | 'nc' | 'geotiff' | 'netcdf'

export type ExportOptions = {
  /** auto | utf-8 | utf-8-sig | gbk | gb18030 | … */
  encoding?: string
}

function normalizeFormat(format: string): ExportFormat {
  const f = format.toLowerCase()
  if (f === 'geotiff' || f === 'tiff') return 'tif'
  if (f === 'netcdf') return 'nc'
  return f as ExportFormat
}

function safeName(name: string, ext: string): string {
  const base =
    (name || 'export')
      .replace(
        /\.(geojson|json|shp|zip|rar|csv|xlsx|xls|txt|dbf|shx|prj|cpg|sbn|sbx|qix|tif|tiff|png|nc)$/i,
        '',
      )
      .replace(/[\\/:*?"<>|]+/g, '_')
      .trim() || 'export'
  return base.toLowerCase().endsWith(`.${ext}`) ? base : `${base}.${ext}`
}

function backendIdOf(
  layer: Pick<ActiveLayer, 'importedVector' | 'importedRaster' | 'catalogId'>,
): string | null {
  return layer.importedVector?.backendLayerId || layer.importedRaster?.overlayLayerId || null
}

async function exportLocalFallback(
  layer: Pick<ActiveLayer, 'name' | 'importedVector'>,
  format: ExportFormat,
): Promise<void> {
  const fc = layer.importedVector?.geojson
  if (!fc?.features?.length) {
    throw new Error('本地预览为空，无法导出（可尝试重新导入或先「加载完整数据」）')
  }
  if (format === 'csv') {
    exportFeatureCollectionAsCsv(fc, safeName(layer.name ?? 'export', 'csv'))
    return
  }
  // shp-zip 无本地实现时降级 geojson
  exportFeatureCollectionAsGeoJson(fc, safeName(layer.name ?? 'export', 'geojson'))
}

export async function exportLayer(
  layer: Pick<ActiveLayer, 'name' | 'importedVector' | 'importedRaster' | 'catalogId'>,
  format: ExportFormat,
  options: ExportOptions = {},
): Promise<void> {
  const fmt = normalizeFormat(format)
  const encoding = options.encoding || 'auto'
  const backendId = backendIdOf(layer)

  if (backendId) {
    try {
      const blob = await exportImportedLayer(backendId, fmt, encoding)
      const ext =
        fmt === 'shp-zip' ? 'zip' : fmt === 'geojson' ? 'geojson' : fmt === 'csv' ? 'csv' : fmt
      downloadBlob(blob, safeName(layer.name ?? 'export', ext))
      return
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      if (layer.importedVector && /404|不存在|not found/i.test(msg)) {
        if (fmt === 'geojson' || fmt === 'csv' || fmt === 'shp-zip') {
          await exportLocalFallback(layer, fmt)
          return
        }
      }
      throw err instanceof Error ? err : new Error(msg)
    }
  }

  if (layer.importedVector) {
    if (fmt === 'csv' || fmt === 'geojson' || fmt === 'shp-zip') {
      await exportLocalFallback(layer, fmt)
      return
    }
  }
  throw new Error('该图层无可导出数据（缺少后端图层或本地预览）')
}

export async function exportLayersBatch(
  layers: Array<Pick<ActiveLayer, 'name' | 'importedVector' | 'importedRaster' | 'catalogId'>>,
  format: ExportFormat,
  onProgress?: (p: number, msg: string) => void,
  options: ExportOptions = {},
): Promise<void> {
  const fmt = normalizeFormat(format)
  const encoding = options.encoding || 'auto'
  const ids = layers.map((l) => backendIdOf(l)).filter((id): id is string => Boolean(id))
  if (!ids.length) {
    for (const layer of layers) {
      await exportLayer(layer, fmt === 'shp-zip' ? 'geojson' : fmt, options)
    }
    return
  }
  onProgress?.(0.05, '提交批导出…')
  try {
    const result = await exportBatchLayers(ids, fmt, encoding)
    if (result.job_id) {
      const job = await waitForImportJob(result.job_id, {
        onProgress: (p, msg) => onProgress?.(p, msg ?? '导出中…'),
      })
      if (job.download_url) {
        const res = await fetch(resolveApiUrl(job.download_url), {
          headers: withWriteAuthHeaders({}, 'GET'),
        })
        if (!res.ok) throw new Error(`下载批导出失败: HTTP ${res.status}`)
        const blob = await res.blob()
        downloadBlob(blob, safeName('batch_export', 'zip'))
        return
      }
    }
    if (result.blob) {
      downloadBlob(result.blob, safeName('batch_export', 'zip'))
      return
    }
    throw new Error('批导出未返回文件')
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    if (/404|不存在|not found/i.test(msg)) {
      onProgress?.(0.2, '批导出不可用，改为逐层导出…')
      for (let i = 0; i < layers.length; i++) {
        await exportLayer(layers[i]!, fmt === 'shp-zip' ? 'geojson' : fmt, options)
        onProgress?.((i + 1) / layers.length, `已导出 ${i + 1}/${layers.length}`)
      }
      return
    }
    throw err instanceof Error ? err : new Error(msg)
  }
}
