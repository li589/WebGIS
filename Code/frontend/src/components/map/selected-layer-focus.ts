import type { LayerHotspot } from '../../stores/layers/types'
import { lngSpanFromList } from '../../services/geo-math'

type MapInstance = import('maplibre-gl').Map

export function focusMapOnHotspots(map: MapInstance, hotspots: LayerHotspot[]) {
  if (hotspots.length === 0) return

  if (hotspots.length === 1) {
    const hotspot = hotspots[0]
    map.easeTo({
      center: [hotspot.lng, hotspot.lat],
      zoom: 6.6,
      duration: 650,
      essential: true,
    })
    return
  }

  const lngSpan = lngSpanFromList(hotspots.map((hotspot) => hotspot.lng))
  if (!lngSpan) return
  const lats = hotspots.map((hotspot) => hotspot.lat).filter(Number.isFinite)
  if (!lats.length) return
  const south = Math.min(...lats)
  const north = Math.max(...lats)
  const bounds: [[number, number], [number, number]] = [
    [lngSpan[0], south],
    [lngSpan[1], north],
  ]

  map.fitBounds(bounds, {
    padding: { top: 120, right: 220, bottom: 120, left: 220 },
    maxZoom: 6.8,
    duration: 700,
    essential: true,
  })
}
