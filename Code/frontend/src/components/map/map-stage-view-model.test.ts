import { describe, expect, it } from 'vitest'

import {
  buildMapStageAppearanceModel,
  buildMapStageDisplayModel,
  buildFallbackActiveLayerDisplay,
  buildMapStageStatusModel,
  buildMapStageTimeVisualState,
} from './map-stage-view-model'

describe('map-stage-view-model', () => {
  it('builds fallback active layer display', () => {
    expect(buildFallbackActiveLayerDisplay()).toMatchObject({
      name: '暂无图层',
      availabilityState: 'empty',
      availabilityLabel: '空状态',
      metricLabel: '—',
      metricValue: '—',
      hotspots: [],
      isAdminBoundary: false,
      visible: true,
      opacity: 1,
      dataState: 'catalog',
    })
  })

  it('builds stage display model from current basemap and active layer', () => {
    expect(
      buildMapStageDisplayModel({
        basemapProvider: 'Esri',
        basemapLabel: 'Street',
        hourLabel: '12:00',
        activeLayer: {
          ...buildFallbackActiveLayerDisplay(),
          name: '风场图层',
          availabilityState: 'partial',
          availabilityLabel: '加载中',
          observationTimeLabel: '11:45',
          trendLabel: '等待工作流返回结果',
        },
      }),
    ).toEqual({
      basemapChipLabel: 'Esri · Street',
      hourChipLabel: '12:00',
      layerChipLabel: '风场图层',
      availabilityChipLabel: '加载中',
      availabilityChipClass: 'chip-partial',
      noteTitle: '风场图层',
      noteSummary: '等待工作流返回结果',
      noteMeta: '11:45 · 加载中',
      hotspotLayerClass: 'hotspot-layer-partial',
    })
  })

  it('builds stage status model for loading and tile error banner', () => {
    expect(
      buildMapStageStatusModel({
        mapReady: false,
        loadingLabel: '正在加载地图引擎...',
        tileLoadFailed: true,
        tileFailedProvider: 'Esri',
      }),
    ).toEqual({
      showLoading: true,
      loadingLabel: '正在加载地图引擎...',
      showTileError: true,
      tileErrorMessage: '底图「Esri」加载失败（需要配置 API Key 或网络不可达）',
      retryButtonLabel: '重试',
    })
  })

  it('builds stage appearance model from basemap, layer state and stage flags', () => {
    expect(
      buildMapStageAppearanceModel({
        basemapStyle: 'satellite',
        activeLayer: {
          ...buildFallbackActiveLayerDisplay(),
          availabilityState: 'partial',
          accentColor: '#12abef',
          accentGlow: 'rgba(18, 171, 239, 0.32)',
          chipTone: 'rgba(18, 171, 239, 0.12)',
        },
        timeVisualState: buildMapStageTimeVisualState(12),
        isMapInteracting: true,
        isSourceTransitioning: false,
        mapVisible: true,
        skeletonVisible: false,
      }),
    ).toEqual({
      usesLightNavigationTheme: true,
      stageClassNames: {
        'map-stage-interacting': true,
        'map-stage-transitioning': false,
        'map-stage-light': true,
        'map-stage-dark': false,
        'map-stage-partial': true,
      },
      stageStyleVars: {
        '--accent-color': '#12abef',
        '--accent-glow': 'rgba(18, 171, 239, 0.32)',
        '--chip-tone': 'rgba(18, 171, 239, 0.12)',
        '--time-progress': `${(12 / 23) * 100}%`,
        '--time-glow-opacity': '0.251',
        '--horizon-position': `${12 + (12 / 23) * 76}%`,
        '--stage-band-opacity': '0.204',
        '--stage-glow-spread': '24rem',
        '--hotspot-scale': '1.08',
        '--hotspot-halo-size': '12px',
        '--hotspot-label-opacity': '1',
      },
      mapHostClassNames: {
        visible: true,
      },
      skeletonClassNames: {
        hidden: true,
      },
    })
  })

  it('builds time visual state from current hour', () => {
    expect(buildMapStageTimeVisualState(12)).toEqual({
      timeProgressPercent: `${(12 / 23) * 100}%`,
      timeGlowOpacity: '0.251',
      horizonPosition: `${12 + (12 / 23) * 76}%`,
      stageBandOpacity: '0.204',
      stageGlowSpread: '24rem',
      hotspotScale: '1.08',
      hotspotHaloSize: '12px',
      hotspotLabelOpacity: '1',
    })
  })
})
