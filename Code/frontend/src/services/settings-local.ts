/**
 * Browser-local preferences for settings (not server secrets history).
 * Write API key: sessionStorage primary; localStorage only when persist opt-in.
 * Legacy local-only keys are treated as persist=true on first read (compat).
 */

const WRITE_KEY_LOCAL = 'cgda.backend_write_api_key'
const WRITE_KEY_SESSION = 'cgda.backend_write_api_key'
const WRITE_KEY_PERSIST = 'cgda.backend_write_api_key_persist'
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
  /**
   * 地图分布淡底 / 氛围遮罩。默认开启；
   * 关闭或无可见数据图层时不盖雾/淡白层。
   */
  mapDistributionChrome?: boolean
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

export function isWriteApiKeyPersistEnabled(): boolean {
  return safeGet(localStorage, WRITE_KEY_PERSIST) === '1'
}

/** Opt-in: keep write key in localStorage across browser sessions (XSS surface). */
export function setWriteApiKeyPersistEnabled(on: boolean): void {
  if (on) {
    safeSet(localStorage, WRITE_KEY_PERSIST, '1')
    const current = getLocalWriteApiKey()
    if (current) safeSet(localStorage, WRITE_KEY_LOCAL, current)
    return
  }
  safeRemove(localStorage, WRITE_KEY_PERSIST)
  safeRemove(localStorage, WRITE_KEY_LOCAL)
}

/**
 * Prefer sessionStorage. Legacy localStorage keys without persist flag are
 * migrated and marked persist=true so existing operators keep the remembered key.
 */
export function getLocalWriteApiKey(): string | null {
  const fromSession = safeGet(sessionStorage, WRITE_KEY_SESSION)?.trim()
  if (fromSession) return fromSession

  const fromLocal = safeGet(localStorage, WRITE_KEY_LOCAL)?.trim()
  if (!fromLocal) return null

  safeSet(sessionStorage, WRITE_KEY_SESSION, fromLocal)
  if (!isWriteApiKeyPersistEnabled()) {
    // Backward compat: prior versions always persisted to localStorage.
    safeSet(localStorage, WRITE_KEY_PERSIST, '1')
  }
  return fromLocal
}

export function setLocalWriteApiKey(key: string | null): void {
  if (!key || !key.trim()) {
    safeRemove(localStorage, WRITE_KEY_LOCAL)
    safeRemove(sessionStorage, WRITE_KEY_SESSION)
    return
  }
  const trimmed = key.trim()
  safeSet(sessionStorage, WRITE_KEY_SESSION, trimmed)
  if (isWriteApiKeyPersistEnabled()) {
    safeSet(localStorage, WRITE_KEY_LOCAL, trimmed)
  } else {
    safeRemove(localStorage, WRITE_KEY_LOCAL)
  }
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

/** 合并写入 settings UI 偏好，避免切 Tab 等场景冲掉其它字段（如 mapDistributionChrome）。 */
export function saveSettingsUiLocal(ui: SettingsUiLocal): void {
  const merged: SettingsUiLocal = { ...loadSettingsUiLocal(), ...ui }
  safeSet(localStorage, SETTINGS_UI, JSON.stringify(merged))
}

/** 地图分布淡底默认开启；显式 false 时关闭。 */
export function isMapDistributionChromeEnabled(): boolean {
  return loadSettingsUiLocal().mapDistributionChrome !== false
}

const mapChromeListeners = new Set<() => void>()

export function subscribeMapDistributionChrome(listener: () => void): () => void {
  mapChromeListeners.add(listener)
  return () => {
    mapChromeListeners.delete(listener)
  }
}

export function setMapDistributionChromeEnabled(on: boolean): void {
  saveSettingsUiLocal({ ...loadSettingsUiLocal(), mapDistributionChrome: on })
  for (const listener of mapChromeListeners) {
    try {
      listener()
    } catch {
      // ignore listener errors
    }
  }
}

/** Clear local preferences only — does not touch server-side key history. */
export function clearAllSettingsLocalPrefs(): void {
  safeRemove(localStorage, API_KEY_PREFS)
  safeRemove(localStorage, SETTINGS_UI)
  // Keep write key unless caller also clears it
}
