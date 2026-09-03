import { describe, expect, it, vi } from 'vitest'

import { installSafeMapStyleAccess, isMapStyleAlive } from '@/components/map/map-style-guards'

describe('map-style-guards', () => {
  it('detects missing style', () => {
    expect(isMapStyleAlive(null)).toBe(false)
    expect(isMapStyleAlive({})).toBe(false)
    expect(isMapStyleAlive({ style: {} })).toBe(true)
  })

  it('getLayer returns undefined when style is cleared instead of throwing', () => {
    const map = {
      style: {
        getLayer: (id: string) => ({ id }),
      },
      getLayer(id: string) {
        return this.style.getLayer(id)
      },
      getSource() {
        return this.style
      },
      removeLayer() {
        return this
      },
      removeSource() {
        return this
      },
      getLayoutProperty() {
        return 'visible'
      },
      setLayoutProperty() {
        return this
      },
      getPaintProperty() {
        return undefined
      },
      setPaintProperty() {
        return this
      },
      moveLayer() {
        return this
      },
    }

    installSafeMapStyleAccess(map as never)
    expect(map.getLayer('a')).toEqual({ id: 'a' })

    map.style = undefined as never
    expect(() => map.getLayer('a')).not.toThrow()
    expect(map.getLayer('a')).toBeUndefined()
    expect(map.removeLayer('a')).toBe(map)
  })

  it('swallows getLayer throws when style exists but is mid-teardown', () => {
    const map = {
      style: {},
      getLayer: vi.fn(() => {
        throw new TypeError("Cannot read properties of undefined (reading 'getLayer')")
      }),
      getSource: vi.fn(),
      removeLayer: vi.fn(function (this: unknown) {
        return this
      }),
      removeSource: vi.fn(function (this: unknown) {
        return this
      }),
      getLayoutProperty: vi.fn(),
      setLayoutProperty: vi.fn(function (this: unknown) {
        return this
      }),
      getPaintProperty: vi.fn(),
      setPaintProperty: vi.fn(function (this: unknown) {
        return this
      }),
      moveLayer: vi.fn(function (this: unknown) {
        return this
      }),
    }
    installSafeMapStyleAccess(map as never)
    expect(map.getLayer('x')).toBeUndefined()
  })
})
