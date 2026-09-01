/**
 * Per-user + per-API-origin browser storage isolation.
 *
 * Scoped keys: `{base}:u{userId}@{apiScope}` — legacy `u{userId}` / unscoped
 * keys are read once as fallback, then migrated when a user session is active.
 */

import { getApiStorageScope } from './_http'

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

function apiScopeSuffix(apiScope: string = getApiStorageScope()): string {
  return `@${encodeURIComponent(apiScope)}`
}

export function scopedStorageKey(
  baseKey: string,
  userId: number | null = activeUserId,
  apiScope: string = getApiStorageScope(),
): string {
  const suffix = apiScopeSuffix(apiScope)
  if (userId == null) return `${baseKey}${suffix}`
  return `${baseKey}:u${userId}${suffix}`
}

function legacyUserScopedKey(baseKey: string, userId: number): string {
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

/** Read scoped value; migrate legacy unscoped / user-only keys into scoped slot. */
export function readScopedItem(
  baseKey: string,
  userId: number | null = activeUserId,
): string | null {
  const apiScope = getApiStorageScope()
  if (userId == null) {
    const scoped = safeGet(scopedStorageKey(baseKey, null, apiScope))
    if (scoped != null) return scoped
    return safeGet(baseKey)
  }

  const primary = scopedStorageKey(baseKey, userId, apiScope)
  const existing = safeGet(primary)
  if (existing != null) return existing

  const legacyUser = safeGet(legacyUserScopedKey(baseKey, userId))
  if (legacyUser != null) {
    safeSet(primary, legacyUser)
    safeRemove(legacyUserScopedKey(baseKey, userId))
    safeRemove(baseKey)
    return legacyUser
  }

  const legacy = safeGet(baseKey)
  if (legacy != null) {
    safeSet(primary, legacy)
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
  if (userId != null) {
    safeRemove(legacyUserScopedKey(baseKey, userId))
  }
  safeRemove(baseKey)
}

/** Clear sensitive prefs on logout; keep scoped geo workspace for re-login. */
export function clearUserLocalState(userId: number | null): void {
  const sensitive = LEGACY_CGDA_SENSITIVE
  for (const key of sensitive) {
    if (userId != null) {
      safeRemove(scopedStorageKey(key, userId))
      safeRemove(legacyUserScopedKey(key, userId))
    }
    safeRemove(key)
    try {
      sessionStorage.removeItem(key)
      if (userId != null) {
        sessionStorage.removeItem(scopedStorageKey(key, userId))
        sessionStorage.removeItem(legacyUserScopedKey(key, userId))
      }
    } catch {
      // ignore
    }
  }
  // Drop legacy unscoped geo keys so the next account cannot hydrate them.
  for (const key of LEGACY_GEO_KEYS) {
    safeRemove(key)
    if (userId != null) {
      safeRemove(legacyUserScopedKey(key, userId))
    }
  }
}
