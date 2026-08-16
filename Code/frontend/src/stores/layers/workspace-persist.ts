/**
 * 图层工作区持久化：刷新后恢复已添加图层；用户移除后不再自动恢复。
 * 矢量仅持久化 backendLayerId 等元数据（不写入 GeoJSON）；刷新后从后端 preview 拉取。
 */
import type { ActiveLayer, ActiveRunLayerGroup } from './types'
import type { ImportedRasterPayload } from './imported-raster'
import type { ImportedVectorPayload } from './imported-vector'

const STORAGE_KEY = 'geo:active-layers-workspace:v1'
const DISMISSED_STORAGE_KEY = 'geo:dismissed-layers:v1'
const MAX_LAYERS = 80
const MAX_DISMISSED = 240

export interface PersistedActiveLayer {
  instanceId: string
  catalogId: string
  name?: string
  visible: boolean
  opacity: number
  order: number
  runGroupId?: string
  runGroupProductTag?: string
  runGroupLocked?: boolean
  importedRaster?: ImportedRasterPayload
  accentColor?: string
  accentGlow?: string
  chipTone?: string
  paletteOverride?: string | null
  vminOverride?: number | null
  vmaxOverride?: number | null
  nodataMode?: 'transparent' | 'solid' | null
  nodataColor?: string | null
}

/** 导入矢量（仅 backend 登记层；刷新后按需拉取 GeoJSON） */
export interface PersistedVectorLayer {
  instanceId: string
  catalogId: string
  backendLayerId: string
  name?: string
  fileName?: string
  visible: boolean
  opacity: number
  order: number
  truncated?: boolean
  style?: ImportedVectorPayload['style']
  accentColor?: string
  accentGlow?: string
  chipTone?: string
}

/** 目录/天气/分析图层（无 overlay 文件）；含计算中占位（runGroupLocked） */
export interface PersistedCatalogLayer {
  instanceId: string
  catalogId: string
  name?: string
  visible: boolean
  opacity: number
  order: number
  dataState?: 'catalog' | 'real'
  runGroupId?: string
  runGroupProductTag?: string
  /** 计算组占位锁定：刷新后需保留，避免多图层组丢失 */
  runGroupLocked?: boolean
  accentColor?: string
  accentGlow?: string
  chipTone?: string
  paletteOverride?: string | null
  vminOverride?: number | null
  vmaxOverride?: number | null
  nodataMode?: 'transparent' | 'solid' | null
  nodataColor?: string | null
}

export interface WorkspaceSnapshot {
  version: 1
  savedAt: string
  layers: PersistedActiveLayer[]
  catalogLayers?: PersistedCatalogLayer[]
  vectorLayers?: PersistedVectorLayer[]
  groups: ActiveRunLayerGroup[]
}

export interface DismissedLayersRegistry {
  overlayLayerIds: string[]
  catalogIds: string[]
  vectorBackendLayerIds: string[]
  runIds: string[]
}

function emptyDismissed(): DismissedLayersRegistry {
  return { overlayLayerIds: [], catalogIds: [], runIds: [], vectorBackendLayerIds: [] }
}

function pushUnique(list: string[], value: string | undefined | null) {
  const v = String(value || '').trim()
  if (!v || list.includes(v)) return
  list.unshift(v)
  if (list.length > MAX_DISMISSED) list.length = MAX_DISMISSED
}

export function loadDismissedLayers(): DismissedLayersRegistry {
  if (typeof window === 'undefined') return emptyDismissed()
  try {
    const raw = window.localStorage.getItem(DISMISSED_STORAGE_KEY)
    if (!raw) return emptyDismissed()
    const parsed = JSON.parse(raw) as Partial<DismissedLayersRegistry>
    return {
      overlayLayerIds: Array.isArray(parsed.overlayLayerIds)
        ? parsed.overlayLayerIds.filter((x) => typeof x === 'string')
        : [],
      catalogIds: Array.isArray(parsed.catalogIds)
        ? parsed.catalogIds.filter((x) => typeof x === 'string')
        : [],
      runIds: Array.isArray(parsed.runIds)
        ? parsed.runIds.filter((x) => typeof x === 'string')
        : [],
      vectorBackendLayerIds: Array.isArray(parsed.vectorBackendLayerIds)
        ? parsed.vectorBackendLayerIds.filter((x) => typeof x === 'string')
        : [],
    }
  } catch {
    return emptyDismissed()
  }
}

function saveDismissedLayers(registry: DismissedLayersRegistry): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(DISMISSED_STORAGE_KEY, JSON.stringify(registry))
  } catch {
    /* quota / private mode */
  }
}

export function rememberDismissedLayer(entry: {
  overlayLayerId?: string | null
  catalogId?: string | null
  vectorBackendLayerId?: string | null
  runId?: string | null
}): void {
  const reg = loadDismissedLayers()
  pushUnique(reg.overlayLayerIds, entry.overlayLayerId)
  pushUnique(reg.catalogIds, entry.catalogId)
  pushUnique(reg.vectorBackendLayerIds, entry.vectorBackendLayerId)
  pushUnique(reg.runIds, entry.runId)
  saveDismissedLayers(reg)
}

/** 从移除清单中解除指定 run / overlay / catalog / vector 的标记。 */
export function forgetDismissedLayer(entry: {
  overlayLayerId?: string | null
  catalogId?: string | null
  vectorBackendLayerId?: string | null
  runId?: string | null
}): void {
  const reg = loadDismissedLayers()
  const remove = (list: string[], value: string | undefined | null) => {
    const v = String(value || '').trim()
    if (!v) return
    const idx = list.indexOf(v)
    if (idx >= 0) list.splice(idx, 1)
  }
  remove(reg.overlayLayerIds, entry.overlayLayerId)
  remove(reg.catalogIds, entry.catalogId)
  remove(reg.vectorBackendLayerIds, entry.vectorBackendLayerId)
  remove(reg.runIds, entry.runId)
  saveDismissedLayers(reg)
}

export function isOverlayDismissed(overlayLayerId: string | undefined | null): boolean {
  const id = String(overlayLayerId || '').trim()
  if (!id) return false
  return loadDismissedLayers().overlayLayerIds.includes(id)
}

export function isCatalogDismissed(catalogId: string | undefined | null): boolean {
  const id = String(catalogId || '').trim()
  if (!id) return false
  return loadDismissedLayers().catalogIds.includes(id)
}

export function isRunDismissed(runId: string | undefined | null): boolean {
  const id = String(runId || '').trim()
  if (!id) return false
  return loadDismissedLayers().runIds.includes(id)
}

export function isVectorDismissed(backendLayerId: string | undefined | null): boolean {
  const id = String(backendLayerId || '').trim()
  if (!id) return false
  return loadDismissedLayers().vectorBackendLayerIds.includes(id)
}

function isPersistableRasterLayer(layer: ActiveLayer): boolean {
  if (layer.isAdminBoundary) return false
  return Boolean(layer.importedRaster?.overlayLayerId)
}

function isPersistableCatalogLayer(layer: ActiveLayer): boolean {
  if (layer.isAdminBoundary) return false
  if (layer.importedRaster?.overlayLayerId) return false
  if (layer.importedVector) return false
  // 计算中占位（无 overlay）必须持久化，否则刷新后多图层组整组消失
  return true
}

function isPersistableVectorLayer(layer: ActiveLayer): boolean {
  if (layer.isAdminBoundary) return false
  return Boolean(layer.importedVector?.backendLayerId)
}

function serializeImportedRaster(
  importedRaster: NonNullable<ActiveLayer['importedRaster']>,
): ImportedRasterPayload {
  return {
    overlayLayerId: importedRaster.overlayLayerId,
    bounds: importedRaster.bounds,
    fileName: importedRaster.fileName,
    sourceCrs: importedRaster.sourceCrs,
    lngOffset: importedRaster.lngOffset,
    latOffset: importedRaster.latOffset,
    nativeStep:
      typeof importedRaster.nativeStep === 'string'
        ? importedRaster.nativeStep
        : importedRaster.nativeStep
          ? `${importedRaster.nativeStep.value}${importedRaster.nativeStep.unit === 'hour' ? 'h' : importedRaster.nativeStep.unit === 'day' ? 'd' : importedRaster.nativeStep.unit === 'month' ? 'm' : 'yr'}`
          : null,
    timeList: importedRaster.timeList,
    followPolicy: importedRaster.followPolicy,
    effectiveTimeLabel: importedRaster.effectiveTimeLabel,
  }
}

export function buildWorkspaceSnapshot(
  activeLayers: ActiveLayer[],
  runLayerGroups: ActiveRunLayerGroup[],
): WorkspaceSnapshot {
  const dismissed = loadDismissedLayers()
  const withOverlay = activeLayers.filter(
    (l) => isPersistableRasterLayer(l) && !isOverlayDismissed(l.importedRaster?.overlayLayerId),
  )
  const catalogLayers = activeLayers
    .filter((l) => isPersistableCatalogLayer(l) && !isCatalogDismissed(l.catalogId))
    .slice(0, MAX_LAYERS)
    .map((l): PersistedCatalogLayer => ({
      instanceId: l.instanceId,
      catalogId: l.catalogId,
      name: l.name,
      visible: l.visible,
      opacity: l.opacity,
      order: l.order,
      dataState: l.dataState === 'real' ? 'real' : 'catalog',
      runGroupId: l.runGroupId,
      runGroupProductTag: l.runGroupProductTag,
      runGroupLocked: Boolean(l.runGroupLocked),
      accentColor: l.accentColor,
      accentGlow: l.accentGlow,
      chipTone: l.chipTone,
      paletteOverride: l.paletteOverride ?? null,
      vminOverride: l.vminOverride ?? null,
      vmaxOverride: l.vmaxOverride ?? null,
      nodataMode: l.nodataMode ?? null,
      nodataColor: l.nodataColor ?? null,
    }))

  const vectorLayers = activeLayers
    .filter(
      (l) => isPersistableVectorLayer(l) && !isVectorDismissed(l.importedVector?.backendLayerId),
    )
    .slice(0, MAX_LAYERS)
    .map((l): PersistedVectorLayer => ({
      instanceId: l.instanceId,
      catalogId: l.catalogId,
      backendLayerId: l.importedVector!.backendLayerId!,
      name: l.name,
      fileName: l.importedVector?.fileName,
      visible: l.visible,
      opacity: l.opacity,
      order: l.order,
      truncated: l.importedVector?.truncated,
      style: l.importedVector?.style,
      accentColor: l.accentColor,
      accentGlow: l.accentGlow,
      chipTone: l.chipTone,
    }))

  if (!withOverlay.length && !catalogLayers.length && !vectorLayers.length) {
    return {
      version: 1,
      savedAt: new Date().toISOString(),
      layers: [],
      catalogLayers: [],
      vectorLayers: [],
      groups: [],
    }
  }

  const persistedInstanceIds = new Set([
    ...withOverlay.map((l) => l.instanceId),
    ...catalogLayers.map((l) => l.instanceId),
    ...vectorLayers.map((l) => l.instanceId),
  ])
  const keepGroupIds = new Set<string>()
  for (const l of activeLayers) {
    if (l.runGroupId && persistedInstanceIds.has(l.instanceId)) {
      keepGroupIds.add(l.runGroupId)
    }
  }
  for (const g of runLayerGroups) {
    if (g.memberInstanceIds.some((id) => persistedInstanceIds.has(id))) {
      keepGroupIds.add(g.groupId)
    }
  }

  const layers = withOverlay.slice(0, MAX_LAYERS).map((l): PersistedActiveLayer => ({
    instanceId: l.instanceId,
    catalogId: l.catalogId,
    name: l.name,
    visible: l.visible,
    opacity: l.opacity,
    order: l.order,
    runGroupId: l.runGroupId,
    runGroupProductTag: l.runGroupProductTag,
    runGroupLocked: Boolean(l.runGroupLocked),
    importedRaster: l.importedRaster ? serializeImportedRaster(l.importedRaster) : undefined,
    accentColor: l.accentColor,
    accentGlow: l.accentGlow,
    chipTone: l.chipTone,
    paletteOverride: l.paletteOverride ?? null,
    vminOverride: l.vminOverride ?? null,
    vmaxOverride: l.vmaxOverride ?? null,
    nodataMode: l.nodataMode ?? null,
    nodataColor: l.nodataColor ?? null,
  }))

  const groups = runLayerGroups
    .filter((g) => keepGroupIds.has(g.groupId) && (!g.runId || !dismissed.runIds.includes(g.runId)))
    .map((g) => {
      const computing = g.status === 'computing'
      return {
        ...g,
        memberInstanceIds: g.memberInstanceIds.filter((id) => persistedInstanceIds.has(id)),
        dissolvable: computing ? false : true,
        status: g.status,
      }
    })
    .filter((g) => g.memberInstanceIds.length > 0)

  return {
    version: 1,
    savedAt: new Date().toISOString(),
    layers,
    catalogLayers,
    vectorLayers,
    groups,
  }
}

export function saveWorkspaceSnapshot(snapshot: WorkspaceSnapshot): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot))
  } catch {
    /* quota / private mode */
  }
}

export function loadWorkspaceSnapshot(): WorkspaceSnapshot | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as WorkspaceSnapshot
    if (!parsed || parsed.version !== 1 || !Array.isArray(parsed.layers)) return null
    if (!Array.isArray(parsed.catalogLayers)) parsed.catalogLayers = []
    if (!Array.isArray(parsed.vectorLayers)) parsed.vectorLayers = []
    if (!Array.isArray(parsed.groups)) parsed.groups = []
    return migrateSnapshot(parsed)
  } catch {
    return null
  }
}

/**
 * 一次性迁移：删除英文占位图层条目（catalogId 为 omega_sf_fenkuai_* /
 * omega_avg_daily_* 等原始 workflow id）。这些占位无目录条目、无独立数据源，
 * 产物恢复改经 restoreActiveWorkflows 映射到「风云/SMAP ω 反演」合并组。
 */
const ENGLISH_PLACEHOLDER_CATALOG_PATTERN = /^omega[-_]sf[-_]fenkuai|^omega[-_]avg[-_]daily/i

function migrateSnapshot(snapshot: WorkspaceSnapshot): WorkspaceSnapshot {
  const drop = (catalogId: string | undefined | null): boolean =>
    Boolean(catalogId) && ENGLISH_PLACEHOLDER_CATALOG_PATTERN.test(String(catalogId))
  const catalogLayers = snapshot.catalogLayers ?? []
  const vectorLayers = snapshot.vectorLayers ?? []
  const beforeLayers = snapshot.layers.length + catalogLayers.length
  snapshot.layers = snapshot.layers.filter((l) => !drop(l.catalogId))
  snapshot.catalogLayers = catalogLayers.filter((l) => !drop(l.catalogId))
  if (snapshot.layers.length + snapshot.catalogLayers.length === beforeLayers) return snapshot
  const keptInstanceIds = new Set([
    ...snapshot.layers.map((l) => l.instanceId),
    ...snapshot.catalogLayers.map((l) => l.instanceId),
    ...vectorLayers.map((l) => l.instanceId),
  ])
  for (const group of snapshot.groups) {
    group.memberInstanceIds = group.memberInstanceIds.filter((id) => keptInstanceIds.has(id))
  }
  snapshot.groups = snapshot.groups.filter((g) => g.memberInstanceIds.length > 0)
  return snapshot
}

export function clearWorkspaceSnapshot(): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* ignore */
  }
}
