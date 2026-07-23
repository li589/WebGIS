import type { ActiveLayerDisplay } from '../../stores/layers/types'

export interface MapStageDisplayModel {
  basemapChipLabel: string
  hourChipLabel: string
  layerChipLabel: string
  availabilityChipLabel: string
  availabilityChipClass: string
  noteTitle: string
  noteSummary: string
  noteMeta: string
  hotspotLayerClass: string
}

export interface MapStageStatusModel {
  showLoading: boolean
  loadingLabel: string
  showTileError: boolean
  tileErrorMessage: string
  retryButtonLabel: string
}

export interface MapStageAppearanceModel {
  usesLightNavigationTheme: boolean
  stageClassNames: Record<string, boolean>
  stageStyleVars: Record<string, string>
  mapHostClassNames: Record<string, boolean>
  skeletonClassNames: Record<string, boolean>
}

export interface MapStageTimeVisualState {
  timeProgressPercent: string
  timeGlowOpacity: string
  horizonPosition: string
  stageBandOpacity: string
  stageGlowSpread: string
  hotspotScale: string
  hotspotHaloSize: string
  hotspotLabelOpacity: string
}

function timeBandValue<T extends string>(
  hour: number,
  entries: Array<{ threshold: number; value: T }>,
): T {
  for (const { threshold, value } of entries) {
    if (hour < threshold) return value
  }
  return entries[entries.length - 1].value
}

export function buildFallbackActiveLayerDisplay(): ActiveLayerDisplay {
  return {
    instanceId: '',
    catalogId: '',
    name: '无图层',
    category: '',
    summary: '',
    metricLabel: '—',
    metricValue: '—',
    trendLabel: '',
    statusLabel: '',
    updateLabel: '',
    sourceLabel: '',
    confidenceLabel: '',
    accentColor: '#5a6a80',
    accentGlow: 'rgba(90, 106, 128, 0.3)',
    chipTone: 'rgba(90, 106, 128, 0.16)',
    availabilityState: 'empty',
    availabilityLabel: '空状态',
    availabilityDescription: '从左侧图层面板添加数据图层。',
    observationTimeLabel: '—',
    missingFieldsLabel: '—',
    hotspots: [],
    isAdminBoundary: false,
    isImported: false,
    isImportedRaster: false,
    visible: true,
    opacity: 1,
    order: 0,
    dataState: 'catalog',
  }
}

export function buildMapStageDisplayModel(options: {
  basemapProvider: string
  basemapLabel: string
  hourLabel: string
  activeLayer: ActiveLayerDisplay
}): MapStageDisplayModel {
  return {
    basemapChipLabel: `${options.basemapProvider} · ${options.basemapLabel}`,
    hourChipLabel: options.hourLabel,
    layerChipLabel: options.activeLayer.name,
    availabilityChipLabel: options.activeLayer.availabilityLabel,
    availabilityChipClass: `chip-${options.activeLayer.availabilityState}`,
    noteTitle: options.activeLayer.name,
    noteSummary: options.activeLayer.trendLabel,
    noteMeta: `${options.activeLayer.observationTimeLabel} · ${options.activeLayer.availabilityLabel}`,
    hotspotLayerClass: `hotspot-layer-${options.activeLayer.availabilityState}`,
  }
}

export function buildMapStageStatusModel(options: {
  mapReady: boolean
  loadingLabel: string
  tileLoadFailed: boolean
  tileFailedProvider: string | null
}): MapStageStatusModel {
  return {
    showLoading: !options.mapReady,
    loadingLabel: options.loadingLabel,
    showTileError: options.tileLoadFailed,
    tileErrorMessage: options.tileFailedProvider
      ? `底图「${options.tileFailedProvider}」加载失败（需要配置 API Key 或网络不可达）`
      : '底图瓦片加载失败',
    retryButtonLabel: '重试',
  }
}

export function buildMapStageAppearanceModel(options: {
  basemapStyle: string
  activeLayer: ActiveLayerDisplay
  timeVisualState: MapStageTimeVisualState
  isMapInteracting: boolean
  isSourceTransitioning: boolean
  mapVisible: boolean
  skeletonVisible: boolean
}): MapStageAppearanceModel {
  const usesLightNavigationTheme =
    options.basemapStyle === 'satellite' || options.basemapStyle === 'terrain'

  return {
    usesLightNavigationTheme,
    stageClassNames: {
      'map-stage-interacting': options.isMapInteracting,
      'map-stage-transitioning': options.isSourceTransitioning,
      'map-stage-light': usesLightNavigationTheme,
      'map-stage-dark': options.basemapStyle === 'dark',
      [`map-stage-${options.activeLayer.availabilityState}`]: true,
    },
    stageStyleVars: {
      '--accent-color': options.activeLayer.accentColor,
      '--accent-glow': options.activeLayer.accentGlow,
      '--chip-tone': options.activeLayer.chipTone,
      '--time-progress': options.timeVisualState.timeProgressPercent,
      '--time-glow-opacity': options.timeVisualState.timeGlowOpacity,
      '--horizon-position': options.timeVisualState.horizonPosition,
      '--stage-band-opacity': options.timeVisualState.stageBandOpacity,
      '--stage-glow-spread': options.timeVisualState.stageGlowSpread,
      '--hotspot-scale': options.timeVisualState.hotspotScale,
      '--hotspot-halo-size': options.timeVisualState.hotspotHaloSize,
      '--hotspot-label-opacity': options.timeVisualState.hotspotLabelOpacity,
    },
    mapHostClassNames: {
      visible: options.mapVisible,
    },
    skeletonClassNames: {
      hidden: !options.skeletonVisible,
    },
  }
}

export function buildMapStageTimeVisualState(currentHour: number): MapStageTimeVisualState {
  const normalized = currentHour / 23
  const glowPeak = 1 - Math.abs(normalized - 0.55) / 0.55
  const bandPeak = 1 - Math.abs(normalized - 0.58) / 0.58

  return {
    timeProgressPercent: `${normalized * 100}%`,
    timeGlowOpacity: (0.08 + Math.max(0, glowPeak) * 0.18).toFixed(3),
    horizonPosition: `${12 + normalized * 76}%`,
    stageBandOpacity: (0.06 + Math.max(0, bandPeak) * 0.16).toFixed(3),
    stageGlowSpread: timeBandValue(currentHour, [
      { threshold: 6, value: '16rem' },
      { threshold: 11, value: '20rem' },
      { threshold: 17, value: '24rem' },
      { threshold: 20, value: '21rem' },
      { threshold: 24, value: '17rem' },
    ]),
    hotspotScale: timeBandValue(currentHour, [
      { threshold: 6, value: '0.88' },
      { threshold: 11, value: '0.96' },
      { threshold: 17, value: '1.08' },
      { threshold: 20, value: '0.98' },
      { threshold: 24, value: '0.9' },
    ]),
    hotspotHaloSize: timeBandValue(currentHour, [
      { threshold: 6, value: '8px' },
      { threshold: 11, value: '10px' },
      { threshold: 17, value: '12px' },
      { threshold: 20, value: '10px' },
      { threshold: 24, value: '8px' },
    ]),
    hotspotLabelOpacity: timeBandValue(currentHour, [
      { threshold: 6, value: '0.82' },
      { threshold: 11, value: '0.9' },
      { threshold: 17, value: '1' },
      { threshold: 20, value: '0.92' },
      { threshold: 24, value: '0.84' },
    ]),
  }
}
