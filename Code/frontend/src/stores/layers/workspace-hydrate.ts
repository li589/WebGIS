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
import { scheduleWorkspaceSyncPush } from './workspace-sync'
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
    flushWorkspacePersistNow: () => void
  }) => void
}

export function createWorkspaceHydrateSlice(deps: WorkspaceHydrateSliceDeps) {
  const weatherTileManager = useWeatherTileManager()
  let workspacePersistTimer: ReturnType<typeof setTimeout> | null = null

  function flushWorkspacePersistNow() {
    if (typeof window === 'undefined') return
    if (workspacePersistTimer != null) {
      window.clearTimeout(workspacePersistTimer)
      workspacePersistTimer = null
    }
    saveWorkspaceSnapshot(buildWorkspaceSnapshot(deps.getActiveLayers(), deps.getRunLayerGroups()))
    scheduleWorkspaceSyncPush()
  }

  function scheduleWorkspacePersist() {
    if (typeof window === 'undefined') return
    if (workspacePersistTimer != null) window.clearTimeout(workspacePersistTimer)
    workspacePersistTimer = window.setTimeout(() => {
      workspacePersistTimer = null
      flushWorkspacePersistNow()
    }, 400)
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
      }
    }

    if (activeLayers.length && deps.getSidebarView() === 'empty') {
      deps.setSidebarView('active')
    }
  }

  return {
    scheduleWorkspacePersist,
    flushWorkspacePersistNow,
    restoreCatalogLayerFromSnapshot,
    restoreRunGroupsFromSnapshot,
    hydrateWorkspaceFromSnapshot,
    hydrateVectorLayersFromSnapshot,
  }
}
