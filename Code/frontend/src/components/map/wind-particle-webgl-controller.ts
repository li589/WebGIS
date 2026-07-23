/**
 * 风粒子 WebGL overlay 控制器。
 *
 * 与 `WindParticleOverlayController`（Canvas 2D）同构、实现同一
 * `WindParticleControllerContract` 契约，可通过 facade 的 DI seam 互换。
 *
 * 差异仅在「粒子渲染层」：Canvas 2D 的 `WindParticleCanvas` 被替换为
 * WebGL 的 `WindParticleWebGLLayer`（MapLibre CustomLayer + 独立 GL context）。
 * 等值线（WindContourLayer）、风羽（WindBarbLayer）与 fetch/token 生命周期
 * 与 Canvas 控制器对齐；风速色底仅在「关闭」模式由 Canvas 路径绘制。
 *
 * 若 WebGL 层初始化失败（无 context / 无顶点纹理 / shader 失败），
 * 自动委托给 Canvas 控制器，保证粒子流始终可用。
 */
import { WindBarbLayer } from './wind-barb-layer'
import { WindContourLayer } from './wind-contour-layer'
import { WindParticleOverlayController } from './wind-particle-overlay-controller'
import { WindParticleWebGLLayer } from './wind-particle-webgl-renderer'
import { removeWeatherMapArtifacts } from './weather-overlay-maplibre'
import { paletteToParticleColors, resolveCanonicalPaletteId } from './weather-render'
import type { WeatherOverlayState } from './weather-overlay-registry'
import type {
  WindParticleControllerContract,
  WindParticleSyncOptions,
} from './wind-particle-controller-contract'
import type { WindGeoJSON } from './types'

type MapInstance = import('maplibre-gl').Map

function debugLog(module: string, ...args: unknown[]) {
  console.log(`[${performance.now().toFixed(1)}ms] [${module}]`, ...args)
}

export class WindParticleWebGLOverlayController implements WindParticleControllerContract {
  private map: MapInstance
  private webglLayer: WindParticleWebGLLayer | null = null
  private windBarbLayer: WindBarbLayer | null = null
  private windContourLayer: WindContourLayer | null = null
  private currentWindGeojson: WindGeoJSON | null = null
  private lastWindGeojsonUrl: string | null = null
  private currentParticleFlowCatalogId: string | null = null
  private windParticleFetchToken = 0
  private windParticleFetchAbort: AbortController | null = null
  private styleLoadHandler: (() => void) | null = null
  /** WebGL 不可用时的 Canvas 回退（惰性创建） */
  private canvasFallback: WindParticleOverlayController | null = null
  /** 回退原因：gl 失败需常驻；streamline 可切回 WebGL particle */
  private fallbackReason: 'gl-failure' | 'streamline' | null = null
  private lastDisplayMode: import('./wind-display-mode').WindDisplayMode = 'particle'

  constructor(map: MapInstance) {
    this.map = map
  }

  get activeCatalogId() {
    return this.canvasFallback?.activeCatalogId ?? this.currentParticleFlowCatalogId
  }

  set activeCatalogId(catalogId: string | null) {
    this.currentParticleFlowCatalogId = catalogId
    if (this.canvasFallback) this.canvasFallback.activeCatalogId = catalogId
  }

  private ensureCanvasFallback(reason: 'gl-failure' | 'streamline'): WindParticleOverlayController {
    if (!this.canvasFallback) {
      debugLog('WindParticleWebGL', 'falling back to Canvas 2D', reason)
      if (reason === 'gl-failure') {
        // GL 不可用：立即销毁 WebGL 层和辅助层
        this.destroyWebGLLayer()
        if (this.windBarbLayer) {
          this.windBarbLayer.destroy()
          this.windBarbLayer = null
        }
        if (this.windContourLayer) {
          this.windContourLayer.destroy()
          this.windContourLayer = null
        }
      }
      // streamline 模式：不在此处销毁 WebGL 层，由 sync() 在 Canvas
      // 渲染就绪后调用 destroyWebGLLayerAndAuxiliaries() 销毁，消除视觉空窗
      this.canvasFallback = new WindParticleOverlayController(this.map)
      this.canvasFallback.activeCatalogId = this.currentParticleFlowCatalogId
      this.fallbackReason = reason
    } else if (reason === 'gl-failure') {
      this.fallbackReason = 'gl-failure'
    } else if (this.fallbackReason !== 'gl-failure') {
      this.fallbackReason = reason
    }
    return this.canvasFallback
  }

  /** 销毁 WebGL 粒子层和辅助层（barb/contour），用于 streamline 切换或数据清空 */
  private destroyWebGLLayerAndAuxiliaries() {
    if (this.webglLayer) {
      this.destroyWebGLLayer()
    }
    if (this.windBarbLayer) {
      this.windBarbLayer.destroy()
      this.windBarbLayer = null
    }
    if (this.windContourLayer) {
      this.windContourLayer.destroy()
      this.windContourLayer = null
    }
  }

  private clearStreamlineFallbackIfNeeded() {
    if (this.canvasFallback && this.fallbackReason === 'streamline') {
      this.canvasFallback.destroy()
      this.canvasFallback = null
      this.fallbackReason = null
    }
  }

  private useCanvasFallback(): boolean {
    return this.canvasFallback !== null
  }

  private abortPendingGeojsonFetch() {
    if (this.windParticleFetchAbort) {
      this.windParticleFetchAbort.abort()
      this.windParticleFetchAbort = null
    }
  }

  reset(options?: { invalidatePendingFetch?: boolean }) {
    debugLog(
      'WindParticleWebGL',
      'reset',
      'invalidatePendingFetch',
      options?.invalidatePendingFetch,
    )
    if (this.canvasFallback) {
      this.canvasFallback.reset(options)
      return
    }
    if (options?.invalidatePendingFetch !== false) {
      this.windParticleFetchToken++
      this.abortPendingGeojsonFetch()
    }
    this.destroyWebGLLayer()
    if (this.windBarbLayer) {
      this.windBarbLayer.destroy()
      this.windBarbLayer = null
    }
    if (this.windContourLayer) {
      this.windContourLayer.destroy()
      this.windContourLayer = null
    }
    this.currentWindGeojson = null
    this.lastWindGeojsonUrl = null
  }

  removeCatalogArtifacts(catalogId: string) {
    if (this.canvasFallback) {
      return this.canvasFallback.removeCatalogArtifacts(catalogId)
    }
    removeWeatherMapArtifacts(this.map, catalogId)
    if (this.currentParticleFlowCatalogId === catalogId) {
      this.reset()
      this.currentParticleFlowCatalogId = null
      return true
    }
    return false
  }

  private clearStyleLoadHandler() {
    if (!this.styleLoadHandler) return
    try {
      this.map.off('style.load', this.styleLoadHandler)
    } catch {
      /* map may already be destroyed */
    }
    this.styleLoadHandler = null
  }

  /** 幂等创建 WebGL 层并注册到 MapLibre（style 未就绪时排队到 style.load）。 */
  private ensureWebGLLayer(): WindParticleWebGLLayer {
    if (!this.webglLayer) {
      this.webglLayer = new WindParticleWebGLLayer()
    }
    const layer = this.webglLayer
    const tryAdd = () => {
      if (!this.webglLayer || this.webglLayer !== layer) return
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
        debugLog('WindParticleWebGL', 'addLayer failed', err)
        return
      }
      if (!layer.isUsable()) {
        debugLog('WindParticleWebGL', 'onAdd failed', layer.getFailureReason())
        try {
          this.map.removeLayer(layer.id)
        } catch {
          /* ignore */
        }
      }
    }
    if (this.map.isStyleLoaded()) {
      tryAdd()
      this.clearStyleLoadHandler()
    } else if (!this.styleLoadHandler) {
      this.styleLoadHandler = () => {
        this.clearStyleLoadHandler()
        tryAdd()
      }
      this.map.once('style.load', this.styleLoadHandler)
    }
    return this.webglLayer
  }

  private destroyWebGLLayer() {
    this.clearStyleLoadHandler()
    if (!this.webglLayer) return
    // map 可能已被销毁（map.destroy() 触发 controller.destroy() 链路），
    // 此时 getLayer/removeLayer 会抛错；用 try-catch 保护确保 dispose() 总能执行
    try {
      if (this.map.getLayer(this.webglLayer.id)) {
        this.map.removeLayer(this.webglLayer.id) // 触发 onRemove → teardown
      }
    } catch (err) {
      debugLog(
        'WindParticleWebGL',
        'destroyWebGLLayer: map already destroyed or layer missing',
        err,
      )
    }
    this.webglLayer.dispose() // 幂等兜底
    this.webglLayer = null
  }

  async sync(overlayState: WeatherOverlayState, options: WindParticleSyncOptions) {
    const displayMode = options.getWindDisplayMode?.() ?? 'particle'
    this.lastDisplayMode = displayMode

    if (displayMode === 'off' || displayMode === 'streamline') {
      // 关闭（仅色底）与流量场均走 Canvas 控制器
      await this.ensureCanvasFallback('streamline').sync(overlayState, options)
      // Canvas 渲染就绪后销毁 WebGL 粒子层和辅助层，消除视觉空窗：
      // 粒子 → 粒子+流线（瞬间）→ 流线
      this.destroyWebGLLayerAndAuxiliaries()
      return
    }

    // particle：若仅因 streamline/off 回退，切回 WebGL
    this.clearStreamlineFallbackIfNeeded()

    if (this.useCanvasFallback()) {
      await this.canvasFallback!.sync(overlayState, options)
      return
    }

    debugLog(
      'WindParticleWebGL',
      'sync start',
      'catalogId',
      overlayState.catalogId,
      'geojsonUrl',
      overlayState.geojsonUrl,
      'hasInlineGeojson',
      !!overlayState.geojsonData,
    )

    const catalogId = overlayState.catalogId

    if (
      options.overlayToken !== options.getSyncWeatherToken() ||
      this.currentParticleFlowCatalogId !== catalogId
    ) {
      return
    }

    const inlineGeojson =
      overlayState.geojsonData &&
      typeof overlayState.geojsonData === 'object' &&
      'features' in overlayState.geojsonData
        ? (overlayState.geojsonData as WindGeoJSON)
        : null

    // 视口切换后 merge 为空：清掉 WebGL 粒子，避免旧视口残留
    if (!inlineGeojson && !overlayState.geojsonUrl) {
      this.destroyWebGLLayerAndAuxiliaries()
      this.currentWindGeojson = null
      this.lastWindGeojsonUrl = null
      removeWeatherMapArtifacts(this.map, catalogId)
      return
    }

    const urlChanged = this.lastWindGeojsonUrl !== overlayState.geojsonUrl
    let geojson: WindGeoJSON | null = inlineGeojson ?? (urlChanged ? null : this.currentWindGeojson)
    this.abortPendingGeojsonFetch()
    const fetchToken = ++this.windParticleFetchToken
    const fetchAbort = new AbortController()
    this.windParticleFetchAbort = fetchAbort

    if (!inlineGeojson && urlChanged && overlayState.geojsonUrl) {
      try {
        const resp = await fetch(overlayState.geojsonUrl, { signal: fetchAbort.signal })
        if (!resp.ok) {
          console.warn('[WindParticleWebGL] sync: fetch failed status=%d', resp.status)
          return
        }
        const fetchedGeojson = (await resp.json()) as WindGeoJSON
        if (
          options.overlayToken !== options.getSyncWeatherToken() ||
          fetchToken !== this.windParticleFetchToken ||
          this.currentParticleFlowCatalogId !== catalogId ||
          options.getEnabledParticleFlowCatalogId() !== catalogId
        ) {
          return
        }
        geojson = fetchedGeojson
        this.currentWindGeojson = fetchedGeojson
        this.lastWindGeojsonUrl = overlayState.geojsonUrl
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') {
          debugLog('WindParticleWebGL', 'sync fetch aborted')
          return
        }
        console.error('[WindParticleWebGL] sync: fetch error', err)
        return
      } finally {
        if (this.windParticleFetchAbort === fetchAbort) {
          this.windParticleFetchAbort = null
        }
      }
    }

    if (inlineGeojson) {
      this.currentWindGeojson = inlineGeojson
      this.lastWindGeojsonUrl = overlayState.geojsonUrl
    }

    if (
      options.overlayToken !== options.getSyncWeatherToken() ||
      fetchToken !== this.windParticleFetchToken ||
      this.currentParticleFlowCatalogId !== catalogId ||
      options.getEnabledParticleFlowCatalogId() !== catalogId
    ) {
      return
    }

    if (!geojson) {
      debugLog('WindParticleWebGL', 'sync no geojson, skip')
      return
    }

    const enableBarbLayer = overlayState.renderHint.paint_mode === 'barb'

    // 冗余更新短路：数据未变且各层就绪时跳过（粒子模式不叠风速底色）
    if (
      !urlChanged &&
      !inlineGeojson &&
      this.webglLayer &&
      this.windContourLayer &&
      (!enableBarbLayer || this.windBarbLayer)
    ) {
      return
    }

    // 仅首次建层时清掉 fill/point 等冲突层（含关闭态留下的色底）；更新时就地 setWindData
    if (!this.webglLayer || !this.windContourLayer) {
      removeWeatherMapArtifacts(this.map, catalogId)
    }

    if (!this.windContourLayer) {
      this.windContourLayer = new WindContourLayer(this.map, geojson)
    } else {
      this.windContourLayer.updateGeoJSON(geojson)
    }
    // 等值线仅作极淡结构参考
    this.windContourLayer.setOpacity(0.06)

    // 粒子层（WebGL）：首次注册 + 喂数据；更新时就地 setWindData
    const layer = this.ensureWebGLLayer()
    if (!layer.isUsable()) {
      debugLog('WindParticleWebGL', 'layer unusable, reason=', layer.getFailureReason())
      await this.ensureCanvasFallback('gl-failure').sync(overlayState, options)
      return
    }
    layer.setWindData(geojson)
    layer.start()
    if (!layer.isUsable()) {
      debugLog('WindParticleWebGL', 'unusable after start', layer.getFailureReason())
      await this.ensureCanvasFallback('gl-failure').sync(overlayState, options)
      return
    }

    // 粒子配色：提亮后的 palette 色（深色底图可见）
    const paletteId = resolveCanonicalPaletteId(overlayState.renderHint?.palette) || 'wind-blue'
    const particleColors = paletteToParticleColors(paletteId)
    if (particleColors.length >= 2) {
      layer.setColors(particleColors)
    }

    if (enableBarbLayer) {
      if (!this.windBarbLayer) {
        this.windBarbLayer = new WindBarbLayer(this.map, geojson)
      } else {
        this.windBarbLayer.updateGeoJSON(geojson)
      }
    } else if (this.windBarbLayer) {
      debugLog('WindParticleWebGL', 'destroy unused barb layer')
      this.windBarbLayer.destroy()
      this.windBarbLayer = null
    }

    debugLog('WindParticleWebGL', 'sync layers updated', 'barbPresent', !!this.windBarbLayer)
  }

  destroy() {
    if (this.canvasFallback) {
      this.canvasFallback.destroy()
      this.canvasFallback = null
      this.fallbackReason = null
    }
    this.reset()
    this.currentParticleFlowCatalogId = null
  }
}
