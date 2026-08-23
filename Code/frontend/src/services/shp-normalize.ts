/**
 * SHP/ZIP 解析结果的规范化（共享纯函数）。
 *
 * 从 data-import.ts 抽出（2026-08-23 shpjs Worker 化）：主线程与
 * shp-parse.worker 共用，避免 worker → data-import → worker URL 的
 * 循环依赖。data-import.ts re-export 保持既有导入路径兼容。
 */
import type GeoJSON from 'geojson'

export function normalizeShpResult(result: unknown): {
  geojson: GeoJSON.FeatureCollection
  layerCount: number
} {
  if (Array.isArray(result)) {
    const collections = result.filter((item): item is GeoJSON.FeatureCollection =>
      Boolean(
        item &&
        typeof item === 'object' &&
        Array.isArray((item as GeoJSON.FeatureCollection).features),
      ),
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
  if (
    result &&
    typeof result === 'object' &&
    Array.isArray((result as GeoJSON.FeatureCollection).features)
  ) {
    return { layerCount: 1, geojson: result as GeoJSON.FeatureCollection }
  }
  if (result && typeof result === 'object') {
    const collections = Object.entries(result as Record<string, unknown>)
      .filter(
        ([key, value]) =>
          !key.endsWith('_null') &&
          Boolean(
            value &&
            typeof value === 'object' &&
            Array.isArray((value as GeoJSON.FeatureCollection).features),
          ),
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
