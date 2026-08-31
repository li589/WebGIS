/**
 * Workspace persist + hydrate slice extracted from the layers god store.
 * Public API remains re-exported via useLayersStore().
 */
import { nextTick } from 'vue'

import { useWeatherTileManager } from '../weather-tile-manager'
import type { BoundingBox } from '../../services/runtime-api'
import { buildImportedRasterPayload } from './imported-raster'
import { buildImportedVectorPayload } from './imported-vector'
import {
  buildWorkspaceSnapshot,
  isCatalogDismissed,
  isOverlayDismissed,
  isRunDismissed,
  isVectorDismissed,
  loadWorkspaceSnapshot,
  saveWorkspaceSnapshot,
  type PersistedActiveLayer,
  type PersistedCatalogLayer,
  type PersistedVectorLayer,
} from './workspace-persist'
import { scheduleWorkspaceSyncPush, suppressWorkspaceSyncPush } from './workspace-sync'
import type {
  ActiveLayer,
  ActiveRunLayerGroup,
  LayerSidebarView,
  RuntimeLayerLibraryItem,
} from './types'

export interface WorkspaceHydrateSliceDeps {
  getActiveLayers: () => ActiveLayer[]
  getRunLayerGroups: () => ActiveRunLayerGroup[]
  getSidebarView: () => LayerSidebarView
  setSidebarView: (view: LayerSidebarView) => void
  getLayerLibraryMap: () => Map<string, RuntimeLayerLibraryItem>
  assignLayerAccent: (preferred?: string | null) => {
    accentColor: string
    accentGlow: string
    chipTone: string
  }
  genInstanceId: () => string
  isLocalImport: (layer: ActiveLayer) => boolean
  isWeatherEngineLayer: (catalogId: string) => boolean
  weatherProviderArg: (catalogId: string) => string
  getMapCenter: () => { lng: number; lat: number }
  getMapZoom: () => number
  getMapBBox: () => BoundingBox | null
  getCurrentHour: () => number
  /** Late-bound setters so active/run slices can call persist before this slice exists. */
  bindPersistFns: (fns: {
    scheduleWorkspacePersist: () => void
    flushWorkspacePersistNow: (opts?: { sync?: boolean }) => void
  }) => void
}

export function createWorkspaceHydrateSlice(deps: WorkspaceHydrateSliceDeps) {
  const weatherTileManager = useWeatherTileManager()
  let workspacePersistTimer: ReturnType<typeof setTimeout> | null = null
  /**
   * boot 水合保护：DashboardView 启动序列（工作区远端同步 + 快照恢复）期间，
   * MapCanvas 草稿恢复等早期变更会在矢量图层恢复完成前触发快照落盘，
   * 把尚未恢复的导入图层从快照中永久抹掉（并被同步推送放大到远端）。
   * 保护期内跳过 flush，保留 boot 前快照；释放时补一次落盘捕获期间改动。
   */
  let hydrationGuard = false
  /**
   * 恢复失败（网络抖动/后端重启/鉴权过期）的矢量图层条目：并回快照保留，
   * 下次刷新重试——否则 guard 释放后的首次 flush 会以 activeLayers 重建
   * 快照，把本轮未恢复的条目永久抹除（数据丢失 bug 2026-08-20 修复）。
   * 条目在成功恢复（backendLayerId 出现在 activeLayers）或用户明确移除
   * （dismissed 登记）后自动出队。
   */
  let pendingRetryVectorLayers: PersistedVectorLayer[] = []

  function reconcilePendingRetryVectors(snapshot: ReturnType<typeof buildWorkspaceSnapshot>) {
    if (!pendingRetryVectorLayers.length) return
    const activeBackendIds = new Set(
      deps
        .getActiveLayers()
        .map((l) => l.importedVector?.backendLayerId)
        .filter((id): id is string => Boolean(id)),
    )
    const snapBackendIds = new Set(
      (snapshot.vectorLayers ?? []).map((v) => v.backendLayerId).filter(Boolean),
    )
    const retained: PersistedVectorLayer[] = []
    for (const saved of pendingRetryVectorLayers) {
      if (!saved.backendLayerId) continue
      if (activeBackendIds.has(saved.backendLayerId) || isVectorDismissed(saved.backendLayerId)) {
        continue // 已成功恢复或用户已删除 → 不再保留
      }
      if (!snapBackendIds.has(saved.backendLayerId)) {
        snapshot.vectorLayers = [...(snapshot.vectorLayers ?? []), saved]
        snapBackendIds.add(saved.backendLayerId)
      }
      retained.push(saved)
    }
    pendingRetryVectorLayers = retained
  }

  function flushWorkspacePersistNow(opts?: { sync?: boolean }) {
    if (typeof window === 'undefined') return
    if (hydrationGuard) return
    if (workspacePersistTimer != null) {
      window.clearTimeout(workspacePersistTimer)
      workspacePersistTimer = null
    }
    const snapshot = buildWorkspaceSnapshot(deps.getActiveLayers(), deps.getRunLayerGroups())
    reconcilePendingRetryVectors(snapshot)
    saveWorkspaceSnapshot(snapshot)
    if (opts?.sync === false) return
    scheduleWorkspaceSyncPush()
  }

  function scheduleWorkspacePersist() {
    if (typeof window === 'undefined') return
    // 水合中禁止排队落盘：否则解除 guard 后 400ms 定时器会把未齐内存态推到 /workspace，
    // 冲掉局域网/公网同账号另一端的完整工作区（localhost ↔ 公网入口串扰）。
    if (hydrationGuard) return
    if (workspacePersistTimer != null) window.clearTimeout(workspacePersistTimer)
    workspacePersistTimer = window.setTimeout(() => {
      workspacePersistTimer = null
      flushWorkspacePersistNow()
    }, 400)
  }

  function setWorkspaceHydrationGuard(active: boolean) {
    hydrationGuard = active
    if (!active) {
      // 取消水合期间可能残留的定时器，再只落盘本地、禁止立刻推远端
      if (typeof window !== 'undefined' && workspacePersistTimer != null) {
        window.clearTimeout(workspacePersistTimer)
        workspacePersistTimer = null
      }
      suppressWorkspaceSyncPush(true)
      try {
        flushWorkspacePersistNow({ sync: false })
      } finally {
        suppressWorkspaceSyncPush(false)
      }
    }
  }

  deps.bindPersistFns({ scheduleWorkspacePersist, flushWorkspacePersistNow })

  if (typeof window !== 'undefined') {
    window.addEventListener('pagehide', () => flushWorkspacePersistNow())
  }

  function restoreCatalogLayerFromSnapshot(
    saved: PersistedCatalogLayer,
    instanceIdMap?: Map<string, string>,
  ) {
    if (isCatalogDismissed(saved.catalogId)) return
    const activeLayers = deps.getActiveLayers()
    if (
      activeLayers.some(
        (l) => l.catalogId === saved.catalogId && !deps.isLocalImport(l) && !l.jobLayer,
      )
    ) {
      return
    }
    const libraryItem = deps.getLayerLibraryMap().get(saved.catalogId)
    const accent = saved.accentColor
      ? {
          accentColor: saved.accentColor,
          accentGlow: saved.accentGlow ?? 'var(--surface-3)',
          chipTone: saved.chipTone ?? 'var(--surface-hover)',
        }
      : deps.assignLayerAccent(libraryItem?.accentColor)
    const instanceId = deps.genInstanceId()
    instanceIdMap?.set(saved.instanceId, instanceId)
    const layer: ActiveLayer = {
      instanceId,
      catalogId: saved.catalogId,
      name: saved.name,
      visible: saved.visible !== false,
      opacity: typeof saved.opacity === 'number' ? saved.opacity : 1,
      order: typeof saved.order === 'number' ? saved.order : activeLayers.length,
      isAdminBoundary: false,
      dataState: saved.dataState === 'real' ? 'real' : 'catalog',
      accentColor: accent.accentColor,
      accentGlow: accent.accentGlow,
      chipTone: accent.chipTone,
      runGroupId: saved.runGroupId,
      runGroupProductTag: saved.runGroupProductTag,
      runGroupLocked: Boolean(saved.runGroupLocked),
      paletteOverride: saved.paletteOverride ?? null,
      vminOverride: saved.vminOverride ?? null,
      vmaxOverride: saved.vmaxOverride ?? null,
      nodataMode: saved.nodataMode ?? null,
      nodataColor: saved.nodataColor ?? null,
    }
    activeLayers.push(layer)
    if (deps.isWeatherEngineLayer(saved.catalogId) && layer.visible) {
      weatherTileManager.setLayerActive(saved.catalogId, true)
      nextTick(() => {
        window.setTimeout(() => {
          weatherTileManager.setViewport(
            saved.catalogId,
            deps.getMapCenter(),
            deps.getMapZoom(),
            deps.getCurrentHour(),
            undefined,
            deps.getMapBBox(),
            deps.weatherProviderArg(saved.catalogId),
          )
        }, 0)
      })
    }
  }

  function restoreRunGroupsFromSnapshot(
    snap: NonNullable<ReturnType<typeof loadWorkspaceSnapshot>>,
    instanceIdMap: Map<string, string>,
  ) {
    const activeLayers = deps.getActiveLayers()
    const runLayerGroups = deps.getRunLayerGroups()
    for (const savedGroup of snap.groups || []) {
      if (savedGroup.runId && isRunDismissed(savedGroup.runId)) continue
      if (
        runLayerGroups.some((g) => g.groupId === savedGroup.groupId || g.runId === savedGroup.runId)
      ) {
        continue
      }
      const memberInstanceIds = (savedGroup.memberInstanceIds || [])
        .map((oldId) => instanceIdMap.get(oldId))
        .filter((id): id is string => Boolean(id))
      if (!memberInstanceIds.length) {
        for (const layer of activeLayers) {
          if (layer.runGroupId === savedGroup.groupId) {
            memberInstanceIds.push(layer.instanceId)
          }
        }
      }
      if (!memberInstanceIds.length) continue
      const computing = savedGroup.status === 'computing'
      runLayerGroups.push({
        groupId: savedGroup.groupId,
        runId: savedGroup.runId || '',
        title: savedGroup.title,
        status: computing ? 'computing' : savedGroup.status || 'ready',
        memberInstanceIds,
        dissolvable: computing ? false : Boolean(savedGroup.dissolvable ?? true),
        sourceLayerId: savedGroup.sourceLayerId,
        workflowId: savedGroup.workflowId,
        progress: savedGroup.progress,
        message: savedGroup.message,
      })
      for (const id of memberInstanceIds) {
        const layer = activeLayers.find((l) => l.instanceId === id)
        if (layer) {
          layer.runGroupId = savedGroup.groupId
          if (computing && !layer.importedRaster?.overlayLayerId) {
            layer.runGroupLocked = true
          }
        }
      }
    }
  }

  function hydrateWorkspaceFromSnapshot(): Map<string, string> {
    const snap = loadWorkspaceSnapshot()
    const instanceIdMap = new Map<string, string>()
    if (!snap) return instanceIdMap
    const hasRaster = snap.layers?.length > 0
    const hasCatalog = (snap.catalogLayers?.length ?? 0) > 0
    const hasVector = (snap.vectorLayers?.length ?? 0) > 0
    if (!hasRaster && !hasCatalog && !hasVector) return instanceIdMap

    const activeLayers = deps.getActiveLayers()
    const existingOverlayIds = new Set(
      activeLayers
        .map((l) => l.importedRaster?.overlayLayerId)
        .filter((id): id is string => Boolean(id)),
    )

    for (const saved of snap.layers as PersistedActiveLayer[]) {
      if (!saved.importedRaster?.overlayLayerId) continue
      if (isOverlayDismissed(saved.importedRaster.overlayLayerId)) continue
      if (existingOverlayIds.has(saved.importedRaster.overlayLayerId)) continue

      const instanceId = deps.genInstanceId()
      instanceIdMap.set(saved.instanceId, instanceId)
      const layer: ActiveLayer = {
        instanceId,
        catalogId: saved.catalogId,
        name: saved.name,
        visible: saved.visible !== false,
        opacity: typeof saved.opacity === 'number' ? saved.opacity : 1,
        order: typeof saved.order === 'number' ? saved.order : activeLayers.length,
        isAdminBoundary: false,
        dataState: 'imported',
        importedRaster: buildImportedRasterPayload(saved.importedRaster.overlayLayerId, {
          bounds: saved.importedRaster.bounds,
          fileName: saved.importedRaster.fileName || saved.name,
          sourceCrs: saved.importedRaster.sourceCrs,
          lngOffset: saved.importedRaster.lngOffset,
          latOffset: saved.importedRaster.latOffset,
          nativeStep: saved.importedRaster.nativeStep,
          timeList: saved.importedRaster.timeList,
          followPolicy: saved.importedRaster.followPolicy,
          effectiveTimeLabel: saved.importedRaster.effectiveTimeLabel,
        }),
        accentColor: saved.accentColor,
        accentGlow: saved.accentGlow,
        chipTone: saved.chipTone,
        runGroupId: saved.runGroupId,
        runGroupProductTag: saved.runGroupProductTag,
        runGroupLocked: Boolean(saved.runGroupLocked),
        paletteOverride: saved.paletteOverride ?? null,
        vminOverride: saved.vminOverride ?? null,
        vmaxOverride: saved.vmaxOverride ?? null,
        nodataMode: saved.nodataMode ?? null,
        nodataColor: saved.nodataColor ?? null,
      }
      activeLayers.push(layer)
      existingOverlayIds.add(saved.importedRaster.overlayLayerId)
    }

    for (const saved of snap.catalogLayers ?? []) {
      restoreCatalogLayerFromSnapshot(saved, instanceIdMap)
    }

    restoreRunGroupsFromSnapshot(snap, instanceIdMap)

    if (activeLayers.length && deps.getSidebarView() === 'empty') {
      deps.setSidebarView('active')
    }
    return instanceIdMap
  }

  async function hydrateVectorLayersFromSnapshot(instanceIdMap: Map<string, string>) {
    const snap = loadWorkspaceSnapshot()
    if (!snap?.vectorLayers?.length) return

    const activeLayers = deps.getActiveLayers()
    const existingBackendIds = new Set(
      activeLayers
        .map((l) => l.importedVector?.backendLayerId)
        .filter((id): id is string => Boolean(id)),
    )

    const { fetchImportedLayerGeojson, fetchImportedLayerMeta } =
      await import('../../data-manager/core/api')

    for (const saved of snap.vectorLayers as PersistedVectorLayer[]) {
      if (!saved.backendLayerId) continue
      if (isVectorDismissed(saved.backendLayerId)) continue
      if (existingBackendIds.has(saved.backendLayerId)) continue

      try {
        const [geojson, meta] = await Promise.all([
          fetchImportedLayerGeojson(saved.backendLayerId, true),
          fetchImportedLayerMeta(saved.backendLayerId).catch(() => null),
        ])
        const instanceId = deps.genInstanceId()
        instanceIdMap.set(saved.instanceId, instanceId)
        const displayName =
          saved.name ||
          (typeof meta?.source_name === 'string' ? meta.source_name : undefined) ||
          saved.fileName ||
          saved.backendLayerId
        const payload = buildImportedVectorPayload(geojson, saved.fileName || displayName, {
          backendLayerId: saved.backendLayerId,
          featureCount: typeof meta?.feature_count === 'number' ? meta.feature_count : undefined,
        })
        if (saved.truncated ?? meta?.truncated) payload.truncated = true
        if (saved.style) payload.style = saved.style

        const accent = saved.accentColor
          ? {
              accentColor: saved.accentColor,
              accentGlow: saved.accentGlow ?? 'var(--surface-3)',
              chipTone: saved.chipTone ?? 'var(--surface-hover)',
            }
          : deps.assignLayerAccent('var(--success)')

        activeLayers.push({
          instanceId,
          catalogId: saved.catalogId || saved.backendLayerId,
          name: displayName,
          visible: saved.visible !== false,
          opacity: typeof saved.opacity === 'number' ? saved.opacity : 0.85,
          order: typeof saved.order === 'number' ? saved.order : activeLayers.length,
          isAdminBoundary: false,
          dataState: 'imported',
          importedVector: payload,
          accentColor: accent.accentColor,
          accentGlow: accent.accentGlow,
          chipTone: accent.chipTone,
        })
        existingBackendIds.add(saved.backendLayerId)
      } catch (err) {
        console.warn('[layers] restore vector layer failed', saved.backendLayerId, err)
        // 保留快照条目待下次刷新重试（防瞬时故障导致图层永久丢失）
        pendingRetryVectorLayers.push(saved)
      }
    }

    if (pendingRetryVectorLayers.length) {
      console.warn(
        '[layers] %d vector layer(s) failed to restore; kept in snapshot for retry',
        pendingRetryVectorLayers.length,
      )
    }

    if (activeLayers.length && deps.getSidebarView() === 'empty') {
      deps.setSidebarView('active')
    }
  }

  return {
    scheduleWorkspacePersist,
    flushWorkspacePersistNow,
    setWorkspaceHydrationGuard,
    restoreCatalogLayerFromSnapshot,
    restoreRunGroupsFromSnapshot,
    hydrateWorkspaceFromSnapshot,
    hydrateVectorLayersFromSnapshot,
  }
}
