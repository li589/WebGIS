/**
 * CRS 注册表 — 镜像后端 `crs_registry.py`，含 13 个常用 CRS（Phase 1 扩展版）。
 *
 * 模块加载时一次性 `proj4.defs()` 注册所有 EPSG CRS 的 proj4 串，
 * 之后 `crs-transformer.ts` 直接用 `proj4(src, tgt, [lng, lat])` 转换。
 *
 * 与后端 `_CRS_DEFS` 列表完全对齐（13 项），保证前后端一致性。
 */
import proj4 from 'proj4'
import type { CRSDef, CRSOption, CRSCategory } from './crs-types'

const _CRS_DEFS: CRSDef[] = [
  // ── 地理坐标系 ──
  {
    code: 'EPSG:4326',
    label: 'WGS84 经纬度',
    category: 'geographic',
    epsg: 4326,
    proj4Def: '+proj=longlat +datum=WGS84 +no_defs',
    area: 'Global',
    deprecated: false,
  },
  {
    code: 'EPSG:4490',
    label: 'CGCS2000 国家大地坐标系',
    category: 'geographic',
    epsg: 4490,
    proj4Def: '+proj=longlat +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +no_defs',
    area: 'China',
    deprecated: false,
  },
  {
    code: 'EPSG:4258',
    label: 'ETRS89 欧洲地理坐标系',
    category: 'geographic',
    epsg: 4258,
    proj4Def: '+proj=longlat +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +no_defs',
    area: 'Europe',
    deprecated: false,
  },
  // ── 加密坐标系（非 EPSG）──
  {
    code: 'GCJ02',
    label: 'GCJ-02 火星坐标系（国测局加密）',
    category: 'encrypted',
    epsg: null,
    proj4Def: null,
    area: 'China',
    deprecated: false,
  },
  {
    code: 'BD09',
    label: 'BD-09 百度坐标系',
    category: 'encrypted',
    epsg: null,
    proj4Def: null,
    area: 'China',
    deprecated: false,
  },
  // ── 投影坐标系 ──
  {
    code: 'EPSG:3857',
    label: 'Web Mercator（伪墨卡托）',
    category: 'projected',
    epsg: 3857,
    proj4Def:
      '+proj=merc +a=6378137 +b=6378137 +lat_ts=0 +lon_0=0 +x_0=0 +y_0=0 +k=1 +units=m +nadgrids=@null +wktext +no_defs',
    area: 'Global',
    deprecated: false,
  },
  {
    code: 'EPSG:6933',
    label: 'EASE-Grid 2.0 全球等积圆柱投影',
    category: 'projected',
    epsg: 6933,
    proj4Def:
      '+proj=cea +lon_0=0 +lat_ts=30 +x_0=0 +y_0=0 +ellps=WGS84 +datum=WGS84 +units=m +no_defs',
    area: 'Global',
    deprecated: false,
  },
  {
    code: 'EPSG:32649',
    label: 'UTM Zone 49N（通用横轴墨卡托 49 带 北半球）',
    category: 'projected',
    epsg: 32649,
    proj4Def: '+proj=utm +zone=49 +datum=WGS84 +units=m +no_defs',
    area: 'China',
    deprecated: false,
  },
  {
    code: 'EPSG:32650',
    label: 'UTM Zone 50N（通用横轴墨卡托 50 带 北半球）',
    category: 'projected',
    epsg: 32650,
    proj4Def: '+proj=utm +zone=50 +datum=WGS84 +units=m +no_defs',
    area: 'China',
    deprecated: false,
  },
  // ── 高斯-克吕格（CGCS2000 3 度带）── Task 6.4 新增 ──
  {
    code: 'EPSG:4527',
    label: 'CGCS2000 / 3度带 高斯-克吕格 zone 39（北京，CM 117E）',
    category: 'projected',
    epsg: 4527,
    proj4Def:
      '+proj=tmerc +lat_0=0 +lon_0=117 +k=1 +x_0=39500000 +y_0=0 +ellps=GRS80 +units=m +no_defs',
    area: 'China',
    deprecated: false,
  },
  {
    code: 'EPSG:4528',
    label: 'CGCS2000 / 3度带 高斯-克吕格 zone 40（上海，CM 120E）',
    category: 'projected',
    epsg: 4528,
    proj4Def:
      '+proj=tmerc +lat_0=0 +lon_0=120 +k=1 +x_0=40500000 +y_0=0 +ellps=GRS80 +units=m +no_defs',
    area: 'China',
    deprecated: false,
  },
  {
    code: 'EPSG:4529',
    label: 'CGCS2000 / 3度带 高斯-克吕格 zone 41（东北，CM 123E）',
    category: 'projected',
    epsg: 4529,
    proj4Def:
      '+proj=tmerc +lat_0=0 +lon_0=123 +k=1 +x_0=41500000 +y_0=0 +ellps=GRS80 +units=m +no_defs',
    area: 'China',
    deprecated: false,
  },
  // ── 兰伯特等角圆锥投影 ── Task 6.4 新增 ──
  // 注意：EPSG:3035 实际是 LAEA（兰伯特方位等积），非 LCC。
  // 用户需求是"兰伯特等角圆锥"（Lambert Conformal Conic），
  // 对应的欧洲 CRS 是 EPSG:3034 (ETRS89 / LCC Europe)。
  {
    code: 'EPSG:3034',
    label: 'ETRS89 / LCC Europe（欧洲兰伯特等角圆锥）',
    category: 'projected',
    epsg: 3034,
    proj4Def:
      '+proj=lcc +lat_1=35 +lat_2=65 +lat_0=52 +lon_0=10 +x_0=4000000 +y_0=2800000 +ellps=GRS80 +units=m +no_defs',
    area: 'Europe',
    deprecated: false,
  },
]

// 模块加载时一次性注册 proj4 defs（GCJ02/BD09 无 proj4 串，跳过）
for (const def of _CRS_DEFS) {
  if (def.proj4Def && def.epsg !== null) {
    proj4.defs(`EPSG:${def.epsg}`, def.proj4Def)
  }
}

export const CRS_REGISTRY: Record<string, CRSDef> = Object.fromEntries(
  _CRS_DEFS.map((c) => [c.code, c]),
)

const _LEGACY_MAP: Record<string, string> = { 'GCJ-02': 'GCJ02', 'BD-09': 'BD09' }

function normalizeCode(code: string): string {
  return _LEGACY_MAP[code] ?? code
}

export function getCrs(code: string): CRSDef | undefined {
  if (!code) return undefined
  return CRS_REGISTRY[normalizeCode(code)]
}

export function listCrs(category?: CRSCategory): CRSDef[] {
  return category ? _CRS_DEFS.filter((c) => c.category === category) : _CRS_DEFS
}

export function toApiPayload(): CRSOption[] {
  return _CRS_DEFS.map((c) => ({
    code: c.code,
    label: c.label,
    category: c.category,
    area: c.area,
    deprecated: c.deprecated,
  }))
}
