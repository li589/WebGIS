/**
 * Browser-local preferences for settings (not server secrets history).
 * Write API key: localStorage primary, sessionStorage legacy fallback.
 */

const WRITE_KEY_LOCAL = 'cgda.backend_write_api_key'
const WRITE_KEY_SESSION = 'cgda.backend_write_api_key'
const API_KEY_PREFS = 'cgda.api_key_prefs'
const SETTINGS_UI = 'cgda.settings_ui'

export interface ApiKeyLocalPref {
  lastRestoredHistoryId?: number | null
  collapsedHistory?: boolean
  lastLabel?: string
}

export type ApiKeyPrefsMap = Record<string, ApiKeyLocalPref>

export interface SettingsUiLocal {
  activeTab?: string
}

function safeGet(storage: Storage, key: string): string | null {
  try {
    return storage.getItem(key)
  } catch {
    return null
  }
}

function safeSet(storage: Storage, key: string, value: string): void {
  try {
    storage.setItem(key, value)
  } catch {
    // private mode / quota
  }
}

function safeRemove(storage: Storage, key: string): void {
  try {
    storage.removeItem(key)
  } catch {
    // ignore
  }
}

/** Prefer localStorage; migrate legacy sessionStorage on first read. */
export function getLocalWriteApiKey(): string | null {
  const fromLocal = safeGet(localStorage, WRITE_KEY_LOCAL)?.trim()
  if (fromLocal) return fromLocal
  const fromSession = safeGet(sessionStorage, WRITE_KEY_SESSION)?.trim()
  if (fromSession) {
    safeSet(localStorage, WRITE_KEY_LOCAL, fromSession)
    return fromSession
  }
  return null
}

export function setLocalWriteApiKey(key: string | null): void {
  if (!key || !key.trim()) {
    safeRemove(localStorage, WRITE_KEY_LOCAL)
    safeRemove(sessionStorage, WRITE_KEY_SESSION)
    return
  }
  const trimmed = key.trim()
  safeSet(localStorage, WRITE_KEY_LOCAL, trimmed)
  // Keep session mirror for older code paths during transition
  safeSet(sessionStorage, WRITE_KEY_SESSION, trimmed)
}

export function clearLocalWriteApiKey(): void {
  setLocalWriteApiKey(null)
}

export function hasLocalWriteApiKey(): boolean {
  return Boolean(getLocalWriteApiKey())
}

export function loadApiKeyPrefs(): ApiKeyPrefsMap {
  const raw = safeGet(localStorage, API_KEY_PREFS)
  if (!raw) return {}
  try {
    const parsed = JSON.parse(raw) as ApiKeyPrefsMap
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

export function saveApiKeyPrefs(prefs: ApiKeyPrefsMap): void {
  safeSet(localStorage, API_KEY_PREFS, JSON.stringify(prefs))
}

export function getApiKeyPref(keyName: string): ApiKeyLocalPref {
  return loadApiKeyPrefs()[keyName] ?? {}
}

export function patchApiKeyPref(keyName: string, patch: Partial<ApiKeyLocalPref>): ApiKeyLocalPref {
  const all = loadApiKeyPrefs()
  const next = { ...(all[keyName] ?? {}), ...patch }
  all[keyName] = next
  saveApiKeyPrefs(all)
  return next
}

export function loadSettingsUiLocal(): SettingsUiLocal {
  const raw = safeGet(localStorage, SETTINGS_UI)
  if (!raw) return {}
  try {
    return (JSON.parse(raw) as SettingsUiLocal) ?? {}
  } catch {
    return {}
  }
}

export function saveSettingsUiLocal(ui: SettingsUiLocal): void {
  safeSet(localStorage, SETTINGS_UI, JSON.stringify(ui))
}

/** Clear local preferences only — does not touch server-side key history. */
export function clearAllSettingsLocalPrefs(): void {
  safeRemove(localStorage, API_KEY_PREFS)
  safeRemove(localStorage, SETTINGS_UI)
  // Keep write key unless caller also clears it
}
