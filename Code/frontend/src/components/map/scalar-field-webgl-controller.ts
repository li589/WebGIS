/**
 * 标量场 WebGL 控制器：grid_fill 优先路径；失败回退由 registry 走 MapLibre fill。
 * 内置 400ms 时次交叉淡入；pressure 叠加 ScalarContourLayer。
 */
import { removeWeatherMapArtifacts, buildWeatherOverlayIds } from './weather-overlay-maplibre'
import type { WeatherOverlayState } from './weather-overlay-registry'
import { buildScalarGridFromGeoJSON, resolveScalarValueRange } from './scalar-field-grid'
import { ScalarFieldWebGLLayer, probeScalarFieldWebGLSupport } from './scalar-field-webgl-renderer'
import { buildPaletteLUT, encodeScalarGridToRGBA } from './scalar-field-webgl-texture'
import { getPaletteColors, getWeatherFillOpacity } from './weather-render'
import {
  ScalarContourLayer,
  buildPressureIsobarLevels,
  buildWeakScalarContourLevels,
  isWeakContourLayerId,
} from './scalar-contour-layer'
import type { WindGeoJSON } from './types'

type MapInstance = import('maplibre-gl').Map

const CROSSFADE_MS = 400

export interface ScalarFieldSyncOptions {
  overlayToken: number
  getSyncWeatherToken: () => number
}

function isScalarGlDisabled(): boolean {
  try {
    return new URLSearchParams(window.location.search).get('scalargl') === '0'
  } catch {
    return false
  }
}

function asWindGeoJSON(data: WeatherOverlayState['geojsonData']): WindGeoJSON | null {
  if (!data || typeof data === 'string') return null
  if (data.type !== 'FeatureCollection' || !Array.isArray(data.features)) return null
  return data as WindGeoJSON
}

export class ScalarFieldWebGLController {
  private map: MapInstance
  private layers = new Map<string, ScalarFieldWebGLLayer>()
  private contours = new Map<string, ScalarContourLayer>()
  private styleHandlers = new Map<string, () => void>()
  private lastChecksum = new Map<string, number>()
  /** 各 catalog 最近一次上传的 grid bounds；bounds 变化（覆盖扩张/收缩）时不做 crossfade */
  private lastBounds = new Map<
    string,
    { west: number; south: number; east: number; north: number }
  >()
  private webglOk: boolean | null = null

  constructor(map: MapInstance) {
    this.map = map
  }

  isAvailable(): boolean {
    if (isScalarGlDisabled()) return false
    if (this.webglOk === null) {
      this.webglOk = probeScalarFieldWebGLSupport().ok
    }
    return this.webglOk
  }

  /**
   * @returns true 表示已用 WebGL 渲染；false 表示应回退 MapLibre fill
   */
  sync(state: WeatherOverlayState, options: ScalarFieldSyncOptions): boolean {
    if (!this.isAvailable()) return false
    if (state.cogPreviewUrl && state.cogBbox) return false

    const opacity = getWeatherFillOpacity(state.renderHint, state.opacity)
    const geojson = asWindGeoJSON(state.geojsonData)

    // 灰底占位：无数据（首次加载/快照之外）但知道目标视口 → 仅画淡灰底，渐填颜色
    if (!geojson) {
      if (!state.viewportBounds) return false
      const layer = this.ensureLayer(state.catalogId)
      if (!layer || !layer.isUsable()) {
        this.removeCatalogArtifacts(state.catalogId)
        return false
      }
      layer.setOpacity(opacity)
      layer.setViewportBounds(state.viewportBounds)
      this.hideMapLibreFill(state.catalogId)
      return true
    }

    const metric = state.renderHint.primary_metric
    if (!metric) return false

    if (options.overlayToken !== options.getSyncWeatherToken()) return true

    const grid = buildScalarGridFromGeoJSON(geojson, metric)
    if (!grid) return false

    // 快速连点：构建网格后 token 已过期则 hold，不上传、不打断进行中的淡入
    if (options.overlayToken !== options.getSyncWeatherToken()) return true

    const range = resolveScalarValueRange(state.renderHint.legend_ticks, grid)
    const encoded = encodeScalarGridToRGBA(grid, range.min, range.max)
    const lut = buildPaletteLUT(getPaletteColors(state.renderHint.palette))

    const layer = this.ensureLayer(state.catalogId)
    if (!layer || !layer.isUsable()) {
      this.removeCatalogArtifacts(state.catalogId)
      return false
    }

    layer.setOpacity(opacity)
    layer.setPaletteLUT(lut)
    layer.setViewportBounds(state.viewportBounds ?? null)

    const prevChecksum = this.lastChecksum.get(state.catalogId)
    if (prevChecksum === grid.checksum) {
      // 同 checksum：不重复上传纹理
      return true
    }

    // 跨淡入仅用于「同一网格布局下的数值更新」（如时次切换）；
    // bounds 变化（瓦片覆盖扩张/收缩）直接硬切，避免流式到达期反复淡入闪烁
    const prevBounds = this.lastBounds.get(state.catalogId)
    const boundsChanged =
      !prevBounds ||
      prevBounds.west !== encoded.west ||
      prevBounds.east !== encoded.east ||
      prevBounds.south !== encoded.south ||
      prevBounds.north !== encoded.north
    const crossfadeMs = prevChecksum !== undefined && !boundsChanged ? CROSSFADE_MS : 0
    // 仅取消其它 token 的淡入；保留当前 token
    layer.cancelBlend(options.overlayToken)
    if (options.overlayToken !== options.getSyncWeatherToken()) return true
    layer.setFieldData(encoded, { crossfadeMs, token: options.overlayToken })
    this.lastChecksum.set(state.catalogId, grid.checksum)
    this.lastBounds.set(state.catalogId, {
      west: encoded.west,
      south: encoded.south,
      east: encoded.east,
      north: encoded.north,
    })

    // 隐藏同 catalog 的 MapLibre fill，避免双绘
    this.hideMapLibreFill(state.catalogId)

    const layerId = state.renderHint.layer_id || state.catalogId
    if (state.catalogId === 'pressure' || layerId === 'pressure') {
      this.syncPressureContour(state.catalogId, geojson, metric, state.renderHint.legend_ticks)
    } else if (isWeakContourLayerId(layerId) || isWeakContourLayerId(state.catalogId)) {
      this.syncWeakScalarContour(
        state.catalogId,
        geojson,
        metric,
        state.renderHint.legend_ticks,
        state.renderHint.unit_label,
        layerId,
      )
    } else {
      this.destroyContour(state.catalogId)
    }

    return true
  }

  removeCatalogArtifacts(catalogId: string): boolean {
    const layer = this.layers.get(catalogId)
    if (layer) {
      layer.destroy()
      this.layers.delete(catalogId)
    }
    this.destroyContour(catalogId)
    this.clearStyleHandler(catalogId)
    this.lastChecksum.delete(catalogId)
    this.lastBounds.delete(catalogId)
    removeWeatherMapArtifacts(this.map, catalogId)
    return Boolean(layer)
  }

  destroy(): void {
    for (const id of Array.from(this.layers.keys())) {
      this.removeCatalogArtifacts(id)
    }
  }

  private ensureLayer(catalogId: string): ScalarFieldWebGLLayer | null {
    let layer = this.layers.get(catalogId)
    if (layer) return layer

    layer = new ScalarFieldWebGLLayer(`scalar-field-webgl-${catalogId}`)
    this.layers.set(catalogId, layer)

    const tryAdd = () => {
      const current = this.layers.get(catalogId)
      if (!current || current !== layer) return
      if (!this.map.isStyleLoaded()) return
      if (this.map.getLayer(layer.id)) {
        if (!layer.isUsable()) {
          try {
            this.map.removeLayer(layer.id)
          } catch {
            /* ignore */
          }
        }
        return
      }
      try {
        this.map.addLayer(layer)
      } catch (err) {
        console.warn('[ScalarFieldWebGL] addLayer failed', err)
      }
    }

    tryAdd()
    if (!this.map.getLayer(layer.id)) {
      const handler = () => {
        tryAdd()
        this.clearStyleHandler(catalogId)
      }
      this.styleHandlers.set(catalogId, handler)
      this.map.on('style.load', handler)
    }
    return layer
  }

  private clearStyleHandler(catalogId: string): void {
    const handler = this.styleHandlers.get(catalogId)
    if (!handler) return
    try {
      this.map.off('style.load', handler)
    } catch {
      /* ignore */
    }
    this.styleHandlers.delete(catalogId)
  }

  private hideMapLibreFill(catalogId: string): void {
    const ids = buildWeatherOverlayIds(catalogId)
    try {
      if (this.map.getLayer(ids.fillLayerId)) {
        this.map.setLayoutProperty(ids.fillLayerId, 'visibility', 'none')
      }
      if (this.map.getLayer(ids.lineLayerId)) {
        this.map.setLayoutProperty(ids.lineLayerId, 'visibility', 'none')
      }
    } catch {
      /* ignore */
    }
  }

  private syncPressureContour(
    catalogId: string,
    geojson: WindGeoJSON,
    metric: string,
    ticks: Array<number | string> | undefined,
  ): void {
    const levels = buildPressureIsobarLevels(ticks)
    let contour = this.contours.get(catalogId)
    if (!contour) {
      contour = new ScalarContourLayer(this.map, {
        metric,
        levels,
        unitLabel: 'hPa',
        opacity: 0.42,
      })
      this.contours.set(catalogId, contour)
    }
    contour.setData(geojson, { metric, levels })
  }

  private syncWeakScalarContour(
    catalogId: string,
    geojson: WindGeoJSON,
    metric: string,
    ticks: Array<number | string> | undefined,
    unitLabel: string | undefined,
    layerId: string,
  ): void {
    const isPrecip = layerId.includes('precip')
    const levels = buildWeakScalarContourLevels(ticks, {
      fallbackMin: isPrecip ? 0 : -10,
      fallbackMax: isPrecip ? 40 : 35,
      targetCount: isPrecip ? 5 : 6,
      alpha: isPrecip ? 0.16 : 0.2,
    })
    let contour = this.contours.get(catalogId)
    if (!contour) {
      contour = new ScalarContourLayer(this.map, {
        metric,
        levels,
        unitLabel: unitLabel ?? '',
        opacity: 0.28,
      })
      this.contours.set(catalogId, contour)
    }
    contour.setData(geojson, { metric, levels })
  }

  private destroyContour(catalogId: string): void {
    const c = this.contours.get(catalogId)
    if (!c) return
    c.destroy()
    this.contours.delete(catalogId)
  }
}
