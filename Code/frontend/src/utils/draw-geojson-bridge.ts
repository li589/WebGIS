import type { DrawFeature } from '../stores/draw-store'

/** GeoJSON 面要素 → 绘制 store 可用的 Polygon / LineString 要素列表 */
export function geojsonToDrawFeatures(
  geojson: GeoJSON.FeatureCollection | null | undefined,
): DrawFeature[] {
  if (!geojson?.features?.length) return []
  const out: DrawFeature[] = []
  for (const feature of geojson.features) {
    if (!feature.geometry) continue
    const props = (feature.properties ?? {}) as Record<string, unknown>
    if (feature.geometry.type === 'Polygon') {
      out.push({ geometry: feature.geometry, properties: { ...props } })
    } else if (feature.geometry.type === 'MultiPolygon') {
      for (const ringSet of feature.geometry.coordinates) {
        out.push({
          geometry: { type: 'Polygon', coordinates: ringSet },
          properties: { ...props },
        })
      }
    } else if (feature.geometry.type === 'LineString') {
      out.push({ geometry: feature.geometry, properties: { ...props } })
    }
  }
  return out
}

export function isPolygonEditableLayer(geometryType: string | undefined): boolean {
  return geometryType === 'Polygon' || geometryType === 'MultiPolygon'
}
