/**
 * Cesium 底图适配：复用前端 TileSourceConfig（经 /unified-tiles 同源代理）。
 * 与 MapLibre basemap-module 同一 URL 模板，后续可再接故障转移。
 */
import { TILE_SOURCE_MAP, type TileSourceId } from '../../../../services/api-config'

export interface CesiumBasemapSpec {
  /** 主影像 URL 模板（{z}/{x}/{y}）；null 表示空白球 */
  urlTemplate: string | null
  /** 注记叠加（如天地图 cva） */
  overlayUrlTemplate: string | null
  maximumLevel: number
  credit: string
}

/** 将应用底图源解析为 Cesium UrlTemplate 规格。 */
export function resolveCesiumBasemap(sourceId: TileSourceId): CesiumBasemapSpec {
  if (sourceId === 'none') {
    return {
      urlTemplate: null,
      overlayUrlTemplate: null,
      maximumLevel: 0,
      credit: '',
    }
  }
  const cfg = TILE_SOURCE_MAP.get(sourceId)
  if (!cfg?.urlTemplate) {
    // 未知源：退回 OSM 标准代理路径（若存在）或空
    const osm = TILE_SOURCE_MAP.get('osm-standard')
    return {
      urlTemplate: osm?.urlTemplate ?? null,
      overlayUrlTemplate: null,
      maximumLevel: 18,
      credit: osm?.attribution ?? '© OpenStreetMap',
    }
  }
  return {
    urlTemplate: cfg.urlTemplate,
    overlayUrlTemplate: cfg.overlayUrlTemplate ?? null,
    maximumLevel: 18,
    credit: cfg.attribution ?? cfg.label,
  }
}

/**
 * Cesium UrlTemplate 使用 {z}/{x}/{y}；部分模板可能带 {s} subdomain。
 * Cesium 不展开 {s}，去掉 subdomain 占位以免请求失败。
 */
export function normalizeCesiumTileUrl(template: string): string {
  return template
    .replace(/\{s\}\./g, '')
    .replace(/\/\{s\}\//g, '/')
    .replace(/\{s\}/g, '')
}
