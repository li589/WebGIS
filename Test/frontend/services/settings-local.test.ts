import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  isMapDistributionChromeEnabled,
  loadSettingsUiLocal,
  saveSettingsUiLocal,
  setMapDistributionChromeEnabled,
} from '@/services/settings-local'

const store = new Map<string, string>()

describe('settings-local UI merge', () => {
  beforeEach(() => {
    store.clear()
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => {
        store.set(k, v)
      },
      removeItem: (k: string) => {
        store.delete(k)
      },
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('keeps mapDistributionChrome=false when only activeTab is saved', () => {
    setMapDistributionChromeEnabled(false)
    expect(isMapDistributionChromeEnabled()).toBe(false)

    // 模拟 SettingsPanel 切 Tab（合并写入 activeTab）
    saveSettingsUiLocal({ activeTab: 'api-keys' })

    expect(isMapDistributionChromeEnabled()).toBe(false)
    expect(loadSettingsUiLocal()).toMatchObject({
      activeTab: 'api-keys',
      mapDistributionChrome: false,
    })
  })

  it('defaults chrome on when unset', () => {
    expect(isMapDistributionChromeEnabled()).toBe(true)
    saveSettingsUiLocal({ activeTab: 'general' })
    expect(isMapDistributionChromeEnabled()).toBe(true)
  })
})
