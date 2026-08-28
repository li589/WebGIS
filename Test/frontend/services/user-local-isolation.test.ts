import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  clearUserLocalState,
  getActiveStorageUserId,
  readScopedItem,
  scopedStorageKey,
  setActiveStorageUserId,
  writeScopedItem,
} from '@/services/user-local-isolation'

const store = new Map<string, string>()
const sessionStore = new Map<string, string>()

function stubStorage(map: Map<string, string>) {
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => {
      map.set(k, v)
    },
    removeItem: (k: string) => {
      map.delete(k)
    },
    clear: () => {
      map.clear()
    },
  }
}

describe('user-local-isolation', () => {
  beforeEach(() => {
    store.clear()
    sessionStore.clear()
    vi.stubGlobal('localStorage', stubStorage(store))
    vi.stubGlobal('sessionStorage', stubStorage(sessionStore))
    setActiveStorageUserId(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('scopes keys by active user id', () => {
    setActiveStorageUserId(7)
    expect(scopedStorageKey('geo:active-layers-workspace:v1')).toBe(
      'geo:active-layers-workspace:v1:u7',
    )
    writeScopedItem('geo:active-layers-workspace:v1', '{"version":1}')
    expect(localStorage.getItem('geo:active-layers-workspace:v1:u7')).toContain('"version":1')
    expect(localStorage.getItem('geo:active-layers-workspace:v1')).toBeNull()
  })

  it('migrates legacy unscoped value into scoped slot on read', () => {
    localStorage.setItem('geo:dismissed-layers:v1', '{"catalogIds":["wind-field"]}')
    setActiveStorageUserId(3)
    const value = readScopedItem('geo:dismissed-layers:v1')
    expect(value).toContain('wind-field')
    expect(localStorage.getItem('geo:dismissed-layers:v1:u3')).toContain('wind-field')
    expect(localStorage.getItem('geo:dismissed-layers:v1')).toBeNull()
  })

  it('clearUserLocalState drops sensitive keys and legacy geo keys', () => {
    setActiveStorageUserId(9)
    writeScopedItem('cgda.settings_ui', '{"agentCompanion":true}')
    localStorage.setItem('cgda.backend_write_api_key', 'secret')
    localStorage.setItem('geo:active-layers-workspace:v1', 'legacy-snap')
    writeScopedItem('geo:active-layers-workspace:v1', 'user-snap')

    clearUserLocalState(9)

    expect(localStorage.getItem('cgda.settings_ui')).toBeNull()
    expect(localStorage.getItem('cgda.settings_ui:u9')).toBeNull()
    expect(localStorage.getItem('cgda.backend_write_api_key')).toBeNull()
    expect(localStorage.getItem('geo:active-layers-workspace:v1')).toBeNull()
    // Scoped workspace retained for re-login of same user
    expect(localStorage.getItem('geo:active-layers-workspace:v1:u9')).toBe('user-snap')
    expect(getActiveStorageUserId()).toBe(9)
  })

  it('different users do not share scoped workspace', () => {
    setActiveStorageUserId(1)
    writeScopedItem('geo:active-layers-workspace:v1', 'alice')
    setActiveStorageUserId(2)
    writeScopedItem('geo:active-layers-workspace:v1', 'bob')
    setActiveStorageUserId(1)
    expect(readScopedItem('geo:active-layers-workspace:v1')).toBe('alice')
    setActiveStorageUserId(2)
    expect(readScopedItem('geo:active-layers-workspace:v1')).toBe('bob')
  })
})
