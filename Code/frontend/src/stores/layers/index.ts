import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { demoLayerCatalog } from '../../app/demo-data'
import { resolveDemoLayer } from '../../app/demo-adapter'
import { LAYER_CATEGORIES, LAYER_LIBRARY, LAYER_LIBRARY_BY_CATEGORY } from './catalog'
import type { ActiveLayer, ActiveLayerDisplay, JobLayerItem, LayerSidebarView } from './types'

function genInstanceId() {
  return `layer-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
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

  function reorderLayers(fromIndex: number, toIndex: number) {
    const sorted = activeLayers.value.slice().sort((a, b) => a.order - b.order)
    const [moved] = sorted.splice(fromIndex, 1)
    sorted.splice(toIndex, 0, moved)
    sorted.forEach((layer, i) => {
      layer.order = i
    })
  }

  return {
    // State
    activeLayers,
    sidebarView,
    selectedInstanceId,
    jobLayers,
    currentHour,
    // Computed
    activeLayersDisplay,
    selectedLayerDisplay,
    activeLayerCount,
    sidebarViewLabel,
    // Data
    layerLibrary: LAYER_LIBRARY,
    layerLibraryByCategory: LAYER_LIBRARY_BY_CATEGORY,
    layerCategories: LAYER_CATEGORIES,
    // Actions
    addLayer,
    removeLayer,
    toggleLayerVisibility,
    setLayerOpacity,
    setLayerOrder,
    selectLayer,
    setSidebarView,
    setCurrentHour,
    setJobLayers,
    reorderLayers,
  }
})
