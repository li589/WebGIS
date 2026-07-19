/**
 * 连接点悬停说明：短标题 + 人性化正文 + 连接建议。
 * 画布上只显示端口名，详细说明放在此提示框中。
 */
import { getPortTypeLabel, suggestConnectorsForPortType } from './litegraph-setup'

export interface PortHoverInfo {
  direction: 'input' | 'output'
  name: string
  type: string
  /** 模板或节点上的简短 description */
  description?: string
  required?: boolean
  connected?: boolean
  /** 节点标题（可选） */
  nodeTitle?: string
  /** 建议连接的节点中文名 */
  suggestTitles?: string[]
}

export interface PortTooltipModel {
  title: string
  badge: string
  typeLabel: string
  body: string
  tips: string[]
  tone: 'in' | 'out'
}

const TYPE_HELP: Record<string, string> = {
  'value:time_range':
    '时间窗口：起止时间 + 分辨率（分钟/小时/天/多天/月/年）+ 可选时间字段映射与时区。可绑定主界面时间轴。用于数据源过滤、遥感合成、GEE 影像筛选等。',
  'geometry:bbox':
    '空间窗口：西/南/东/北 + 可选 CRS 与空间字段。用于数据源过滤、裁剪、重投影、网格抓取、GEE clip（geometry 端口）等。视口 bbox 与手工 AOI 语义不同。',
  'value:number':
    '数值参数。常见用途：纬度/经度、预报小时数、缓冲距离、频率、分辨率等。可从「数值」或「经纬度」节点连入。',
  'value:string':
    '文本参数。常见用途：图层 ID、气象模型名、Provider ID、Asset ID、枚举选项等。可从「文本」节点连入。',
  'value:boolean':
    '开关参数（是/否）。可从「开关」节点连入；未连接时使用节点上的控件默认值。',
  'data:source':
    '数据源路径或 URI（目录/文件/远程地址）。通常由「数据源」节点提供，接到各处理模块的 input_dir。',
  'data:raster':
    '栅格数据流（影像、网格、DEM 等）。在预处理、统计分析、GEE、天气渲染之间传递。',
  'data:mat':
    'MATLAB .mat 产品。遥感日常处理与反演链路的主要中间格式。',
  'data:timeseries':
    '时间序列 .mat。由「时间序列合成」产出，供批量反演 / Omega 反演使用。',
  'data:geojson':
    '矢量 GeoJSON（点/线/面）。风场渲染、缓冲区、分区统计等会产出或消费此类型。',
  data: '通用数据流（兼容多种 data:* 子类型）。优先使用更具体的类型端口以便校验。',
}

const NAME_HELP: Record<string, string> = {
  time_range:
    '连接「时间范围」。注意：窗口分辨率应与数据原生分辨率匹配（如 3 日产品用 step=3、unit=day）。未连接时可能用主时间轴或全量时间。',
  bbox:
    '连接「空间范围」或「地图视口」。表示本次运行的 AOI；与数据源上声明的原生空间字段是两回事。',
  viewport_bbox:
    '当前地图视口。接到「地图视口」更合适；适合天气渲染等跟视图走的场景，不同于固定 AOI。',
  geometry: '与 bbox 同类型。请连接「空间范围」或「地图视口」的 bbox / viewport_bbox 输出。',
  latitude: '中心点纬度（度）。建议从「经纬度」节点的 latitude 口连入，或用「数值」节点。',
  longitude: '中心点经度（度）。建议从「经纬度」节点的 longitude 口连入，或用「数值」节点。',
  layer_id: '目标图层标识（如 wind-field、temperature）。用「文本」节点提供，需与目录中的图层 ID 一致。',
  input_dir: '输入数据目录。连接「数据源」；数据源本身还可再接时间/空间过滤。',
  input_mat: '上游 .mat 产品。通常来自日常合成、日常处理或时间序列合成的输出。',
  grid_data: '上游网格栅格。通常来自「网格数据抓取」，再交给各类渲染/瓦片节点。',
  forecast_hours: '向前预报的小时数。可选；不连时使用节点默认或引擎配置。',
  provider_id: '钉选天气数据源（open-meteo-online / open-meteo-local / weatherapi / openweather）。留空则按自动优先级选择。',
  model: '气象模式名称（如 icon_seamless）。可选，取决于所选 Provider 是否支持。',
  data: '已解析的数据源引用。下游按格式适配器读取；时间/空间过滤应尽量在数据源节点完成。',
}

function stripArrowHints(text: string): string {
  return text
    .replace(/\s*[←→].*$/u, '')
    .replace(/（可连线[^）]*）/g, '')
    .replace(/\(可连线[^)]*\)/g, '')
    .trim()
}

export function buildPortTooltip(info: PortHoverInfo): PortTooltipModel {
  const typeLabel = getPortTypeLabel(info.type)
  const shortDesc = info.description ? stripArrowHints(info.description) : ''
  const nameHelp = NAME_HELP[info.name] ?? ''
  const typeHelp = TYPE_HELP[info.type] ?? `${typeLabel}类型的数据端口。`
  const bodyParts = [shortDesc, nameHelp, typeHelp].filter(Boolean)
  // 去重相近段落
  const body = Array.from(new Set(bodyParts)).join('\n\n')

  const tips: string[] = []
  if (info.direction === 'input') {
    tips.push(info.required === false ? '可选输入：不连接也能运行，将使用默认值或上下文。' : '建议连接后再运行，以保证数据完整。')
    if (info.connected) tips.push('当前已连接。')
    else tips.push('当前未连接。')
  } else {
    tips.push('从此端口拖出连线，接到下游同色/同类型输入口。')
    if (info.connected) tips.push(`已连接到 ${info.connected ? '下游' : ''}节点。`)
  }

  const suggests = info.suggestTitles?.length
    ? info.suggestTitles
    : suggestConnectorsForPortType(info.type)
  if (info.direction === 'input' && suggests.length) {
    tips.push(`可从节点库拖入：${suggests.slice(0, 4).join('、')}`)
  }

  return {
    title: info.name,
    badge: info.direction === 'input' ? '输入' : '输出',
    typeLabel,
    body,
    tips,
    tone: info.direction === 'input' ? 'in' : 'out',
  }
}
