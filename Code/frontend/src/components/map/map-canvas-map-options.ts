import type { MapOptions, StyleSpecification } from 'maplibre-gl'

interface CreateMapCanvasMapOptionsOptions {
  container: HTMLElement
}

export function createMapCanvasMapOptions(options: CreateMapCanvasMapOptionsOptions): MapOptions {
  return {
    container: options.container,
    style: {
      version: 8,
      sources: {},
      layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#07111e' } }],
    } as StyleSpecification,
    center: [113.2644, 23.1291],
    zoom: 4.8,
    pitch: 0,
    bearing: 0,
    attributionControl: false,
    // 允许全球浏览：世界在东西方向重复渲染，用户可拖动到任意经度
    renderWorldCopies: true,
    cancelPendingTileRequestsWhileZooming: true,
    refreshExpiredTiles: false,
    canvasContextAttributes: {
      // preserveDrawingBuffer=false（默认）：不回读 framebuffer，大幅提升与 Canvas 2D 叠加层的合成性能
      // 截图改用 captureMapCanvas() 在 render() 后同步读取
      preserveDrawingBuffer: false,
    },
  }
}
