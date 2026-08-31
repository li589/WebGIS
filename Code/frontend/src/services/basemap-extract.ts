/**
 * 底图要素提取服务。
 *
 * 所有底图均为栅格瓦片（无 vector source），无法 queryRenderedFeatures，
 * 故「底图要素提取」走两条替代链路：
 * - 行政区：本地行政区边界 GeoJSON（@datapool/guangdong.geojson）+ 点包含判断
 * - 道路：当前视口 bbox + OSM Overpass API（需外部网络）
 * 提取结果经 /import/vector 登记后端，再注册为前端矢量图层（可持久化）。
 */
import { importVectorMultipart } from '../data-manager/core/api'
import { registerImportedVectorLayer } from '../data-manager/adapters/layers'

export type RoadClassFilter = 'major' | 'all'

export interface ExtractedAdminArea {
  name: string
  adcode: number | string
  geometry: GeoJSON.Geometry
}

export interface MapBBox {
  west: number
  south: number
  east: number
  north: number
}

const ROAD_CLASS_PATTERNS: Record<RoadClassFilter, string> = {
  major: 'motorway|trunk|primary',
  all: 'motorway|trunk|primary|secondary|tertiary|residential|unclassified',
}

// D0+D1（去硬编码）：Overpass 端点可配。默认官方实例；部署可通过
// VITE_OVERPASS_ENDPOINT 覆盖（私有镜像/加速实例，如 kumi.systems）。
const OVERPASS_ENDPOINT =
  import.meta.env.VITE_OVERPASS_ENDPOINT?.replace(/\/$/, '') ||
  'https://overpass-api.de/api/interpreter'
const OVERPASS_TIMEOUT_SEC = 30
/** 视口 bbox 面积上限（平方度），超过则要求缩小视野，避免 Overpass 超时 */
const MAX_BBOX_AREA_SQ_DEG = 0.5
/** 单次提取要素上限，超出截断并提示 */
const MAX_ROAD_FEATURES = 4000

// ── 几何：点包含判断（ray casting） ────────────────────────────────────────

function pointInRing(lng: number, lat: number, ring: number[][]): boolean {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const [xi, yi] = ring[i]
    const [xj, yj] = ring[j]
    const intersects = yi > lat !== yj > lat && lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi
    if (intersects) inside = !inside
  }
  return inside
}

export function pointInPolygonGeometry(
  lng: number,
  lat: number,
  geometry: GeoJSON.Geometry,
): boolean {
  if (geometry.type === 'Polygon') {
    // 外环包含且不在任一内环（洞）中
    if (!pointInRing(lng, lat, geometry.coordinates[0])) return false
    return geometry.coordinates.slice(1).every((hole) => !pointInRing(lng, lat, hole))
  }
  if (geometry.type === 'MultiPolygon') {
    return geometry.coordinates.some(
      (polygon) =>
        pointInRing(lng, lat, polygon[0]) &&
        polygon.slice(1).every((hole) => !pointInRing(lng, lat, hole)),
    )
  }
  return false
}

// ── 行政区提取 ──────────────────────────────────────────────────────────────

let boundariesCache: GeoJSON.FeatureCollection | null = null

async function loadBoundaries(): Promise<GeoJSON.FeatureCollection | null> {
  if (boundariesCache) return boundariesCache
  try {
    const mod = await import('../app/guangdong-boundaries')
    boundariesCache = mod.guangdongCityBoundaries as GeoJSON.FeatureCollection
    return boundariesCache
  } catch {
    return null
  }
}

/** 提取 (lng, lat) 所在行政区多边形；未命中（点在边界数据外）返回 null */
export async function extractAdminAreaAt(
  lng: number,
  lat: number,
): Promise<ExtractedAdminArea | null> {
  const boundaries = await loadBoundaries()
  if (!boundaries) throw new Error('行政区边界数据加载失败')
  for (const feature of boundaries.features ?? []) {
    if (!feature.geometry) continue
    if (pointInPolygonGeometry(lng, lat, feature.geometry)) {
      const props = (feature.properties ?? {}) as { name?: unknown; adcode?: unknown }
      const adcode = props.adcode
      return {
        name: typeof props.name === 'string' ? props.name : '未命名行政区',
        adcode: typeof adcode === 'string' || typeof adcode === 'number' ? adcode : '',
        geometry: feature.geometry,
      }
    }
  }
  return null
}

// ── 道路提取（OSM Overpass） ───────────────────────────────────────────────

export function bboxAreaSqDeg(bbox: MapBBox): number {
  return Math.abs(bbox.east - bbox.west) * Math.abs(bbox.north - bbox.south)
}

export function buildOverpassQuery(bbox: MapBBox, roadClass: RoadClassFilter): string {
  const pattern = ROAD_CLASS_PATTERNS[roadClass]
  const { west, south, east, north } = bbox
  return (
    `[out:json][timeout:${OVERPASS_TIMEOUT_SEC}];` +
    `way["highway"~"^(${pattern})$"](${south},${west},${north},${east});` +
    'out geom qt;'
  )
}

interface OverpassWay {
  type: string
  id: number
  tags?: Record<string, string>
  geometry?: { lat: number; lon: number }[]
}

export function overpassWaysToGeoJson(
  elements: OverpassWay[],
  limit = MAX_ROAD_FEATURES,
): { geojson: GeoJSON.FeatureCollection; truncated: boolean } {
  const features: GeoJSON.Feature[] = []
  let truncated = false
  for (const el of elements) {
    if (features.length >= limit) {
      truncated = true
      break
    }
    if (el.type !== 'way' || !el.geometry || el.geometry.length < 2) continue
    features.push({
      type: 'Feature',
      properties: {
        osm_id: el.id,
        highway: el.tags?.highway ?? '',
        name: el.tags?.name ?? '',
      },
      geometry: {
        type: 'LineString',
        coordinates: el.geometry.map((p) => [p.lon, p.lat]),
      },
    })
  }
  return { geojson: { type: 'FeatureCollection', features }, truncated }
}

/** 提取当前视口内的 OSM 道路（需外部网络可达 Overpass API） */
export async function extractViewportRoads(
  bbox: MapBBox,
  roadClass: RoadClassFilter,
): Promise<{ geojson: GeoJSON.FeatureCollection; truncated: boolean }> {
  const area = bboxAreaSqDeg(bbox)
  if (area > MAX_BBOX_AREA_SQ_DEG) {
    throw new Error(
      `当前视野过大（约 ${area.toFixed(2)} 平方度），请缩放到城市尺度后再提取（上限 ${MAX_BBOX_AREA_SQ_DEG}）`,
    )
  }
  const query = buildOverpassQuery(bbox, roadClass)
  let resp: Response
  try {
    resp = await fetch(OVERPASS_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ data: query }).toString(),
    })
  } catch {
    throw new Error('无法连接 OSM Overpass 服务（需要外部网络）')
  }
  if (!resp.ok) {
    throw new Error(`Overpass 服务返回 ${resp.status}，请稍后重试或缩小视野`)
  }
  const data = (await resp.json()) as { elements?: OverpassWay[] }
  return overpassWaysToGeoJson(data.elements ?? [])
}

// ── 创建矢量图层 ────────────────────────────────────────────────────────────

export interface CreatedVectorLayer {
  instanceId: string
  backendLayerId: string | null
  name: string
}

/** 后端登记（/import/vector）→ 注册前端图层；登记失败时降级为纯前端图层 */
export async function createExtractedVectorLayer(
  name: string,
  geojson: GeoJSON.FeatureCollection,
): Promise<CreatedVectorLayer> {
  let backendLayerId: string | null = null
  let finalGeojson = geojson
  try {
    const file = new File([JSON.stringify(geojson)], 'basemap-extract.geojson', {
      type: 'application/geo+json',
    })
    const result = await importVectorMultipart([file])
    backendLayerId = result.layer_id ?? null
    finalGeojson = result.preview_geojson ?? geojson
  } catch {
    // 后端登记失败：backendLayerId 保持 null，降级为纯前端图层
  }
  const layer = await registerImportedVectorLayer(name, finalGeojson, {
    backendLayerId: backendLayerId ?? undefined,
    featureCount: finalGeojson.features.length,
  })
  return { instanceId: layer.instanceId, backendLayerId, name: layer.name ?? name }
}
