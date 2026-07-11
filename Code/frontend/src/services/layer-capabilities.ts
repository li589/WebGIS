import type { RuntimeLayerCapabilities, RuntimeLayerDescriptor } from './runtime-api'

type RenderStrategyBehavior = {
  tileManaged: boolean
  supportsMapLayer: boolean
  supportsViewportRefresh: boolean
  viewportRefreshMode: 'tile' | 'workflow' | 'none'
}

type PaintModeBehavior = {
  supportsParticleFlow: boolean
}

const RENDER_STRATEGY_REGISTRY: Record<string, RenderStrategyBehavior> = {
  weather_tile: {
    tileManaged: true,
    supportsMapLayer: true,
    supportsViewportRefresh: true,
    viewportRefreshMode: 'tile',
  },
  workflow_map_layer: {
    tileManaged: false,
    supportsMapLayer: true,
    supportsViewportRefresh: true,
    viewportRefreshMode: 'workflow',
  },
  workflow_result: {
    tileManaged: false,
    supportsMapLayer: false,
    supportsViewportRefresh: false,
    viewportRefreshMode: 'none',
  },
}

const PAINT_MODE_REGISTRY: Record<string, PaintModeBehavior> = {
  particle_flow: { supportsParticleFlow: true },
  grid_fill: { supportsParticleFlow: false },
  heatmap: { supportsParticleFlow: false },
  point_symbol: { supportsParticleFlow: false },
  point: { supportsParticleFlow: false },
  barb: { supportsParticleFlow: false },
}

const LEGACY_MAP_LAYER_RENDER_TYPES = new Set([
  'grid_fill',
  'point',
  'point_symbol',
  'particle_flow',
  'heatmap',
  'vector',
  'raster',
])

function matchesLegacyWeatherLayer(catalogId: string) {
  if (catalogId.startsWith('wind-field')) return true
  if (catalogId.startsWith('temperature')) return true
  return ['precipitation', 'pressure', 'humidity', 'visibility'].includes(catalogId)
}

export function getLayerCapabilities(descriptor?: RuntimeLayerDescriptor | null): RuntimeLayerCapabilities | null {
  return descriptor?.capabilities ?? null
}

export function resolveRenderStrategy(descriptor?: RuntimeLayerDescriptor | null, catalogId?: string | null) {
  const strategy = descriptor?.capabilities?.render_strategy
  if (strategy) return strategy
  if (descriptor?.source_type === 'weather' || (catalogId && matchesLegacyWeatherLayer(catalogId))) {
    return 'weather_tile'
  }
  if (descriptor?.render_type && LEGACY_MAP_LAYER_RENDER_TYPES.has(descriptor.render_type)) {
    return 'workflow_map_layer'
  }
  return 'workflow_result'
}

export function getRenderStrategyBehavior(descriptor?: RuntimeLayerDescriptor | null, catalogId?: string | null) {
  return RENDER_STRATEGY_REGISTRY[resolveRenderStrategy(descriptor, catalogId)] ?? RENDER_STRATEGY_REGISTRY.workflow_result
}

export function resolvePaintMode(descriptor?: RuntimeLayerDescriptor | null) {
  return descriptor?.capabilities?.paint_mode ?? null
}

export function isTileManagedLayer(descriptor?: RuntimeLayerDescriptor | null, catalogId?: string | null) {
  return getRenderStrategyBehavior(descriptor, catalogId).tileManaged
}

export function isWeatherLayerDescriptor(descriptor?: RuntimeLayerDescriptor | null, catalogId?: string | null) {
  const capabilities = getLayerCapabilities(descriptor)
  if (capabilities?.data_domain) {
    return capabilities.data_domain === 'weather'
  }
  if (descriptor?.source_type) {
    return descriptor.source_type === 'weather'
  }
  return Boolean(catalogId && matchesLegacyWeatherLayer(catalogId))
}

export function supportsParticleFlowCapability(descriptor?: RuntimeLayerDescriptor | null, catalogId?: string | null) {
  const capabilities = getLayerCapabilities(descriptor)
  if (typeof capabilities?.supports_particle_flow === 'boolean') {
    return capabilities.supports_particle_flow
  }
  const paintMode = resolvePaintMode(descriptor)
  if (paintMode) {
    return PAINT_MODE_REGISTRY[paintMode]?.supportsParticleFlow ?? false
  }
  return Boolean(catalogId && catalogId.startsWith('wind-field'))
}

export function supportsMapLayerCapability(descriptor?: RuntimeLayerDescriptor | null, catalogId?: string | null) {
  const capabilities = getLayerCapabilities(descriptor)
  if (typeof capabilities?.supports_map_layer === 'boolean') {
    return capabilities.supports_map_layer
  }
  if (capabilities?.result_interfaces?.includes('map_layer')) {
    return true
  }
  return getRenderStrategyBehavior(descriptor, catalogId).supportsMapLayer
}

export function supportsViewportDrivenRefreshCapability(descriptor?: RuntimeLayerDescriptor | null, catalogId?: string | null) {
  const capabilities = getLayerCapabilities(descriptor)
  if (typeof capabilities?.supports_viewport_refresh === 'boolean') {
    return capabilities.supports_viewport_refresh
  }
  return getRenderStrategyBehavior(descriptor, catalogId).supportsViewportRefresh
}
