/**
 * 工作区跨设备同步引擎（单账号多机一致；按 API 入口 apiScope 分桶，避免局域网/公网互冲）。
 *
 * 策略：
 * - boot（Dashboard 挂载、hydrate 前）：拉取远端 v2 scopes，仅接管**当前入口**分桶；
 *   savedAt 新者胜出写入 localStorage，既有 hydrate 流程无需改动即可恢复。
 * - 本地变更：workspace-persist 落盘后防抖推送（乐观并发 base_revision），合并写入当前 scope。
 * - 409 冲突：savedAt 新者胜（按当前 scope）；远端新 → 接管并整页刷新；本地新 → 强推。
 * - 账号切换：清空本地；远端仅采纳当前 scope 分桶（无则清空）。
 * - API 入口切换：不采纳其它 scope 的快照；当前 scope 有远端且较新才接管，否则保留本机 localStorage。
 * - 会话内慢轮询：仅当**当前 scope** 远端更新且本地无未推送变更时刷新页面。
 */
import { ref } from 'vue'

import {
  fetchWorkspace,
  pushWorkspace,
  WorkspaceConflictApiError,
  type RemoteWorkspacePayload,
} from '../../services/workspace-api'
import { getApiStorageScope } from '../../services/_http'
import { readScopedItem, writeScopedItem } from '../../services/user-local-isolation'
import { useAuthStore } from '../auth'
import {
  clearWorkspaceSnapshot,
  loadDismissedLayers,
  loadWorkspaceSnapshot,
  sanitizeSnapshotForCurrentApi,
  saveWorkspaceSnapshot,
  writeDismissedLayers,
  type DismissedLayersRegistry,
  type WorkspaceSnapshot,
} from './workspace-persist'
import {
  getScopeBundle,
  mergeScopeBundle,
  normalizeRemotePayload,
  toRemotePayload,
  type ScopedWorkspaceBundle,
} from './workspace-remote-payload'

export type WorkspaceSyncStatus = 'disabled' | 'idle' | 'syncing' | 'error'

const SYNC_USER_KEY = 'geo:workspace-sync-user:v1'
const PUSH_DEBOUNCE_MS = 1200
const SLOW_POLL_MS = 90_000

export const workspaceSyncStatus = ref<WorkspaceSyncStatus>('disabled')
export const workspaceSyncError = ref<string | null>(null)
export const workspaceSyncedAt = ref<string | null>(null)

let activeUsername: string | null = null
let remoteRevision: number | null = null
let cachedRemoteNormalized = normalizeRemotePayload(null)
let pushTimer: ReturnType<typeof setTimeout> | null = null
let pollTimer: ReturnType<typeof setInterval> | null = null
let dirty = false
let suppressSyncPush = false

function emptyDismissed(): DismissedLayersRegistry {
  return { overlayLayerIds: [], catalogIds: [], runIds: [], vectorBackendLayerIds: [] }
}

function snapshotIsEmpty(snap: WorkspaceSnapshot | null | undefined): boolean {
  if (!snap) return true
  return (
    (snap.layers?.length ?? 0) === 0 &&
    (snap.catalogLayers?.length ?? 0) === 0 &&
    (snap.vectorLayers?.length ?? 0) === 0
  )
}

function snapshotContentKey(snap: WorkspaceSnapshot | null | undefined): string {
  if (!snap || snapshotIsEmpty(snap)) return ''
  const layerIds = [
    ...(snap.layers ?? []).map((l) => l.importedRaster?.overlayLayerId || l.instanceId),
    ...(snap.catalogLayers ?? []).map((l) => l.catalogId),
    ...(snap.vectorLayers ?? []).map((l) => l.backendLayerId),
  ]
    .filter(Boolean)
    .sort()
  const groupIds = (snap.groups ?? [])
    .map((g) => `${g.groupId}:${g.runId ?? ''}:${g.status ?? ''}`)
    .sort()
  return `${layerIds.join('|')}#${groupIds.join('|')}`
}

interface SyncMarker {
  username: string
  apiScope: string
}

function parseMarker(raw: string | null): SyncMarker | null {
  if (!raw) return null
  const pipe = raw.indexOf('|')
  if (pipe < 0) {
    return { username: raw, apiScope: '' }
  }
  return { username: raw.slice(0, pipe), apiScope: raw.slice(pipe + 1) }
}

function formatMarker(username: string): string {
  return `${username}|${getApiStorageScope()}`
}

function readMarker(): SyncMarker | null {
  if (typeof window === 'undefined') return null
  try {
    return parseMarker(readScopedItem(SYNC_USER_KEY))
  } catch {
    return null
  }
}

function writeMarker(username: string): void {
  writeScopedItem(SYNC_USER_KEY, formatMarker(username))
}

function adoptScoped(bundle: ScopedWorkspaceBundle): void {
  const snapshot = sanitizeSnapshotForCurrentApi(bundle.snapshot)
  saveWorkspaceSnapshot(snapshot)
  writeDismissedLayers(bundle.dismissed ?? emptyDismissed())
}

function currentScopeBundleFromRemote(): ScopedWorkspaceBundle | null {
  return getScopeBundle(cachedRemoteNormalized, getApiStorageScope())
}

function rememberRemotePayload(payload: RemoteWorkspacePayload | null | undefined): void {
  cachedRemoteNormalized = normalizeRemotePayload(payload)
}

/**
 * 空本地不得覆盖非空远端（同 scope）。返回 true 表示已接管远端或无需推送。
 */
async function refuseEmptyOverwriteIfNeeded(local: WorkspaceSnapshot): Promise<boolean> {
  if (!snapshotIsEmpty(local)) return false
  const scope = getApiStorageScope()
  const remoteBundle = getScopeBundle(cachedRemoteNormalized, scope)
  if (remoteBundle && !snapshotIsEmpty(remoteBundle.snapshot)) {
    adoptScoped(remoteBundle)
    dirty = false
    workspaceSyncStatus.value = 'idle'
    return true
  }
  if (remoteRevision == null || remoteRevision <= 0) {
    try {
      const remote = await fetchWorkspace()
      remoteRevision = remote.revision
      rememberRemotePayload(remote.payload)
      workspaceSyncedAt.value = remote.updated_at
      const bundle = getScopeBundle(cachedRemoteNormalized, scope)
      if (!bundle || snapshotIsEmpty(bundle.snapshot)) return false
      adoptScoped(bundle)
      dirty = false
      workspaceSyncStatus.value = 'idle'
      return true
    } catch {
      return false
    }
  }
  return false
}

async function pushNow(): Promise<void> {
  const localSnapshot = loadWorkspaceSnapshot()
  if (!localSnapshot) return
  if (await refuseEmptyOverwriteIfNeeded(localSnapshot)) {
    return
  }
  const scope = getApiStorageScope()
  const merged = mergeScopeBundle(cachedRemoteNormalized, scope, {
    snapshot: localSnapshot,
    dismissed: loadDismissedLayers(),
  })
  const payload = toRemotePayload(merged)
  const result = await pushWorkspace(payload, remoteRevision)
  remoteRevision = result.revision
  cachedRemoteNormalized = merged
  workspaceSyncedAt.value = result.updated_at
  workspaceSyncError.value = null
  workspaceSyncStatus.value = 'idle'
}

async function resolveConflict(_serverRevision: number): Promise<void> {
  const remote = await fetchWorkspace()
  remoteRevision = remote.revision
  rememberRemotePayload(remote.payload)
  const scope = getApiStorageScope()
  const remoteBundle = getScopeBundle(cachedRemoteNormalized, scope)
  const remoteAt = remoteBundle?.snapshot?.savedAt ?? ''
  const local = loadWorkspaceSnapshot()
  const localAt = local?.savedAt ?? ''
  if (remoteBundle && remoteAt > localAt) {
    adoptScoped(remoteBundle)
    window.location.reload()
    return
  }
  if (remoteBundle && !snapshotIsEmpty(remoteBundle.snapshot) && snapshotIsEmpty(local)) {
    adoptScoped(remoteBundle)
    window.location.reload()
    return
  }
  await pushNow()
  dirty = false
}

async function runPush(): Promise<void> {
  if (!activeUsername) {
    dirty = false
    return
  }
  workspaceSyncStatus.value = 'syncing'
  try {
    await pushNow()
    dirty = false
  } catch (err) {
    if (err instanceof WorkspaceConflictApiError) {
      try {
        await resolveConflict(err.serverRevision)
        return
      } catch (conflictErr) {
        workspaceSyncStatus.value = 'error'
        workspaceSyncError.value =
          conflictErr instanceof Error ? conflictErr.message : String(conflictErr)
        return
      }
    }
    workspaceSyncStatus.value = 'error'
    workspaceSyncError.value = err instanceof Error ? err.message : String(err)
  }
}

export function scheduleWorkspaceSyncPush(): void {
  if (!activeUsername || typeof window === 'undefined') return
  if (suppressSyncPush) return
  dirty = true
  if (pushTimer != null) window.clearTimeout(pushTimer)
  pushTimer = window.setTimeout(() => {
    pushTimer = null
    void runPush()
  }, PUSH_DEBOUNCE_MS)
}

export function suppressWorkspaceSyncPush(active: boolean): void {
  suppressSyncPush = active
}

async function pollRemote(): Promise<void> {
  if (!activeUsername || dirty || pushTimer != null) return
  if (typeof document !== 'undefined' && document.visibilityState !== 'visible') return
  try {
    const remote = await fetchWorkspace()
    const remotePayload = remote.payload
    if (!remotePayload) return
    if (remote.revision === remoteRevision) return
    rememberRemotePayload(remotePayload)
    const scope = getApiStorageScope()
    const remoteBundle = getScopeBundle(cachedRemoteNormalized, scope)
    if (!remoteBundle || snapshotIsEmpty(remoteBundle.snapshot)) {
      remoteRevision = remote.revision
      return
    }
    const remoteAt = remoteBundle.snapshot.savedAt ?? ''
    const local = loadWorkspaceSnapshot()
    const localAt = local?.savedAt ?? ''
    if (remoteAt <= localAt) {
      remoteRevision = remote.revision
      return
    }
    if (snapshotContentKey(remoteBundle.snapshot) === snapshotContentKey(local)) {
      remoteRevision = remote.revision
      return
    }
    remoteRevision = remote.revision
    adoptScoped(remoteBundle)
    window.location.reload()
  } catch {
    /* 网络抖动：下轮再试 */
  }
}

function startPoll(): void {
  if (typeof window === 'undefined' || pollTimer != null) return
  pollTimer = window.setInterval(() => void pollRemote(), SLOW_POLL_MS)
}

function stopPoll(): void {
  if (pollTimer != null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

/**
 * 按当前 apiScope 决定是否采纳远端分桶（savedAt 较新或本地为空）。
 */
function adoptCurrentScopeIfNewer(
  remoteBundle: ScopedWorkspaceBundle | null,
  local: WorkspaceSnapshot | null,
): boolean {
  if (!remoteBundle || snapshotIsEmpty(remoteBundle.snapshot)) return false
  const remoteAt = remoteBundle.snapshot.savedAt ?? ''
  const localAt = local?.savedAt ?? ''
  if (!local || snapshotIsEmpty(local)) {
    adoptScoped(remoteBundle)
    return true
  }
  if (remoteAt > localAt) {
    adoptScoped(remoteBundle)
    return true
  }
  return false
}

export async function syncWorkspaceOnBoot(): Promise<void> {
  const username = currentSyncUsername()
  if (!username) {
    activeUsername = null
    workspaceSyncStatus.value = 'disabled'
    stopPoll()
    return
  }
  activeUsername = username
  workspaceSyncStatus.value = 'syncing'
  workspaceSyncError.value = null
  try {
    const marker = readMarker()
    const currentScope = getApiStorageScope()
    const userSwitched = marker != null && marker.username !== username
    const envSwitched =
      marker != null && marker.apiScope !== '' && marker.apiScope !== currentScope

    const remote = await fetchWorkspace()
    remoteRevision = remote.revision
    workspaceSyncedAt.value = remote.updated_at
    rememberRemotePayload(remote.payload)
    const remoteBundle = currentScopeBundleFromRemote()
    const local = loadWorkspaceSnapshot()

    if (userSwitched) {
      if (remoteBundle && !snapshotIsEmpty(remoteBundle.snapshot)) {
        adoptScoped(remoteBundle)
      } else {
        clearWorkspaceSnapshot()
        writeDismissedLayers(emptyDismissed())
      }
    } else if (envSwitched) {
      // 入口切换：绝不采纳其它 scope 的快照；仅当前 scope 分桶较新时接管
      adoptCurrentScopeIfNewer(remoteBundle, local)
      // 否则保留本 origin 的 localStorage，避免公网↔局域网互冲
    } else if (adoptCurrentScopeIfNewer(remoteBundle, local)) {
      /* 远端当前 scope 较新 */
    } else if (remoteBundle && snapshotIsEmpty(local) && !snapshotIsEmpty(remoteBundle.snapshot)) {
      adoptScoped(remoteBundle)
    } else if (!snapshotIsEmpty(local)) {
      await pushNow()
    }
    writeMarker(username)
    dirty = false
    workspaceSyncStatus.value = 'idle'
    startPoll()
  } catch (err) {
    workspaceSyncStatus.value = 'error'
    workspaceSyncError.value = err instanceof Error ? err.message : String(err)
  }
}

function currentSyncUsername(): string | null {
  const auth = useAuthStore()
  const user = auth.user
  if (!user || user.role === 'demo') return null
  return user.username
}

export function teardownWorkspaceSync(): void {
  stopPoll()
  if (pushTimer != null) {
    window.clearTimeout(pushTimer)
    pushTimer = null
  }
}

export function resetWorkspaceSyncState(): void {
  teardownWorkspaceSync()
  activeUsername = null
  remoteRevision = null
  cachedRemoteNormalized = normalizeRemotePayload(null)
  dirty = false
  suppressSyncPush = false
  workspaceSyncStatus.value = 'disabled'
  workspaceSyncError.value = null
  workspaceSyncedAt.value = null
}
