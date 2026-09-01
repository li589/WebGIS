import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getApiStorageScope } from '@/services/_http'
import { setActiveStorageUserId, writeScopedItem } from '@/services/user-local-isolation'
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
import { toRemotePayload, type ScopedWorkspaceBundle } from '@/stores/layers/workspace-remote-payload'

const fetchWorkspaceMock = vi.fn()
const pushWorkspaceMock = vi.fn()
const reloadMock = vi.fn()

vi.mock('@/services/workspace-api', () => ({
  fetchWorkspace: (...args: unknown[]) => fetchWorkspaceMock(...(args as [])),
  pushWorkspace: (...args: unknown[]) => pushWorkspaceMock(...(args as [])),
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

const MARKER_KEY = 'geo:workspace-sync-user:v1'
const TEST_ORIGIN = 'http://test.local'

function syncMarker(username: string): string {
  return `${username}|${getApiStorageScope()}`
}

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
    location: { reload: reloadMock, origin: TEST_ORIGIN },
  })
  return storage
}

function snapshot(savedAt: string, tag = 'koppen', apiScope = TEST_ORIGIN): WorkspaceSnapshot {
  return {
    version: 1,
    savedAt,
    apiScope,
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

function scopeBundle(
  savedAt: string,
  tag = 'koppen',
  apiScope = TEST_ORIGIN,
): ScopedWorkspaceBundle {
  return {
    snapshot: snapshot(savedAt, tag, apiScope),
    dismissed: {
      overlayLayerIds: [],
      catalogIds: [],
      runIds: [],
      vectorBackendLayerIds: [],
    },
  }
}

function remoteState(
  revision: number,
  scopes: Record<string, ScopedWorkspaceBundle> | null,
): RemoteWorkspaceState {
  return {
    revision,
    updated_at: '2026-08-17T00:00:00Z',
    payload: scopes ? toRemotePayload({ version: 2, scopes }) : null,
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
    setActiveStorageUserId(null)
    store = mockBrowserStorage()
  })

  afterEach(() => {
    resetWorkspaceSyncState()
    setActiveStorageUserId(null)
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

  it('同账号且远端当前 scope 较新：接管远端快照', async () => {
    authUserMock = { id: 1, username: 'alice', role: 'standard' }
    setActiveStorageUserId(1)
    writeScopedItem(MARKER_KEY, syncMarker('alice'))
    saveWorkspaceSnapshot(snapshot('2026-08-10T00:00:00Z', 'old'))
    const remoteDismissed = {
      overlayLayerIds: ['ov-1'],
      catalogIds: ['cat-1'],
      runIds: [],
      vectorBackendLayerIds: [],
    }
    fetchWorkspaceMock.mockResolvedValue(
      remoteState(5, {
        [TEST_ORIGIN]: {
          snapshot: snapshot('2026-08-16T00:00:00Z', 'new'),
          dismissed: remoteDismissed,
        },
      }),
    )

    await syncWorkspaceOnBoot()

    expect(pushWorkspaceMock).not.toHaveBeenCalled()
    const local = loadWorkspaceSnapshot()
    expect(local?.catalogLayers?.[0]?.catalogId).toBe('new')
    expect(loadDismissedLayers().overlayLayerIds).toEqual(['ov-1'])
  })

  it('同账号且本地较新：推送 v2 分桶快照', async () => {
    authUserMock = { id: 1, username: 'alice', role: 'standard' }
    setActiveStorageUserId(1)
    writeScopedItem(MARKER_KEY, syncMarker('alice'))
    saveWorkspaceSnapshot(snapshot('2026-08-16T00:00:00Z', 'local-new'))
    fetchWorkspaceMock.mockResolvedValue(
      remoteState(3, {
        [TEST_ORIGIN]: scopeBundle('2026-08-01T00:00:00Z', 'remote-old'),
      }),
    )
    pushWorkspaceMock.mockResolvedValue({ revision: 4, updated_at: '2026-08-17T01:00:00Z' })

    await syncWorkspaceOnBoot()

    expect(pushWorkspaceMock).toHaveBeenCalledTimes(1)
    const [payload, baseRevision] = pushWorkspaceMock.mock.calls[0]
    expect(baseRevision).toBe(3)
    expect(payload.version).toBe(2)
    expect(payload.scopes[TEST_ORIGIN].snapshot.catalogLayers[0].catalogId).toBe('local-new')
    expect(workspaceSyncStatus.value).toBe('idle')
  })

  it('账号切换且远端当前 scope 为空：清空本地工作区', async () => {
    authUserMock = { id: 2, username: 'bob', role: 'standard' }
    setActiveStorageUserId(2)
    writeScopedItem(MARKER_KEY, syncMarker('alice'))
    saveWorkspaceSnapshot(snapshot('2026-08-16T00:00:00Z', 'alice-data'))
    fetchWorkspaceMock.mockResolvedValue(remoteState(0, null))

    await syncWorkspaceOnBoot()

    expect(pushWorkspaceMock).not.toHaveBeenCalled()
    expect(loadWorkspaceSnapshot()).toBeNull()
    expect(loadDismissedLayers().overlayLayerIds).toEqual([])
  })

  it('API 入口切换：不采纳其它 scope 的快照，保留本机 localStorage', async () => {
    authUserMock = { id: 1, username: 'alice', role: 'standard' }
    setActiveStorageUserId(1)
    writeScopedItem(MARKER_KEY, syncMarker('alice').replace(TEST_ORIGIN, 'http://localhost:5175'))
    saveWorkspaceSnapshot(snapshot('2026-08-16T00:00:00Z', 'local-only'))
    const otherScopeSnap: WorkspaceSnapshot = {
      ...snapshot('2026-08-20T00:00:00Z', 'remote-from-lan'),
      apiScope: 'http://localhost:5175',
      groups: [
        {
          groupId: 'g1',
          runId: 'run-other-env',
          title: 'ω',
          status: 'computing',
          memberInstanceIds: ['inst-remote'],
          dissolvable: false,
          sourceLayerId: 'method-x',
        },
      ],
    }
    fetchWorkspaceMock.mockResolvedValue(
      remoteState(7, {
        'http://localhost:5175': {
          snapshot: otherScopeSnap,
          dismissed: {
            overlayLayerIds: [],
            catalogIds: [],
            runIds: [],
            vectorBackendLayerIds: [],
          },
        },
      }),
    )

    await syncWorkspaceOnBoot()

    expect(pushWorkspaceMock).not.toHaveBeenCalled()
    const local = loadWorkspaceSnapshot()
    expect(local?.catalogLayers?.[0]?.catalogId).toBe('local-only')
    expect(local?.groups).toEqual([])
  })

  it('API 入口切换：采纳当前 scope 分桶（若较新）', async () => {
    authUserMock = { id: 1, username: 'alice', role: 'standard' }
    setActiveStorageUserId(1)
    writeScopedItem(MARKER_KEY, syncMarker('alice').replace(TEST_ORIGIN, 'http://localhost:5175'))
    saveWorkspaceSnapshot(snapshot('2026-08-10T00:00:00Z', 'stale-local'))
    fetchWorkspaceMock.mockResolvedValue(
      remoteState(2, {
        [TEST_ORIGIN]: scopeBundle('2026-08-18T00:00:00Z', 'public-new'),
      }),
    )

    await syncWorkspaceOnBoot()

    const local = loadWorkspaceSnapshot()
    expect(local?.catalogLayers?.[0]?.catalogId).toBe('public-new')
  })

  it('本地变更防抖推送：落盘后推送 v2 合并快照', async () => {
    authUserMock = { id: 1, username: 'alice', role: 'standard' }
    setActiveStorageUserId(1)
    writeScopedItem(MARKER_KEY, syncMarker('alice'))
    fetchWorkspaceMock.mockResolvedValue(remoteState(2, null))
    await syncWorkspaceOnBoot()

    pushWorkspaceMock.mockResolvedValue({ revision: 3, updated_at: '2026-08-17T02:00:00Z' })
    saveWorkspaceSnapshot(snapshot('2026-08-17T02:30:00Z', 'edited'))
    scheduleWorkspaceSyncPush()
    await vi.advanceTimersByTimeAsync(1500)

    expect(pushWorkspaceMock).toHaveBeenCalledTimes(1)
    const [payload, baseRevision] = pushWorkspaceMock.mock.calls[0]
    expect(baseRevision).toBe(2)
    expect(payload.version).toBe(2)
    expect(payload.scopes[TEST_ORIGIN].snapshot.catalogLayers[0].catalogId).toBe('edited')
  })

  it('推送冲突且远端当前 scope 较新：接管远端并刷新页面', async () => {
    authUserMock = { id: 1, username: 'alice', role: 'standard' }
    setActiveStorageUserId(1)
    writeScopedItem(MARKER_KEY, syncMarker('alice'))
    fetchWorkspaceMock.mockResolvedValueOnce(remoteState(2, null))
    await syncWorkspaceOnBoot()

    pushWorkspaceMock.mockRejectedValueOnce(new WorkspaceConflictApiError('conflict', 9))
    fetchWorkspaceMock.mockResolvedValueOnce(
      remoteState(9, {
        [TEST_ORIGIN]: scopeBundle('2026-08-17T03:00:00Z', 'other-device'),
      }),
    )
    saveWorkspaceSnapshot(snapshot('2026-08-17T01:00:00Z', 'stale-local'))
    scheduleWorkspaceSyncPush()
    await vi.advanceTimersByTimeAsync(1500)

    expect(reloadMock).toHaveBeenCalled()
    expect(loadWorkspaceSnapshot()?.catalogLayers?.[0]?.catalogId).toBe('other-device')
  })

  it('拉取失败：进入 error 状态且不抛出（不影响 hydrate 启动）', async () => {
    authUserMock = { id: 1, username: 'alice', role: 'standard' }
    setActiveStorageUserId(1)
    writeScopedItem(MARKER_KEY, syncMarker('alice'))
    fetchWorkspaceMock.mockRejectedValue(new Error('backend offline'))

    await expect(syncWorkspaceOnBoot()).resolves.toBeUndefined()
    expect(workspaceSyncStatus.value).toBe('error')
  })
})
