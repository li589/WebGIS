import type { LayerHotspot } from '../../stores/layers/types'

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

  const lngs = hotspots.map((hotspot) => hotspot.lng)
  const lats = hotspots.map((hotspot) => hotspot.lat)
  const bounds: [[number, number], [number, number]] = [
    [Math.min(...lngs), Math.min(...lats)],
    [Math.max(...lngs), Math.max(...lats)],
  ]

  map.fitBounds(bounds, {
    padding: { top: 120, right: 220, bottom: 120, left: 220 },
    maxZoom: 6.8,
    duration: 700,
    essential: true,
  })
}
