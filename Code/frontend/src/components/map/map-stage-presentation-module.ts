type MapContainerGetter = () => HTMLElement | null

export interface MapStagePresentationModule {
  prepareMount: () => Promise<void>
  setLoadingLabel: (label: string) => void
  syncNavigationControlTheme: () => void
  scheduleNavigationThemeSync: () => void
  revealMap: () => void
  dispose: () => void
}

interface CreateMapStagePresentationModuleOptions {
  getMapContainer: MapContainerGetter
  getUsesLightNavigationTheme: () => boolean
  setLoadingLabel: (label: string) => void
  setMapVisible: (visible: boolean) => void
  setSkeletonVisible: (visible: boolean) => void
  dependencies?: {
    requestAnimationFrame?: typeof requestAnimationFrame
    setTimeout?: typeof setTimeout
    clearTimeout?: typeof clearTimeout
  }
}

export function createMapStagePresentationModule(
  options: CreateMapStagePresentationModuleOptions,
): MapStagePresentationModule {
  const requestAnimationFrameImpl = options.dependencies?.requestAnimationFrame ?? requestAnimationFrame
  const setTimeoutImpl = options.dependencies?.setTimeout ?? setTimeout
  const clearTimeoutImpl = options.dependencies?.clearTimeout ?? clearTimeout

  let pendingThemeSyncHandle: ReturnType<typeof setTimeout> | null = null
  let pendingSkeletonHideHandle: ReturnType<typeof setTimeout> | null = null

  function setLoadingLabel(label: string) {
    options.setLoadingLabel(label)
  }

  function syncNavigationControlTheme() {
    const navButtons = options.getMapContainer()?.querySelectorAll('.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group button')
    if (!navButtons?.length) return

    const buttonBackground = options.getUsesLightNavigationTheme()
      ? 'rgba(255,255,255,0.86)'
      : 'rgba(8,18,33,0.85)'

    navButtons.forEach((button) => {
      ;(button as HTMLElement).style.backgroundColor = buttonBackground
    })
  }

  async function prepareMount() {
    setLoadingLabel('正在准备地图...')
    await new Promise<void>((resolve) => requestAnimationFrameImpl(() => resolve()))
    setLoadingLabel('正在加载地图引擎...')
  }

  function scheduleNavigationThemeSync() {
    if (pendingThemeSyncHandle !== null) {
      clearTimeoutImpl(pendingThemeSyncHandle)
    }
    pendingThemeSyncHandle = setTimeoutImpl(() => {
      pendingThemeSyncHandle = null
      syncNavigationControlTheme()
    }, 0)
  }

  function revealMap() {
    requestAnimationFrameImpl(() => {
      options.setMapVisible(true)
      if (pendingSkeletonHideHandle !== null) {
        clearTimeoutImpl(pendingSkeletonHideHandle)
      }
      pendingSkeletonHideHandle = setTimeoutImpl(() => {
        pendingSkeletonHideHandle = null
        options.setSkeletonVisible(false)
      }, 260)
    })
  }

  function dispose() {
    if (pendingThemeSyncHandle !== null) {
      clearTimeoutImpl(pendingThemeSyncHandle)
      pendingThemeSyncHandle = null
    }
    if (pendingSkeletonHideHandle !== null) {
      clearTimeoutImpl(pendingSkeletonHideHandle)
      pendingSkeletonHideHandle = null
    }
  }

  return {
    prepareMount,
    setLoadingLabel,
    syncNavigationControlTheme,
    scheduleNavigationThemeSync,
    revealMap,
    dispose,
  }
}
