import type { WeatherLayerRenderHint } from '../../services/runtime-api'
import type { WindGeoJSON } from './types'

export interface WeatherOverlayState {
  catalogId: string
  geojsonUrl: string | null
  geojsonData: WindGeoJSON | Record<string, unknown> | null
  cogPreviewUrl: string | null
  cogBbox: { west: number; south: number; east: number; north: number } | null
  /** 瓦片请求的目标视口 bounds；grid_fill 用它画灰底占位（无数据区域渐填） */
  viewportBounds?: { west: number; south: number; east: number; north: number } | null
  renderHint: WeatherLayerRenderHint
  opacity: number
}

export interface WeatherOverlayRenderContext {
  enabledParticleFlowCatalogId: string | null
  markRendered: (catalogId: string) => void
  syncWeatherCogOverlay: (state: WeatherOverlayState) => void
  syncWeatherGridFillOverlay: (state: WeatherOverlayState) => void
  syncWeatherPointOverlay: (state: WeatherOverlayState) => void
  syncWindParticleFlow: (state: WeatherOverlayState, overlayToken: number) => Promise<void>
  /** WebGL 标量场；返回 true 表示已渲染，false 应回退 fill */
  syncScalarFieldWebGL: (state: WeatherOverlayState, overlayToken: number) => boolean
}

interface WeatherOverlayRenderer {
  canRender: (state: WeatherOverlayState) => boolean
  render: (
    state: WeatherOverlayState,
    context: WeatherOverlayRenderContext,
    overlayToken: number,
  ) => void
}

function hasGeojsonSource(state: WeatherOverlayState) {
  return Boolean(state.geojsonData || state.geojsonUrl)
}

function hasCogPreview(state: WeatherOverlayState) {
  return Boolean(state.cogPreviewUrl && state.cogBbox)
}

function hasViewportPlaceholder(state: WeatherOverlayState) {
  return Boolean(state.viewportBounds)
}

const WEATHER_OVERLAY_RENDERERS: Record<string, WeatherOverlayRenderer> = {
  particle_flow: {
    canRender: hasGeojsonSource,
    render: (state, context, overlayToken) => {
      if (state.catalogId !== context.enabledParticleFlowCatalogId) return
      void context.syncWindParticleFlow(state, overlayToken)
      context.markRendered(state.catalogId)
    },
  },
  barb: {
    canRender: hasGeojsonSource,
    render: (state, context, overlayToken) => {
      if (state.catalogId !== context.enabledParticleFlowCatalogId) return
      void context.syncWindParticleFlow(state, overlayToken)
      context.markRendered(state.catalogId)
    },
  },
  heatmap: {
    canRender: hasGeojsonSource,
    render: (state, context, overlayToken) => {
      // 2026-08-25 平滑渲染修复：heatmap 与 grid_fill 同为标量场，但后端
      // constants.py 给 temperature/humidity 等标量层的 paint_mode='heatmap'
      // ——此前直接调 grid fill（MapLibre 网格），完全绕过 syncScalarField
      // WebGL（WebGL 连续面），导致「平滑渲染-连续数值面」开关对这类图层
      // 无效。现在与 grid_fill 同构：WebGL 优先，失败回退网格 fill。
      const gridFillState = {
        ...state,
        renderHint: { ...state.renderHint, paint_mode: 'grid_fill' as const },
      }
      if (!context.syncScalarFieldWebGL(gridFillState, overlayToken)) {
        context.syncWeatherGridFillOverlay(gridFillState)
      }
      context.markRendered(state.catalogId)
    },
  },
  grid_fill: {
    // 有视口 bounds 即可渲染灰底占位，数据瓦片到达后渐进填色
    canRender: (state) =>
      hasGeojsonSource(state) || hasCogPreview(state) || hasViewportPlaceholder(state),
    render: (state, context, overlayToken) => {
      if (hasCogPreview(state)) {
        context.syncWeatherCogOverlay(state)
      } else if (!context.syncScalarFieldWebGL(state, overlayToken)) {
        context.syncWeatherGridFillOverlay(state)
      }
      context.markRendered(state.catalogId)
    },
  },
  point_symbol: {
    canRender: hasGeojsonSource,
    render: (state, context) => {
      context.syncWeatherPointOverlay(state)
      context.markRendered(state.catalogId)
    },
  },
}

export function canRenderWeatherOverlayState(state: WeatherOverlayState) {
  const renderer = WEATHER_OVERLAY_RENDERERS[state.renderHint.paint_mode]
  return renderer ? renderer.canRender(state) : false
}

export function renderWeatherOverlayState(
  state: WeatherOverlayState,
  context: WeatherOverlayRenderContext,
  overlayToken: number,
) {
  const renderer = WEATHER_OVERLAY_RENDERERS[state.renderHint.paint_mode]
  if (!renderer || !renderer.canRender(state)) return false
  renderer.render(state, context, overlayToken)
  return true
}
