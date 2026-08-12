import type { MapOptions, StyleSpecification } from 'maplibre-gl'

import { getMapDefaults } from '../../services/map-defaults'

interface CreateMapCanvasMapOptionsOptions {
  container: HTMLElement
}

export function createMapCanvasMapOptions(options: CreateMapCanvasMapOptionsOptions): MapOptions {
  const mapDefaults = getMapDefaults()
  return {
    container: options.container,
    style: {
      version: 8,
      sources: {},
      layers: [
        { id: 'background', type: 'background', paint: { 'background-color': 'var(--surface-1)' } },
      ],
    } as StyleSpecification,
    center: [mapDefaults.longitude, mapDefaults.latitude],
    zoom: mapDefaults.zoom,
    pitch: 0,
    bearing: 0,
    attributionControl: false,
    // 允许全球浏览：世界在东西方向重复渲染，用户可拖动到任意经度
    renderWorldCopies: true,
    cancelPendingTileRequestsWhileZooming: true,
    refreshExpiredTiles: false,
    canvasContextAttributes: {
      // preserveDrawingBuffer=false（默认）：不回读 framebuffer，大幅提升与 Canvas 2D 叠加层的合成性能
      // 截图：captureMapCanvas() 在 MapLibre `render` 事件回调内同步 toDataURL（无公开 Map.render）
      preserveDrawingBuffer: false,
    },
  }
}
