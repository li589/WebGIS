/**
 * Runtime layer catalog + library slice extracted from the layers god store.
 * Public API remains re-exported via useLayersStore().
 */
import { computed, ref, type ComputedRef, type Ref } from 'vue'

import {
  fetchLayerCatalog,
  fetchLayerCategories,
  type LayerCategoryResponse,
  type LayerDescriptor,
  type OnlineTemporalCapability,
} from '../../services/runtime-api'
import {
  getOnlineTemporalConfig,
  supportsMapLayerCapability,
  supportsOnlineTemporalCapability,
  supportsParticleFlowCapability,
  supportsViewportDrivenRefreshCapability,
} from '../../services/layer-capabilities'
import {
  applyResearchGroupCategoryLabel,
  LAYER_CATEGORIES,
  LAYER_LIBRARY,
  setRuntimeCategoryNameOverrides,
} from './catalog'
import {
  buildCatalogFallbackItem,
  buildCategoryIndex,
  buildRuntimeLayerLibraryItem,
  getCatalogDisplayName,
  isBlockedRunReadiness,
} from './catalog-builders'
import {
  useWorkflowOutputLayersStore,
  WORKFLOW_OUTPUT_SUBCATEGORY,
} from '../workflow-output-layers'
import { isWeatherEngineCatalogId } from './weather-session'
import { isEnglishInversionCatalogId, resolveInversionCatalogId } from './inversion-catalog'
import type {
  ActiveLayer,
  ActiveRunLayerGroup,
  JobLayerItem,
  JobStatus,
  LayerCategory,
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
  /** 图层平台 P1：运行时分组（种子⊕管理；空表时回落静态 codegen） */
  layerCategories: ComputedRef<LayerCategory[]>
  layerLibrary: ComputedRef<RuntimeLayerLibraryItem[]>
  layerLibraryMap: ComputedRef<Map<string, RuntimeLayerLibraryItem>>
  catalogJobStatus: ComputedRef<Map<string, JobStatus>>
  catalogRunReadiness: ComputedRef<Map<string, string>>
  ensureRuntimeLayerCatalog: (force?: boolean) => Promise<void>
  /** 图层平台 P1：仅刷新分组定义（分组管理对话框保存后调用） */
  reloadLayerCategories: () => Promise<void>
  getRuntimeLayerDescriptor: (catalogId: string) => LayerDescriptor | null
  resolveBackendLayerId: (catalogId: string) => string
  resolveEffectiveDescriptor: (catalogId: string) => LayerDescriptor | null
  getCatalogWorkflowEngine: (catalogId: string) => string | null
  supportsAnalysisWorkflow: (catalogId: string) => boolean
  /** overlay 静态/时间序列图层（engine=overlay_registry 或空）：无工作流但有 PNG 缓存。 */
  isOverlayDisplayOnlyLayer: (catalogId: string) => boolean
  /** 添加路径独立语义：overlay 图层永不阻断。运行按钮仍走 getCatalogRunBlockReason。 */
  getCatalogAddBlockReason: (catalogId: string) => string | null
  getCatalogRunBlockReason: (catalogId: string) => string | null
  canRunCatalog: (catalogId: string) => boolean
  isWeatherEngineLayer: (catalogId: string) => boolean
  supportsMapLayerResult: (catalogId: string) => boolean
  supportsViewportDrivenRefresh: (catalogId: string) => boolean
  supportsParticleFlow: (catalogId: string) => boolean
  supportsOnlineTemporal: (catalogId: string) => boolean
  getOnlineTemporalConfig: (catalogId: string) => OnlineTemporalCapability | null
  getLayerPrimaryMetric: (catalogId: string) => string | null
  setRuntimeLayerCatalog: (catalog: Record<string, LayerDescriptor>) => void
}

export function createCatalogRuntimeSlice(deps: CatalogRuntimeSliceDeps): CatalogRuntimeSlice {
  const runtimeLayerCatalog = ref<Record<string, LayerDescriptor>>({})
  const runtimeLayerCatalogLoading = ref(false)
  let runtimeLayerCatalogRequest: Promise<void> | null = null

  // ── 图层平台 P1：运行时分组（/layers/categories，种子⊕管理状态） ──────────
  const runtimeLayerCategories = ref<LayerCategory[]>([])

  function applyLayerCategoryResponse(response: LayerCategoryResponse) {
    const mapped = applyResearchGroupCategoryLabel(
      response.items.map((item) => ({
        id: item.id,
        name: item.name,
        icon: item.icon ?? '',
        accentColor: item.accent_color ?? '',
        chipTone: item.chip_tone ?? '',
        position: item.position ?? undefined,
        isCustom: item.is_custom ?? undefined,
      })),
    )
    runtimeLayerCategories.value = mapped
    setRuntimeCategoryNameOverrides(new Map(mapped.map((c) => [c.id, c.name])))
  }

  /** 运行时分组（未加载/失败回落静态 codegen 表） */
  const layerCategories = computed<LayerCategory[]>(() =>
    runtimeLayerCategories.value.length > 0 ? runtimeLayerCategories.value : LAYER_CATEGORIES,
  )
  const categoryIndexById = computed(() => buildCategoryIndex(layerCategories.value))

  const layerLibrary = computed<RuntimeLayerLibraryItem[]>(() => {
    const categories = layerCategories.value
    const allRuntimeItems = Object.values(runtimeLayerCatalog.value).map((descriptor) =>
      buildRuntimeLayerLibraryItem(descriptor, categories),
    )

    let items: RuntimeLayerLibraryItem[]
    if (allRuntimeItems.length > 0) {
      // X1: 分离独立条目、合并组虚拟条目与合并源条目（均从后端 descriptor 派生）
      const standaloneItems: RuntimeLayerLibraryItem[] = []
      const mergedGroupItems: RuntimeLayerLibraryItem[] = []
      const mergedSourceItems = new Map<string, RuntimeLayerLibraryItem>()

      for (const item of allRuntimeItems) {
        if (item.isMergedGroup) {
          // X1: 合并组虚拟条目 — 后端 descriptor.is_merged_group=true
          mergedGroupItems.push(item)
        } else if (item.mergedInto) {
          // X1: 合并组成员 — 后端 descriptor.merged_into 指向父条目
          mergedSourceItems.set(item.catalogId, item)
        } else {
          standaloneItems.push(item)
        }
      }

      // X1: 为每个合并组虚拟条目 enriched sources（注入成员的运行时状态）
      const mergedEntries: RuntimeLayerLibraryItem[] = mergedGroupItems.map((groupItem) => {
        const memberIds = groupItem.members ?? []

        const enrichedSources = groupItem.sources.map((source) => {
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
          memberIds
            .map((sid) => mergedSourceItems.get(sid))
            .find((rt) => rt && !isBlockedRunReadiness(rt.runReadiness)) ??
          (memberIds.length > 0 ? mergedSourceItems.get(memberIds[0]) : undefined)

        return {
          ...groupItem,
          sources: enrichedSources,
          description: representative?.description ?? groupItem.description,
          runReadiness: representative?.runReadiness ?? groupItem.runReadiness,
          runReadinessSummary: representative?.runReadinessSummary ?? groupItem.runReadinessSummary,
          runReadinessNotes: representative?.runReadinessNotes ?? groupItem.runReadinessNotes,
          backendStatus: representative?.backendStatus ?? groupItem.backendStatus,
          supportsTime: representative?.supportsTime ?? groupItem.supportsTime,
          engine: representative?.engine ?? groupItem.engine,
          sourceType: representative?.sourceType ?? groupItem.sourceType,
          renderType: representative?.renderType ?? groupItem.renderType,
          workflowName: representative?.workflowName ?? groupItem.workflowName,
          defaultVisible: representative?.defaultVisible ?? groupItem.defaultVisible,
        }
      })

      items = standaloneItems.concat(mergedEntries)
    } else {
      // 静态兜底：显示独立条目和合并组虚拟条目，隐藏合并源成员条目
      items = LAYER_LIBRARY.filter((item) => !item.isAdminBoundary && !item.mergedInto).map(
        (item) => buildCatalogFallbackItem(null, item.catalogId),
      )
    }

    const outputStore = useWorkflowOutputLayersStore()
    const researchCategory = categories.find((c) => c.id === 'research-group')
    const researchAccent = researchCategory?.accentColor ?? '#ff6f91'
    const researchChip = researchCategory?.chipTone ?? 'rgba(255, 111, 145, 0.16)'
    // 仅滤显示名/localId 污染；sourceWorkflowId 是机器路由键，不进卡片名
    const outputItems: RuntimeLayerLibraryItem[] = outputStore.entries
      .filter(
        (entry) =>
          !isEnglishInversionCatalogId(entry.name) && !isEnglishInversionCatalogId(entry.localId),
      )
      .map((entry) => {
        // 勿把 omega_sf_fenkuai_* 写进 sourceLabel / description（库卡片副文案）
        const sourceLabel = isEnglishInversionCatalogId(entry.sourceWorkflowId)
          ? '工作流产出'
          : `工作流: ${entry.sourceWorkflowId}`
        const mappedSource = resolveInversionCatalogId(entry.sourceLayerId)
        const sourceLayerLabel = isEnglishInversionCatalogId(entry.sourceLayerId)
          ? mappedSource.startsWith('method-')
            ? mappedSource
            : '反演目录图层'
          : entry.sourceLayerId
        return {
          catalogId: entry.localId,
          name: entry.name,
          category: 'research-group' as const,
          subCategory: WORKFLOW_OUTPUT_SUBCATEGORY,
          metricLabel: '产出',
          metricUnit: '',
          metricPrecision: 1,
          updateLabel: '工作流驱动',
          sourceLabel,
          accentColor: researchAccent,
          accentGlow: 'rgba(255, 111, 145, 0.28)',
          chipTone: researchChip,
          sources: [],
          description: `模型输出 · 源图层: ${sourceLayerLabel}`,
          engine: entry.engine,
          workflowName: entry.name,
          runReadiness: 'ready' as const,
          runReadinessSummary: '工作流产出图层，可运行源工作流刷新数据',
          runReadinessNotes: [],
          backendStatus: 'sample' as const,
          supportsTime: false,
        }
      })

    const isDatasetLibraryItem = (item: RuntimeLayerLibraryItem) =>
      item.category !== 'boundary' &&
      !item.isAdminBoundary &&
      item.catalogId !== 'admin-boundary' &&
      item.catalogId !== 'admin-boundary-cn'

    return items
      .concat(outputItems)
      .filter(isDatasetLibraryItem)
      .filter(
        (item) =>
          !isEnglishInversionCatalogId(item.catalogId) && !isEnglishInversionCatalogId(item.name),
      )
      .sort((a, b) => {
        const categoryIndex = categoryIndexById.value
        const categoryOrderA = categoryIndex.get(a.category) ?? Number.MAX_SAFE_INTEGER
        const categoryOrderB = categoryIndex.get(b.category) ?? Number.MAX_SAFE_INTEGER
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
    // X1: 合并条目的各源 ID 也需可查（addLayer 等通过 source ID 查找 accent 等信息）
    for (const descriptor of Object.values(runtimeLayerCatalog.value)) {
      if (!map.has(descriptor.layer_id) && descriptor.merged_into) {
        map.set(
          descriptor.layer_id,
          buildRuntimeLayerLibraryItem(descriptor, layerCategories.value),
        )
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
    // 图层平台 P1：分组定义与目录并行加载；分组失败不阻断目录（回落静态表）
    void fetchLayerCategories()
      .then(applyLayerCategoryResponse)
      .catch((error) => {
        console.warn('[LayersStore] fetchLayerCategories failed, fallback to static:', error)
      })
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
    if (engine === 'python_provider' || engine === 'gee') return true
    // overlay_registry 也有图层资产工作流（/overlay-asset-workflows），
    // 只是不走分析引擎；runWorkflowForCatalog 会根据该返回值分流。
    if (engine === 'overlay_registry' || engine === '') return true
    return false
  }

  /** overlay 静态/时间序列图层也是工作流驱动：/overlay-asset-workflows
   * 先检查烘焙资产，陈旧/缺失后台重烘；只是不走 python_provider 分析引擎。 */
  function isOverlayDisplayOnlyLayer(catalogId: string): boolean {
    const backendLayerId = resolveBackendLayerId(catalogId)
    if (isWeatherEngineLayer(backendLayerId) || isWeatherEngineLayer(catalogId)) return false
    const engine =
      getCatalogWorkflowEngine(backendLayerId) || getCatalogWorkflowEngine(catalogId) || ''
    return engine === 'overlay_registry' || engine === ''
  }

  /** 添加路径独立语义：overlay 图层永不阻断（其 PNG 缓存由 map-canvas 自动加载）。 */
  function getCatalogAddBlockReason(catalogId: string): string | null {
    if (isOverlayDisplayOnlyLayer(catalogId)) return null
    return getCatalogRunBlockReason(catalogId)
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

  function supportsOnlineTemporal(catalogId: string): boolean {
    const descriptor = resolveEffectiveDescriptor(catalogId)
    return supportsOnlineTemporalCapability(descriptor)
  }

  function getOnlineTemporalConfigForCatalog(catalogId: string): OnlineTemporalCapability | null {
    const descriptor = resolveEffectiveDescriptor(catalogId)
    return getOnlineTemporalConfig(descriptor)
  }

  function getLayerPrimaryMetric(catalogId: string): string | null {
    return getRuntimeLayerDescriptor(catalogId)?.capabilities?.primary_metric ?? null
  }

  function setRuntimeLayerCatalog(catalog: Record<string, LayerDescriptor>) {
    runtimeLayerCatalog.value = catalog
  }

  async function reloadLayerCategories() {
    // 分组管理保存后刷新：失败时保留现值（下一次 ensureRuntimeLayerCatalog 仍会重试）
    try {
      applyLayerCategoryResponse(await fetchLayerCategories())
    } catch (error) {
      console.warn('[LayersStore] reloadLayerCategories failed:', error)
      throw error
    }
  }

  return {
    runtimeLayerCatalog,
    runtimeLayerCatalogLoading,
    layerCategories,
    reloadLayerCategories,
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
    isOverlayDisplayOnlyLayer,
    getCatalogAddBlockReason,
    getCatalogRunBlockReason,
    canRunCatalog,
    isWeatherEngineLayer,
    supportsMapLayerResult,
    supportsViewportDrivenRefresh,
    supportsParticleFlow,
    supportsOnlineTemporal,
    getOnlineTemporalConfig: getOnlineTemporalConfigForCatalog,
    getLayerPrimaryMetric,
    setRuntimeLayerCatalog,
  }
}
