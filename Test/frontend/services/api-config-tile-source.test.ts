import { describe, expect, it } from 'vitest'
import { resolveKnownTileSourceId } from '@/services/api-config'

describe('resolveKnownTileSourceId', () => {
  it('accepts known basemap ids', () => {
    expect(resolveKnownTileSourceId('tianditu-img')).toBe('tianditu-img')
    expect(resolveKnownTileSourceId('  gaode-street  ')).toBe('gaode-street')
  })

  it('migrates legacy tianditu-cva to vec', () => {
    expect(resolveKnownTileSourceId('tianditu-cva')).toBe('tianditu-vec')
  })

  it('rejects unknown or empty ids without silent fallback', () => {
    expect(resolveKnownTileSourceId('')).toBeNull()
    expect(resolveKnownTileSourceId('not-a-real-basemap')).toBeNull()
    expect(resolveKnownTileSourceId('osm')).toBeNull()
  })
})
