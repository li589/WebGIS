import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  withWriteAuthHeaders,
  setBackendWriteApiKey,
  clearBackendWriteApiKey,
} from '@/services/backend-auth'
import {
  clearLocalWriteApiKey,
  getLocalWriteApiKey,
  isWriteApiKeyPersistEnabled,
  setLocalWriteApiKey,
  setWriteApiKeyPersistEnabled,
} from '@/services/settings-local'

function makeMemoryStorage(): Storage {
  const map = new Map<string, string>()
  return {
    get length() {
      return map.size
    },
    clear() {
      map.clear()
    },
    getItem(key: string) {
      return map.has(key) ? map.get(key)! : null
    },
    key(index: number) {
      return [...map.keys()][index] ?? null
    },
    removeItem(key: string) {
      map.delete(key)
    },
    setItem(key: string, value: string) {
      map.set(key, String(value))
    },
  }
}

beforeEach(() => {
  const local = makeMemoryStorage()
  const session = makeMemoryStorage()
  vi.stubGlobal('localStorage', local)
  vi.stubGlobal('sessionStorage', session)
  vi.stubGlobal('window', { localStorage: local, sessionStorage: session })
})

afterEach(() => {
  clearBackendWriteApiKey()
  clearLocalWriteApiKey()
  vi.unstubAllGlobals()
})

describe('withWriteAuthHeaders', () => {
  it('skips GET by default', () => {
    setBackendWriteApiKey('secret')
    expect(withWriteAuthHeaders({}, 'GET')).toEqual({})
  })

  it('attaches on GET when forSensitiveGet', () => {
    setBackendWriteApiKey('secret')
    expect(withWriteAuthHeaders({}, 'GET', true)).toEqual({ 'X-Api-Key': 'secret' })
  })

  it('attaches on POST', () => {
    setBackendWriteApiKey('secret')
    expect(withWriteAuthHeaders({}, 'POST')).toEqual({ 'X-Api-Key': 'secret' })
  })
})

describe('settings-local write key persist', () => {
  it('defaults to session-only storage', () => {
    setWriteApiKeyPersistEnabled(false)
    setLocalWriteApiKey('abc')
    expect(isWriteApiKeyPersistEnabled()).toBe(false)
    expect(sessionStorage.getItem('cgda.backend_write_api_key')).toBe('abc')
    expect(localStorage.getItem('cgda.backend_write_api_key')).toBeNull()
    expect(getLocalWriteApiKey()).toBe('abc')
  })

  it('persists to localStorage when opted in', () => {
    setWriteApiKeyPersistEnabled(true)
    setLocalWriteApiKey('xyz')
    expect(localStorage.getItem('cgda.backend_write_api_key')).toBe('xyz')
    expect(sessionStorage.getItem('cgda.backend_write_api_key')).toBe('xyz')
  })

  it('marks legacy local-only key as persist=true on read', () => {
    localStorage.setItem('cgda.backend_write_api_key', 'legacy')
    expect(getLocalWriteApiKey()).toBe('legacy')
    expect(isWriteApiKeyPersistEnabled()).toBe(true)
  })
})
