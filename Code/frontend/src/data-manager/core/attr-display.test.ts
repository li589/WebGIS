import { describe, expect, it } from 'vitest'
import {
  describeSourceEncoding,
  formatAttrCell,
  sanitizeFieldName,
  sanitizeSafeText,
} from './attr-display'

describe('formatAttrCell', () => {
  it('handles null and numbers', () => {
    expect(formatAttrCell(null)).toBe('')
    expect(formatAttrCell(undefined)).toBe('')
    expect(formatAttrCell(12)).toBe('12')
    expect(formatAttrCell(1.234567891)).toBe('1.23456789')
  })

  it('keeps CJK text', () => {
    expect(formatAttrCell('基地带')).toBe('基地带')
  })

  it('surfaces replacement chars', () => {
    expect(formatAttrCell('a\uFFFDb')).toContain('�')
  })
})

describe('describeSourceEncoding', () => {
  it('summarizes meta', () => {
    const s = describeSourceEncoding({
      source_encoding: 'gbk',
      encoding_strict: true,
      encoding_sources: ['cpg'],
    })
    expect(s).toContain('gbk')
    expect(s).toContain('cpg')
  })
})

describe('safe input', () => {
  it('rejects dangerous field names', () => {
    expect(sanitizeFieldName('../x').ok).toBe(false)
    expect(sanitizeFieldName('a:b').ok).toBe(false)
    const ok = sanitizeFieldName(' 名称 ')
    expect(ok.ok).toBe(true)
    if (ok.ok) expect(ok.value).toBe('名称')
  })

  it('strips control chars from values', () => {
    const r = sanitizeSafeText('a\u0000b\nc')
    expect(r.ok).toBe(true)
    if (r.ok) expect(r.value).toBe('ab c')
  })
})
