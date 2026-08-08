import { describe, expect, it } from 'vitest'
import {
  buildImportTemporalPayload,
  guessTimeLabelFromFilename,
  normalizeYmdInput,
} from '@/utils/import-temporal'

describe('import-temporal', () => {
  it('guesses point and range from filename', () => {
    expect(guessTimeLabelFromFilename('SM_20251227.tif')?.label).toBe('20251227')
    expect(guessTimeLabelFromFilename('block_20251227_20251231.mat')?.label).toBe(
      '20251227_20251231',
    )
    expect(guessTimeLabelFromFilename('x_2025.12.03.h5')?.label).toBe('20251203')
  })

  it('normalizes ymd input', () => {
    expect(normalizeYmdInput('2025-12-27')).toBe('20251227')
    expect(normalizeYmdInput('bad')).toBeNull()
  })

  it('builds auto/static/point/range payloads', () => {
    expect(buildImportTemporalPayload({ mode: 'static' }).preview?.kind).toBe('static')
    expect(
      buildImportTemporalPayload({ mode: 'auto', fileName: 'a_20251227.tif' }).preview?.label,
    ).toBe('20251227')
    expect(
      buildImportTemporalPayload({ mode: 'point', timePoint: '2025-12-01' }).preview?.label,
    ).toBe('20251201')
    expect(
      buildImportTemporalPayload({
        mode: 'range',
        timeStart: '20251203',
        timeEnd: '20251210',
      }).preview?.label,
    ).toBe('20251203_20251210')
  })
})
