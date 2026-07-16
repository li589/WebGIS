/**
 * Client write-auth for mutating backend endpoints (X-Api-Key).
 * Priority: sessionStorage paste > VITE_BACKEND_API_KEY.
 */

const STORAGE_KEY = 'cgda.backend_write_api_key'

export function getBackendWriteApiKey(): string | null {
  try {
    const fromSession = sessionStorage.getItem(STORAGE_KEY)?.trim()
    if (fromSession) return fromSession
  } catch {
    // ignore storage errors (private mode)
  }
  const fromEnv = (import.meta.env.VITE_BACKEND_API_KEY as string | undefined)?.trim()
  return fromEnv || null
}

export function setBackendWriteApiKey(key: string | null): void {
  try {
    if (!key || !key.trim()) {
      sessionStorage.removeItem(STORAGE_KEY)
      return
    }
    sessionStorage.setItem(STORAGE_KEY, key.trim())
  } catch {
    // ignore
  }
}

export function clearBackendWriteApiKey(): void {
  setBackendWriteApiKey(null)
}

export function hasBackendWriteApiKey(): boolean {
  return Boolean(getBackendWriteApiKey())
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
