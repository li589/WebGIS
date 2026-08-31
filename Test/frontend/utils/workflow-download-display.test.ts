import { describe, expect, it } from 'vitest'

import {
  formatDownloadProgressDetail,
  formatSpeed,
  hasDownloadProgressDetail,
} from '@/utils/workflow-download-display'

describe('workflow-download-display', () => {
  it('formats multi_file with many items as index only', () => {
    const line = formatDownloadProgressDetail({
      download_mode: 'multi_file',
      downloaded_items: 128,
      total_items: 5000,
      downloaded_bytes: 12_300_000_000,
      speed_bps: 3_200_000,
      phase: 'downloading',
    })
    expect(line).toContain('128/5000')
    expect(line).toContain('MB/s')
    expect(line).not.toMatch(/\.HDF/)
  })

  it('formats byte_stream single file', () => {
    const line = formatDownloadProgressDetail({
      download_mode: 'byte_stream',
      current_item_name: 'SMAP_L3_SM_P_E_20251201.h5',
      downloaded_bytes: 156_000_000,
      total_bytes: 200_000_000,
      speed_bps: 1_835_008,
      phase: 'downloading',
    })
    expect(line).toContain('SMAP_L3')
    expect(line).toContain('/')
    expect(line).toContain('MB/s')
  })

  it('formats scanning phase', () => {
    expect(
      formatDownloadProgressDetail({ phase: 'scanning', total_items: 1200 }),
    ).toContain('1200')
  })

  it('hasDownloadProgressDetail detects download fields', () => {
    expect(hasDownloadProgressDetail({ downloaded_items: 1 })).toBe(true)
    expect(hasDownloadProgressDetail({ phase: 'complete' })).toBe(true)
    expect(hasDownloadProgressDetail({ chunksTotal: 10 })).toBe(false)
  })

  it('formatSpeed matches algorithm rules', () => {
    expect(formatSpeed(1_835_008)).toBe('1.8 MB/s')
  })
})
