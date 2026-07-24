/**
 * Client write-auth for mutating backend endpoints (X-Api-Key).
 * Priority: localStorage (via settings-local) > sessionStorage legacy > VITE_BACKEND_API_KEY.
 */

import {
  clearLocalWriteApiKey,
  getLocalWriteApiKey,
  hasLocalWriteApiKey,
  setLocalWriteApiKey,
} from './settings-local'

export function getBackendWriteApiKey(): string | null {
  const fromLocal = getLocalWriteApiKey()
  if (fromLocal) return fromLocal
  const fromEnv = (import.meta.env.VITE_BACKEND_API_KEY as string | undefined)?.trim()
  return fromEnv || null
}

export function setBackendWriteApiKey(key: string | null): void {
  setLocalWriteApiKey(key)
}

export function clearBackendWriteApiKey(): void {
  clearLocalWriteApiKey()
}

export function hasBackendWriteApiKey(): boolean {
  return (
    hasLocalWriteApiKey() ||
    Boolean((import.meta.env.VITE_BACKEND_API_KEY as string | undefined)?.trim())
  )
}

/** Attach X-Api-Key for mutating requests when a write key is available. */
export function withWriteAuthHeaders(
  headers: Record<string, string> = {},
  method = 'GET',
): Record<string, string> {
  const upper = method.toUpperCase()
  if (upper === 'GET' || upper === 'HEAD' || upper === 'OPTIONS') {
    return headers
  }
  const key = getBackendWriteApiKey()
  if (!key) return headers
  return { ...headers, 'X-Api-Key': key }
}
