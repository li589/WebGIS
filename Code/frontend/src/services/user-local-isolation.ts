/**
 * Per-user browser storage isolation (same browser, multiple accounts).
 *
 * Scoped keys: `{base}:u{userId}` — legacy unscoped keys are read as fallback
 * once, then migrated/removed when a user session is active.
 */

let activeUserId: number | null = null

const LEGACY_GEO_KEYS = [
  'geo:active-layers-workspace:v1',
  'geo:dismissed-layers:v1',
  'geo:workspace-sync-user:v1',
  'geo:workflow-output-layers:v1',
  'geo:layer-display-names:v1',
  'geo:tracked-workflow-runs:v1',
  'geo:draw-draft:v1',
] as const

const LEGACY_CGDA_SENSITIVE = [
  'cgda.backend_write_api_key',
  'cgda.backend_write_api_key_persist',
  'cgda.api_key_prefs',
  'cgda.settings_ui',
] as const

export function setActiveStorageUserId(userId: number | null): void {
  activeUserId = userId
}

export function getActiveStorageUserId(): number | null {
  return activeUserId
}

export function scopedStorageKey(baseKey: string, userId: number | null = activeUserId): string {
  if (userId == null) return baseKey
  return `${baseKey}:u${userId}`
}

function safeGet(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function safeSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    // ignore
  }
}

function safeRemove(key: string): void {
  try {
    localStorage.removeItem(key)
  } catch {
    // ignore
  }
}

/** Read scoped value; optionally migrate legacy unscoped key into scoped slot. */
export function readScopedItem(
  baseKey: string,
  userId: number | null = activeUserId,
): string | null {
  if (userId == null) return safeGet(baseKey)
  const scoped = scopedStorageKey(baseKey, userId)
  const existing = safeGet(scoped)
  if (existing != null) return existing
  const legacy = safeGet(baseKey)
  if (legacy != null) {
    safeSet(scoped, legacy)
    safeRemove(baseKey)
    return legacy
  }
  return null
}

export function writeScopedItem(
  baseKey: string,
  value: string,
  userId: number | null = activeUserId,
): void {
  safeSet(scopedStorageKey(baseKey, userId), value)
}

export function removeScopedItem(baseKey: string, userId: number | null = activeUserId): void {
  safeRemove(scopedStorageKey(baseKey, userId))
  if (userId != null) safeRemove(baseKey)
}

/** Clear sensitive prefs on logout; keep scoped geo workspace for re-login. */
export function clearUserLocalState(userId: number | null): void {
  const sensitive = LEGACY_CGDA_SENSITIVE
  for (const key of sensitive) {
    if (userId != null) {
      safeRemove(scopedStorageKey(key, userId))
    }
    safeRemove(key)
    try {
      sessionStorage.removeItem(key)
      if (userId != null) sessionStorage.removeItem(scopedStorageKey(key, userId))
    } catch {
      // ignore
    }
  }
  // Drop legacy unscoped geo keys so the next account cannot hydrate them.
  for (const key of LEGACY_GEO_KEYS) {
    safeRemove(key)
  }
}
