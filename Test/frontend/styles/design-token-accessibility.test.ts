/**
 * 设计系统主题对比度回归（2026-08-24 深度视觉设计）。
 *
 * 目标：防止深/浅主题关键文字、强调色、语义色与背景互相接近，
 * 造成图形/文字不可读。检查 CSS token 的 WCAG AA 基础对比度。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const TOKENS_PATH = resolve(__dirname, '../../../Code/frontend/src/styles/tokens.css')

function hexToRgb(hex: string): [number, number, number] {
  const raw = hex.replace('#', '').trim()
  const full = raw.length === 3 ? [...raw].map((c) => c + c).join('') : raw
  const n = Number.parseInt(full, 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function luminance(hex: string): number {
  const [r, g, b] = hexToRgb(hex).map((v) => {
    const c = v / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrast(a: string, b: string): number {
  const l1 = luminance(a)
  const l2 = luminance(b)
  const [hi, lo] = l1 > l2 ? [l1, l2] : [l2, l1]
  return (hi + 0.05) / (lo + 0.05)
}

function readToken(css: string, scope: string, name: string): string {
  const escapedScope = scope.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const scopeMatch = css.match(new RegExp(`${escapedScope}\\s*\\{([\\s\\S]*?)\\n\\}`))
  expect(scopeMatch, `missing scope ${scope}`).toBeTruthy()
  const match = scopeMatch![1].match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{3,6})\\b`))
  expect(match, `missing ${name} in ${scope}`).toBeTruthy()
  return match![1]
}

describe('design tokens contrast', () => {
  const css = readFileSync(TOKENS_PATH, 'utf-8')

  it.each([
    ['text-strong', 'surface-base'],
    ['text-primary', 'surface-base'],
    ['text-secondary', 'surface-base'],
    ['accent', 'surface-base'],
    ['success', 'surface-base'],
    ['warning', 'surface-base'],
    ['danger', 'surface-base'],
  ])('dark token %s contrasts with %s', (token, surface) => {
    expect(contrast(readToken(css, ':root', token), readToken(css, ':root', surface))).toBeGreaterThanOrEqual(4.5)
  })

  it.each([
    ['text-strong', 'surface-base'],
    ['text-primary', 'surface-base'],
    ['text-secondary', 'surface-base'],
    ['accent', 'surface-base'],
    ['success', 'surface-base'],
    ['warning', 'surface-base'],
    ['danger', 'surface-base'],
  ])('light token %s contrasts with %s', (token, surface) => {
    expect(contrast(readToken(css, "[data-theme='light']", token), readToken(css, "[data-theme='light']", surface))).toBeGreaterThanOrEqual(4.5)
  })

  it('dark/light surfaces are visually distinct', () => {
    expect(contrast(readToken(css, ':root', 'surface-base'), readToken(css, "[data-theme='light']", 'surface-base'))).toBeGreaterThanOrEqual(7)
  })
})
