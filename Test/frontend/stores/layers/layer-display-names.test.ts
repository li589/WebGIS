import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  clearPersistedLayerDisplayNames,
  getPersistedLayerDisplayName,
  persistLayerDisplayName,
  resolvePersistedDisplayName,
} from '@/stores/layers/layer-display-names'

function mockBrowserStorage() {
  const store = new Map<string, string>()
  const storage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => {
      store.set(k, v)
    },
    removeItem: (k: string) => {
      store.delete(k)
    },
    clear: () => store.clear(),
  }
  vi.stubGlobal('localStorage', storage)
  vi.stubGlobal('window', { localStorage: storage })
}

describe('layer-display-names', () => {
  beforeEach(() => {
    mockBrowserStorage()
  })

  it('persists and resolves by key priority', () => {
    persistLayerDisplayName('catalog-old', '旧目录名')
    persistLayerDisplayName('inst-1', '实例名')
    expect(resolvePersistedDisplayName('inst-1', 'catalog-old')).toBe('实例名')
    expect(getPersistedLayerDisplayName('catalog-old')).toBe('旧目录名')
  })

  it('clears multiple keys at once', () => {
    persistLayerDisplayName('a', 'A')
    persistLayerDisplayName('b', 'B')
    persistLayerDisplayName('c', 'C')
    clearPersistedLayerDisplayNames(['a', 'b'])
    expect(getPersistedLayerDisplayName('a')).toBeNull()
    expect(getPersistedLayerDisplayName('b')).toBeNull()
    expect(getPersistedLayerDisplayName('c')).toBe('C')
  })
})
