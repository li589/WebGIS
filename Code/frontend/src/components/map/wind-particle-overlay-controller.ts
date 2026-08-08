import { WindBarbLayer } from './wind-barb-layer'
import { WindContourLayer } from './wind-contour-layer'
import { WindParticleCanvas } from './wind-particle-canvas'
import { WindStreamlineLayer } from './wind-streamline-layer'
import type { WindDisplayMode } from './wind-display-mode'
import { removeWeatherMapArtifacts } from './weather-overlay-maplibre'
import { syncWeatherSpeedUnderlay } from './weather-overlay-renderers'
import { paletteToParticleColors, resolveCanonicalPaletteId } from './weather-render'
import type { WeatherOverlayState } from './weather-overlay-registry'
import type { WindGeoJSON } from './types'
import { lonFrameFromViewportBounds } from './lon-frame'
import { shouldUseSmoothWindOffUnderlay } from './wind-off-underlay'
import type { WindParticleSyncOptions } from './wind-particle-controller-contract'
import { debugLog } from '../../utils/perf-probe'

type MapInstance = import('maplibre-gl').Map

function windDebugLog(module: string, ...args: unknown[]) {
  debugLog(`[${performance.now().toFixed(1)}ms] [${module}]`, ...args)
}

export class WindParticleOverlayController {
  private map: MapInstance
  private windParticleCanvas: WindParticleCanvas | null = null
  private windStreamlineLayer: WindStreamlineLayer | null = null
  private windBarbLayer: WindBarbLayer | null = null
  private windContourLayer: WindContourLayer | null = null
  private currentWindGeojson: WindGeoJSON | null = null
  private lastWindGeojsonUrl: string | null = null
  private currentParticleFlowCatalogId: string | null = null
  private windParticleFetchToken = 0
  private windParticleFetchAbort: AbortController | null = null
  private lastDisplayMode: WindDisplayMode = 'particle'
  /** 全屏面板盖住地图时暂停粒子/流量场 RAF */
  private animationPaused = false
  /** 快速切换模式时作废过期 sync，避免色底与粒子叠绘 */
  private applyGeneration = 0

  constructor(map: MapInstance) {
    this.map = map
  }

  get activeCatalogId() {
    return this.currentParticleFlowCatalogId
  }

  set activeCatalogId(catalogId: string | null) {
    this.currentParticleFlowCatalogId = catalogId
  }

  setAnimationPaused(paused: boolean) {
    if (this.animationPaused === paused) return
    this.animationPaused = paused
    this.windParticleCanvas?.setAnimationPaused(paused)
    this.windStreamlineLayer?.setAnimationPaused(paused)
  }

  private abortPendingGeojsonFetch() {
    if (this.windParticleFetchAbort) {
      this.windParticleFetchAbort.abort()
      this.windParticleFetchAbort = null
    }
  }

  private destroyParticleCanvas() {
    if (this.windParticleCanvas) {
      this.windParticleCanvas.destroy()
      this.windParticleCanvas = null
    }
  }

  private destroyStreamlineLayer() {
    if (this.windStreamlineLayer) {
      this.windStreamlineLayer.destroy()
      this.windStreamlineLayer = null
    }
  }

  private destroyAuxLayers() {
    if (this.windBarbLayer) {
      this.windBarbLayer.destroy()
      this.windBarbLayer = null
    }
    if (this.windContourLayer) {
      this.windContourLayer.destroy()
      this.windContourLayer = null
    }
  }

  reset(options?: { invalidatePendingFetch?: boolean }) {
    windDebugLog(
      'WindParticleController',
      'reset',
      'invalidatePendingFetch',
      options?.invalidatePendingFetch,
    )
    if (options?.invalidatePendingFetch !== false) {
      this.windParticleFetchToken++
      this.abortPendingGeojsonFetch()
    }
    this.destroyParticleCanvas()
    this.destroyStreamlineLayer()
    this.destroyAuxLayers()
    this.currentWindGeojson = null
    this.lastWindGeojsonUrl = null
    this.applyGeneration++
  }

  removeCatalogArtifacts(catalogId: string) {
    removeWeatherMapArtifacts(this.map, catalogId)
    if (this.currentParticleFlowCatalogId === catalogId) {
      this.reset()
      this.currentParticleFlowCatalogId = null
      return true
    }
    return false
  }

  private stillCurrent(
    options: {
      overlayToken: number
      getSyncWeatherToken: () => number
      getEnabledParticleFlowCatalogId: () => string | null
    },
    catalogId: string,
    fetchToken?: number,
  ) {
    if (options.overlayToken !== options.getSyncWeatherToken()) return false
    if (this.currentParticleFlowCatalogId !== catalogId) return false
    if (options.getEnabledParticleFlowCatalogId() !== catalogId) return false
    if (fetchToken !== undefined && fetchToken !== this.windParticleFetchToken) return false
    return true
  }

  /** 比较两次 inline geojson 是否需要重绘（避免引用相同但内容已变时漏更） */
  private geojsonNeedsUpdate(next: WindGeoJSON | null): boolean {
    const prev = this.currentWindGeojson
    if (!next) return !!prev
    if (!prev) return true
    if (prev === next) return false
    const prevN = Array.isArray(prev.features) ? prev.features.length : 0
    const nextN = Array.isArray(next.features) ? next.features.length : 0
    return prevN !== nextN || prev !== next
  }

  async sync(overlayState: WeatherOverlayState, options: WindParticleSyncOptions) {
    const catalogId = overlayState.catalogId
    const applyGen = ++this.applyGeneration
    const displayMode: WindDisplayMode = options.getWindDisplayMode?.() ?? 'particle'

    const isStale = () =>
      applyGen !== this.applyGeneration ||
      !this.stillCurrent(options, catalogId) ||
      (options.getWindDisplayMode?.() ?? 'particle') !== displayMode

    if (isStale()) return

    const inlineGeojson =
      overlayState.geojsonData &&
      typeof overlayState.geojsonData === 'object' &&
      'features' in overlayState.geojsonData
        ? (overlayState.geojsonData as WindGeoJSON)
        : null

    // 视口切换后 merge 可能短暂为 null。保留已有粒子层和最后一份 GeoJSON，
    // 等新瓦片到达后就地更新；不要把一次调度空窗升级成 destroy/recreate 闪烁。
    // 真正关闭/删除图层时由 reset()/removeCatalogArtifacts() 显式清理。
    if (!inlineGeojson && !overlayState.geojsonUrl) {
      if (this.currentWindGeojson || this.windParticleCanvas || this.windStreamlineLayer) {
        windDebugLog(
          'WindParticleController',
          'transient empty viewport data; keep last wind frame',
        )
      }
      return
    }

    let geojson = this.currentWindGeojson
    let dataChanged = false

    if (inlineGeojson) {
      dataChanged = this.geojsonNeedsUpdate(inlineGeojson)
      geojson = inlineGeojson
      this.currentWindGeojson = inlineGeojson
      this.lastWindGeojsonUrl = overlayState.geojsonUrl
    } else if (overlayState.geojsonUrl && overlayState.geojsonUrl !== this.lastWindGeojsonUrl) {
      dataChanged = true
      this.lastWindGeojsonUrl = overlayState.geojsonUrl
      const fetchToken = ++this.windParticleFetchToken
      this.abortPendingGeojsonFetch()
      const abort = new AbortController()
      this.windParticleFetchAbort = abort
      try {
        const resp = await fetch(overlayState.geojsonUrl, { signal: abort.signal })
        if (!resp.ok) throw new Error(`wind geojson ${resp.status}`)
        geojson = (await resp.json()) as WindGeoJSON
      } catch (err) {
        if ((err as Error)?.name === 'AbortError') return
        windDebugLog('WindParticleController', 'fetch failed', err)
        return
      } finally {
        if (this.windParticleFetchAbort === abort) this.windParticleFetchAbort = null
      }
      if (isStale() || fetchToken !== this.windParticleFetchToken) return
      this.currentWindGeojson = geojson
    }

    if (isStale()) return
    if (!geojson) return

    const modeChanged = displayMode !== this.lastDisplayMode
    this.lastDisplayMode = displayMode

    // ── 网格（off）：仅风速色底，无粒子/流线/等值线 ───────────────────────
    if (displayMode === 'off') {
      this.destroyParticleCanvas()
      this.destroyStreamlineLayer()
      this.destroyAuxLayers()
      if (isStale()) return
      const underlayState: WeatherOverlayState = {
        ...overlayState,
        geojsonData: geojson,
        opacity: Math.min(1, Math.max(0.55, overlayState.opacity * 1.05)),
      }
      const wantSmooth = shouldUseSmoothWindOffUnderlay(
        options.getSmoothRendering?.() ?? true,
        typeof options.syncSmoothScalarUnderlay === 'function',
      )
      if (wantSmooth) {
        removeWeatherMapArtifacts(this.map, catalogId)
        if (isStale()) return
        const ok = options.syncSmoothScalarUnderlay!(underlayState)
        if (isStale()) {
          // 已切回粒子流：拆掉刚画的平滑色底
          options.clearSmoothScalarUnderlay?.(catalogId)
          return
        }
        if (!ok) {
          options.clearSmoothScalarUnderlay?.(catalogId)
          syncWeatherSpeedUnderlay(this.map, underlayState)
        }
      } else {
        options.clearSmoothScalarUnderlay?.(catalogId)
        if (isStale()) return
        syncWeatherSpeedUnderlay(this.map, underlayState)
      }
      return
    }

    // 粒子 / 流量场：始终清掉网格色底残留（含快速切换竞态）
    options.clearSmoothScalarUnderlay?.(catalogId)
    removeWeatherMapArtifacts(this.map, catalogId)

    const enableBarbLayer = overlayState.renderHint.paint_mode === 'barb'
    const useStreamline = displayMode === 'streamline'
    const useParticle = displayMode === 'particle'

    if (useStreamline) this.destroyParticleCanvas()
    if (useParticle) this.destroyStreamlineLayer()

    const hasVisualLayer = useParticle ? !!this.windParticleCanvas : !!this.windStreamlineLayer

    // 粒子/流量场：不叠风速底色；数据未变且层已就绪时仍刷新 LonFrame（日界线半球）
    if (
      !dataChanged &&
      !modeChanged &&
      hasVisualLayer &&
      this.windContourLayer &&
      (!enableBarbLayer || this.windBarbLayer)
    ) {
      const lonFrame = lonFrameFromViewportBounds(
        overlayState.viewportBounds ?? null,
        this.map.getCenter().lng,
      )
      if (useParticle && this.windParticleCanvas) {
        this.windParticleCanvas.updateGeoJSON(geojson, lonFrame)
      } else if (useStreamline && this.windStreamlineLayer) {
        this.windStreamlineLayer.updateGeoJSON(geojson, lonFrame)
      }
      return
    }

    if (!hasVisualLayer || !this.windContourLayer || modeChanged) {
      removeWeatherMapArtifacts(this.map, catalogId)
    }

    if (isStale()) return

    if (!this.windContourLayer) {
      this.windContourLayer = new WindContourLayer(this.map, geojson)
    } else {
      this.windContourLayer.updateGeoJSON(geojson)
    }
    this.windContourLayer.setOpacity(useStreamline ? 0.1 : 0.06)

    const lonFrame = lonFrameFromViewportBounds(
      overlayState.viewportBounds ?? null,
      this.map.getCenter().lng,
    )

    if (useParticle) {
      if (!this.windParticleCanvas) {
        this.windParticleCanvas = new WindParticleCanvas(this.map, geojson, undefined, lonFrame)
        this.windParticleCanvas.setAnimationPaused(this.animationPaused)
        this.windParticleCanvas.start()
      } else {
        this.windParticleCanvas.updateGeoJSON(geojson, lonFrame)
      }
      const paletteId = resolveCanonicalPaletteId(overlayState.renderHint?.palette) || 'wind-blue'
      const particleColors = paletteToParticleColors(paletteId)
      if (particleColors.length >= 2) {
        this.windParticleCanvas.setColors(particleColors)
      }
    } else if (useStreamline) {
      if (!this.windStreamlineLayer) {
        this.windStreamlineLayer = new WindStreamlineLayer(this.map, geojson, lonFrame)
        this.windStreamlineLayer.setAnimationPaused(this.animationPaused)
        this.windStreamlineLayer.start()
      } else {
        this.windStreamlineLayer.updateGeoJSON(geojson, lonFrame)
      }
    }

    if (enableBarbLayer && useParticle) {
      if (!this.windBarbLayer) {
        this.windBarbLayer = new WindBarbLayer(this.map, geojson)
      } else {
        this.windBarbLayer.updateGeoJSON(geojson)
      }
    } else if (this.windBarbLayer) {
      this.windBarbLayer.destroy()
      this.windBarbLayer = null
    }
  }

  destroy() {
    this.reset()
    this.currentParticleFlowCatalogId = null
  }
}
