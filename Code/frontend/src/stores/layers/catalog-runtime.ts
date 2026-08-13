/**
 * Runtime layer catalog + library slice extracted from the layers god store.
 * Public API remains re-exported via useLayersStore().
 */
import { computed, ref, type ComputedRef, type Ref } from 'vue'

import { fetchLayerCatalog, type LayerDescriptor } from '../../services/runtime-api'
import {
  supportsMapLayerCapability,
  supportsParticleFlowCapability,
  supportsViewportDrivenRefreshCapability,
} from '../../services/layer-capabilities'
import { LAYER_CATEGORIES, LAYER_LIBRARY, MERGED_LAYER_GROUPS, getMergedCatalogId } from './catalog'
import {
  buildCatalogFallbackItem,
  buildRuntimeLayerLibraryItem,
  CATEGORY_INDEX_BY_ID,
  getCatalogDisplayName,
  getStaticLayerLibraryItem,
  isBlockedRunReadiness,
} from './catalog-builders'
import {
  useWorkflowOutputLayersStore,
  WORKFLOW_OUTPUT_SUBCATEGORY,
} from '../workflow-output-layers'
import { isWeatherEngineCatalogId } from './weather-session'
import type {
  ActiveLayer,
  ActiveRunLayerGroup,
  JobLayerItem,
  JobStatus,
  RuntimeLayerLibraryItem,
} from './types'

export interface CatalogRuntimeSliceDeps {
  getActiveLayers: () => ActiveLayer[]
  getRunLayerGroups: () => ActiveRunLayerGroup[]
  getJobLayers: () => JobLayerItem[]
  /** Called after catalog fetch succeeds (e.g. reconcile weather tile active set). */
  onCatalogLoaded?: () => void
}

export interface CatalogRuntimeSlice {
  runtimeLayerCatalog: Ref<Record<string, LayerDescriptor>>
  runtimeLayerCatalogLoading: Ref<boolean>
  layerLibrary: ComputedRef<RuntimeLayerLibraryItem[]>
  layerLibraryMap: ComputedRef<Map<string, RuntimeLayerLibraryItem>>
  catalogJobStatus: ComputedRef<Map<string, JobStatus>>
  catalogRunReadiness: ComputedRef<Map<string, string>>
  ensureRuntimeLayerCatalog: (force?: boolean) => Promise<void>
  getRuntimeLayerDescriptor: (catalogId: string) => LayerDescriptor | null
  resolveBackendLayerId: (catalogId: string) => string
  resolveEffectiveDescriptor: (catalogId: string) => LayerDescriptor | null
  getCatalogWorkflowEngine: (catalogId: string) => string | null
  supportsAnalysisWorkflow: (catalogId: string) => boolean
  getCatalogRunBlockReason: (catalogId: string) => string | null
  canRunCatalog: (catalogId: string) => boolean
  isWeatherEngineLayer: (catalogId: string) => boolean
  supportsMapLayerResult: (catalogId: string) => boolean
  supportsViewportDrivenRefresh: (catalogId: string) => boolean
  supportsParticleFlow: (catalogId: string) => boolean
  getLayerPrimaryMetric: (catalogId: string) => string | null
  setRuntimeLayerCatalog: (catalog: Record<string, LayerDescriptor>) => void
}

export function createCatalogRuntimeSlice(deps: CatalogRuntimeSliceDeps): CatalogRuntimeSlice {
  const runtimeLayerCatalog = ref<Record<string, LayerDescriptor>>({})
  const runtimeLayerCatalogLoading = ref(false)
  let runtimeLayerCatalogRequest: Promise<void> | null = null

  const layerLibrary = computed<RuntimeLayerLibraryItem[]>(() => {
    const allRuntimeItems = Object.values(runtimeLayerCatalog.value).map((descriptor) =>
      buildRuntimeLayerLibraryItem(descriptor),
    )

    let items: RuntimeLayerLibraryItem[]
    if (allRuntimeItems.length > 0) {
      // 分离独立条目与合并源条目
      const standaloneItems: RuntimeLayerLibraryItem[] = []
      const mergedSourceItems = new Map<string, RuntimeLayerLibraryItem>()

      for (const item of allRuntimeItems) {
        const mergedId = getMergedCatalogId(item.catalogId)
        if (mergedId) {
          mergedSourceItems.set(item.catalogId, item)
        } else {
          standaloneItems.push(item)
        }
      }

      // 为每个合并组构建 enriched 条目
      const mergedEntries: RuntimeLayerLibraryItem[] = []
      for (const [mergedCatalogId, sourceIds] of MERGED_LAYER_GROUPS) {
        const staticEntry = getStaticLayerLibraryItem(mergedCatalogId)
        if (!staticEntry) continue

        const enrichedSources = staticEntry.sources.map((source) => {
          const rt = mergedSourceItems.get(source.id)
          return {
            ...source,
            runReadiness: rt?.runReadiness,
            runReadinessSummary: rt?.runReadinessSummary,
            backendStatus: rt?.backendStatus,
            supportsTime: rt?.supportsTime,
          }
        })

        // 选取第一个 ready 的源作为代表状态
        const representative =
          sourceIds
            .map((sid) => mergedSourceItems.get(sid))
            .find((rt) => rt && !isBlockedRunReadiness(rt.runReadiness)) ??
          mergedSourceItems.get(sourceIds[0])

        mergedEntries.push({
          ...staticEntry,
          sources: enrichedSources,
          description: representative?.description ?? `${staticEntry.name}（多源可选）`,
          runReadiness: representative?.runReadiness ?? 'ready',
          runReadinessSummary: representative?.runReadinessSummary ?? null,
          runReadinessNotes: representative?.runReadinessNotes ?? [],
          backendStatus: representative?.backendStatus ?? null,
          supportsTime: representative?.supportsTime ?? false,
          engine: representative?.engine ?? null,
          sourceType: representative?.sourceType ?? null,
          renderType: representative?.renderType ?? null,
          workflowName: representative?.workflowName ?? null,
          defaultVisible: representative?.defaultVisible ?? undefined,
        })
      }

      items = standaloneItems.concat(mergedEntries)
    } else {
      // 静态兜底：隐藏已合并的独立条目
      items = LAYER_LIBRARY.filter((item) => !item.isAdminBoundary && !item.mergedInto).map(
        (item) => buildCatalogFallbackItem(null, item.catalogId),
      )
    }

    const outputStore = useWorkflowOutputLayersStore()
    const researchCategory = LAYER_CATEGORIES.find((c) => c.id === 'research-group')
    const researchAccent = researchCategory?.accentColor ?? '#ff6f91'
    const researchChip = researchCategory?.chipTone ?? 'rgba(255, 111, 145, 0.16)'
    const outputItems: RuntimeLayerLibraryItem[] = outputStore.entries.map((entry) => ({
      catalogId: entry.localId,
      name: entry.name,
      category: 'research-group',
      subCategory: WORKFLOW_OUTPUT_SUBCATEGORY,
      metricLabel: '产出',
      metricUnit: '',
      metricPrecision: 1,
      updateLabel: '工作流驱动',
      sourceLabel: `工作流: ${entry.sourceWorkflowId}`,
      accentColor: researchAccent,
      accentGlow: 'rgba(255, 111, 145, 0.28)',
      chipTone: researchChip,
      sources: [],
      description: `模型输出 · 源图层: ${entry.sourceLayerId}`,
      engine: entry.engine,
      workflowName: entry.name,
      runReadiness: 'ready',
      runReadinessSummary: '工作流产出图层，可运行源工作流刷新数据',
      runReadinessNotes: [],
      backendStatus: 'sample',
      supportsTime: false,
    }))

    const isDatasetLibraryItem = (item: RuntimeLayerLibraryItem) =>
      item.category !== 'boundary' &&
      !item.isAdminBoundary &&
      item.catalogId !== 'admin-boundary' &&
      item.catalogId !== 'admin-boundary-cn'

    return items
      .concat(outputItems)
      .filter(isDatasetLibraryItem)
      .sort((a, b) => {
        const categoryOrderA = CATEGORY_INDEX_BY_ID.get(a.category) ?? Number.MAX_SAFE_INTEGER
        const categoryOrderB = CATEGORY_INDEX_BY_ID.get(b.category) ?? Number.MAX_SAFE_INTEGER
        if (categoryOrderA !== categoryOrderB) {
          return categoryOrderA - categoryOrderB
        }
        return a.name.localeCompare(b.name, 'zh-CN')
      })
  })

  const layerLibraryMap = computed(() => {
    const map = new Map<string, RuntimeLayerLibraryItem>()
    for (const item of layerLibrary.value) {
      map.set(item.catalogId, item)
    }
    // 合并条目的各源 ID 也需可查（addLayer 等通过 source ID 查找 accent 等信息）
    for (const descriptor of Object.values(runtimeLayerCatalog.value)) {
      if (!map.has(descriptor.layer_id) && getMergedCatalogId(descriptor.layer_id)) {
        map.set(descriptor.layer_id, buildRuntimeLayerLibraryItem(descriptor))
      }
    }
    // 静态兜底：后端未返回时也需包含被隐藏的独立源条目
    for (const item of LAYER_LIBRARY) {
      if (item.mergedInto && !map.has(item.catalogId)) {
        map.set(item.catalogId, buildCatalogFallbackItem(null, item.catalogId))
      }
    }
    return map
  })

  const catalogJobStatus = computed(() => {
    const map = new Map<string, JobStatus>()
    for (const job of deps.getJobLayers()) {
      if (job.catalogId) map.set(job.catalogId, job.status)
    }
    for (const layer of deps.getActiveLayers()) {
      if (layer.jobLayer) {
        map.set(layer.catalogId, layer.jobLayer.status)
      }
    }
    return map
  })

  const catalogRunReadiness = computed(() => {
    const map = new Map<string, string>()
    for (const descriptor of Object.values(runtimeLayerCatalog.value)) {
      map.set(descriptor.layer_id, descriptor.run_readiness ?? 'ready')
    }
    return map
  })

  function getRuntimeLayerDescriptor(catalogId: string) {
    return runtimeLayerCatalog.value[catalogId] ?? null
  }

  function resolveBackendLayerId(catalogId: string): string {
    if (catalogId.startsWith('wf-out-')) {
      const outputStore = useWorkflowOutputLayersStore()
      const entry = outputStore.getByLocalId(catalogId)
      return entry?.sourceLayerId ?? catalogId
    }
    if (catalogId.startsWith('wf-run-')) {
      const layer = deps.getActiveLayers().find((l) => l.catalogId === catalogId)
      if (layer?.runGroupId) {
        const g = deps.getRunLayerGroups().find((x) => x.groupId === layer.runGroupId)
        if (g?.sourceLayerId) return g.sourceLayerId
      }
    }
    return catalogId
  }

  function resolveEffectiveDescriptor(catalogId: string): LayerDescriptor | null {
    if (catalogId.startsWith('wf-out-') || catalogId.startsWith('wf-run-')) {
      const backendId = resolveBackendLayerId(catalogId)
      return getRuntimeLayerDescriptor(backendId)
    }
    return getRuntimeLayerDescriptor(catalogId)
  }

  async function ensureRuntimeLayerCatalog(force = false) {
    if (!force && Object.keys(runtimeLayerCatalog.value).length > 0) {
      return
    }
    if (runtimeLayerCatalogRequest && !force) {
      return runtimeLayerCatalogRequest
    }

    runtimeLayerCatalogLoading.value = true
    runtimeLayerCatalogRequest = fetchLayerCatalog()
      .catch(async (error) => {
        const message = error instanceof Error ? error.message : String(error)
        const shouldRetry = /AbortError|aborted without reason|Failed to fetch|NetworkError/i.test(
          message,
        )
        if (!shouldRetry) {
          throw error
        }
        await new Promise((resolve) => window.setTimeout(resolve, 250))
        return fetchLayerCatalog()
      })
      .then((response) => {
        runtimeLayerCatalog.value = Object.fromEntries(
          response.items.map((item) => [item.layer_id, item]),
        )
        deps.onCatalogLoaded?.()
      })
      .catch((error) => {
        console.warn(
          '[LayersStore] ensureRuntimeLayerCatalog failed, will retry on next call:',
          error.message,
        )
        runtimeLayerCatalogRequest = null
        throw error
      })
      .finally(() => {
        runtimeLayerCatalogLoading.value = false
        runtimeLayerCatalogRequest = null
      })

    return runtimeLayerCatalogRequest
  }

  function getCatalogWorkflowEngine(catalogId: string): string | null {
    const descriptor = getRuntimeLayerDescriptor(catalogId)
    if (descriptor?.engine) return descriptor.engine
    const libItem = layerLibraryMap.value.get(catalogId)
    return libItem?.engine ?? null
  }

  function isWeatherEngineLayer(catalogId: string): boolean {
    return isWeatherEngineCatalogId(catalogId, getRuntimeLayerDescriptor(catalogId))
  }

  function supportsAnalysisWorkflow(catalogId: string): boolean {
    const backendLayerId = resolveBackendLayerId(catalogId)
    if (isWeatherEngineLayer(backendLayerId) || isWeatherEngineLayer(catalogId)) return false
    const engine = getCatalogWorkflowEngine(backendLayerId) || getCatalogWorkflowEngine(catalogId)
    // overlay_registry / missing engine = display-only; only these engines can submit /workflow-runs
    return engine === 'python_provider' || engine === 'gee'
  }

  function getCatalogRunBlockReason(catalogId: string) {
    const backendLayerId = resolveBackendLayerId(catalogId)
    if (isWeatherEngineLayer(backendLayerId) || isWeatherEngineLayer(catalogId)) {
      return null
    }
    if (!supportsAnalysisWorkflow(catalogId)) {
      return `${getCatalogDisplayName(catalogId)} 未配置分析工作流引擎（静态叠加请直接加载图层）`
    }

    const descriptor =
      getRuntimeLayerDescriptor(backendLayerId) ?? getRuntimeLayerDescriptor(catalogId)
    if (!descriptor || !isBlockedRunReadiness(descriptor.run_readiness)) {
      return null
    }

    return (
      descriptor.run_readiness_summary ??
      descriptor.run_readiness_notes?.[0] ??
      `${getCatalogDisplayName(catalogId)} 默认数据源未就绪`
    )
  }

  function canRunCatalog(catalogId: string) {
    return !getCatalogRunBlockReason(catalogId)
  }

  function supportsMapLayerResult(catalogId: string) {
    return supportsMapLayerCapability(getRuntimeLayerDescriptor(catalogId))
  }

  function supportsViewportDrivenRefresh(catalogId: string) {
    return supportsViewportDrivenRefreshCapability(getRuntimeLayerDescriptor(catalogId))
  }

  function supportsParticleFlow(catalogId: string): boolean {
    const descriptor = getRuntimeLayerDescriptor(catalogId)
    if (descriptor) {
      return supportsParticleFlowCapability(descriptor)
    }
    return catalogId.startsWith('wind-field')
  }

  function getLayerPrimaryMetric(catalogId: string): string | null {
    return getRuntimeLayerDescriptor(catalogId)?.capabilities?.primary_metric ?? null
  }

  function setRuntimeLayerCatalog(catalog: Record<string, LayerDescriptor>) {
    runtimeLayerCatalog.value = catalog
  }

  return {
    runtimeLayerCatalog,
    runtimeLayerCatalogLoading,
    layerLibrary,
    layerLibraryMap,
    catalogJobStatus,
    catalogRunReadiness,
    ensureRuntimeLayerCatalog,
    getRuntimeLayerDescriptor,
    resolveBackendLayerId,
    resolveEffectiveDescriptor,
    getCatalogWorkflowEngine,
    supportsAnalysisWorkflow,
    getCatalogRunBlockReason,
    canRunCatalog,
    isWeatherEngineLayer,
    supportsMapLayerResult,
    supportsViewportDrivenRefresh,
    supportsParticleFlow,
    getLayerPrimaryMetric,
    setRuntimeLayerCatalog,
  }
}
