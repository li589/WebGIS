import type { WeatherLayerRenderHint } from '../../services/runtime-api'
import type { WindGeoJSON } from './types'

export interface WeatherOverlayState {
  catalogId: string
  geojsonUrl: string | null
  geojsonData: WindGeoJSON | Record<string, unknown> | null
  cogPreviewUrl: string | null
  cogBbox: { west: number; south: number; east: number; north: number } | null
  renderHint: WeatherLayerRenderHint
  opacity: number
}

export interface WeatherOverlayRenderContext {
  enabledParticleFlowCatalogId: string | null
  markRendered: (catalogId: string) => void
  syncWeatherCogOverlay: (state: WeatherOverlayState) => void
  syncWeatherGridFillOverlay: (state: WeatherOverlayState) => void
  syncWeatherHeatmapOverlay: (state: WeatherOverlayState) => void
  syncWeatherPointOverlay: (state: WeatherOverlayState) => void
  syncWindParticleFlow: (state: WeatherOverlayState, overlayToken: number) => Promise<void>
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
    render: (state, context) => {
      context.syncWeatherHeatmapOverlay(state)
      context.markRendered(state.catalogId)
    },
  },
  grid_fill: {
    canRender: (state) => hasGeojsonSource(state) || hasCogPreview(state),
    render: (state, context) => {
      if (hasCogPreview(state)) {
        context.syncWeatherCogOverlay(state)
      } else {
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
