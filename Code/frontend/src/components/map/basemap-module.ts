import {
  getFailoverCandidates as defaultGetFailoverCandidates,
  type TileSourceConfig,
  type TileSourceId,
} from '../../services/api-config'

type MapInstance = import('maplibre-gl').Map
type RasterSourceSpecification = import('maplibre-gl').RasterSourceSpecification
type RasterTileSource = import('maplibre-gl').RasterTileSource

const TILE_SOURCE_ID = 'tile-base'
const TILE_LAYER_ID = 'tile-base-raster'
const TILE_OVERLAY_SOURCE_ID = 'tile-base-overlay'
const TILE_OVERLAY_LAYER_ID = 'tile-base-overlay-raster'
const TILE_ERROR_WINDOW_MS = 5000
const TILE_ERROR_THRESHOLD = 8
/** 熔断触发后自动恢复重试的延迟（毫秒） */
const AUTO_RECOVERY_DELAY_MS = 15000
/** 熔断过的 provider 在此期间不参与故障转移候选（毫秒） */
const PROVIDER_COOLDOWN_MS = 10 * 60 * 1000

export interface BasemapModule {
  ensureInitialLayer: (sourceId: TileSourceId) => void
  switchTileSource: (sourceId: TileSourceId) => void
  scheduleTileSourceSwitch: (sourceId: TileSourceId) => void
  handleTileError: (failedProvider: string | null) => void
  handleMapErrorEvent: (event: unknown) => void
  retryTileLoad: () => void
  dispose: () => void
}

interface CreateBasemapModuleOptions {
  map: MapInstance
  getTileConfig: (sourceId: TileSourceId) => TileSourceConfig | undefined
  getCurrentTileSourceId: () => TileSourceId
  setTileLoadFailed: (failed: boolean) => void
  setTileFailedProvider: (provider: string | null) => void
  setSourceTransitioning: (transitioning: boolean) => void
  onAfterSourceSwitch?: () => void
  /** 熔断后选中了替代源时回调（用于同步 UI 选中态并提示用户） */
  onProviderFailover?: (nextSourceId: TileSourceId, failedProvider: string) => void
  /** 故障转移候选筛选（默认取 api-config 同风格组；调用方可叠加 API Key 可用性过滤） */
  getFailoverCandidates?: (
    currentSourceId: TileSourceId,
    excludeProviders: ReadonlySet<string>,
  ) => TileSourceId[]
  dependencies?: {
    setTimeout?: typeof setTimeout
    clearTimeout?: typeof clearTimeout
    now?: () => number
  }
}

export function createBasemapModule(options: CreateBasemapModuleOptions): BasemapModule {
  const setTimeoutImpl = options.dependencies?.setTimeout ?? setTimeout
  const clearTimeoutImpl = options.dependencies?.clearTimeout ?? clearTimeout
  const nowImpl = options.dependencies?.now ?? Date.now

  const tileErrorTimestamps: number[] = []
  let switchTileToken = 0
  let sourceTransitionTimer: ReturnType<typeof setTimeout> | null = null
  let tileSourceDebounceHandle: ReturnType<typeof setTimeout> | null = null
  /** 熔断后自动恢复重试定时器 */
  let autoRecoveryTimer: ReturnType<typeof setTimeout> | null = null
  /** 标记当前是否处于熔断状态 */
  let isCircuitBroken = false
  /** provider -> 冷却截止时间戳（毫秒），冷却期内不参与故障转移候选 */
  const providerCooldownUntil = new Map<string, number>()
  /** 已调度的故障转移目标（防抖完成前抑制重复触发），switchTileSource 执行时清空 */
  let pendingFailoverSourceId: TileSourceId | null = null
  /**
   * 最近一次「外来 provider」瓦片错误时间戳（归因检查跳过的那类）。
   * 用户已切走但旧源请求仍在超时失败时，错误不会进熔断窗口（归因保护），
   * 但它们证明旧源挂起请求正在拖连接池——切换重建判定需要该信号。
   * 初始 -Infinity（绝不能把「从未有外来错误」误判为刚发生）。
   */
  let lastForeignTileErrorAt = Number.NEGATIVE_INFINITY

  function hideOverlay() {
    if (options.map.getLayer(TILE_OVERLAY_LAYER_ID)) {
      options.map.setLayoutProperty(TILE_OVERLAY_LAYER_ID, 'visibility', 'none')
    }
  }

  /** background 恒居栈底；返回第一个非 background 且非底图自身的图层 id，无则 undefined。 */
  function firstDataLayerId(): string | undefined {
    const layers = options.map.getStyle().layers ?? []
    for (const layer of layers) {
      if (layer.type === 'background' || layer.id === TILE_LAYER_ID) continue
      return layer.id
    }
    return undefined
  }

  /** 目标图层之前是否只剩 background（即紧贴 background 之上）。 */
  function isDirectlyAboveBackground(layerId: string): boolean {
    const layers = options.map.getStyle().layers ?? []
    const idx = layers.findIndex((l) => l.id === layerId)
    return idx > 0 && layers.slice(0, idx).every((l) => l.type === 'background')
  }

  /** 紧贴底图之上的图层 id；底图缺失或已居栈顶时返回 undefined。 */
  function layerAboveBasemapId(): string | undefined {
    const layers = options.map.getStyle().layers ?? []
    const baseIdx = layers.findIndex((l) => l.id === TILE_LAYER_ID)
    if (baseIdx < 0) return firstDataLayerId()
    return baseIdx + 1 < layers.length ? layers[baseIdx + 1].id : undefined
  }

  /**
   * 强制图层栈不变量：background 恒居栈底，底图紧贴其上、注记再上（所有数据叠加层之下）。
   * 空白底图起步后叠加层已上图，再切回真实底图时若仅 addLayer 追加会落栈顶盖住数据层；
   * 底图若沉到 background 之下会被背景色（--surface-1 半透明深色）罩住导致整图发暗，
   * 故每次切换后幂等校正两件事：background 归底、底图归位。
   */
  function enforceBasemapStackPosition() {
    const map = options.map
    const layers = map.getStyle().layers ?? []

    const backgroundLayer = layers.find((l) => l.type === 'background')
    if (backgroundLayer && layers.length > 0 && layers[0].id !== backgroundLayer.id) {
      const firstNonBackground = layers.find((l) => l.type !== 'background')
      if (firstNonBackground) {
        map.moveLayer(backgroundLayer.id, firstNonBackground.id)
      }
    }

    if (map.getLayer(TILE_LAYER_ID)) {
      const anchor = firstDataLayerId()
      if (anchor) {
        map.moveLayer(TILE_LAYER_ID, anchor)
      } else if (!isDirectlyAboveBackground(TILE_LAYER_ID)) {
        map.moveLayer(TILE_LAYER_ID)
      }
    }
    if (map.getLayer(TILE_OVERLAY_LAYER_ID)) {
      const above = layerAboveBasemapId()
      if (above && above !== TILE_OVERLAY_LAYER_ID) {
        options.map.moveLayer(TILE_OVERLAY_LAYER_ID, above)
      }
    }
  }

  function syncOverlayLayer(cfg: TileSourceConfig | undefined, visible: boolean) {
    const overlayUrl = cfg?.overlayUrlTemplate
    if (!overlayUrl) {
      // 完全无 overlay 配置：移除已有 overlay 源和图层，避免无期限常驻隐藏
      if (options.map.getLayer(TILE_OVERLAY_LAYER_ID)) {
        options.map.removeLayer(TILE_OVERLAY_LAYER_ID)
      }
      if (options.map.getSource(TILE_OVERLAY_SOURCE_ID)) {
        options.map.removeSource(TILE_OVERLAY_SOURCE_ID)
      }
      return
    }
    if (!visible) {
      // 有 overlay 配置但不展示（熔断 / ensureTileLayer 初始）：仅隐藏，保留源/层供恢复
      hideOverlay()
      return
    }

    const existingOverlay = options.map.getSource(TILE_OVERLAY_SOURCE_ID) as
      RasterTileSource | undefined
    if (existingOverlay && existingOverlay.type === 'raster') {
      existingOverlay.setTiles([overlayUrl])
    } else if (!options.map.getSource(TILE_OVERLAY_SOURCE_ID)) {
      options.map.addSource(TILE_OVERLAY_SOURCE_ID, {
        type: 'raster',
        tiles: [overlayUrl],
        tileSize: cfg.tileSize ?? 256,
        maxzoom: 18,
        scheme: 'xyz',
      } as RasterSourceSpecification)
    }

    if (!options.map.getLayer(TILE_OVERLAY_LAYER_ID)) {
      // 注记紧贴底图之上、所有数据叠加层之下
      const beforeLayerId = layerAboveBasemapId()
      options.map.addLayer(
        {
          id: TILE_OVERLAY_LAYER_ID,
          type: 'raster',
          source: TILE_OVERLAY_SOURCE_ID,
          layout: { visibility: 'visible' },
          paint: {
            'raster-opacity': 1,
          },
        },
        beforeLayerId,
      )
    } else {
      options.map.setLayoutProperty(TILE_OVERLAY_LAYER_ID, 'visibility', 'visible')
    }
  }

  function ensureTileLayer(sourceId: TileSourceId) {
    const cfg = options.getTileConfig(sourceId)
    if (!cfg) {
      console.warn(`[basemap] getTileConfig returned undefined for sourceId="${sourceId}"`)
      return
    }

    if (!options.map.getSource(TILE_SOURCE_ID)) {
      options.map.addSource(TILE_SOURCE_ID, {
        type: 'raster',
        tiles: [cfg.urlTemplate],
        tileSize: cfg.tileSize ?? 256,
        attribution: cfg.attribution,
        maxzoom: 18,
        scheme: 'xyz',
      } as RasterSourceSpecification)
    }

    if (!options.map.getLayer(TILE_LAYER_ID)) {
      // 底图插到 background 之上、既有数据叠加层之下（沉到 background 之下会被背景色罩暗整图）
      const beforeLayerId = firstDataLayerId()
      options.map.addLayer(
        {
          id: TILE_LAYER_ID,
          type: 'raster',
          source: TILE_SOURCE_ID,
          layout: { visibility: 'none' },
          paint: {
            'raster-opacity': 1,
            'raster-saturation': cfg.saturation,
            'raster-brightness-max': Math.min(1.0, 1.0 + cfg.brightness),
            'raster-brightness-min': Math.max(0.0, Math.min(1.0, cfg.brightness)),
            'raster-contrast': cfg.contrast,
          },
        },
        beforeLayerId,
      )
    }

    syncOverlayLayer(cfg, false)
  }

  function triggerSourceTransition() {
    options.setSourceTransitioning(true)
    if (sourceTransitionTimer !== null) clearTimeoutImpl(sourceTransitionTimer)
    sourceTransitionTimer = setTimeoutImpl(() => {
      options.setSourceTransitioning(false)
      sourceTransitionTimer = null
    }, 260)
  }

  /**
   * 源当前是否有未消解的瓦片异常（慢/失败请求挂起中）。
   *
   * 全部底图源经 ``/unified-tiles/`` 后端代理（同源），浏览器对同源
   * HTTP/1.1 并发连接上限 6 条：源挂起时视口内几十个瓦片请求占满连接
   * 池，``setTiles`` 不中止这些请求 → 新源请求排队其后 → 「切了底图
   * 但卡一段时间才显示」（2026-08-24 复发报障根因）。此状态下切换必须
   * 重建源（removeSource 会 abort 全部挂起请求，立即释放连接）。
   */
  function hasUnresolvedTileErrors(): boolean {
    return (
      isCircuitBroken ||
      tileErrorTimestamps.length > 0 ||
      nowImpl() - lastForeignTileErrorAt < TILE_ERROR_WINDOW_MS
    )
  }

  /**
   * 重建底图源+图层（先删后建）。
   *
   * ``removeSource`` 触发 MapLibre 中止该源全部 in-flight 瓦片请求
   * （每瓦片 AbortController），挂起连接立即释放——这是「切源立即生效」
   * 的关键路径；``setTiles`` 不会中止旧请求（只换 URL 模板，旧 Tile
   * 对象继续等超时）。重建后 ``ensureTileLayer`` 幂等补建 source/layer，
   * 栈位由 ``enforceBasemapStackPosition`` 校正。瓦片命中浏览器 HTTP
   * 缓存不受影响（同 URL 复用缓存），重选该源时缓存照常生效。
   */
  function recreateTileSource(sourceId: TileSourceId): void {
    const map = options.map
    if (map.getLayer(TILE_LAYER_ID)) {
      map.removeLayer(TILE_LAYER_ID)
    }
    if (map.getSource(TILE_SOURCE_ID)) {
      map.removeSource(TILE_SOURCE_ID)
    }
    ensureTileLayer(sourceId)
  }

  function resetTileErrorState() {
    options.setTileLoadFailed(false)
    options.setTileFailedProvider(null)
    tileErrorTimestamps.length = 0
    isCircuitBroken = false
    if (autoRecoveryTimer !== null) {
      clearTimeoutImpl(autoRecoveryTimer)
      autoRecoveryTimer = null
    }
  }

  /** 调度自动恢复：熔断后一段时间自动重试一次 */
  function scheduleAutoRecovery() {
    if (autoRecoveryTimer !== null) {
      clearTimeoutImpl(autoRecoveryTimer)
    }
    autoRecoveryTimer = setTimeoutImpl(() => {
      autoRecoveryTimer = null
      if (isCircuitBroken) {
        retryTileLoad()
      }
    }, AUTO_RECOVERY_DELAY_MS)
  }

  function switchTileSource(sourceId: TileSourceId) {
    // 先快照异常态再 reset（reset 会清空错误窗口/熔断标记——重建判定依赖它）
    const hadUnresolvedErrors = hasUnresolvedTileErrors()
    resetTileErrorState()
    pendingFailoverSourceId = null

    if (sourceId === 'none') {
      if (options.map.getLayer(TILE_LAYER_ID)) {
        options.map.setLayoutProperty(TILE_LAYER_ID, 'visibility', 'none')
        options.map.setPaintProperty(TILE_LAYER_ID, 'raster-opacity', 0)
      }
      // 空白模式只做 visibility/opacity 隐藏，**不**清空 tiles：
      // setTiles([]) 会走 maplibre loadTile 的空 URL 异常路径，快速切换（尤其
      // none→真实源）时 tile 状态机竞态 → painter 的 texture.bind() 读 undefined
      // 持续崩溃（vendor-maplibre 内部无守卫，见 2026-08-22 用户日志 56 条）。
      // 切回真实源时 switchTileSource 必 setTiles([新 url])，无旧图残留风险。
      options.map.triggerRepaint()
      hideOverlay()
      // 空白模式下卸掉注记 overlay 源，避免残留
      syncOverlayLayer(undefined, false)
      return
    }

    const cfg = options.getTileConfig(sourceId)
    if (!cfg) {
      console.warn(
        `[basemap] switchTileSource: getTileConfig returned undefined for sourceId="${sourceId}"`,
      )
      return
    }

    const existingSource = options.map.getSource(TILE_SOURCE_ID) as RasterTileSource | undefined
    if (existingSource && existingSource.type === 'raster') {
      if (hadUnresolvedErrors) {
        // 慢/挂源切换：重建源以 abort 全部挂起瓦片请求，立即释放同源连接
        // 池给新源（见 hasUnresolvedTileErrors 注释）；否则 setTiles 只换
        // URL 模板，新源请求会排在旧源挂起请求之后 → 切换被拖住。
        recreateTileSource(sourceId)
      } else {
        existingSource.setTiles([cfg.urlTemplate])
        options.map.triggerRepaint()
      }
    }

    ensureTileLayer(sourceId)

    if (options.map.getLayer(TILE_LAYER_ID)) {
      options.map.setLayoutProperty(TILE_LAYER_ID, 'visibility', 'visible')
      options.map.setPaintProperty(TILE_LAYER_ID, 'raster-opacity', 1)
      options.map.setPaintProperty(TILE_LAYER_ID, 'raster-saturation', cfg.saturation)
      options.map.setPaintProperty(
        TILE_LAYER_ID,
        'raster-brightness-max',
        Math.min(1.0, 1.0 + cfg.brightness),
      )
      options.map.setPaintProperty(
        TILE_LAYER_ID,
        'raster-brightness-min',
        Math.max(0.0, Math.min(1.0, cfg.brightness)),
      )
      options.map.setPaintProperty(TILE_LAYER_ID, 'raster-contrast', cfg.contrast)
    }

    syncOverlayLayer(cfg, true)
    enforceBasemapStackPosition()
  }

  function scheduleTileSourceSwitch(sourceId: TileSourceId) {
    if (tileSourceDebounceHandle !== null) {
      clearTimeoutImpl(tileSourceDebounceHandle)
    }
    const token = ++switchTileToken
    tileSourceDebounceHandle = setTimeoutImpl(() => {
      tileSourceDebounceHandle = null
      if (token !== switchTileToken) return
      triggerSourceTransition()
      switchTileSource(sourceId)
      options.onAfterSourceSwitch?.()
    }, 80)
  }

  /**
   * 熔断后尝试自动切换到同风格的可用替代源。
   * 返回 true 表示已调度切换；false 表示无候选，走熔断+自动恢复路径。
   */
  function requestFailover(failedProvider: string): boolean {
    const currentSourceId = options.getCurrentTileSourceId()
    if (currentSourceId === 'none') return false

    const now = nowImpl()
    const excludeProviders = new Set<string>([failedProvider])
    for (const [provider, until] of providerCooldownUntil) {
      if (until <= now) {
        providerCooldownUntil.delete(provider)
      } else {
        excludeProviders.add(provider)
      }
    }

    const selectCandidates = options.getFailoverCandidates ?? defaultGetFailoverCandidates
    const candidates = selectCandidates(currentSourceId, excludeProviders)
    if (candidates.length === 0) return false

    const nextSourceId = candidates[0]
    providerCooldownUntil.set(failedProvider, now + PROVIDER_COOLDOWN_MS)
    if (pendingFailoverSourceId !== null) {
      // 已有转移在防抖队列中：不再重复回调，仅刷新错误窗口
      tileErrorTimestamps.length = 0
      return true
    }
    pendingFailoverSourceId = nextSourceId
    options.onProviderFailover?.(nextSourceId, failedProvider)
    // 立即清空错误窗口，防止 80ms 切换防抖期内错误继续累计导致重复触发
    tileErrorTimestamps.length = 0
    scheduleTileSourceSwitch(nextSourceId)
    return true
  }

  function handleTileError(failedProvider: string | null) {
    // 仅累计仍指向「当前选中底图」的错误，避免快速切换时旧 provider 迟到失败误伤
    const currentSourceId = options.getCurrentTileSourceId()
    const currentProvider = options.getTileConfig(currentSourceId)?.provider ?? null
    // 无法归因的错误（常见于切换瞬间）不计入熔断阈值
    if (!failedProvider) {
      return
    }
    if (
      currentProvider &&
      failedProvider !== currentProvider &&
      failedProvider !== currentSourceId &&
      !options
        .getTileConfig(currentSourceId)
        ?.overlayUrlTemplate?.includes(`/unified-tiles/${failedProvider}/`)
    ) {
      // 外来 provider（用户已切走、旧源迟到失败）：不进熔断窗口，但记录
      // 时间戳供切换重建判定（旧源挂起请求正在拖连接池的证据）。
      lastForeignTileErrorAt = nowImpl()
      return
    }

    const now = nowImpl()
    while (tileErrorTimestamps.length > 0 && now - tileErrorTimestamps[0] > TILE_ERROR_WINDOW_MS) {
      tileErrorTimestamps.shift()
    }
    tileErrorTimestamps.push(now)

    if (tileErrorTimestamps.length > TILE_ERROR_THRESHOLD) {
      const brokenProvider = failedProvider ?? currentProvider ?? ''
      // 优先故障转移到同风格可用源；无候选才进入熔断等待自动恢复
      if (brokenProvider && requestFailover(brokenProvider)) {
        isCircuitBroken = false
        return
      }
      isCircuitBroken = true
      options.setTileLoadFailed(true)
      options.setTileFailedProvider(brokenProvider || null)
      if (options.map.getLayer(TILE_LAYER_ID)) {
        options.map.setLayoutProperty(TILE_LAYER_ID, 'visibility', 'none')
      }
      hideOverlay()
      // 熔断即重建源：挂起瓦片请求立即 abort——否则它们继续占用同源连接
      // 池（/unified-tiles 代理与 API 同源），拖慢自动恢复重试与其余同源
      // 请求直到超时。重建后 layer 隐藏（ensureTileLayer 默认 visibility
      // none），15s 自动恢复走 retryTileLoad 重新加载。
      if (options.getTileConfig(currentSourceId)?.urlTemplate) {
        recreateTileSource(currentSourceId)
      }
      scheduleAutoRecovery()
    }
  }

  function handleMapErrorEvent(event: unknown) {
    const mapError = event as {
      sourceId?: string
      error?: {
        status?: number
        url?: string
      }
    }

    if (
      mapError.sourceId !== TILE_SOURCE_ID &&
      mapError.sourceId !== TILE_OVERLAY_SOURCE_ID &&
      mapError.sourceId !== undefined
    ) {
      return
    }

    const status = mapError.error?.status
    if (
      status !== undefined &&
      status !== 0 &&
      status !== 403 &&
      status !== 404 &&
      status !== 502 &&
      status !== 503
    ) {
      return
    }

    const url = mapError.error?.url ?? ''
    const match = url.match(/\/(?:unified-)?tiles\/([^/]+)\//)
    const provider = match ? match[1] : null
    handleTileError(provider)
  }

  function retryTileLoad() {
    resetTileErrorState()
    const currentTileConfig = options.getTileConfig(options.getCurrentTileSourceId())
    if (options.getCurrentTileSourceId() === 'none') {
      syncOverlayLayer(undefined, false)
      return
    }
    if (!currentTileConfig?.urlTemplate) return

    // 重建源（而非 setTiles）：熔断期间挂起的旧请求随 removeSource abort，
    // 且重建即重发请求（15s 恢复窗口内网络若已恢复则立即出图）；已加载
    // 瓦片命中浏览器 HTTP 缓存，无重复下载。
    recreateTileSource(options.getCurrentTileSourceId())
    if (options.map.getLayer(TILE_LAYER_ID)) {
      options.map.setLayoutProperty(TILE_LAYER_ID, 'visibility', 'visible')
    }
    syncOverlayLayer(currentTileConfig, true)
    options.map.triggerRepaint()
  }

  function dispose() {
    if (sourceTransitionTimer !== null) {
      clearTimeoutImpl(sourceTransitionTimer)
      sourceTransitionTimer = null
    }
    if (tileSourceDebounceHandle !== null) {
      clearTimeoutImpl(tileSourceDebounceHandle)
      tileSourceDebounceHandle = null
    }
    if (autoRecoveryTimer !== null) {
      clearTimeoutImpl(autoRecoveryTimer)
      autoRecoveryTimer = null
    }
    // 清理错误时间戳数组，避免内存泄漏
    tileErrorTimestamps.length = 0
    providerCooldownUntil.clear()
    pendingFailoverSourceId = null
    lastForeignTileErrorAt = Number.NEGATIVE_INFINITY
    isCircuitBroken = false
  }

  return {
    ensureInitialLayer: ensureTileLayer,
    switchTileSource,
    scheduleTileSourceSwitch,
    handleTileError,
    handleMapErrorEvent,
    retryTileLoad,
    dispose,
  }
}
