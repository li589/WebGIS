/**
 * 工作区跨设备同步引擎（单账号多机一致）。
 *
 * 策略：
 * - boot（Dashboard 挂载、hydrate 前）：拉取远端，savedAt 新者胜出写入 localStorage，
 *   既有 hydrate 流程无需改动即可恢复远端状态。
 * - 本地变更：workspace-persist 落盘后防抖推送（乐观并发 base_revision）。
 * - 409 冲突：savedAt 新者胜；远端新 → 接管并整页刷新重新 hydrate；本地新 → 以服务端 revision 强推。
 * - 账号切换（本机 sync 标记变化）：远端硬接管，远端为空则清空本地，避免跨账号数据串扰。
 * - 会话内慢轮询：远端有更新且本地无未推送变更时刷新页面收敛状态。
 *
 * 未保存的绘图草稿不经 snapshot 持久化，天然不同步（符合需求）。
 */
import { ref } from 'vue'

import {
  fetchWorkspace,
  pushWorkspace,
  WorkspaceConflictApiError,
  type RemoteWorkspacePayload,
} from '../../services/workspace-api'
import { useAuthStore } from '../auth'
import {
  clearWorkspaceSnapshot,
  loadDismissedLayers,
  loadWorkspaceSnapshot,
  saveWorkspaceSnapshot,
  writeDismissedLayers,
  type DismissedLayersRegistry,
  type WorkspaceSnapshot,
} from './workspace-persist'

export type WorkspaceSyncStatus = 'disabled' | 'idle' | 'syncing' | 'error'

const SYNC_USER_KEY = 'geo:workspace-sync-user:v1'
const PUSH_DEBOUNCE_MS = 1200
const SLOW_POLL_MS = 90_000

export const workspaceSyncStatus = ref<WorkspaceSyncStatus>('disabled')
export const workspaceSyncError = ref<string | null>(null)
export const workspaceSyncedAt = ref<string | null>(null)

let activeUsername: string | null = null
let remoteRevision: number | null = null
let pushTimer: ReturnType<typeof setTimeout> | null = null
let pollTimer: ReturnType<typeof setInterval> | null = null
/** 本地有未推送变更（推送失败时保留，等待下次触发或慢轮询跳过接管） */
let dirty = false

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

function readMarker(): string | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage.getItem(SYNC_USER_KEY)
  } catch {
    return null
  }
}

function writeMarker(username: string): void {
  try {
    window.localStorage.setItem(SYNC_USER_KEY, username)
  } catch {
    /* quota / private mode */
  }
}

function adoptRemote(payload: RemoteWorkspacePayload): void {
  saveWorkspaceSnapshot(payload.snapshot)
  writeDismissedLayers(payload.dismissed ?? emptyDismissed())
}

/** demo 账号后端拒绝同步；匿名完全停用。 */
function currentSyncUsername(): string | null {
  const auth = useAuthStore()
  const user = auth.user
  if (!user || user.role === 'demo') return null
  return user.username
}

async function pushNow(): Promise<void> {
  const snapshot = loadWorkspaceSnapshot()
  if (!snapshot) return
  const result = await pushWorkspace(
    { version: 1, snapshot, dismissed: loadDismissedLayers() },
    remoteRevision,
  )
  remoteRevision = result.revision
  workspaceSyncedAt.value = result.updated_at
  workspaceSyncError.value = null
  workspaceSyncStatus.value = 'idle'
}

async function resolveConflict(_serverRevision: number): Promise<void> {
  const remote = await fetchWorkspace()
  remoteRevision = remote.revision
  const remotePayload = remote.payload
  const remoteAt = remotePayload?.snapshot?.savedAt ?? ''
  const localAt = loadWorkspaceSnapshot()?.savedAt ?? ''
  if (remotePayload && remoteAt > localAt) {
    adoptRemote(remotePayload)
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

/** workspace-persist 落盘后调用：防抖推送远端。 */
export function scheduleWorkspaceSyncPush(): void {
  if (!activeUsername || typeof window === 'undefined') return
  dirty = true
  if (pushTimer != null) window.clearTimeout(pushTimer)
  pushTimer = window.setTimeout(() => {
    pushTimer = null
    void runPush()
  }, PUSH_DEBOUNCE_MS)
}

async function pollRemote(): Promise<void> {
  if (!activeUsername || dirty || pushTimer != null) return
  if (typeof document !== 'undefined' && document.visibilityState !== 'visible') return
  try {
    const remote = await fetchWorkspace()
    const remotePayload = remote.payload
    if (!remotePayload || snapshotIsEmpty(remotePayload.snapshot)) return
    if (remote.revision === remoteRevision) return
    const remoteAt = remotePayload.snapshot.savedAt ?? ''
    const localAt = loadWorkspaceSnapshot()?.savedAt ?? ''
    if (remoteAt <= localAt) return
    remoteRevision = remote.revision
    adoptRemote(remotePayload)
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
 * Dashboard 挂载时调用；必须在 restoreActiveWorkflows（hydrate）之前 await，
 * 使远端较新时本地 localStorage 已被接管，hydrate 自然恢复远端状态。
 */
export async function syncWorkspaceOnBoot(): Promise<void> {
  const username = currentSyncUsername()
  if (!username) {
    activeUsername = null
    workspaceSyncStatus.value = 'disabled'
    stopPoll()
    return
  }
  const userSwitched = readMarker() !== username
  activeUsername = username
  workspaceSyncStatus.value = 'syncing'
  workspaceSyncError.value = null
  try {
    const remote = await fetchWorkspace()
    remoteRevision = remote.revision
    workspaceSyncedAt.value = remote.updated_at
    const remotePayload = remote.payload
    const local = loadWorkspaceSnapshot()
    const remoteAt = remotePayload?.snapshot?.savedAt ?? ''
    const localAt = local?.savedAt ?? ''

    if (userSwitched) {
      if (remotePayload && !snapshotIsEmpty(remotePayload.snapshot)) {
        adoptRemote(remotePayload)
      } else {
        clearWorkspaceSnapshot()
        writeDismissedLayers(emptyDismissed())
      }
    } else if (remotePayload && remoteAt > localAt) {
      adoptRemote(remotePayload)
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

/** Dashboard 卸载时停止轮询/推送定时器。 */
export function teardownWorkspaceSync(): void {
  stopPoll()
  if (pushTimer != null) {
    window.clearTimeout(pushTimer)
    pushTimer = null
  }
}

/** 仅供测试：重置模块级可变状态。 */
export function resetWorkspaceSyncState(): void {
  teardownWorkspaceSync()
  activeUsername = null
  remoteRevision = null
  dirty = false
  workspaceSyncStatus.value = 'disabled'
  workspaceSyncError.value = null
  workspaceSyncedAt.value = null
}
