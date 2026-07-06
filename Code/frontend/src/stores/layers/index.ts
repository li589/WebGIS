import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { demoLayerCatalog } from '../../app/demo-data'
import { resolveDemoLayer } from '../../app/demo-adapter'
import { getWorkflowRun, submitWorkflow, cancelWorkflowRun, retryWorkflowRun } from '../../services/runtime-api'
import type { BoundingBox } from '../../services/runtime-api'
import { LAYER_CATEGORIES, LAYER_LIBRARY, LAYER_LIBRARY_BY_CATEGORY } from './catalog'
import { buildJobLayer } from './result-adapter'
import type { ActiveLayer, ActiveLayerDisplay, JobLayerItem, JobStatus, LayerSidebarView } from './types'

function genInstanceId() {
  return `layer-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function isTerminalStatus(status: string) {
  // retry_pending 是非终态（等待重试），不应包含在此处
  return status === 'succeeded' || status === 'failed' || status === 'cancelled'
}

// 轮询退避配置：对齐后端 retry_policy（max_attempts=3, initial_backoff=2s）
const POLL_INITIAL_INTERVAL_MS = 1500
const POLL_MAX_INTERVAL_MS = 10000
const POLL_MAX_ATTEMPTS = 30 // 总轮询次数上限，防止后端异常时无限轮询

function getCatalogDisplayName(catalogId: string) {
  return LAYER_LIBRARY.find((item) => item.catalogId === catalogId)?.name ?? catalogId
}

// ─── Store ───────────────────────────────────────────────────────────────────

export const useLayersStore = defineStore('layers', () => {
  // ── Active layers (已添加的图层实例) ──────────────────────────────────────
  const activeLayers = ref<ActiveLayer[]>([])

  // ── Sidebar view mode ────────────────────────────────────────────────────
  const sidebarView = ref<LayerSidebarView>('empty')

  // ── Selected instance ID (点击某个已添加图层时在 InfoPanel 展示详情) ──────
  const selectedInstanceId = ref<string | null>(null)

  // ── Job layers (作业生产数据，从后端 workflow 拉取) ─────────────────────────
  const jobLayers = ref<JobLayerItem[]>([])

  // ── Current hour (用于 resolveDemoLayer 派生 display 数据) ─────────────────
  const currentHour = ref(12)
  const workflowError = ref<string | null>(null)
  const workflowPollingHandles = new Map<string, number>()
  const isSubmitting = ref(false)

  // ── 粒子流独占启用状态 ───────────────────────────────────────────────────
  // particle_flow 是 Canvas 叠加层，性能开销大且视觉冲突，同一时间只允许一个图层启用
  // null 表示未启用任何粒子流；值为 catalogId 时该图层独占粒子流渲染
  const particleFlowCatalogId = ref<string | null>(null)

  // ── 当前地图视口（中心点 + 可见范围）─────────────────────────────────────
  // 用于 runWorkflowForCatalog 时把视口范围传给后端，使风场网格在用户当前位置生成
  // 而非硬编码为广州。bbox 可能为 null（地图未初始化完成时）。
  const currentMapCenter = ref<{ lng: number; lat: number }>({ lng: 113.2644, lat: 23.1291 })
  const currentMapBBox = ref<BoundingBox | null>(null)

  // ─────────────────────────────────────────────────────────────────────────────

  const activeLayersDisplay = computed<ActiveLayerDisplay[]>(() => {
    return activeLayers.value
      .slice()
      .sort((a, b) => a.order - b.order)
      .map((layer): ActiveLayerDisplay | null => {
        // 从 demoLayerCatalog 派生 display 数据（未来替换为真实数据）
        const catalog = demoLayerCatalog.find((c) => c.id === layer.catalogId)
        if (!catalog) {
          return null
        }
        const demo = resolveDemoLayer(catalog.id, currentHour.value)
        return {
          instanceId: layer.instanceId,
          catalogId: layer.catalogId,
          name: layer.isAdminBoundary ? '行政区边界' : demo.name,
          category: layer.isAdminBoundary ? 'boundary' : demo.category,
          summary: layer.isAdminBoundary ? '广东省市级行政区边界叠加层' : demo.summary,
          metricLabel: layer.isAdminBoundary ? '边界层级' : demo.metricLabel,
          metricValue: layer.isAdminBoundary ? '省市级' : demo.metricValue,
          trendLabel: layer.isAdminBoundary ? '静态矢量边界叠加' : demo.trendLabel,
          statusLabel: layer.isAdminBoundary ? '静态数据' : demo.statusLabel,
          updateLabel: layer.isAdminBoundary ? '静态数据' : demo.updateLabel,
          sourceLabel: layer.isAdminBoundary ? '广东省市级边界' : demo.sourceLabel,
          confidenceLabel: layer.isAdminBoundary ? '置信度 100%' : demo.confidenceLabel,
          accentColor: layer.isAdminBoundary ? '#88d8ff' : demo.accentColor,
          accentGlow: layer.isAdminBoundary ? 'rgba(136, 216, 255, 0.3)' : demo.accentGlow,
          chipTone: layer.isAdminBoundary ? 'rgba(136, 216, 255, 0.16)' : demo.chipTone,
          availabilityState: layer.isAdminBoundary ? 'ready' : demo.availabilityState,
          availabilityLabel: layer.isAdminBoundary ? '完整数据' : demo.availabilityLabel,
          availabilityDescription: layer.isAdminBoundary
            ? '静态矢量边界数据，已完整加载。'
            : demo.availabilityDescription,
          observationTimeLabel: layer.isAdminBoundary ? '静态数据' : demo.observationTimeLabel,
          missingFieldsLabel: layer.isAdminBoundary ? '无' : demo.missingFieldsLabel,
          hotspots: layer.isAdminBoundary ? [] : demo.hotspots,
          isAdminBoundary: layer.isAdminBoundary,
          jobLayer: layer.jobLayer,
          visible: layer.visible,
          opacity: layer.opacity,
          order: layer.order,
          dataState: layer.dataState,
        }
      })
      .filter((d): d is ActiveLayerDisplay => d !== null)
  })

  const selectedLayerDisplay = computed<ActiveLayerDisplay | null>(() => {
    if (!selectedInstanceId.value) return null
    return activeLayersDisplay.value.find((d) => d.instanceId === selectedInstanceId.value) ?? null
  })

  const activeLayerCount = computed(() => activeLayers.value.length)

  const sidebarViewLabel = computed(() => {
    if (sidebarView.value === 'empty') return '图层'
    if (sidebarView.value === 'library') return '图层库'
    return `图层 (${activeLayerCount.value})`
  })

  // ─────────────────────────────────────────────────────────────────────────────

  function addLayer(catalogId: string, isAdminBoundary = false, jobLayer?: JobLayerItem) {
    // 防止重复添加同 catalogId (除非来自不同 job)
    if (!isAdminBoundary && !jobLayer) {
      if (activeLayers.value.some((l) => l.catalogId === catalogId && !l.jobLayer)) {
        return
      }
    }

    const maxOrder = activeLayers.value.reduce((max, l) => Math.max(max, l.order), 0)
    const layer: ActiveLayer = {
      instanceId: genInstanceId(),
      catalogId,
      sourceId: '',
      visible: true,
      opacity: 1,
      order: maxOrder + 1,
      isAdminBoundary,
      jobLayer,
      dataState: jobLayer ? 'real' : 'demo',
    }
    activeLayers.value.push(layer)
    selectedInstanceId.value = layer.instanceId

    if (sidebarView.value === 'empty' || sidebarView.value === 'library') {
      sidebarView.value = 'active'
    }
  }

  function removeLayer(instanceId: string) {
    const idx = activeLayers.value.findIndex((l) => l.instanceId === instanceId)
    if (idx === -1) return
    // 修复：删除图层时停止对应工作流轮询，避免泄漏 setTimeout 句柄
    const layer = activeLayers.value[idx]
    if (layer.jobLayer?.jobId) {
      stopWorkflowPolling(layer.jobLayer.jobId)
    }
    activeLayers.value.splice(idx, 1)

    if (selectedInstanceId.value === instanceId) {
      selectedInstanceId.value = activeLayers.value[0]?.instanceId ?? null
    }
  }

  function toggleLayerVisibility(instanceId: string) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (layer) {
      layer.visible = !layer.visible
    }
  }

  /** 批量设置所有图层可见性 */
  function setAllLayerVisibility(visible: boolean) {
    for (const layer of activeLayers.value) {
      layer.visible = visible
    }
  }

  /** 批量移除所有图层（保留行政区边界） */
  function removeAllLayers(keepBoundary = true) {
    if (keepBoundary) {
      activeLayers.value = activeLayers.value.filter((l) => l.isAdminBoundary)
    } else {
      activeLayers.value = []
    }
    if (!activeLayers.value.some((l) => l.instanceId === selectedInstanceId.value)) {
      selectedInstanceId.value = activeLayers.value[0]?.instanceId ?? null
    }
  }

  function setLayerOpacity(instanceId: string, opacity: number) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (layer) {
      layer.opacity = Math.max(0, Math.min(1, opacity))
    }
  }

  function setLayerOrder(instanceId: string, newOrder: number) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (layer) {
      layer.order = newOrder
    }
  }

  function selectLayer(instanceId: string | null) {
    selectedInstanceId.value = instanceId
  }

  function setSidebarView(view: LayerSidebarView) {
    sidebarView.value = view
  }

  function setCurrentHour(hour: number) {
    currentHour.value = hour
  }

  function setJobLayers(jobs: JobLayerItem[]) {
    jobLayers.value = jobs
  }

  function stopWorkflowPolling(jobId: string) {
    const handle = workflowPollingHandles.get(jobId)
    if (handle !== undefined) {
      window.clearTimeout(handle)
      workflowPollingHandles.delete(jobId)
    }
  }

  function syncJobLayerToActiveLayer(catalogId: string, jobLayer: JobLayerItem) {
    const existingRealLayer = activeLayers.value.find((layer) => layer.jobLayer?.jobId === jobLayer.jobId)
    if (existingRealLayer) {
      existingRealLayer.jobLayer = jobLayer
      existingRealLayer.dataState = 'real'
      return
    }

    const existingCatalogLayer = activeLayers.value.find((layer) => layer.catalogId === catalogId && !layer.isAdminBoundary)
    if (existingCatalogLayer) {
      existingCatalogLayer.jobLayer = jobLayer
      existingCatalogLayer.dataState = 'real'
      selectedInstanceId.value = existingCatalogLayer.instanceId
      return
    }

    addLayer(catalogId, false, jobLayer)
  }

  function upsertJobLayer(catalogId: string, jobLayer: JobLayerItem) {
    const existingIndex = jobLayers.value.findIndex((item) => item.jobId === jobLayer.jobId)
    if (existingIndex >= 0) {
      jobLayers.value.splice(existingIndex, 1, jobLayer)
    } else {
      jobLayers.value.unshift(jobLayer)
    }
    syncJobLayerToActiveLayer(catalogId, jobLayer)
  }

  async function pollWorkflowRun(jobId: string, catalogId: string, attempt = 1) {
    try {
      const run = await getWorkflowRun(jobId)
      const jobLayer = await buildJobLayer(run, catalogId)
      upsertJobLayer(catalogId, jobLayer)
      workflowError.value = null

      if (isTerminalStatus(jobLayer.status)) {
        stopWorkflowPolling(jobId)
        return
      }
    } catch (error) {
      workflowError.value = error instanceof Error ? error.message : '轮询 workflow-runs 失败'
    }

    // 修复：加入最大轮询次数上限，防止后端异常时无限轮询
    if (attempt >= POLL_MAX_ATTEMPTS) {
      workflowError.value = `工作流轮询超过最大次数 (${POLL_MAX_ATTEMPTS})，已停止轮询`
      stopWorkflowPolling(jobId)
      return
    }

    // 修复：指数退避，对齐后端 retry_policy。retry_pending 状态下更应拉长间隔
    const backoffMs = Math.min(
      POLL_INITIAL_INTERVAL_MS * Math.pow(1.5, attempt - 1),
      POLL_MAX_INTERVAL_MS,
    )
    const handle = window.setTimeout(() => {
      void pollWorkflowRun(jobId, catalogId, attempt + 1)
    }, backoffMs)
    workflowPollingHandles.set(jobId, handle)
  }

  async function runWorkflowForCatalog(catalogId: string) {
    if (isSubmitting.value) return
    workflowError.value = null
    isSubmitting.value = true
    try {
      const catalogName = getCatalogDisplayName(catalogId)
      // 支持 map_layer 渲染的图层：风场全高度变体 + 温度 + 降水
      const supportsMapLayer =
        catalogId.startsWith('wind-field') ||
        catalogId.startsWith('temperature') ||
        catalogId === 'precipitation'
      const requestedOutputs = supportsMapLayer
        ? ['json', 'text', 'table', 'map_layer']
        : ['json', 'text', 'table']

      const accepted = await submitWorkflow({
        command_type: 'analysis',
        command_label: `运行 ${catalogName} 分析`,
        layer_id: catalogId,
        requested_outputs: requestedOutputs,
        parameters: {
          hour: currentHour.value,
          // 把当前地图中心点作为预报点传给后端，使风场网格围绕用户当前位置生成
          // 后端 _resolve_point 优先读 parameters.latitude/longitude
          latitude: currentMapCenter.value.lat,
          longitude: currentMapCenter.value.lng,
        },
        client: {
          page: 'dashboard',
          view_id: 'map-2d',
        },
        map_context: {
          active_layer_id: catalogId,
          map_mode: '2d',
          // 把当前视口范围传给后端，后端 _resolve_render_bbox 优先使用此 bbox 生成网格
          // 允许全球范围浏览：用户缩放到全球时，网格会覆盖整个可见区域
          viewport_bbox: currentMapBBox.value ?? undefined,
        },
      })

      upsertJobLayer(catalogId, {
        jobId: accepted.run_id,
        name: catalogName,
        commandType: 'analysis',
        status: 'queued',
        progress: 12,
        createdAt: accepted.created_at,
        updatedAt: accepted.created_at,
        message: accepted.message,
        metrics: [],
        reportSummary: accepted.message,
        resultUrl: undefined,
      })

      void pollWorkflowRun(accepted.run_id, catalogId)
      return accepted.run_id
    } catch (error) {
      workflowError.value = error instanceof Error ? error.message : '提交 workflow 失败'
      throw error
    } finally {
      isSubmitting.value = false
    }
  }

  async function cancelWorkflowRunForJob(jobId: string, catalogId: string) {
    try {
      const run = await cancelWorkflowRun(jobId)
      const jobLayer = await buildJobLayer(run, catalogId)
      upsertJobLayer(catalogId, jobLayer)
      stopWorkflowPolling(jobId)
    } catch (error) {
      workflowError.value = error instanceof Error ? error.message : '取消 workflow 失败'
    }
  }

  async function retryWorkflowRunForJob(jobId: string, catalogId: string) {
    if (isSubmitting.value) return
    workflowError.value = null
    isSubmitting.value = true
    try {
      const accepted = await retryWorkflowRun(jobId)
      const catalogName = getCatalogDisplayName(catalogId)
      upsertJobLayer(catalogId, {
        jobId: accepted.run_id,
        name: catalogName,
        commandType: 'analysis',
        status: 'queued',
        progress: 12,
        createdAt: accepted.created_at,
        updatedAt: accepted.created_at,
        message: accepted.message,
        metrics: [],
        reportSummary: accepted.message,
        resultUrl: undefined,
      })
      void pollWorkflowRun(accepted.run_id, catalogId)
      return accepted.run_id
    } catch (error) {
      workflowError.value = error instanceof Error ? error.message : '重试 workflow 失败'
      throw error
    } finally {
      isSubmitting.value = false
    }
  }

  function reorderLayers(fromIndex: number, toIndex: number) {
    const sorted = activeLayers.value.slice().sort((a, b) => a.order - b.order)
    const [moved] = sorted.splice(fromIndex, 1)
    sorted.splice(toIndex, 0, moved)
    sorted.forEach((layer, i) => {
      layer.order = i
    })
  }

  /** 判断 catalogId 是否由 weatherengine 后端支持（用于自动运行工作流） */
  function isWeatherEngineLayer(catalogId: string): boolean {
    // 风场全高度变体（wind-field / wind-field-80m / wind-field-120m / wind-field-180m）
    if (catalogId.startsWith('wind-field')) return true
    // 温度全高度变体（temperature / temperature-80m / temperature-120m / temperature-180m）
    if (catalogId.startsWith('temperature')) return true
    // 其他 weatherengine 图层
    return ['precipitation', 'pressure', 'humidity', 'visibility'].includes(catalogId)
  }

  /** 判断 catalogId 是否支持粒子流渲染（所有 wind-field 变体都支持） */
  function supportsParticleFlow(catalogId: string): boolean {
    return catalogId.startsWith('wind-field')
  }

  /** 切换粒子流启用状态：再次点击同一图层会关闭，点击新图层会切换 */
  function toggleParticleFlow(catalogId: string) {
    if (particleFlowCatalogId.value === catalogId) {
      particleFlowCatalogId.value = null
    } else {
      particleFlowCatalogId.value = catalogId
    }
  }

  /** 直接设置粒子流启用图层（设为 null 关闭） */
  function setParticleFlow(catalogId: string | null) {
    particleFlowCatalogId.value = catalogId
  }

  /** 更新当前地图视口（中心点 + 可见 bbox），由 MapCanvas 在 moveend 时调用 */
  function setMapViewport(center: { lng: number; lat: number }, bbox: BoundingBox | null) {
    currentMapCenter.value = center
    currentMapBBox.value = bbox
  }

  /** catalogId → 工作流状态映射，用于 library 卡片显示自动运行反馈 */
  const catalogJobStatus = computed(() => {
    const map = new Map<string, JobStatus>()
    for (const layer of activeLayers.value) {
      if (layer.jobLayer) {
        map.set(layer.catalogId, layer.jobLayer.status)
      }
    }
    return map
  })

  return {
    // State
    activeLayers,
    sidebarView,
    selectedInstanceId,
    jobLayers,
    currentHour,
    workflowError,
    isSubmitting,
    particleFlowCatalogId,
    currentMapCenter,
    currentMapBBox,
    // Computed
    activeLayersDisplay,
    selectedLayerDisplay,
    activeLayerCount,
    sidebarViewLabel,
    catalogJobStatus,
    // Data
    layerLibrary: LAYER_LIBRARY,
    layerLibraryByCategory: LAYER_LIBRARY_BY_CATEGORY,
    layerCategories: LAYER_CATEGORIES,
    // Actions
    addLayer,
    removeLayer,
    toggleLayerVisibility,
    setAllLayerVisibility,
    removeAllLayers,
    setLayerOpacity,
    setLayerOrder,
    selectLayer,
    setSidebarView,
    setCurrentHour,
    setJobLayers,
    reorderLayers,
    runWorkflowForCatalog,
    cancelWorkflowRunForJob,
    retryWorkflowRunForJob,
    stopWorkflowPolling,
    isWeatherEngineLayer,
    supportsParticleFlow,
    toggleParticleFlow,
    setParticleFlow,
    setMapViewport,
  }
})
