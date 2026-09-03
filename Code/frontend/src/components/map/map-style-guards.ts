/**
 * MapLibre 在 setProjection / map.remove / 样式重建间隙 `map.style` 可能为 undefined，
 * 此时原生 `map.getLayer` 会抛 Cannot read properties of undefined (reading 'getLayer')。
 * 快速切 2D↔3D 或 MapLibre↔Cesium 时尤其常见。
 */
import type { Map as MaplibreMap } from 'maplibre-gl'

type StyleBearingMap = {
  style?: unknown
  getLayer: MaplibreMap['getLayer']
  getSource: MaplibreMap['getSource']
  removeLayer: MaplibreMap['removeLayer']
  removeSource: MaplibreMap['removeSource']
  getLayoutProperty: MaplibreMap['getLayoutProperty']
  setLayoutProperty: MaplibreMap['setLayoutProperty']
  getPaintProperty: MaplibreMap['getPaintProperty']
  setPaintProperty: MaplibreMap['setPaintProperty']
  moveLayer: MaplibreMap['moveLayer']
}

export function isMapStyleAlive(map: { style?: unknown } | null | undefined): boolean {
  return Boolean(map && map.style)
}

/**
 * 给 Map 实例打补丁：style 缺失时 get* 返回 undefined，mutating 调用静默 no-op。
 * 应在 `new maplibregl.Map(...)` 后立刻调用一次。
 */
export function installSafeMapStyleAccess(map: MaplibreMap): void {
  const m = map as unknown as StyleBearingMap
  const patch = <K extends keyof StyleBearingMap>(
    key: K,
    onDead: (...args: unknown[]) => unknown,
  ) => {
    const original = m[key]
    if (typeof original !== 'function') return
    ;(m as Record<string, unknown>)[key as string] = (...args: unknown[]) => {
      if (!m.style) return onDead(...args)
      try {
        return (original as (...a: unknown[]) => unknown).apply(m, args)
      } catch {
        return onDead(...args)
      }
    }
  }

  patch('getLayer', () => undefined)
  patch('getSource', () => undefined)
  patch('getLayoutProperty', () => undefined)
  patch('getPaintProperty', () => undefined)
  patch('removeLayer', () => map)
  patch('removeSource', () => map)
  patch('setLayoutProperty', () => map)
  patch('setPaintProperty', () => map)
  patch('moveLayer', () => map)
}
