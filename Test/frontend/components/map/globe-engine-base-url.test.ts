/**
 * Cesium base-url helper（无 DOM 副作用可单测）。
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

import { ensureCesiumBaseUrl, getCesiumBaseUrl } from '@/components/map/globe-engine/cesium/base-url'

describe('cesium base-url', () => {
  beforeEach(() => {
    vi.stubGlobal('window', { CESIUM_BASE_URL: undefined as string | undefined })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sets default /cesium/ once', () => {
    ensureCesiumBaseUrl()
    expect(getCesiumBaseUrl()).toBe('/cesium/')
    ensureCesiumBaseUrl('/other/')
    // 已设置则不覆盖
    expect(getCesiumBaseUrl()).toBe('/cesium/')
  })

  it('normalizes trailing slash', () => {
    vi.stubGlobal('window', { CESIUM_BASE_URL: undefined as string | undefined })
    ensureCesiumBaseUrl('/assets/cesium')
    expect(getCesiumBaseUrl()).toBe('/assets/cesium/')
  })
})
