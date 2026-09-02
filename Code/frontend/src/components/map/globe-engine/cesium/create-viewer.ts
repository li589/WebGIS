/**
 * Cesium Viewer 创建 / 销毁 + 底图 / 光影 / overlay 瓦片热更新。
 */
import type { TileSourceId } from '../../../../services/api-config'
import type { GlobeDaylightMode } from '../../../../services/settings-local'
import type { GlobeEngineHost } from '../types'
import { boundsCenterAndHeight, type LngLatBoundsTuple } from '../layer-extent'
import { ensureCesiumBaseUrl } from './base-url'
import { normalizeCesiumTileUrl, resolveCesiumBasemap } from './basemap-adapter'
import { applyCesiumDaylight } from './lighting'
import type { CesiumOverlayTileSpec } from './overlay-tiles-adapter'

type CesiumModule = typeof import('cesium')
type CesiumViewer = import('cesium').Viewer

export interface CesiumViewerOptions {
  tileSourceId: TileSourceId
  daylightMode: GlobeDaylightMode
  hour: number
  date?: Date | null
  /** 初始视口（引擎互切桥） */
  initialView?: { lng: number; lat: number; heightMeters: number } | null
}

export interface CesiumViewerHandle extends GlobeEngineHost {
  kind: 'cesium'
  getViewer(): CesiumViewer | null
  setBasemap(sourceId: TileSourceId): void
  setDaylight(mode: GlobeDaylightMode, hour: number, date?: Date | null): void
  syncOverlayImagery(specs: ReadonlyArray<CesiumOverlayTileSpec>): void
  flyTo(lng: number, lat: number, heightMeters?: number): void
  flyToBounds(bounds: LngLatBoundsTuple): void
  captureView(): { lng: number; lat: number; heightMeters: number } | null
}

export async function createCesiumViewer(
  container: HTMLElement,
  options: CesiumViewerOptions,
): Promise<CesiumViewerHandle> {
  ensureCesiumBaseUrl()
  await import('cesium/Build/Cesium/Widgets/widgets.css')
  const Cesium: CesiumModule = await import('cesium')

  // skyAtmosphere 勿传 true：Cesium 会把布尔值赋给 scene.skyAtmosphere，随后 EventHelper
  // 会抛 Expected listener to be typeof function, actual typeof was undefined。
  // 省略该选项即可使用默认 SkyAtmosphere 实例；skyBox:false 关闭星盒但仍保留地球大气。
  const viewer = new Cesium.Viewer(container, {
    animation: false,
    timeline: false,
    baseLayerPicker: false,
    geocoder: false,
    homeButton: false,
    sceneModePicker: false,
    navigationHelpButton: false,
    fullscreenButton: false,
    infoBox: false,
    selectionIndicator: false,
    baseLayer: false,
    skyBox: false,
    terrainProvider: new Cesium.EllipsoidTerrainProvider(),
  })

  let basemapLayerCount = 0
  let lastOverlaySpecs: CesiumOverlayTileSpec[] = []

  function rebuildBasemap(sourceId: TileSourceId): void {
    viewer.imageryLayers.removeAll()
    const spec = resolveCesiumBasemap(sourceId)
    if (spec.urlTemplate) {
      const main = new Cesium.UrlTemplateImageryProvider({
        url: normalizeCesiumTileUrl(spec.urlTemplate),
        maximumLevel: spec.maximumLevel,
        credit: spec.credit || undefined,
      })
      viewer.imageryLayers.addImageryProvider(main)
      if (spec.overlayUrlTemplate) {
        viewer.imageryLayers.addImageryProvider(
          new Cesium.UrlTemplateImageryProvider({
            url: normalizeCesiumTileUrl(spec.overlayUrlTemplate),
            maximumLevel: spec.maximumLevel,
          }),
        )
      }
    }
    basemapLayerCount = viewer.imageryLayers.length
    applyOverlaySpecs(lastOverlaySpecs)
  }

  function applyOverlaySpecs(specs: ReadonlyArray<CesiumOverlayTileSpec>): void {
    lastOverlaySpecs = [...specs]
    while (viewer.imageryLayers.length > basemapLayerCount) {
      const last = viewer.imageryLayers.get(viewer.imageryLayers.length - 1)
      viewer.imageryLayers.remove(last, false)
    }
    for (const spec of specs) {
      const provider = new Cesium.UrlTemplateImageryProvider({
        url: normalizeCesiumTileUrl(spec.urlTemplate),
        maximumLevel: spec.maximumLevel,
      })
      const layer = viewer.imageryLayers.addImageryProvider(provider)
      layer.alpha = spec.opacity
    }
  }

  rebuildBasemap(options.tileSourceId)
  applyCesiumDaylight(Cesium, viewer, options.daylightMode, options.hour, options.date)

  viewer.scene.fog.enabled = false
  viewer.scene.globe.showGroundAtmosphere = true
  viewer.scene.globe.depthTestAgainstTerrain = false

  if (options.initialView) {
    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(
        options.initialView.lng,
        options.initialView.lat,
        options.initialView.heightMeters,
      ),
    })
  } else {
    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(105, 35, 12_000_000),
    })
  }

  const credit = viewer.cesiumWidget.creditContainer as HTMLElement | undefined
  if (credit) credit.style.display = 'none'

  return {
    kind: 'cesium',
    getViewer: () => (viewer.isDestroyed() ? null : viewer),
    async mount() {
      /* constructed mounted */
    },
    resize() {
      if (!viewer.isDestroyed()) viewer.resize()
    },
    destroy() {
      if (!viewer.isDestroyed()) viewer.destroy()
    },
    setBasemap(sourceId: TileSourceId) {
      if (viewer.isDestroyed()) return
      rebuildBasemap(sourceId)
    },
    setDaylight(mode, hour, date) {
      if (viewer.isDestroyed()) return
      applyCesiumDaylight(Cesium, viewer, mode, hour, date)
    },
    syncOverlayImagery(specs) {
      if (viewer.isDestroyed()) return
      applyOverlaySpecs(specs)
    },
    flyTo(lng, lat, heightMeters = 2_500_000) {
      if (viewer.isDestroyed()) return
      viewer.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(lng, lat, heightMeters),
        duration: 1.2,
      })
    },
    flyToBounds(bounds) {
      if (viewer.isDestroyed()) return
      const [west, south, east, north] = bounds
      const span = Math.max(Math.abs(east - west), Math.abs(north - south))
      if (span < 0.02) {
        const { lng, lat, heightMeters } = boundsCenterAndHeight(bounds)
        viewer.camera.flyTo({
          destination: Cesium.Cartesian3.fromDegrees(lng, lat, heightMeters),
          duration: 1.2,
        })
        return
      }
      viewer.camera.flyTo({
        destination: Cesium.Rectangle.fromDegrees(west, south, east, north),
        duration: 1.2,
      })
    },
    captureView() {
      if (viewer.isDestroyed()) return null
      const carto = viewer.camera.positionCartographic
      if (!carto) return null
      return {
        lng: Cesium.Math.toDegrees(carto.longitude),
        lat: Cesium.Math.toDegrees(carto.latitude),
        heightMeters: carto.height,
      }
    },
  }
}
