/**
 * Lifecycle domain — 图层平台子系统 P0（2026-08-24）。
 *
 * 第四个 layers store 域：聚合「资产 + 工作流 + 时间轴」为统一图层生命周期视图。
 * - 真源：后端 GET /layers/{layer_id}/lifecycle（资产状态 + 最近 run + 时间轴元数据）
 * - 本地信号：jobLayers（workflow-run 域）+ overlayTimeStates（MapCanvas 双写过渡）
 * - 派生：lifecycle_state ∈ fresh | stale | updating | missing | failed
 *
 * 设计约束：
 * - 不动 ActiveLayer.dataState 三值（catalog/real/imported）——lifecycle 是叠加维度
 * - overlayTimeStates 仍是地图渲染真源；本域仅读取用于派生，不反向写入
 * - 禁用 storeToRefs（Pinia 3.0.4 崩溃），selectors 用 toRef(store, key)
 */

import { computed, ref, type ComputedRef, type Ref } from 'vue'

import type { CrossDomainBindings } from './bindings'
import type { JobLayerItem } from './types'
import {
  fetchLayerLifecycle,
  type LayerLifecycleResponse,
} from '../../services/runtime-api'

/** 单图层生命周期聚合视图（本地信号 + 后端真源合并）。 */
export interface LayerLifecycleEntry {
  layerId: string
  /** 后端 lifecycle_state；后端不可用时由本地信号推导。 */
  lifecycleState: 'fresh' | 'stale' | 'updating' | 'missing' | 'failed' | 'unknown'
  /** 后端资产状态（missing/unversioned/stale/fresh）；无后端数据时为 null。 */
  assetState: string | null
  bakeVersion: number | null
  currentBakeVersion: number | null
  /** 时间轴可用时间块（overlayTimeStates 优先，后端 time_list 兜底）。 */
  availableTimes: string[]
  currentTime: string | null
  /** 本地活跃 jobLayer 的进度（0-100）；无活跃 run 时为 null。 */
  localProgress: number | null
  message: string | null
  updatedAt: string | null
}

export interface LifecycleDomain {
  /** layerId → 生命周期条目（响应式）。 */
  layerLifecycle: ComputedRef<Map<string, LayerLifecycleEntry>>
  /** 后端 lifecycle 响应缓存（按 layerId）。 */
  serverLifecycle: Ref<Record<string, LayerLifecycleResponse>>
  /** 拉取某图层后端 lifecycle（失败静默，保留本地推导）。 */
  refreshLayerLifecycle: (layerId: string) => Promise<void>
  /** 批量刷新（图层添加后触发）。 */
  refreshAll: (layerIds: string[]) => Promise<void>
  /** MapCanvas 双写：接收地图 overlay 时间状态真源（P1）。 */
  setMapOverlayTimeStates: (
    states: Array<{
      layerId: string
      category: string
      timeList: string[]
      currentTime: string | null
    }>,
  ) => void
}

interface LifecycleDomainDeps {
  bindings: CrossDomainBindings
  getJobLayers: () => JobLayerItem[]
}

const ACTIVE_JOB_STATUSES = new Set(['queued', 'running', 'retry_pending', 'accepted'])

/** 由本地信号（jobLayer + overlayTimeStates）推导生命周期状态。 */
function deriveLocalState(
  jobLayer: JobLayerItem | undefined,
  hasTimeline: boolean,
): LayerLifecycleEntry['lifecycleState'] {
  if (jobLayer && ACTIVE_JOB_STATUSES.has(jobLayer.status)) {
    return 'updating'
  }
  if (jobLayer?.status === 'failed') {
    return 'failed'
  }
  if (hasTimeline) {
    return 'fresh'
  }
  return 'unknown'
}

export function createLifecycleDomain(deps: LifecycleDomainDeps): LifecycleDomain {
  const { bindings } = deps
  const serverLifecycle = ref<Record<string, LayerLifecycleResponse>>({})
  // P1：MapCanvas 双写过来的地图 overlay 时间状态真源（替代 bindings 空 stub）。
  const mapOverlayTimeStates = ref<
    Array<{
      layerId: string
      category: string
      timeList: string[]
      currentTime: string | null
    }>
  >([])

  const layerLifecycle = computed(() => {
    const map = new Map<string, LayerLifecycleEntry>()
    const overlayStates = new Map(
      mapOverlayTimeStates.value.map((s) => [s.layerId, s]),
    )

    // 1) 后端真源条目
    for (const [layerId, resp] of Object.entries(serverLifecycle.value)) {
      const overlay = overlayStates.get(layerId)
      map.set(layerId, {
        layerId,
        lifecycleState: (resp.lifecycle_state as LayerLifecycleEntry['lifecycleState']) ?? 'unknown',
        assetState: resp.asset?.asset_state ?? null,
        bakeVersion: resp.asset?.bake_version ?? null,
        currentBakeVersion: resp.asset?.current_bake_version ?? null,
        availableTimes: overlay?.timeList ?? resp.asset?.time_list ?? [],
        currentTime: overlay?.currentTime ?? resp.asset?.default_time ?? null,
        localProgress: null,
        message: resp.message ?? null,
        updatedAt: resp.updated_at ?? null,
      })
      overlayStates.delete(layerId)
    }

    // 2) 仅本地信号条目（后端未返回或请求失败）
    for (const [layerId, overlay] of overlayStates) {
      const jobLayer = deps.getJobLayers().find((j) => j.catalogId === layerId)
      map.set(layerId, {
        layerId,
        lifecycleState: deriveLocalState(jobLayer, (overlay.timeList?.length ?? 0) > 0),
        assetState: null,
        bakeVersion: null,
        currentBakeVersion: null,
        availableTimes: overlay.timeList ?? [],
        currentTime: overlay.currentTime ?? null,
        localProgress: jobLayer?.progress ?? null,
        message: jobLayer?.message ?? null,
        updatedAt: jobLayer?.updatedAt ?? null,
      })
    }

    // 3) 有活跃 jobLayer 但无 overlay/后端数据的图层（如资产烘焙中）
    for (const jobLayer of deps.getJobLayers()) {
      const catalogId = jobLayer.catalogId
      if (!catalogId || map.has(catalogId)) continue
      if (!ACTIVE_JOB_STATUSES.has(jobLayer.status) && jobLayer.status !== 'failed') continue
      map.set(catalogId, {
        layerId: catalogId,
        lifecycleState: deriveLocalState(jobLayer, false),
        assetState: null,
        bakeVersion: null,
        currentBakeVersion: null,
        availableTimes: [],
        currentTime: null,
        localProgress: jobLayer.progress,
        message: jobLayer.message,
        updatedAt: jobLayer.updatedAt,
      })
    }

    return map
  })

  async function refreshLayerLifecycle(layerId: string): Promise<void> {
    try {
      const resp = await fetchLayerLifecycle(layerId)
      serverLifecycle.value = {
        ...serverLifecycle.value,
        [layerId]: resp,
      }
      bindings.onLifecycleRefreshed(layerId, resp.lifecycle_state)
    } catch {
      // 后端不可用/404：保留本地推导，不阻塞 UI
    }
  }

  async function refreshAll(layerIds: string[]): Promise<void> {
    await Promise.allSettled(layerIds.map((id) => refreshLayerLifecycle(id)))
  }

  function setMapOverlayTimeStates(
    states: Array<{
      layerId: string
      category: string
      timeList: string[]
      currentTime: string | null
    }>,
  ): void {
    // 深拷贝时间列表，避免与地图模块共享数组引用导致响应式追踪混乱。
    mapOverlayTimeStates.value = states.map((s) => ({
      layerId: s.layerId,
      category: s.category,
      timeList: [...s.timeList],
      currentTime: s.currentTime,
    }))
  }

  return {
    layerLifecycle,
    serverLifecycle,
    refreshLayerLifecycle,
    refreshAll,
    setMapOverlayTimeStates,
  }
}
