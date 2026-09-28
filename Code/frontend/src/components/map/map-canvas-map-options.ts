import type { MapOptions, StyleSpecification } from 'maplibre-gl'

import { getMapDefaults } from '../../services/map-defaults'

interface CreateMapCanvasMapOptionsOptions {
  container: HTMLElement
}

/**
 * 从 :root 读取 CSS 变量的实际计算值， fallback 到暗色默认。
 * MapLibre GL JS 的 WebGL 渲染器不支持 CSS 自定义属性（var(--xxx)），
 * 必须传入字面量颜色值。
 */
export function resolveSurfaceColor(varName = '--surface-1'): string {
  if (typeof document === 'undefined') return '#0b1a2a'
  const value = getComputedStyle(document.documentElement).getPropertyValue(varName).trim()
  return value || '#0b1a2a'
}

/**
 * 解析 background layer 颜色（globe 感知）。
 *
 * - 2D：--surface-1（原行为，地图画布底色）
 * - 3D globe：深空蓝（暗色主题）/浅蓝灰（浅色主题）——background layer 在
 *   globe 投影下渲染于球面，作为"无瓦片区域兜底色"（高德等仅覆盖中国的源
 *   拖到南半球时避免露出 --surface-1 导致球面发白发灰）；球外区域保持
 *   透明，让 GlobeStarfield 星图层透出。
 */
export function resolveGlobeBackgroundColor(isGlobe: boolean, isLightTheme: boolean): string {
  if (!isGlobe) return resolveSurfaceColor()
  return isLightTheme ? '#c3d0de' : '#0d2436'
}

export function createMapCanvasMapOptions(options: CreateMapCanvasMapOptionsOptions): MapOptions {
  const mapDefaults = getMapDefaults()
  return {
    container: options.container,
    style: {
      version: 8,
      sources: {},
      layers: [
        {
          id: 'background',
          type: 'background',
          paint: { 'background-color': resolveSurfaceColor() },
        },
      ],
    } as StyleSpecification,
    center: [mapDefaults.longitude, mapDefaults.latitude],
    zoom: mapDefaults.zoom,
    pitch: 0,
    bearing: 0,
    attributionControl: false,
    // 只渲染一份世界：不再东西方向重复世界副本，拖动到 ±180° 边界即停住
    // （全球覆盖的叠加层如 smap-aux-h 此前会在 ±360° 各重复一份）
    renderWorldCopies: false,
    cancelPendingTileRequestsWhileZooming: true,
    refreshExpiredTiles: false,
    canvasContextAttributes: {
      // preserveDrawingBuffer=false（默认）：不回读 framebuffer，大幅提升与 Canvas 2D 叠加层的合成性能
      // 截图：captureMapCanvas() 在 MapLibre `render` 事件回调内同步 toDataURL（无公开 Map.render）
      preserveDrawingBuffer: false,
    },
  }
}
