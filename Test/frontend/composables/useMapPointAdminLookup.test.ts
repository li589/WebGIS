import { describe, expect, it } from 'vitest'

import { formatMapPointAdminLine } from '@/composables/useMapPointAdminLookup'

describe('formatMapPointAdminLine', () => {
  it('formats loading and miss states', () => {
    expect(formatMapPointAdminLine('loading', null, null)).toBe('正在解析行政区…')
    expect(formatMapPointAdminLine('miss', null, null)).toBe('行政区未命中')
  })

  it('joins state and country labels', () => {
    expect(formatMapPointAdminLine('ready', 'Samangan', 'Afghanistan')).toBe(
      'Samangan（省/州） / Afghanistan（国家）',
    )
    expect(formatMapPointAdminLine('ready', null, 'Afghanistan')).toBe('Afghanistan（国家）')
  })
})
