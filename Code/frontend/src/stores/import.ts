import { ref } from 'vue'
import { defineStore } from 'pinia'
import { useLogStore } from './log'

export type ImportedLayerType = 'vector' | 'raster'

export type ImportedGeometryType =
  | 'Point'
  | 'LineString'
  | 'Polygon'
  | 'MultiPoint'
  | 'MultiLineString'
  | 'MultiPolygon'
  | 'GeometryCollection'
  | 'Unknown'

export interface ImportedLayer {
  id: string
  name: string
  type: ImportedLayerType
  geojson?: GeoJSON.FeatureCollection
  overlayLayerId?: string
  visible: boolean
  opacity: number
  geometryType?: ImportedGeometryType
  featureCount?: number
  bounds?: [number, number, number, number]
  addedAt: number
}

function inferGeometryType(fc: GeoJSON.FeatureCollection): ImportedGeometryType {
  for (const f of fc.features) {
    if (f.geometry) return f.geometry.type as ImportedGeometryType
  }
  return 'Unknown'
}

function computeBounds(fc: GeoJSON.FeatureCollection): [number, number, number, number] | undefined {
  let minLng = Infinity, minLat = Infinity, maxLng = -Infinity, maxLat = -Infinity
  let hasCoord = false
  for (const f of fc.features) {
    if (!f.geometry) continue
    const coords = _flattenCoords(f.geometry)
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

function _flattenCoords(geom: GeoJSON.Geometry): number[] {
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
      out.push(..._flattenCoords(child))
    }
    return out
  }
  walk(geom.coordinates)
  return out
}

export const useImportStore = defineStore('import', () => {
  const importedLayers = ref<ImportedLayer[]>([])
  let counter = 0

  function _genId(): string {
    counter += 1
    return `imported-${Date.now()}-${counter}`
  }

  function addVectorLayer(name: string, geojson: GeoJSON.FeatureCollection): ImportedLayer {
    const logStore = useLogStore()
    const geometryType = inferGeometryType(geojson)
    const bounds = computeBounds(geojson)
    const layer: ImportedLayer = {
      id: _genId(),
      name,
      type: 'vector',
      geojson,
      visible: true,
      opacity: 0.85,
      geometryType,
      featureCount: geojson.features.length,
      bounds,
      addedAt: Date.now(),
    }
    importedLayers.value.push(layer)
    logStore.logOperation(
      'import-vector',
      `导入矢量图层「${name}」`,
      `类型: ${geometryType}, 要素数: ${geojson.features.length}`,
    )
    return layer
  }

  function addRasterLayer(name: string, overlayLayerId: string, bounds?: [number, number, number, number]): ImportedLayer {
    const logStore = useLogStore()
    const layer: ImportedLayer = {
      id: _genId(),
      name,
      type: 'raster',
      overlayLayerId,
      visible: true,
      opacity: 0.7,
      bounds,
      addedAt: Date.now(),
    }
    importedLayers.value.push(layer)
    logStore.logOperation(
      'import-raster',
      `导入栅格图层「${name}」`,
      `Overlay ID: ${overlayLayerId}`,
    )
    return layer
  }

  function removeLayer(id: string) {
    const logStore = useLogStore()
    const layer = importedLayers.value.find((l) => l.id === id)
    if (!layer) return
    importedLayers.value = importedLayers.value.filter((l) => l.id !== id)
    logStore.logOperation('import-remove', `移除导入图层「${layer.name}」`)
  }

  function toggleVisibility(id: string) {
    const layer = importedLayers.value.find((l) => l.id === id)
    if (!layer) return
    layer.visible = !layer.visible
  }

  function setVisibility(id: string, visible: boolean) {
    const layer = importedLayers.value.find((l) => l.id === id)
    if (!layer) return
    layer.visible = visible
  }

  function setOpacity(id: string, opacity: number) {
    const layer = importedLayers.value.find((l) => l.id === id)
    if (!layer) return
    layer.opacity = opacity
  }

  function renameLayer(id: string, name: string) {
    const layer = importedLayers.value.find((l) => l.id === id)
    if (!layer) return
    layer.name = name
  }

  return {
    importedLayers,
    addVectorLayer,
    addRasterLayer,
    removeLayer,
    toggleVisibility,
    setVisibility,
    setOpacity,
    renameLayer,
  }
})
