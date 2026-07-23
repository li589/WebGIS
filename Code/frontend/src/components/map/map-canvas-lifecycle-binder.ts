type MapInstance = import('maplibre-gl').Map
type MapControl = import('maplibre-gl').IControl

interface MapControlConstructors {
  NavigationControl: new (options: { visualizePitch: boolean }) => MapControl
  ScaleControl: new (options: { unit: 'metric' }) => MapControl
}

export interface MapCanvasLifecycleBinder {
  bind: () => void
}

interface CreateMapCanvasLifecycleBinderOptions {
  map: MapInstance
  controls: MapControlConstructors
  onMapError: (event: unknown) => void
  onMapLoad: () => void | Promise<void>
  scheduleNavigationThemeSync: () => void
  dependencies?: {
    error?: (message?: unknown, ...optionalParams: unknown[]) => void
  }
}

export function createMapCanvasLifecycleBinder(
  options: CreateMapCanvasLifecycleBinderOptions,
): MapCanvasLifecycleBinder {
  let bound = false
  const reportError = options.dependencies?.error ?? console.error

  function bind() {
    if (bound) return
    bound = true

    options.map.addControl(
      new options.controls.NavigationControl({ visualizePitch: true }),
      'bottom-right',
    )
    options.map.addControl(new options.controls.ScaleControl({ unit: 'metric' }), 'bottom-left')
    options.scheduleNavigationThemeSync()

    options.map.on('error', (event) => {
      options.onMapError(event)
    })
    options.map.on('load', () => {
      Promise.resolve(options.onMapLoad()).catch((error: unknown) => {
        reportError('[MapCanvasLifecycleBinder] onMapLoad failed', error)
      })
    })
  }

  return {
    bind,
  }
}
