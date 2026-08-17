import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { WorkspaceConflictApiError, type RemoteWorkspaceState } from '@/services/workspace-api'
import {
  loadWorkspaceSnapshot,
  loadDismissedLayers,
  saveWorkspaceSnapshot,
  type WorkspaceSnapshot,
} from '@/stores/layers/workspace-persist'
import {
  resetWorkspaceSyncState,
  scheduleWorkspaceSyncPush,
  syncWorkspaceOnBoot,
  workspaceSyncStatus,
} from '@/stores/layers/workspace-sync'

const fetchWorkspaceMock = vi.fn()
const pushWorkspaceMock = vi.fn()
const reloadMock = vi.fn()

vi.mock('@/services/workspace-api', () => ({
  fetchWorkspace: (...args: unknown[]) => fetchWorkspaceMock(...(args as [])),
  pushWorkspace: (...args: unknown[]) => pushWorkspaceMock(...args),
  WorkspaceConflictApiError: class WorkspaceConflictApiError extends Error {
    readonly serverRevision: number
    constructor(message: string, serverRevision: number) {
      super(message)
      this.serverRevision = serverRevision
    }
  },
}))

let authUserMock: { id: number; username: string; role: string } | null = null

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: authUserMock }),
}))

const STORAGE_KEY = 'geo:active-layers-workspace:v1'
const MARKER_KEY = 'geo:workspace-sync-user:v1'

function mockBrowserStorage() {
  const store = new Map<string, string>()
  const storage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => {
      store.set(k, v)
    },
    removeItem: (k: string) => {
      store.delete(k)
    },
    clear: () => store.clear(),
  }
  vi.stubGlobal('localStorage', storage)
  vi.stubGlobal('window', {
    localStorage: storage,
    setTimeout: globalThis.setTimeout.bind(globalThis),
    clearTimeout: globalThis.clearTimeout.bind(globalThis),
    setInterval: globalThis.setInterval.bind(globalThis),
    clearInterval: globalThis.clearInterval.bind(globalThis),
    location: { reload: reloadMock },
  })
  return storage
}

function snapshot(savedAt: string, tag = 'koppen'): WorkspaceSnapshot {
  return {
    version: 1,
    savedAt,
    layers: [],
    catalogLayers: [
      {
        instanceId: `inst-${tag}`,
        catalogId: tag,
        visible: true,
        opacity: 1,
        order: 0,
      },
    ],
    vectorLayers: [],
    groups: [],
  }
}

function remoteState(
  revision: number,
  payload: { snapshot: WorkspaceSnapshot; dismissed?: object } | null,
): RemoteWorkspaceState {
  return {
    revision,
    updated_at: '2026-08-17T00:00:00Z',
    payload: payload ? { version: 1, ...payload } : null,
  }
}

describe('workspace-sync 跨设备同步引擎', () => {
  let store: { getItem: (k: string) => string | null; setItem: (k: string, v: string) => void }

  beforeEach(() => {
    vi.useFakeTimers()
    fetchWorkspaceMock.mockReset()
    pushWorkspaceMock.mockReset()
    reloadMock.mockReset()
    authUserMock = null
    store = mockBrowserStorage()
  })

  afterEach(() => {
    resetWorkspaceSyncState()
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it('未登录 / demo 账号：同步停用且不发起任何请求', async () => {
    authUserMock = null
    await syncWorkspaceOnBoot()
    expect(workspaceSyncStatus.value).toBe('disabled')
    expect(fetchWorkspaceMock).not.toHaveBeenCalled()

    authUserMock = { id: 3, username: 'guest', role: 'demo' }
    await syncWorkspaceOnBoot()
    expect(workspaceSyncStatus.value).toBe('disabled')
    expect(fetchWorkspaceMock).not.toHaveBeenCalled()
  })

  it('同账号且远端较新：接管远端快照与移除登记', async () => {
    authUserMock = { id: 1, username: 'alice', role: 'standard' }
    store.setItem(MARKER_KEY, 'alice')
    saveWorkspaceSnapshot(snapshot('2026-08-10T00:00:00Z', 'old'))
    const remoteDismissed = {
      overlayLayerIds: ['ov-1'],
      catalogIds: ['cat-1'],
      runIds: [],
      vectorBackendLayerIds: [],
    }
    fetchWorkspaceMock.mockResolvedValue(
      remoteState(5, { snapshot: snapshot('2026-08-16T00:00:00Z', 'new'), dismissed: remoteDismissed }),
    )

    await syncWorkspaceOnBoot()

    expect(pushWorkspaceMock).not.toHaveBeenCalled()
    const local = loadWorkspaceSnapshot()
    expect(local?.catalogLayers?.[0]?.catalogId).toBe('new')
    expect(loadDismissedLayers().overlayLayerIds).toEqual(['ov-1'])
    expect(store.getItem(MARKER_KEY)).toBe('alice')
  })

  it('同账号且本地较新：推送本地快照并携带 base_revision', async () => {
    authUserMock = { id: 1, username: 'alice', role: 'standard' }
    store.setItem(MARKER_KEY, 'alice')
    saveWorkspaceSnapshot(snapshot('2026-08-16T00:00:00Z', 'local-new'))
    fetchWorkspaceMock.mockResolvedValue(
      remoteState(3, { snapshot: snapshot('2026-08-01T00:00:00Z', 'remote-old') }),
    )
    pushWorkspaceMock.mockResolvedValue({ revision: 4, updated_at: '2026-08-17T01:00:00Z' })

    await syncWorkspaceOnBoot()

    expect(pushWorkspaceMock).toHaveBeenCalledTimes(1)
    const [payload, baseRevision] = pushWorkspaceMock.mock.calls[0]
    expect(baseRevision).toBe(3)
    expect(payload.snapshot.catalogLayers[0].catalogId).toBe('local-new')
    expect(workspaceSyncStatus.value).toBe('idle')
  })

  it('账号切换且远端为空：清空本地工作区避免跨账号串扰', async () => {
    authUserMock = { id: 2, username: 'bob', role: 'standard' }
    store.setItem(MARKER_KEY, 'alice')
    saveWorkspaceSnapshot(snapshot('2026-08-16T00:00:00Z', 'alice-data'))
    fetchWorkspaceMock.mockResolvedValue(remoteState(0, null))

    await syncWorkspaceOnBoot()

    expect(pushWorkspaceMock).not.toHaveBeenCalled()
    expect(loadWorkspaceSnapshot()).toBeNull()
    expect(loadDismissedLayers().overlayLayerIds).toEqual([])
    expect(store.getItem(MARKER_KEY)).toBe('bob')
  })

  it('账号切换且远端有内容：即使本地较新也远端硬接管', async () => {
    authUserMock = { id: 2, username: 'bob', role: 'standard' }
    store.setItem(MARKER_KEY, 'alice')
    saveWorkspaceSnapshot(snapshot('2026-08-16T00:00:00Z', 'alice-newer'))
    fetchWorkspaceMock.mockResolvedValue(
      remoteState(7, { snapshot: snapshot('2026-08-01T00:00:00Z', 'bob-remote') }),
    )

    await syncWorkspaceOnBoot()

    expect(pushWorkspaceMock).not.toHaveBeenCalled()
    expect(loadWorkspaceSnapshot()?.catalogLayers?.[0]?.catalogId).toBe('bob-remote')
  })

  it('本地变更防抖推送：落盘后推送最新快照', async () => {
    authUserMock = { id: 1, username: 'alice', role: 'standard' }
    store.setItem(MARKER_KEY, 'alice')
    fetchWorkspaceMock.mockResolvedValue(remoteState(2, null))
    await syncWorkspaceOnBoot()

    pushWorkspaceMock.mockResolvedValue({ revision: 3, updated_at: '2026-08-17T02:00:00Z' })
    saveWorkspaceSnapshot(snapshot('2026-08-17T02:30:00Z', 'edited'))
    scheduleWorkspaceSyncPush()
    await vi.advanceTimersByTimeAsync(1500)

    expect(pushWorkspaceMock).toHaveBeenCalledTimes(1)
    const [payload, baseRevision] = pushWorkspaceMock.mock.calls[0]
    expect(baseRevision).toBe(2)
    expect(payload.snapshot.catalogLayers[0].catalogId).toBe('edited')
  })

  it('推送冲突且远端较新：接管远端并刷新页面', async () => {
    authUserMock = { id: 1, username: 'alice', role: 'standard' }
    store.setItem(MARKER_KEY, 'alice')
    fetchWorkspaceMock.mockResolvedValueOnce(remoteState(2, null))
    await syncWorkspaceOnBoot()

    pushWorkspaceMock.mockRejectedValueOnce(new WorkspaceConflictApiError('conflict', 9))
    fetchWorkspaceMock.mockResolvedValueOnce(
      remoteState(9, { snapshot: snapshot('2026-08-17T03:00:00Z', 'other-device') }),
    )
    saveWorkspaceSnapshot(snapshot('2026-08-17T01:00:00Z', 'stale-local'))
    scheduleWorkspaceSyncPush()
    await vi.advanceTimersByTimeAsync(1500)

    expect(reloadMock).toHaveBeenCalled()
    expect(loadWorkspaceSnapshot()?.catalogLayers?.[0]?.catalogId).toBe('other-device')
  })

  it('推送冲突但本地较新：以服务端 revision 强推本地', async () => {
    authUserMock = { id: 1, username: 'alice', role: 'standard' }
    store.setItem(MARKER_KEY, 'alice')
    fetchWorkspaceMock.mockResolvedValueOnce(remoteState(2, null))
    await syncWorkspaceOnBoot()

    pushWorkspaceMock.mockRejectedValueOnce(new WorkspaceConflictApiError('conflict', 9))
    fetchWorkspaceMock.mockResolvedValueOnce(
      remoteState(9, { snapshot: snapshot('2026-08-17T00:30:00Z', 'remote-older') }),
    )
    pushWorkspaceMock.mockResolvedValueOnce({ revision: 10, updated_at: '2026-08-17T04:00:00Z' })
    saveWorkspaceSnapshot(snapshot('2026-08-17T01:00:00Z', 'local-newer'))
    scheduleWorkspaceSyncPush()
    await vi.advanceTimersByTimeAsync(1500)

    expect(reloadMock).not.toHaveBeenCalled()
    expect(pushWorkspaceMock).toHaveBeenCalledTimes(2)
    const [, forcedBase] = pushWorkspaceMock.mock.calls[1]
    expect(forcedBase).toBe(9)
    expect(loadWorkspaceSnapshot()?.catalogLayers?.[0]?.catalogId).toBe('local-newer')
  })

  it('拉取失败：进入 error 状态且不抛出（不影响 hydrate 启动）', async () => {
    authUserMock = { id: 1, username: 'alice', role: 'standard' }
    store.setItem(MARKER_KEY, 'alice')
    fetchWorkspaceMock.mockRejectedValue(new Error('backend offline'))

    await expect(syncWorkspaceOnBoot()).resolves.toBeUndefined()
    expect(workspaceSyncStatus.value).toBe('error')
  })
})
