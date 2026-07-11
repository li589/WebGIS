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

export function getLayerCapabilities(descriptor?: RuntimeLayerDescriptor | null): RuntimeLayerCapabilities | null {
  return descriptor?.capabilities ?? null
}

export function resolveRenderStrategy(descriptor?: RuntimeLayerDescriptor | null) {
  return descriptor?.capabilities?.render_strategy ?? 'workflow_result'
}

export function getRenderStrategyBehavior(descriptor?: RuntimeLayerDescriptor | null) {
  return RENDER_STRATEGY_REGISTRY[resolveRenderStrategy(descriptor)] ?? RENDER_STRATEGY_REGISTRY.workflow_result
}

export function resolvePaintMode(descriptor?: RuntimeLayerDescriptor | null) {
  return descriptor?.capabilities?.paint_mode ?? null
}

export function isTileManagedLayer(descriptor?: RuntimeLayerDescriptor | null) {
  return getRenderStrategyBehavior(descriptor).tileManaged
}

export function isWeatherLayerDescriptor(descriptor?: RuntimeLayerDescriptor | null) {
  const capabilities = getLayerCapabilities(descriptor)
  if (capabilities?.data_domain) {
    return capabilities.data_domain === 'weather'
  }
  return descriptor?.source_type === 'weather'
}

export function supportsParticleFlowCapability(descriptor?: RuntimeLayerDescriptor | null) {
  const capabilities = getLayerCapabilities(descriptor)
  if (typeof capabilities?.supports_particle_flow === 'boolean') {
    return capabilities.supports_particle_flow
  }
  const paintMode = resolvePaintMode(descriptor)
  return PAINT_MODE_REGISTRY[paintMode ?? '']?.supportsParticleFlow ?? false
}

export function supportsMapLayerCapability(descriptor?: RuntimeLayerDescriptor | null) {
  const capabilities = getLayerCapabilities(descriptor)
  if (typeof capabilities?.supports_map_layer === 'boolean') {
    return capabilities.supports_map_layer
  }
  if (capabilities?.result_interfaces?.includes('map_layer')) {
    return true
  }
  return getRenderStrategyBehavior(descriptor).supportsMapLayer
}

export function supportsViewportDrivenRefreshCapability(descriptor?: RuntimeLayerDescriptor | null) {
  const capabilities = getLayerCapabilities(descriptor)
  if (typeof capabilities?.supports_viewport_refresh === 'boolean') {
    return capabilities.supports_viewport_refresh
  }
  return getRenderStrategyBehavior(descriptor).supportsViewportRefresh
}
