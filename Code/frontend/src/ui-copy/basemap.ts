/** 底图风格 / Key / pill 短名 */
export const BASEMAP_COPY = {
  styleNone: '空白',
  styleStreet: '街道',
  styleSatellite: '影像',
  styleDark: '深色',
  styleTerrain: '地形',
  needApiKey: '需配置底图 API Key',
  noLayers: '暂无图层',
} as const

const STYLE_LABELS: Record<string, string> = {
  none: BASEMAP_COPY.styleNone,
  street: BASEMAP_COPY.styleStreet,
  satellite: BASEMAP_COPY.styleSatellite,
  dark: BASEMAP_COPY.styleDark,
  terrain: BASEMAP_COPY.styleTerrain,
}

export function basemapStyleLabel(style: string): string {
  return STYLE_LABELS[style] ?? style
}

/** 工具栏源 pill 短标签（可读，非单字母） */
const PROVIDER_SHORT: Record<string, string> = {
  none: '空白',
  gaode: '高德',
  bing: 'Bing',
  esri: 'Esri',
  osm: 'OSM',
  carto: 'CARTO',
  tianditu: '天地',
  baidu: '百度',
}

export function basemapProviderShort(sourceId: string, provider: string): string {
  const prefix = sourceId.split('-')[0]?.toLowerCase() ?? ''
  if (PROVIDER_SHORT[prefix]) return PROVIDER_SHORT[prefix]
  if (provider === 'None' || provider === 'Blank') return PROVIDER_SHORT.none
  return provider.slice(0, 4)
}
