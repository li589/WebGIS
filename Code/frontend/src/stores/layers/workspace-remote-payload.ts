/**
 * 远端工作区 payload：按 API 入口（apiScope）分桶，避免 localhost 与公网同账号互相冲掉图层。
 *
 * v1（legacy）：单份 snapshot + dismissed，仅对 snapshot.apiScope 匹配的入口有效。
 * v2：scopes[apiScope] = { snapshot, dismissed }，各入口独立同步。
 */
import type { DismissedLayersRegistry, WorkspaceSnapshot } from './workspace-persist'

export interface ScopedWorkspaceBundle {
  snapshot: WorkspaceSnapshot
  dismissed: DismissedLayersRegistry
}

/** 写入 /workspace 的契约（服务端不透明存储） */
export interface RemoteWorkspacePayload {
  version: 1 | 2
  /** v1 */
  snapshot?: WorkspaceSnapshot
  dismissed?: DismissedLayersRegistry | null
  /** v2 */
  scopes?: Record<string, ScopedWorkspaceBundle>
}

export interface NormalizedRemoteWorkspace {
  version: 2
  scopes: Record<string, ScopedWorkspaceBundle>
}

function emptyDismissed(): DismissedLayersRegistry {
  return { overlayLayerIds: [], catalogIds: [], runIds: [], vectorBackendLayerIds: [] }
}

export function normalizeRemotePayload(
  payload: RemoteWorkspacePayload | null | undefined,
): NormalizedRemoteWorkspace {
  if (!payload) return { version: 2, scopes: {} }
  if (payload.version === 2 && payload.scopes && typeof payload.scopes === 'object') {
    return { version: 2, scopes: { ...payload.scopes } }
  }
  if (payload.snapshot && typeof payload.snapshot === 'object') {
    const scope = String(payload.snapshot.apiScope || 'legacy-unknown')
    return {
      version: 2,
      scopes: {
        [scope]: {
          snapshot: payload.snapshot,
          dismissed: payload.dismissed ?? emptyDismissed(),
        },
      },
    }
  }
  return { version: 2, scopes: {} }
}

export function getScopeBundle(
  normalized: NormalizedRemoteWorkspace,
  apiScope: string,
): ScopedWorkspaceBundle | null {
  return normalized.scopes[apiScope] ?? null
}

export function mergeScopeBundle(
  normalized: NormalizedRemoteWorkspace,
  apiScope: string,
  bundle: ScopedWorkspaceBundle,
): NormalizedRemoteWorkspace {
  return {
    version: 2,
    scopes: {
      ...normalized.scopes,
      [apiScope]: bundle,
    },
  }
}

export function toRemotePayload(normalized: NormalizedRemoteWorkspace): RemoteWorkspacePayload {
  return { version: 2, scopes: normalized.scopes }
}
