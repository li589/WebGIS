import type { LayerHotspot } from '../../stores/layers/types'

export interface ProjectedHotspotPin {
  id: string
  name: string
  value: string
  x: number
  y: number
  selected: boolean
}

export interface DisplayHotspotPin {
  id: string
  name: string
  value: string
  left: string
  top: string
  selected: boolean
}

export interface HotspotPointProjector {
  project: (lngLat: [number, number]) => { x: number; y: number }
}

export interface PlaceHotspotPinsOptions {
  minDistance?: number
  offsetStep?: number
}

export function getVisibleHotspotsForZoom(hotspots: LayerHotspot[], zoom: number): LayerHotspot[] {
  if (zoom < 5.4) return hotspots.slice(0, 1)
  if (zoom < 6.2) return hotspots.slice(0, 2)
  if (zoom < 7) return hotspots.slice(0, 3)
  return hotspots
}

export function buildProjectedHotspotPins(
  hotspots: LayerHotspot[],
  projector: HotspotPointProjector,
  selectedHotspotId: string | null,
): ProjectedHotspotPin[] {
  return hotspots.map((hotspot) => {
    const point = projector.project([hotspot.lng, hotspot.lat])
    return {
      id: hotspot.id,
      name: hotspot.name,
      value: hotspot.value,
      x: point.x,
      y: point.y,
      selected: hotspot.id === selectedHotspotId,
    }
  })
}

export function placeHotspotPins(
  rawPins: ProjectedHotspotPin[],
  options: PlaceHotspotPinsOptions = {},
): ProjectedHotspotPin[] {
  const minDistance = options.minDistance ?? 70
  const offsetStep = options.offsetStep ?? 36
  const placed: ProjectedHotspotPin[] = []

  const sorted = [...rawPins].sort((a, b) => {
    if (a.selected !== b.selected) return a.selected ? -1 : 1
    return a.y - b.y
  })

  for (const pin of sorted) {
    let px = pin.x
    let py = pin.y

    const candidates: Array<[number, number]> = [
      [0, 0],
      [0, offsetStep],
      [0, -offsetStep],
      [offsetStep * 2, 0],
      [-offsetStep * 2, 0],
      [0, offsetStep * 2],
      [0, -offsetStep * 2],
    ]

    for (const [dx, dy] of candidates) {
      const cx = pin.x + dx
      const cy = pin.y + dy
      const overlaps = placed.some((existing) => {
        const ddx = cx - existing.x
        const ddy = cy - existing.y
        return Math.sqrt(ddx * ddx + ddy * ddy) < minDistance
      })
      if (!overlaps) {
        px = cx
        py = cy
        break
      }
    }

    placed.push({ ...pin, x: px, y: py })
  }

  return placed
}

export function buildDisplayHotspotPins(pins: ProjectedHotspotPin[]): DisplayHotspotPin[] {
  return pins.map((pin) => ({
    id: pin.id,
    name: pin.name,
    value: pin.value,
    left: `${pin.x}px`,
    top: `${pin.y}px`,
    selected: pin.selected,
  }))
}
