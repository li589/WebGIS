/**
 * 导入矢量图层的几何推断 / 导出工具。
 */
import { markRaw } from 'vue'

export type ImportedGeometryType =
  | 'Point'
  | 'LineString'
  | 'Polygon'
  | 'MultiPoint'
  | 'MultiLineString'
  | 'MultiPolygon'
  | 'GeometryCollection'
  | 'Unknown'

export interface ImportedVectorStyle {
  color?: string
  width?: number
  radius?: number
  fillOpacity?: number
}

/**
 * 导入/绘制矢量的默认样式单一真源。
 * 地图渲染（imported-layer-module）与 InfoPanel 样式 Tab 的兜底值必须读这里，
 * 避免两处硬编码漂移导致「面板初值 ≠ 地图实际渲染」。
 * color 以创建图层时解析到的 --success 实色写入（MapLibre paint 不支持 var()）。
 */
export const IMPORTED_VECTOR_STYLE_DEFAULTS: Required<ImportedVectorStyle> = {
  color: '#9ff8cf',
  width: 2,
  radius: 4,
  fillOpacity: 0.25,
}

/** 解析当前主题下的 --success 实色（无 DOM 环境时退回常量），供默认色写入 payload 与面板兜底共用 */
export function resolveImportedVectorDefaultColor(): string {
  if (typeof document === 'undefined') return IMPORTED_VECTOR_STYLE_DEFAULTS.color
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--success')
  const value = raw.trim()
  return value || IMPORTED_VECTOR_STYLE_DEFAULTS.color
}

export interface ImportedVectorPayload {
  /**
   * 图层 GeoJSON（D-4：markRaw 非深响应式——80MB 导入的百万级
   * features/coordinates 不再逐个建 Proxy）。更新必须**整体替换引用**
   * （走 `updateImportedVectorGeojson`，revision 自增驱动地图 watcher），
   * 严禁就地修改内部（静默不触发 UI 更新）。
   */
  geojson: GeoJSON.FeatureCollection
  geometryType: ImportedGeometryType
  featureCount: number
  bounds?: [number, number, number, number]
  /** 原始文件名（含扩展名），用于导出命名 */
  fileName?: string
  /** 后端统一导入登记的 layer_id（用于 /export/layer） */
  backendLayerId?: string
  /** 导入时后端是否截断预览 */
  truncated?: boolean
  /** geojson 替换次数：驱动地图 watcher 检测同 featureCount 下的数据变更 */
  revision?: number
  /** 用户自定义矢量样式 */
  style?: ImportedVectorStyle
}

export function inferGeometryType(fc: GeoJSON.FeatureCollection): ImportedGeometryType {
  for (const f of fc.features) {
    if (f.geometry) return f.geometry.type as ImportedGeometryType
  }
  return 'Unknown'
}

export function computeBounds(
  fc: GeoJSON.FeatureCollection,
): [number, number, number, number] | undefined {
  let minLng = Infinity,
    minLat = Infinity,
    maxLng = -Infinity,
    maxLat = -Infinity
  let hasCoord = false
  for (const f of fc.features) {
    if (!f.geometry) continue
    const coords = flattenCoords(f.geometry)
    for (let i = 0; i < coords.length; i += 2) {
      const lng = coords[i]
      const lat = coords[i + 1]
      if (!Number.isFinite(lng) || !Number.isFinite(lat)) continue
      hasCoord = true
      if (lng < minLng) minLng = lng
      if (lat < minLat) minLat = lat
      if (lng > maxLng) maxLng = lng
      if (lat > maxLat) maxLat = lat
    }
  }
  if (!hasCoord) return undefined
  return [minLng, minLat, maxLng, maxLat]
}

function flattenCoords(geom: GeoJSON.Geometry): number[] {
  const out: number[] = []
  function walk(arr: unknown) {
    if (typeof arr === 'number') {
      out.push(arr)
      return
    }
    if (Array.isArray(arr)) {
      for (const item of arr) walk(item)
    }
  }
  if (geom.type === 'GeometryCollection') {
    for (const child of geom.geometries) {
      out.push(...flattenCoords(child))
    }
    return out
  }
  walk(geom.coordinates)
  return out
}

export function buildImportedVectorPayload(
  geojson: GeoJSON.FeatureCollection,
  fileName?: string,
  options?: { backendLayerId?: string; featureCount?: number },
): ImportedVectorPayload {
  return {
    // D-4：markRaw 豁免深响应式——大 GeoJSON 不进 proxy 树
    geojson: markRaw(geojson),
    geometryType: inferGeometryType(geojson),
    featureCount: options?.featureCount ?? geojson.features.length,
    bounds: computeBounds(geojson),
    fileName,
    backendLayerId: options?.backendLayerId,
    // 创建图层即写实默认样式：地图渲染与面板初值天然一致
    style: {
      ...IMPORTED_VECTOR_STYLE_DEFAULTS,
      color: resolveImportedVectorDefaultColor(),
    },
  }
}

function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export function exportFeatureCollectionAsGeoJson(fc: GeoJSON.FeatureCollection, baseName: string) {
  const safe = baseName.replace(/\.(geojson|json|shp|zip|csv)$/i, '') || 'export'
  const blob = new Blob([JSON.stringify(fc, null, 2)], { type: 'application/geo+json' })
  downloadBlob(`${safe}.geojson`, blob)
}

/** 将要素属性导出为 CSV；点要素附带 lon/lat 列 */
export function exportFeatureCollectionAsCsv(fc: GeoJSON.FeatureCollection, baseName: string) {
  const safe = baseName.replace(/\.(geojson|json|shp|zip|csv)$/i, '') || 'export'
  const propKeys = new Set<string>()
  for (const f of fc.features) {
    const props = f.properties
    if (props && typeof props === 'object') {
      for (const key of Object.keys(props)) propKeys.add(key)
    }
  }
  const keys = Array.from(propKeys)
  const hasPoint = fc.features.some(
    (f) => f.geometry?.type === 'Point' || f.geometry?.type === 'MultiPoint',
  )
  const header = [...(hasPoint ? ['lon', 'lat'] : []), ...keys]

  const escapeCell = (value: unknown) => {
    let text = value == null ? '' : String(value)
    // 防止 Excel/LibreOffice 把公式当代码执行（CSV injection）
    if (/^[=+\-@\t\r]/.test(text)) {
      text = `'${text}`
    }
    if (/[",\n\r]/.test(text)) return `"${text.replace(/"/g, '""')}"`
    return text
  }

  const rows = [header.join(',')]
  for (const f of fc.features) {
    const cells: string[] = []
    if (hasPoint) {
      if (f.geometry?.type === 'Point') {
        cells.push(escapeCell(f.geometry.coordinates[0]), escapeCell(f.geometry.coordinates[1]))
      } else {
        cells.push('', '')
      }
    }
    const props = (f.properties ?? {}) as Record<string, unknown>
    for (const key of keys) {
      cells.push(escapeCell(props[key]))
    }
    rows.push(cells.join(','))
  }

  const blob = new Blob([`\uFEFF${rows.join('\n')}`], { type: 'text/csv;charset=utf-8' })
  downloadBlob(`${safe}.csv`, blob)
}
