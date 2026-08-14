import type { LayerCapabilities, LayerDescriptor, OnlineTemporalCapability } from './runtime-api'

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

/**
 * Catalog paint_mode → 默认渲染行为。
 * 与 UI WindDisplayMode（particle|streamline|off）是不同轴：
 * `barb` 等仅出现在此 registry，不会出现在 WindDisplayMode。
 */
const PAINT_MODE_REGISTRY: Record<string, PaintModeBehavior> = {
  particle_flow: { supportsParticleFlow: true },
  grid_fill: { supportsParticleFlow: false },
  heatmap: { supportsParticleFlow: false },
  point_symbol: { supportsParticleFlow: false },
  point: { supportsParticleFlow: false },
  barb: { supportsParticleFlow: false },
}

export function getLayerCapabilities(
  descriptor?: LayerDescriptor | null,
): LayerCapabilities | null {
  return descriptor?.capabilities ?? null
}

export function resolveRenderStrategy(descriptor?: LayerDescriptor | null) {
  return descriptor?.capabilities?.render_strategy ?? 'workflow_result'
}

export function getRenderStrategyBehavior(descriptor?: LayerDescriptor | null) {
  return (
    RENDER_STRATEGY_REGISTRY[resolveRenderStrategy(descriptor)] ??
    RENDER_STRATEGY_REGISTRY.workflow_result
  )
}

export function resolvePaintMode(descriptor?: LayerDescriptor | null) {
  return descriptor?.capabilities?.paint_mode ?? null
}

export function isTileManagedLayer(descriptor?: LayerDescriptor | null) {
  return getRenderStrategyBehavior(descriptor).tileManaged
}

export function isWeatherLayerDescriptor(descriptor?: LayerDescriptor | null) {
  const capabilities = getLayerCapabilities(descriptor)
  if (capabilities?.data_domain) {
    return capabilities.data_domain === 'weather'
  }
  return descriptor?.source_type === 'weather'
}

export function supportsParticleFlowCapability(descriptor?: LayerDescriptor | null) {
  const capabilities = getLayerCapabilities(descriptor)
  if (typeof capabilities?.supports_particle_flow === 'boolean') {
    return capabilities.supports_particle_flow
  }
  const paintMode = resolvePaintMode(descriptor)
  return PAINT_MODE_REGISTRY[paintMode ?? '']?.supportsParticleFlow ?? false
}

export function supportsMapLayerCapability(descriptor?: LayerDescriptor | null) {
  const capabilities = getLayerCapabilities(descriptor)
  if (typeof capabilities?.supports_map_layer === 'boolean') {
    return capabilities.supports_map_layer
  }
  if (capabilities?.result_interfaces?.includes('map_layer')) {
    return true
  }
  return getRenderStrategyBehavior(descriptor).supportsMapLayer
}

export function supportsViewportDrivenRefreshCapability(descriptor?: LayerDescriptor | null) {
  const capabilities = getLayerCapabilities(descriptor)
  if (typeof capabilities?.supports_viewport_refresh === 'boolean') {
    return capabilities.supports_viewport_refresh
  }
  return getRenderStrategyBehavior(descriptor).supportsViewportRefresh
}

// ── Online Temporal 能力判定 ──────────────────────────────────────────────

/**
 * 判断图层是否支持在线时间获取（用户选时间点 → 自动在线获取 → 动态刷新）。
 *
 * 判定依据：descriptor.online_temporal?.enabled === true。
 * None / false 均视为不支持。
 */
export function supportsOnlineTemporalCapability(descriptor?: LayerDescriptor | null): boolean {
  return Boolean(descriptor?.online_temporal?.enabled)
}

/**
 * 返回图层的在线时间获取配置；不支持时返回 null。
 *
 * 调用方可用 coverage_start / coverage_end 限制时间轴可选范围，
 * 用 native_step / max_batch / prefetch_depth / queue_tag / priority
 * 驱动编排器提交工作流。
 */
export function getOnlineTemporalConfig(
  descriptor?: LayerDescriptor | null,
): OnlineTemporalCapability | null {
  const cap = descriptor?.online_temporal
  if (!cap?.enabled) return null
  return cap
}
