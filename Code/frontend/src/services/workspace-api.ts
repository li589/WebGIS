/**
 * 工作区跨设备同步 API（/workspace/*）。
 *
 * payload 契约见 workspace-remote-payload.ts（v2 按 apiScope 分桶；v1 向后兼容）。
 * 乐观并发：push 携带 base_revision；409 冲突时返回服务端 revision 供 adopt/retry。
 */

import { applyApiFetchDefaults } from './http-credentials'
import { extractErrorDetail } from './http-errors'
import { resolveApiUrl } from './runtime-api'
import type { RemoteWorkspacePayload } from '../stores/layers/workspace-remote-payload'

export type { RemoteWorkspacePayload } from '../stores/layers/workspace-remote-payload'

export interface RemoteWorkspaceState {
  revision: number
  updated_at: string | null
  payload: RemoteWorkspacePayload | null
}

export class WorkspaceConflictApiError extends Error {
  readonly serverRevision: number

  constructor(message: string, serverRevision: number) {
    super(message)
    this.name = 'WorkspaceConflictApiError'
    this.serverRevision = serverRevision
  }
}

async function workspaceFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? 'GET').toUpperCase()
  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string> | undefined),
  }
  if (method !== 'GET' && method !== 'HEAD' && init?.body != null) {
    headers['Content-Type'] = headers['Content-Type'] ?? 'application/json'
  }

  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), 15_000)
  try {
    const response = await fetch(
      resolveApiUrl(path),
      applyApiFetchDefaults({ ...init, headers, signal: controller.signal }),
    )
    if (!response.ok) {
      let body: unknown = null
      try {
        body = await response.json()
      } catch {
        /* non-json error */
      }
      const detailRec = (body as { detail?: { message?: unknown; revision?: number } } | null)
        ?.detail
      const detail = extractErrorDetail(body, `workspace sync failed (${response.status})`)
      if (response.status === 409) {
        throw new WorkspaceConflictApiError(
          typeof detailRec?.message === 'string' ? detailRec.message : 'workspace conflict',
          typeof detailRec?.revision === 'number' ? detailRec.revision : -1,
        )
      }
      throw new Error(detail || `workspace sync failed (${response.status})`)
    }
    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  } finally {
    window.clearTimeout(timeoutId)
  }
}

export function fetchWorkspace(): Promise<RemoteWorkspaceState> {
  return workspaceFetch<RemoteWorkspaceState>('/workspace')
}

export function pushWorkspace(
  payload: RemoteWorkspacePayload,
  baseRevision: number | null,
): Promise<{ revision: number; updated_at: string }> {
  const body = baseRevision == null ? { payload } : { payload, base_revision: baseRevision }
  return workspaceFetch<{ revision: number; updated_at: string }>('/workspace', {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}
