/**
 * 工作流时间 / 空间维度约定（编辑器 + 运行时契约）。
 *
 * ────────────────────────────────────────────────────────────
 * 一、两层语义（必须区分）
 * ────────────────────────────────────────────────────────────
 * 1) 原生维度（Source Native）——挂在「数据源」节点参数上：
 *    - 这份数据本身如何编码时间/空间（字段名、格式、原生分辨率、CRS）
 *    - 例：FY 产品可能是「天」；某气候数据是「年」；雷达是「分钟」；
 *      合成产品可能是「3 天」一步；时间可能由 year+doy 多字段组成
 *
 * 2) 运行窗口（Run Window）——经连线传入的 time_range / bbox：
 *    - 「本次运行」要从数据里切出哪一段、哪一块
 *    - 可绑定主界面 TimelineScrubber / 地图视口，也可手工指定
 *
 * 数据源应同时接受 time_range + bbox；下游算法优先消费同名端口，
 * 未连接时回退：节点默认值 → 主时间轴/视口注入 → 全量。
 *
 * ────────────────────────────────────────────────────────────
 * 二、时间分辨率与对齐
 * ────────────────────────────────────────────────────────────
 * resolution_unit + resolution_step 表达「步长」：
 *   day + 1 → 逐日；day + 3 → 3 日合成；minute + 10 → 10 分钟
 *
 * 运行时对齐策略（执行器侧建议）：
 *   - 窗口与原生分辨率不整除时：向下对齐到原生步长，并在日志中告警
 *   - bind_timeline=true：用主时间轴 currentTime / window 覆盖 start/end
 *   - 多源合流：以「最粗」分辨率重采样，或要求用户显式 resample 节点
 *
 * ────────────────────────────────────────────────────────────
 * 三、字段映射与格式适配
 * ────────────────────────────────────────────────────────────
 * time_fields: string[]  —— 如 ['datetime'] 或 ['year','doy']
 * field_format           —— 解析提示（ISO、YYYYMMDD、doy 等）
 * timezone               —— 默认 UTC
 *
 * 传输流：编辑器只传轻量 JSON 窗口对象；实际字节流仍走 data:* 端口。
 * 格式适配（mat/tif/netcdf/csv…）由 source_fetcher / provider 完成，
 * 窗口对象作为读取参数下发，不替代数据流本身。
 *
 * ────────────────────────────────────────────────────────────
 * 四、空间同理
 * ────────────────────────────────────────────────────────────
 * bbox = AOI 矩形；viewport_bbox = 当前地图视口（语义不同）
 * spatial_fields / crs 声明原生几何；geometry 端口与 bbox 同类型
 *
 * ────────────────────────────────────────────────────────────
 * 五、主界面时间轴
 * ────────────────────────────────────────────────────────────
 * TimelineScrubber 显示「运行窗口」在时间轴上的投影；
 * 若图中多个 time_range 且 bind_timeline 冲突，以被选中输出层 /
 * 工作流运行对话框指定的主窗口为准（后续可做多轴）。
 */

export const TIME_RESOLUTION_UNITS = [
  'minute',
  'hour',
  'day',
  'month',
  'year',
  'custom',
] as const

export type TimeResolutionUnit = (typeof TIME_RESOLUTION_UNITS)[number]

export const TIME_RESOLUTION_LABELS: Record<TimeResolutionUnit, string> = {
  minute: '分钟',
  hour: '小时',
  day: '天',
  month: '月',
  year: '年',
  custom: '自定义',
}

export interface TimeRangeValue {
  start_at?: string
  end_at?: string
  resolution_unit?: TimeResolutionUnit
  resolution_step?: number
  /** 兼容旧字段 */
  granularity?: string
  time_fields?: string[]
  field_format?: string
  timezone?: string
  bind_timeline?: boolean
}

export interface BBoxValue {
  west: number
  south: number
  east: number
  north: number
  crs?: string
  spatial_fields?: string[]
  source?: 'manual' | 'map_viewport' | 'layer_extent'
}

/** 需要时间窗口输入的节点类型前缀 / 精确类型 */
export const TIME_RANGE_CONSUMER_HINTS = [
  'module/',
  'weather/',
  'gee/',
  'stats/',
  'fusion/',
  'viz/',
  'data/source',
] as const

/** 需要空间范围输入的常见端口名 */
export const BBOX_PORT_NAMES = ['bbox', 'viewport_bbox', 'geometry', 'aoi_bbox'] as const

export function nodeTypeWantsTimeRange(nodeType: string): boolean {
  if (nodeType.startsWith('data/') && nodeType !== 'data/source') return false
  if (nodeType.startsWith('output/')) return false
  return TIME_RANGE_CONSUMER_HINTS.some(
    (h) => h === nodeType || (h.endsWith('/') && nodeType.startsWith(h)),
  )
}

export function parseTimeFields(raw: unknown): string[] {
  if (Array.isArray(raw)) return raw.map(String).map((s) => s.trim()).filter(Boolean)
  if (typeof raw !== 'string' || !raw.trim()) return []
  return raw.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
}

/** 从节点 properties / 连线结果拼装运行时 time_range 对象 */
export function buildTimeRangeFromProps(props: Record<string, unknown>): TimeRangeValue {
  const unitRaw = String(props.resolution_unit ?? props.granularity ?? 'day')
  const unit = (TIME_RESOLUTION_UNITS as readonly string[]).includes(unitRaw)
    ? (unitRaw as TimeResolutionUnit)
    : 'day'
  const step = Number(props.resolution_step ?? 1)
  return {
    start_at: String(props.start_at ?? '') || undefined,
    end_at: String(props.end_at ?? '') || undefined,
    resolution_unit: unit,
    resolution_step: Number.isFinite(step) && step > 0 ? step : 1,
    granularity: String(props.granularity ?? unit),
    time_fields: parseTimeFields(props.time_fields),
    field_format: String(props.field_format ?? '') || undefined,
    timezone: String(props.timezone ?? 'UTC') || 'UTC',
    bind_timeline: props.bind_timeline !== false && props.bind_timeline !== 'false',
  }
}

export function buildBBoxFromProps(props: Record<string, unknown>): BBoxValue {
  return {
    west: Number(props.west ?? -180),
    south: Number(props.south ?? -90),
    east: Number(props.east ?? 180),
    north: Number(props.north ?? 90),
    crs: String(props.crs ?? 'EPSG:4326'),
    spatial_fields: parseTimeFields(props.spatial_fields),
    source: (String(props.source ?? 'manual') as BBoxValue['source']) || 'manual',
  }
}
