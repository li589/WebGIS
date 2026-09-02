import type { ActiveLayerDisplay, RuntimeLayerLibraryItem } from '../stores/layers/types'

export interface LayerVisualProductSummary {
  productName: string
  unit: string
  resolution: string
  dataSourceMode: string
}

const RESOLUTION_PATTERNS = [
  /EASE-Grid\s*2?\.?0?\s*(\d+\s*km)/i,
  /(\d+(?:\.\d+)?\s*km)\s*(?:分辨率|网格|格网)?/i,
  /(\d+(?:\.\d+)?°|(?:\d+'\s*){2}\d+")/i,
  /(\d+\s*(?:m|arc-?sec|s)\b)/i,
]

function extractResolutionLabel(...texts: (string | null | undefined)[]): string {
  for (const raw of texts) {
    const text = String(raw ?? '').trim()
    if (!text) continue
    for (const pattern of RESOLUTION_PATTERNS) {
      const match = text.match(pattern)
      if (match?.[1]) return match[1].replace(/\s+/g, '')
    }
  }
  return '—'
}

export type LayerSourceRouteKey = 'auto' | 'local' | 'online' | null

export function resolveLayerSourceRouteKey(input: {
  catalogId: string
  hasLocalOnlineVariants: boolean
  pinned: boolean
  preference: string | null | undefined
}): LayerSourceRouteKey {
  if (!input.hasLocalOnlineVariants) return null
  if (!input.pinned) return 'auto'
  if (input.preference === 'online') return 'online'
  if (input.preference === 'local') return 'local'
  return 'auto'
}

export function formatLayerDataSourceMode(routeKey: LayerSourceRouteKey): string {
  if (routeKey === 'online') return '在线'
  if (routeKey === 'local') return '本地'
  if (routeKey === 'auto') return '自动'
  return '本地'
}

export function buildLayerVisualProductSummary(input: {
  layer: ActiveLayerDisplay
  catalogItem?: RuntimeLayerLibraryItem | null
  symbologyUnit?: string | null
  sourceRouteKey?: LayerSourceRouteKey
}): LayerVisualProductSummary {
  const { layer, catalogItem, symbologyUnit, sourceRouteKey = null } = input
  const productName =
    layer.name?.trim() ||
    (layer.runGroupProductTag ? String(layer.runGroupProductTag) : '') ||
    catalogItem?.name ||
    '—'
  const unit =
    symbologyUnit?.trim() || catalogItem?.metricUnit?.trim() || layer.metricLabel?.trim() || '—'
  const resolution = extractResolutionLabel(
    catalogItem?.description,
    catalogItem?.runReadinessSummary,
    layer.description,
    layer.runReadinessSummary,
    layer.importedRasterNativeStep ? `步长 ${layer.importedRasterNativeStep}` : undefined,
  )
  const dataSourceMode = formatLayerDataSourceMode(sourceRouteKey)
  return { productName, unit, resolution, dataSourceMode }
}
