import type { LayerHotspot } from '../../stores/layers/types'
import {
  buildDisplayHotspotPins,
  buildProjectedHotspotPins,
  getVisibleHotspotsForZoom,
  placeHotspotPins,
  type DisplayHotspotPin,
} from './hotspot-pins'

type MapInstance = import('maplibre-gl').Map

export interface HotspotPinsModule {
  scheduleSync: () => void
  runSyncNow: () => void
  toggleSelection: (pinId: string) => void
  dispose: () => void
}

interface CreateHotspotPinsModuleOptions {
  map: MapInstance
  getHotspots: () => LayerHotspot[]
  getSelectedHotspotId: () => string | null
  setSelectedHotspotId: (hotspotId: string | null) => void
  emitVisibleHotspotsChange: (hotspots: LayerHotspot[]) => void
  emitHotspotSelect: (hotspot: LayerHotspot | null) => void
  setHotspotPins: (pins: DisplayHotspotPin[]) => void
  dependencies?: {
    requestAnimationFrame?: typeof requestAnimationFrame
    cancelAnimationFrame?: typeof cancelAnimationFrame
  }
}

export function createHotspotPinsModule(
  options: CreateHotspotPinsModuleOptions,
): HotspotPinsModule {
  const requestAnimationFrameImpl =
    options.dependencies?.requestAnimationFrame ??
    ((callback: FrameRequestCallback) =>
      globalThis.setTimeout(() => callback(Date.now()), 16) as unknown as number)
  const cancelAnimationFrameImpl =
    options.dependencies?.cancelAnimationFrame ??
    ((handle: number) => globalThis.clearTimeout(handle))

  let animationFrameId: number | null = null

  function runSyncNow() {
    const visibleHotspots = getVisibleHotspotsForZoom(options.getHotspots(), options.map.getZoom())
    options.emitVisibleHotspotsChange(visibleHotspots)

    const selectedHotspotId = options.getSelectedHotspotId()
    if (selectedHotspotId && !visibleHotspots.some((hotspot) => hotspot.id === selectedHotspotId)) {
      options.setSelectedHotspotId(null)
      options.emitHotspotSelect(null)
    }

    const rawPins = buildProjectedHotspotPins(
      visibleHotspots,
      options.map,
      options.getSelectedHotspotId(),
    )
    const placedPins = placeHotspotPins(rawPins)
    options.setHotspotPins(buildDisplayHotspotPins(placedPins))
  }

  function scheduleSync() {
    if (animationFrameId !== null) return
    animationFrameId = requestAnimationFrameImpl(() => {
      animationFrameId = null
      runSyncNow()
    })
  }

  function toggleSelection(pinId: string) {
    const nextId = options.getSelectedHotspotId() === pinId ? null : pinId
    options.setSelectedHotspotId(nextId)
    options.emitHotspotSelect(
      options.getHotspots().find((hotspot) => hotspot.id === nextId) ?? null,
    )
    runSyncNow()
  }

  function dispose() {
    if (animationFrameId === null) return
    cancelAnimationFrameImpl(animationFrameId)
    animationFrameId = null
  }

  return {
    scheduleSync,
    runSyncNow,
    toggleSelection,
    dispose,
  }
}
