/**
 * Active layer list CRUD / display / import slice.
 * Public API re-exported via useLayersStore().
 */
import { computed, markRaw, nextTick, ref } from 'vue'

import type { LayerDescriptor } from '../../services/runtime-api'
import { deleteImportedRaster } from '../../services/data-import'
import { useWeatherTileManager } from '../weather-tile-manager'
import { useUiStore } from '../ui'
import { safeLog } from '../log'
import { useWorkflowOutputLayersStore } from '../workflow-output-layers'
import { allocateLayerAccent } from './layer-accent'
import { buildImportedVectorPayload, computeBounds, inferGeometryType } from './imported-vector'
import { buildImportedRasterPayload } from './imported-raster'
import { clearPersistedLayerDisplayNames, persistLayerDisplayName } from './layer-display-names'
import {
  collectLayerDisplayNameKeys,
  isRuntimeCatalogId,
  normalizeDisplayName,
} from './layer-naming'
import { projectActiveLayersDisplay } from './display-projection'
import { rememberDismissedLayer } from './workspace-persist'
import { MERGED_LAYER_GROUPS } from './catalog'
import type {
  ActiveLayer,
  ActiveLayerDisplay,
  ActiveRunLayerGroup,
  JobLayerItem,
  LayerSidebarView,
  RuntimeLayerLibraryItem,
} from './types'

function genInstanceId() {
  return crypto.randomUUID()
}

function isLocalImport(layer: ActiveLayer): boolean {
  return Boolean(layer.importedVector || layer.importedRaster)
}

export interface ActiveLayersSliceDeps {
  getLayerLibraryMap: () => Map<string, RuntimeLayerLibraryItem>
  getRuntimeLayerCatalog: () => Record<string, LayerDescriptor>
  getRunLayerGroups: () => ActiveRunLayerGroup[]
  setRunLayerGroups: (groups: ActiveRunLayerGroup[]) => void
  getJobLayers: () => JobLayerItem[]
  isWeatherEngineLayer: (catalogId: string) => boolean
  supportsParticleFlow: (catalogId: string) => boolean
  weatherProviderArg: (catalogId: string) => string
  getMapCenter: () => { lng: number; lat: number }
  getMapZoom: () => number
  getMapBBox: () => import('../../services/runtime-api').BoundingBox | null
  getCurrentHour: () => number
  getParticleFlowCatalogId: () => string | null
  enableParticleIfUnset: (catalogId: string) => void
  clearWindForCatalog: (catalogId: string) => void
  stopWorkflowPolling: (jobId: string) => void
  cancelWorkflowRunForJob: (jobId: string, catalogId: string) => Promise<unknown>
  forgetTrackedWorkflowRun: (runId: string) => void
  saveTrackedWorkflowRuns: (runs: unknown[]) => void
  getWorkflowRetryTimers: () => Map<string, number>
  getWorkflowRetryCounts: () => Map<string, number>
  getActiveWorkflowCatalogIds: () => Set<string>
  isLocalSubmitJobId: (jobId: string | null | undefined) => boolean
  scheduleWorkspacePersist: () => void
  flushWorkspacePersistNow: () => void
  debugLog: (module: string, ...args: unknown[]) => void
  // ── Auto-run workflow on layer add ──
  supportsAnalysisWorkflow: (catalogId: string) => boolean
  canRunCatalog: (catalogId: string) => boolean
  runWorkflowForCatalog: (catalogId: string) => Promise<void>
}

export function createActiveLayersSlice(deps: ActiveLayersSliceDeps) {
  const weatherTileManager = useWeatherTileManager()
  const uiStore = useUiStore()

  const activeLayers = ref<ActiveLayer[]>([])
  const sidebarView = ref<LayerSidebarView>('empty')
  const selectedInstanceId = ref<string | null>(null)

  const activeLayersDisplay = computed<ActiveLayerDisplay[]>(() =>
    projectActiveLayersDisplay({
      activeLayers: activeLayers.value,
      layerLibraryMap: deps.getLayerLibraryMap(),
      runtimeLayerCatalog: deps.getRuntimeLayerCatalog(),
      currentHour: uiStore.currentHour,
      weatherTileManager,
      isWeatherEngineLayer: deps.isWeatherEngineLayer,
      runLayerGroups: deps.getRunLayerGroups(),
    }),
  )

  const selectedLayerDisplay = computed<ActiveLayerDisplay | null>(() => {
    if (!selectedInstanceId.value) return null
    return activeLayersDisplay.value.find((d) => d.instanceId === selectedInstanceId.value) ?? null
  })

  const activeLayerCount = computed(() => activeLayers.value.length)
  const sidebarViewLabel = computed(() => {
    if (sidebarView.value === 'empty') return '图层'
    if (sidebarView.value === 'library') return '图层库'
    // 数量由右上角 badge 展示，标题不再重复写「图层 (N)」
    return '已添加图层'
  })

  // ─────────────────────────────────────────────────────────────────────────────

  function usedLayerAccentColors(): string[] {
    return activeLayers.value
      .map((l) => l.accentColor)
      .filter((c): c is string => typeof c === 'string' && c.length > 0)
  }

  function assignLayerAccent(preferred?: string | null) {
    return allocateLayerAccent(usedLayerAccentColors(), preferred)
  }

  function addLayer(catalogId: string, isAdminBoundary = false, jobLayer?: JobLayerItem) {
    // 行政边界不再作为可添加数据集
    if (isAdminBoundary || catalogId === 'admin-boundary' || catalogId === 'admin-boundary-cn') {
      return
    }
    // FE-only 合并虚拟卡（如 soil-moisture）不可作为后端 layer_id 添加
    if (MERGED_LAYER_GROUPS.has(catalogId)) {
      safeLog('warn', 'layer-add', `拒绝添加虚拟合并图层「${catalogId}」，请选择具体数据源`)
      return
    }

    // 防止重复添加同 catalogId (除非来自不同 job)
    if (!jobLayer) {
      if (
        activeLayers.value.some(
          (l) => l.catalogId === catalogId && !l.jobLayer && !isLocalImport(l),
        )
      ) {
        return
      }
    }

    const libraryItem = deps.getLayerLibraryMap().get(catalogId)
    const accent = assignLayerAccent(libraryItem?.accentColor)
    const maxOrder = activeLayers.value.reduce((max, l) => Math.max(max, l.order), 0)
    const layer: ActiveLayer = {
      instanceId: genInstanceId(),
      catalogId,
      visible: true,
      opacity: 1,
      order: maxOrder + 1,
      isAdminBoundary: false,
      jobLayer,
      dataState: jobLayer ? 'real' : 'catalog',
      accentColor: accent.accentColor,
      accentGlow: accent.accentGlow,
      chipTone: accent.chipTone,
    }
    activeLayers.value.push(layer)
    selectedInstanceId.value = layer.instanceId

    // 仅从空态进入「已添加」；从图层库添加时留在库页，立刻显示「已添加 ✓」
    // （若立刻切走，风场瓦片调度又会卡住主线程，库卡片状态看起来像没加上）
    if (sidebarView.value === 'empty') {
      sidebarView.value = 'active'
    }

    // 天气图层接入瓦片管理器，由 tile manager 按需拉取瓦片。
    // setLayerActive 是轻量操作（仅设置 visible 标志），同步执行以确保
    // overlay watcher 和 map 事件处理器在同一 flush 周期内能看到图层已激活。
    // setViewport 是重操作（计算瓦片 + 入队 + drainQueue），推迟到下一宏任务，
    // 让 Vue 先完成「已添加 ✓」与角标刷新。
    if (deps.isWeatherEngineLayer(catalogId)) {
      weatherTileManager.setLayerActive(catalogId, true)
      const cc = deps.getMapCenter()
      const cz = deps.getMapZoom()
      const ch = deps.getCurrentHour()
      const cb = deps.getMapBBox()
      nextTick(() => {
        window.setTimeout(() => {
          weatherTileManager.setViewport(
            catalogId,
            cc,
            cz,
            ch,
            undefined,
            cb,
            deps.weatherProviderArg(catalogId),
          )
          if (deps.supportsParticleFlow(catalogId)) {
            deps.enableParticleIfUnset(catalogId)
            if (deps.getParticleFlowCatalogId() === catalogId) {
              deps.debugLog('addLayer', 'auto-enable particle flow for', catalogId)
            }
          }
        }, 0)
      })
    }

    // 非天气分析图层（python_provider / gee）添加后自动运行工作流，
    // 消除"待运行"状态并生成数据供点选/时序分析。
    if (
      !jobLayer && // 不是工作流产物回填
      !deps.isWeatherEngineLayer(catalogId) && // 非天气图层
      deps.supportsAnalysisWorkflow(catalogId) && // engine 为 python_provider 或 gee
      deps.canRunCatalog(catalogId) // readiness 非 blocked
    ) {
      // 推迟到下一宏任务，让 Vue 先完成「已添加 ✓」UI 刷新
      nextTick(() => {
        window.setTimeout(() => {
          deps.runWorkflowForCatalog(catalogId).catch((err) => {
            deps.debugLog('addLayer', 'auto-run workflow failed for', catalogId, err)
          })
        }, 0)
      })
    }

    deps.scheduleWorkspacePersist()
  }

  /** 将导入矢量添加到活动图层列表（本地解析或后端统一导入） */
  function addImportedVectorLayer(
    name: string,
    geojson: GeoJSON.FeatureCollection,
    options?: { backendLayerId?: string; featureCount?: number; truncated?: boolean },
  ): ActiveLayer {
    const maxOrder = activeLayers.value.reduce((max, l) => Math.max(max, l.order), 0)
    const instanceId = genInstanceId()
    const catalogId = options?.backendLayerId || `imported-${instanceId}`
    const payload = buildImportedVectorPayload(geojson, name, {
      backendLayerId: options?.backendLayerId,
      featureCount: options?.featureCount,
    })
    if (options?.truncated) payload.truncated = true
    const accent = assignLayerAccent('var(--success)')
    const layer: ActiveLayer = {
      instanceId,
      catalogId,
      name:
        name.replace(
          /\.(geojson|json|shp|zip|rar|csv|xlsx|xls|txt|dbf|shx|prj|cpg|sbn|sbx|qix|tif|tiff|nc|hdf|h5|he5|mat)$/i,
          '',
        ) || name,
      visible: true,
      opacity: 0.85,
      order: maxOrder + 1,
      isAdminBoundary: false,
      importedVector: payload,
      dataState: 'imported',
      accentColor: accent.accentColor,
      accentGlow: accent.accentGlow,
      chipTone: accent.chipTone,
    }
    activeLayers.value.push(layer)
    selectedInstanceId.value = layer.instanceId
    if (sidebarView.value === 'empty' || sidebarView.value === 'library') {
      sidebarView.value = 'active'
    }
    deps.scheduleWorkspacePersist()
    return layer
  }

  /** 创建绘制草稿图层（空 GeoJSON，等待用户绘制要素） */
  function addDrawDraftLayer(name: string): ActiveLayer {
    const maxOrder = activeLayers.value.reduce((max, l) => Math.max(max, l.order), 0)
    const instanceId = genInstanceId()
    const catalogId = `draw-draft-${instanceId}`
    const emptyGeojson: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] }
    const payload = buildImportedVectorPayload(emptyGeojson, name, {
      featureCount: 0,
    })
    const accent = assignLayerAccent('var(--accent)')
    const layer: ActiveLayer = {
      instanceId,
      catalogId,
      name: name || `绘制图层-${new Date().toLocaleString('zh-CN')}`,
      visible: true,
      opacity: 0.85,
      order: maxOrder + 1,
      isAdminBoundary: false,
      importedVector: payload,
      dataState: 'imported',
      accentColor: accent.accentColor,
      accentGlow: accent.accentGlow,
      chipTone: accent.chipTone,
    }
    activeLayers.value.push(layer)
    selectedInstanceId.value = layer.instanceId
    if (sidebarView.value === 'empty' || sidebarView.value === 'library') {
      sidebarView.value = 'active'
    }
    deps.scheduleWorkspacePersist()
    return layer
  }

  function getImportedVectorGeojson(instanceId: string): GeoJSON.FeatureCollection | null {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    return layer?.importedVector?.geojson ?? null
  }

  function updateImportedVectorGeojson(
    instanceId: string,
    geojson: GeoJSON.FeatureCollection,
    extras?: { featureCount?: number; truncated?: boolean },
  ) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (!layer?.importedVector) return
    layer.importedVector = {
      ...layer.importedVector,
      // D-4：替换时同样 markRaw（传入对象可能未标记，进入 proxy 树前豁免）
      geojson: markRaw(geojson),
      featureCount: extras?.featureCount ?? geojson.features.length,
      truncated: extras?.truncated ?? layer.importedVector.truncated,
      geometryType: inferGeometryType(geojson),
      bounds: computeBounds(geojson),
      revision: (layer.importedVector.revision ?? 0) + 1,
    }
  }

  function setImportedVectorStyle(
    instanceId: string,
    style: NonNullable<import('./imported-vector').ImportedVectorPayload['style']>,
  ) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (!layer?.importedVector) return
    layer.importedVector = {
      ...layer.importedVector,
      style: { ...layer.importedVector.style, ...style },
    }
    deps.scheduleWorkspacePersist()
  }

  /** 将后端已注册的 TIF overlay 挂入活动图层列表 */
  function addImportedRasterLayer(
    name: string,
    overlayLayerId: string,
    bounds?: [number, number, number, number],
    options?: {
      sourceCrs?: string
      lngOffset?: number
      latOffset?: number
      nativeStep?: string | null
      timeList?: string[]
      followPolicy?: import('../../utils/temporal-interval').TemporalFollowPolicy
    },
  ): ActiveLayer {
    const maxOrder = activeLayers.value.reduce((max, l) => Math.max(max, l.order), 0)
    const instanceId = genInstanceId()
    const payload = buildImportedRasterPayload(overlayLayerId, {
      bounds,
      fileName: name,
      sourceCrs: options?.sourceCrs,
      lngOffset: options?.lngOffset,
      latOffset: options?.latOffset,
      nativeStep: options?.nativeStep,
      timeList: options?.timeList,
      followPolicy: options?.followPolicy,
    })
    const accent = assignLayerAccent('#7eb8e0')
    const layer: ActiveLayer = {
      instanceId,
      // catalogId 与后端 overlay_layer_id 对齐，便于 overlay-image-module 加载
      catalogId: overlayLayerId,
      name: name.replace(/\.(tif|tiff)$/i, '') || name,
      visible: true,
      opacity: 0.7,
      order: maxOrder + 1,
      isAdminBoundary: false,
      importedRaster: payload,
      dataState: 'imported',
      accentColor: accent.accentColor,
      accentGlow: accent.accentGlow,
      chipTone: accent.chipTone,
    }
    activeLayers.value.push(layer)
    selectedInstanceId.value = layer.instanceId
    if (sidebarView.value === 'empty' || sidebarView.value === 'library') {
      sidebarView.value = 'active'
    }
    deps.scheduleWorkspacePersist()
    return layer
  }

  function maybeDismissWorkflowRun(runId: string | undefined) {
    if (!runId || deps.isLocalSubmitJobId(runId)) return
    const stillReferenced = activeLayers.value.some((l) => {
      if (l.jobLayer?.jobId === runId) return true
      if (!l.runGroupId) return false
      const g = deps.getRunLayerGroups().find((x) => x.groupId === l.runGroupId)
      return g?.runId === runId
    })
    if (!stillReferenced) {
      rememberDismissedLayer({ runId })
      deps.forgetTrackedWorkflowRun(runId)
    }
  }

  function removeLayer(instanceId: string) {
    const idx = activeLayers.value.findIndex((l) => l.instanceId === instanceId)
    if (idx === -1) return
    pendingVisibilitySync.delete(instanceId)
    const layer = activeLayers.value[idx]!
    const groupBeforeRemove = layer.runGroupId
      ? deps.getRunLayerGroups().find((x) => x.groupId === layer.runGroupId)
      : undefined
    const runIdHint = layer.jobLayer?.jobId || groupBeforeRemove?.runId

    if (layer.jobLayer?.jobId) {
      const jobId = layer.jobLayer.jobId
      deps.stopWorkflowPolling(jobId)
      // 删除运行中图层必须取消后端 run；仅停轮询会留下活跃任务，任务完成后
      // restore/auto-attach 会把图层重新挂回（用户反馈#7）。取消请求异步发出，
      // 本地 UI 先移除；后端取消接口幂等，失败只记日志不阻塞删除。
      if (!['succeeded', 'failed', 'cancelled'].includes(layer.jobLayer.status)) {
        void deps.cancelWorkflowRunForJob(jobId, layer.catalogId).catch((err) => {
          console.warn('[layers] cancel removed workflow failed', jobId, err)
        })
      }
    }
    const retryTimer = deps.getWorkflowRetryTimers().get(layer.catalogId)
    if (retryTimer !== undefined) {
      window.clearTimeout(retryTimer)
      deps.getWorkflowRetryTimers().delete(layer.catalogId)
    }
    deps.getWorkflowRetryCounts().delete(layer.catalogId)
    if (
      !layer.isAdminBoundary &&
      !isLocalImport(layer) &&
      deps.isWeatherEngineLayer(layer.catalogId)
    ) {
      weatherTileManager.clearLayer(layer.catalogId)
    }
    const overlayId = layer.importedRaster?.overlayLayerId
    if (overlayId) {
      void deleteImportedRaster(overlayId).catch((err) => {
        console.warn('[layers] deleteImportedRaster failed', overlayId, err)
        safeLog(
          'client-error',
          '删除导入栅格失败',
          `overlay=${overlayId} err=${String(err)}`,
          'warn',
        )
      })
    }
    const vecBackendId = layer.importedVector?.backendLayerId
    if (vecBackendId) {
      void import('../../services/data-io').then(({ deleteImportedLayer }) =>
        deleteImportedLayer(vecBackendId).catch((err) => {
          console.warn('[layers] deleteImportedLayer failed', vecBackendId, err)
          safeLog(
            'client-error',
            '删除导入矢量失败',
            `backend=${vecBackendId} err=${String(err)}`,
            'warn',
          )
        }),
      )
    }
    rememberDismissedLayer({
      overlayLayerId: overlayId,
      catalogId: isLocalImport(layer) ? undefined : layer.catalogId,
      vectorBackendLayerId: layer.importedVector?.backendLayerId,
      // 持久化真实 runId：否则刷新恢复会重新发现仍在运行/稍后完成的 run，
      // 造成“移除后过一会儿又出现”。
      runId: runIdHint,
    })

    deps.clearWindForCatalog(layer.catalogId)
    if (layer.runGroupId) {
      const g = deps.getRunLayerGroups().find((x) => x.groupId === layer.runGroupId)
      if (g) {
        g.memberInstanceIds = g.memberInstanceIds.filter((id) => id !== instanceId)
        if (!g.memberInstanceIds.length) {
          deps.setRunLayerGroups(deps.getRunLayerGroups().filter((x) => x.groupId !== g.groupId))
        }
      }
    }
    clearPersistedLayerDisplayNames(collectLayerDisplayNameKeys(layer))
    activeLayers.value.splice(idx, 1)

    if (selectedInstanceId.value === instanceId) {
      selectedInstanceId.value = activeLayers.value[0]?.instanceId ?? null
    }
    maybeDismissWorkflowRun(runIdHint)
    deps.flushWorkspacePersistNow()
  }

  /** 同帧内多次显隐：只把最终 visible 同步给 tile manager，避免狂点冲刷 generation */
  const pendingVisibilitySync = new Map<string, ActiveLayer>()
  let visibilitySyncRaf: number | null = null

  function flushVisibilitySyncToTileManager() {
    visibilitySyncRaf = null
    const layers = Array.from(pendingVisibilitySync.values())
    pendingVisibilitySync.clear()
    for (const layer of layers) {
      if (layer.isAdminBoundary) continue
      // 以当前 activeLayers 中的真实状态为准，防止 flush 前图层已被移除
      const live = activeLayers.value.find((item) => item.instanceId === layer.instanceId)
      if (!live) {
        if (!isLocalImport(layer) && deps.isWeatherEngineLayer(layer.catalogId)) {
          weatherTileManager.clearLayer(layer.catalogId)
        }
        continue
      }
      if (isLocalImport(live)) continue
      if (!deps.isWeatherEngineLayer(live.catalogId)) {
        weatherTileManager.clearLayer(live.catalogId)
        continue
      }
      weatherTileManager.setLayerActive(live.catalogId, live.visible)
      if (live.visible && deps.isWeatherEngineLayer(live.catalogId)) {
        weatherTileManager.setViewport(
          live.catalogId,
          deps.getMapCenter(),
          deps.getMapZoom(),
          deps.getCurrentHour(),
          undefined,
          deps.getMapBBox(),
          deps.weatherProviderArg(live.catalogId),
        )
      }
    }
  }

  function scheduleVisibilitySyncToTileManager(layer: ActiveLayer) {
    pendingVisibilitySync.set(layer.instanceId, layer)
    if (visibilitySyncRaf !== null) return
    visibilitySyncRaf = globalThis.requestAnimationFrame(() => {
      flushVisibilitySyncToTileManager()
    })
  }

  function toggleLayerVisibility(instanceId: string) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (!layer) return
    layer.visible = !layer.visible
    scheduleVisibilitySyncToTileManager(layer)
    deps.scheduleWorkspacePersist()
  }

  /** 批量设置所有图层可见性 */
  function setAllLayerVisibility(visible: boolean) {
    // 批量操作立即同步：取消同帧 toggle 排队，避免顺序颠倒
    if (visibilitySyncRaf !== null) {
      globalThis.cancelAnimationFrame(visibilitySyncRaf)
      visibilitySyncRaf = null
    }
    pendingVisibilitySync.clear()
    for (const layer of activeLayers.value) {
      layer.visible = visible
      if (layer.isAdminBoundary || isLocalImport(layer)) continue
      if (!deps.isWeatherEngineLayer(layer.catalogId)) {
        if (visible) continue
        weatherTileManager.clearLayer(layer.catalogId)
        continue
      }
      weatherTileManager.setLayerActive(layer.catalogId, visible)
      if (visible && deps.isWeatherEngineLayer(layer.catalogId)) {
        weatherTileManager.setViewport(
          layer.catalogId,
          deps.getMapCenter(),
          deps.getMapZoom(),
          deps.getCurrentHour(),
          undefined,
          deps.getMapBBox(),
          deps.weatherProviderArg(layer.catalogId),
        )
      }
    }
    deps.scheduleWorkspacePersist()
  }

  /** 批量移除所有图层 */
  function removeAllLayers(_keepBoundary = false) {
    if (visibilitySyncRaf !== null) {
      globalThis.cancelAnimationFrame(visibilitySyncRaf)
      visibilitySyncRaf = null
    }
    pendingVisibilitySync.clear()
    const layersToRemove = [...activeLayers.value]
    const removedJobIds = layersToRemove
      .map((layer) => layer.jobLayer?.jobId)
      .filter((jobId): jobId is string => Boolean(jobId))
    for (const jobId of removedJobIds) {
      deps.stopWorkflowPolling(jobId)
    }
    // 清理所有 429 重试定时器
    for (const timer of deps.getWorkflowRetryTimers().values()) {
      window.clearTimeout(timer)
    }
    deps.getWorkflowRetryTimers().clear()
    deps.getWorkflowRetryCounts().clear()
    const displayNameKeys: string[] = []
    for (const layer of layersToRemove) {
      rememberDismissedLayer({
        overlayLayerId: layer.importedRaster?.overlayLayerId,
        catalogId: isLocalImport(layer) ? undefined : layer.catalogId,
        vectorBackendLayerId: layer.importedVector?.backendLayerId,
        runId: layer.jobLayer?.jobId,
      })
      displayNameKeys.push(...collectLayerDisplayNameKeys(layer))
      if (!isLocalImport(layer) && deps.isWeatherEngineLayer(layer.catalogId)) {
        weatherTileManager.clearLayer(layer.catalogId)
      }
      deps.clearWindForCatalog(layer.catalogId)
      deps.getActiveWorkflowCatalogIds().delete(layer.catalogId)
      if (layer.jobLayer?.jobId) deps.forgetTrackedWorkflowRun(layer.jobLayer.jobId)
    }
    clearPersistedLayerDisplayNames(displayNameKeys)
    activeLayers.value = []
    deps.setRunLayerGroups([])
    selectedInstanceId.value = null
    deps.saveTrackedWorkflowRuns([])
    deps.flushWorkspacePersistNow()
  }

  function setLayerOpacity(instanceId: string, opacity: number) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (layer) {
      layer.opacity = Math.max(0, Math.min(1, opacity))
      deps.scheduleWorkspacePersist()
    }
  }

  /** 设置图层配色方案覆盖（null 恢复为默认配色） */
  function setLayerPaletteOverride(instanceId: string, palette: string | null) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (layer) {
      layer.paletteOverride = palette
      deps.scheduleWorkspacePersist()
    }
  }

  function setLayerRangeOverride(
    instanceId: string,
    range: { vmin?: number | null; vmax?: number | null },
  ) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (!layer) return
    if ('vmin' in range) layer.vminOverride = range.vmin ?? null
    if ('vmax' in range) layer.vmaxOverride = range.vmax ?? null
    deps.scheduleWorkspacePersist()
  }

  function setLayerNodataDisplay(
    instanceId: string,
    options: { mode?: 'transparent' | 'solid' | null; color?: string | null },
  ) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (!layer) return
    if ('mode' in options) layer.nodataMode = options.mode ?? null
    if ('color' in options) layer.nodataColor = options.color ?? null
    deps.scheduleWorkspacePersist()
  }

  function setLayerOrder(instanceId: string, newOrder: number) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (layer) {
      layer.order = newOrder
      deps.scheduleWorkspacePersist()
    }
  }

  /** 覆盖图层显示名（仅显示名；不改 catalogId / overlay / instanceId） */
  function setLayerDisplayName(instanceId: string, name: string) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (!layer) return
    const trimmed = normalizeDisplayName(name)
    if (!trimmed) return
    layer.name = trimmed

    // 同步导入载荷上的展示名（导出文件名 / 源标签 / 图例）
    if (layer.importedVector) {
      layer.importedVector = { ...layer.importedVector, fileName: trimmed }
    }
    if (layer.importedRaster) {
      layer.importedRaster = { ...layer.importedRaster, fileName: trimmed }
    }

    // 新写入：instanceId + 导入后端键；目录/天气不再写 catalogId，避免污染新实例
    const keys = new Set<string>()
    keys.add(layer.instanceId)
    if (layer.importedVector?.backendLayerId) {
      keys.add(layer.importedVector.backendLayerId)
    }
    if (layer.importedRaster?.overlayLayerId) {
      keys.add(layer.importedRaster.overlayLayerId)
    }
    for (const key of keys) {
      persistLayerDisplayName(key, trimmed)
    }
    // 清理旧 catalogId 键（含运行时 id 上的历史污染）
    clearPersistedLayerDisplayNames([layer.catalogId])

    // 同步 jobLayers / 运行跟踪名（分析面板、状态条）——按 jobId / 本实例关联
    if (layer.jobLayer) {
      layer.jobLayer = { ...layer.jobLayer, name: trimmed }
    }
    const jobId = layer.jobLayer?.jobId
    for (const job of deps.getJobLayers()) {
      if (jobId && job.jobId === jobId) {
        job.name = trimmed
      }
    }

    // 同步工作流产出注册表（图层面板库）
    if (isRuntimeCatalogId(layer.catalogId) && layer.catalogId.startsWith('wf-out-')) {
      try {
        useWorkflowOutputLayersStore().renameOutputLayer(layer.catalogId, trimmed)
      } catch {
        /* store may be unavailable in tests */
      }
    }

    // 通知地图矢量弹窗标题刷新
    if (typeof window !== 'undefined') {
      window.dispatchEvent(
        new CustomEvent('cgda:layer-renamed', {
          detail: { instanceId, catalogId: layer.catalogId, name: trimmed },
        }),
      )
    }

    // 导入图层：异步写回后端 meta.display_name（失败不影响本地）
    const backendId =
      layer.importedVector?.backendLayerId ||
      layer.importedRaster?.overlayLayerId ||
      (layer.catalogId.startsWith('imported-') ? layer.catalogId : null)
    if (backendId) {
      void import('../../data-manager/core/api')
        .then(({ renameImportedLayerDisplayName }) =>
          renameImportedLayerDisplayName(backendId, trimmed),
        )
        .catch(() => undefined)
    }
    deps.scheduleWorkspacePersist()
  }

  /** 置顶：order = max+1 */
  function bringLayerToFront(instanceId: string) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (!layer) return
    const maxOrder = activeLayers.value.reduce((max, l) => Math.max(max, l.order), 0)
    layer.order = maxOrder + 1
    deps.scheduleWorkspacePersist()
  }

  /** 置底：order = min-1 */
  function sendLayerToBack(instanceId: string) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (!layer) return
    const minOrder = activeLayers.value.reduce((min, l) => Math.min(min, l.order), 0)
    layer.order = minOrder - 1
    deps.scheduleWorkspacePersist()
  }

  function selectLayer(instanceId: string | null) {
    selectedInstanceId.value = instanceId
  }

  function setSidebarView(view: LayerSidebarView) {
    sidebarView.value = view
  }

  return {
    activeLayers,
    sidebarView,
    selectedInstanceId,
    activeLayersDisplay,
    selectedLayerDisplay,
    activeLayerCount,
    sidebarViewLabel,
    usedLayerAccentColors,
    assignLayerAccent,
    addLayer,
    addImportedVectorLayer,
    addDrawDraftLayer,
    getImportedVectorGeojson,
    updateImportedVectorGeojson,
    setImportedVectorStyle,
    addImportedRasterLayer,
    maybeDismissWorkflowRun,
    removeLayer,
    toggleLayerVisibility,
    setAllLayerVisibility,
    removeAllLayers,
    setLayerOpacity,
    setLayerPaletteOverride,
    setLayerRangeOverride,
    setLayerNodataDisplay,
    setLayerOrder,
    setLayerDisplayName,
    bringLayerToFront,
    sendLayerToBack,
    selectLayer,
    setSidebarView,
    isLocalImport,
    genInstanceId,
  }
}
