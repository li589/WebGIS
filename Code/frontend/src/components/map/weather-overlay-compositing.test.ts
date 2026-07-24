import { describe, expect, it } from 'vitest'

import { shouldYieldScalarWebGLToWind } from './weather-overlay-compositing'

describe('weather-overlay-compositing', () => {
  it('yields scalar WebGL when particle flow catalog is set and mode is particle', () => {
    expect(
      shouldYieldScalarWebGLToWind({
        enabledParticleFlowCatalogId: 'weather.wind',
        windDisplayMode: 'particle',
      }),
    ).toBe(true)
  })

  it('yields scalar WebGL when mode is streamline', () => {
    expect(
      shouldYieldScalarWebGLToWind({
        enabledParticleFlowCatalogId: 'weather.wind',
        windDisplayMode: 'streamline',
      }),
    ).toBe(true)
  })

  it('does not yield when mode is off', () => {
    expect(
      shouldYieldScalarWebGLToWind({
        enabledParticleFlowCatalogId: 'weather.wind',
        windDisplayMode: 'off',
      }),
    ).toBe(false)
  })

  it('does not yield when no particle flow catalog is enabled', () => {
    expect(
      shouldYieldScalarWebGLToWind({
        enabledParticleFlowCatalogId: null,
        windDisplayMode: 'particle',
      }),
    ).toBe(false)
  })
})
