/**
 * 统一图层导出入口（侧栏 / InfoPanel / 导出面板共用）。
 */
import type { ActiveLayer } from '../../stores/layers/types'
import { applyApiFetchDefaults } from '../../services/http-credentials'
import { resolveApiUrl } from '../../services/_http'
import { withWriteAuthHeaders } from '../../services/backend-auth'
import {
  downloadBlob,
  exportImportedLayer,
  exportBatchLayers,
  waitForImportJob,
  type ExportBBoxPayload,
} from '../core/api'
import {
  exportFeatureCollectionAsCsv,
  exportFeatureCollectionAsGeoJson,
} from '../../stores/layers/imported-vector'
import { resolveExportBasename } from '../../stores/layers/layer-naming'

export type ExportFormat =
  'geojson' | 'csv' | 'shp-zip' | 'tif' | 'png' | 'nc' | 'mat' | 'geotiff' | 'netcdf' | 'matlab'

export type ExportOptions = {
  /** auto | utf-8 | utf-8-sig | gbk | gb18030 | … */
  encoding?: string
  /** 单时刻切片，如 20251227_20251231；写入文件名 */
  time?: string | null
  /** 多时刻；长度>1 时后端返回 zip */
  times?: string[] | null
  /** 裁剪到地图/指定范围 */
  bbox?: ExportBBoxPayload | null
  /** 输出坐标系，如 EPSG:4326 */
  outputCrs?: string | null
  /** 矢量属性字段子集 */
  fields?: string[] | null
}

function normalizeFormat(format: string): ExportFormat {
  const f = format.toLowerCase()
  if (f === 'geotiff' || f === 'tiff') return 'tif'
  if (f === 'netcdf') return 'nc'
  if (f === 'matlab') return 'mat'
  return f as ExportFormat
}

function safeName(name: string, ext: string, time?: string | null): string {
  let base =
    (name || 'export')
      .replace(
        /\.(geojson|json|shp|zip|rar|csv|xlsx|xls|txt|dbf|shx|prj|cpg|sbn|sbx|qix|tif|tiff|png|nc|mat)$/i,
        '',
      )
      .replace(/[\\/:*?"<>|]+/g, '_')
      .trim() || 'export'
  if (time) {
    const t = String(time).replace(/[\\/:*?"<>|]+/g, '_')
    if (!base.includes(t)) base = `${base}_${t}`
  }
  return base.toLowerCase().endsWith(`.${ext}`) ? base : `${base}.${ext}`
}

function backendIdOf(
  layer: Pick<ActiveLayer, 'importedVector' | 'importedRaster' | 'catalogId'>,
): string | null {
  return layer.importedVector?.backendLayerId || layer.importedRaster?.overlayLayerId || null
}

function exportBasenameFor(
  layer: Pick<ActiveLayer, 'name' | 'importedVector' | 'importedRaster' | 'catalogId'>,
): string {
  return resolveExportBasename({
    catalogId: layer.catalogId,
    overlayLayerId: layer.importedRaster?.overlayLayerId,
    backendLayerId: layer.importedVector?.backendLayerId,
    sourceFilename: layer.importedVector?.fileName ?? layer.importedRaster?.fileName,
    displayName: layer.name,
  })
}

async function exportLocalFallback(
  layer: Pick<ActiveLayer, 'name' | 'importedVector' | 'importedRaster' | 'catalogId'>,
  format: ExportFormat,
): Promise<void> {
  const fc = layer.importedVector?.geojson
  if (!fc?.features?.length) {
    if (layer.catalogId.startsWith('draw-draft-')) {
      throw new Error(
        '当前为绘制草稿且尚无已保存数据：请先在绘制工具栏点「保存」生成正式图层后再导出，或先绘制要素',
      )
    }
    throw new Error('本地预览为空，无法导出（可尝试重新导入或先「加载完整数据」）')
  }
  const base = exportBasenameFor(layer)
  if (format === 'csv') {
    exportFeatureCollectionAsCsv(fc, safeName(base, 'csv'))
    return
  }
  // shp-zip 无本地实现时降级 geojson
  exportFeatureCollectionAsGeoJson(fc, safeName(base, 'geojson'))
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
      const multi = options.times?.filter(Boolean) ?? []
      const blob = await exportImportedLayer(backendId, fmt, {
        encoding,
        time: multi.length > 1 ? null : options.time,
        times: multi.length > 1 ? multi : null,
        bbox: options.bbox,
        outputCrs: options.outputCrs,
        fields: options.fields,
      })
      const isZip =
        multi.length > 1 ||
        blob.type.includes('zip') ||
        (typeof blob.type === 'string' && blob.type === 'application/zip')
      const ext = isZip
        ? 'zip'
        : fmt === 'shp-zip'
          ? 'zip'
          : fmt === 'geojson'
            ? 'geojson'
            : fmt === 'csv'
              ? 'csv'
              : fmt
      const stamp =
        multi.length > 1
          ? multi.length > 3
            ? `${multi.length}times`
            : `${multi[0]}_${multi[multi.length - 1]}`
          : options.time
      downloadBlob(blob, safeName(exportBasenameFor(layer), ext, stamp))
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
    const result = await exportBatchLayers(ids, fmt, {
      encoding,
      time: options.time,
      times: options.times,
      bbox: options.bbox,
      outputCrs: options.outputCrs,
      fields: options.fields,
    })
    if (result.job_id) {
      const job = await waitForImportJob(result.job_id, {
        onProgress: (p, msg) => onProgress?.(p, msg ?? '导出中…'),
      })
      if (job.download_url) {
        const res = await fetch(
          resolveApiUrl(job.download_url),
          applyApiFetchDefaults({ headers: withWriteAuthHeaders({}, 'GET') }),
        )
        if (!res.ok) throw new Error(`下载批导出失败: HTTP ${res.status}`)
        const blob = await res.blob()
        downloadBlob(blob, safeName('batch_export', 'zip'))
        return
      }
    }
    if (result.blob) {
      // 同网格多图层 MAT 合并为单 .mat；网格不一致时后端仍返回 zip
      const ext =
        result.blob.type.includes('matlab') || (fmt === 'mat' && !result.blob.type.includes('zip'))
          ? 'mat'
          : 'zip'
      downloadBlob(result.blob, safeName('batch_export', ext))
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
