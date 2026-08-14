#!/usr/bin/env node
/**
 * migrate-tokens.mjs — 自动将硬编码 hex/rgba 替换为 var(--token)
 *
 * 仅替换在 token-map 中有精确匹配的值。不匹配的值保持原样。
 *
 * 用法：
 *   node scripts/migrate-tokens.mjs <file-or-directory>
 *   node scripts/migrate-tokens.mjs src/components/info-panel/InfoPanel.styles.css
 *   node scripts/migrate-tokens.mjs src/components/
 */

import { readFileSync, writeFileSync, readdirSync, statSync, existsSync } from 'fs'
import { join, relative, dirname } from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const FRONTEND_ROOT = join(__dirname, '..')

// ═══ 豁免清单（与 audit-ui-tokens.mjs 一致 + catalog.ts 数据色） ═══
const EXEMPT_PATHS = [
  'src/components/map/weather-render.ts',
  'src/components/map/layer-symbology.ts',
  'src/components/map/wind-particle-webgl-shaders.ts',
  'src/components/map/scalar-field-webgl-texture.ts',
  'src/components/map/scalar-field-webgl-shaders.ts',
  'src/components/map/scalar-field-webgl-texture.ts',
  'src/components/map/scalar-field-webgl-renderer.ts',
  'src/components/map/scalar-field-webgl-controller.ts',
  'src/components/workflow/litegraph-ui-overrides.css',
  'src/styles/tokens.css',
  'src/styles/token-map.ts',
  'src/stores/layers/catalog.ts',
]

// ═══ hex → token 映射 ═══
const HEX_MAP = {
  // ── 文本（亮色，暗色主题） ──
  f0faff: '--text-strong',
  e8f3fc: '--text-strong',
  edf6ff: '--text-strong',
  f0f7ff: '--text-strong',
  d8e6f5: '--text-primary',
  d7e6f5: '--text-primary',
  eaf3fb: '--text-primary',
  c8dff0: '--text-primary',
  c5d8ea: '--text-primary',
  dfeefe: '--text-primary',
  d5e5f5: '--text-primary',
  d9ebfb: '--text-primary',
  '9fb6cc': '--text-secondary',
  '94a3b8': '--text-secondary',
  '9ec4e0': '--text-secondary',
  bfd3e6: '--text-secondary',
  c4d6e8: '--text-secondary',
  '64748b': '--text-secondary',
  '8aa8bf': '--text-muted',
  '8cb5d9': '--text-muted',
  '7f93a9': '--text-muted',
  '8aa0b4': '--text-muted',
  '9eb3c8': '--text-muted',
  '8aa0b6': '--text-muted',
  '7f96ab': '--text-muted',
  '8aa2bd': '--text-muted',
  '6e8ba0': '--text-faint',
  '6a8094': '--text-faint',
  '5a7080': '--text-disabled',
  // ── 品牌 / 强调 ──
  '5ad5ff': '--accent',
  '38bdf8': '--accent',
  '4fc3f7': '--accent',
  '0a84ff': '--accent',
  '88dfff': '--accent-strong',
  a8e8ff: '--accent-strong',
  ffc878: '--accent-warm',
  ffd38a: '--accent-warm',
  '2f7eff': '--accent-blue-deep',
  // ── 语义色 ──
  '9ff8cf': '--success',
  '7ee0a8': '--success',
  '72ffcf': '--success',
  '78ffa0': '--success',
  ffb070: '--warning',
  ffb84d: '--warning',
  ffd166: '--warning',
  ff8c64: '--danger',
  ff8a8a: '--danger',
  ff9999: '--danger',
  ffb0b0: '--danger',
  ff7b7b: '--danger',
  ff9b9b: '--danger',
  ffb4a8: '--danger',
  // ── 表面层 ──
  '020814': '--surface-base',
  '040c17': '--surface-sunken',
  '08111f': '--surface-1',
  '07111e': '--surface-1',
  '0d1727': '--surface-2',
  '121e30': '--surface-3',
  142842: '--surface-hover',
  f8fafc: '--surface-base',
}

// rgba → token 映射
const RGBA_MAP = {
  // ── 表面层 rgba ──
  'rgba(4,12,23,0.5)': '--surface-sunken',
  'rgba(4,12,23,0.3)': '--surface-sunken',
  'rgba(4,12,23,0.6)': '--surface-raised',
  'rgba(4,12,23,0.8)': '--surface-1',
  'rgba(8,17,31,0.86)': '--surface-1',
  'rgba(8,17,31,0.92)': '--surface-1',
  'rgba(8,17,31,0.96)': '--surface-1',
  'rgba(8,17,31,0.8)': '--surface-1',
  'rgba(13,23,39,0.92)': '--surface-2',
  'rgba(13,23,39,0.96)': '--surface-2',
  'rgba(13,23,39,0.8)': '--surface-2',
  'rgba(18,30,48,0.96)': '--surface-3',
  'rgba(20,40,66,0.98)': '--surface-hover',
  'rgba(12,22,38,0.65)': '--surface-1',
  // ── 边框 rgba(136,192,255,X) ──
  'rgba(136,192,255,0.06)': '--border-subtle',
  'rgba(136,192,255,0.08)': '--border-subtle',
  'rgba(136,192,255,0.1)': '--border-subtle',
  'rgba(136,192,255,0.12)': '--border-default',
  'rgba(136,192,255,0.14)': '--border-default',
  'rgba(136,192,255,0.16)': '--border-default',
  'rgba(136,192,255,0.18)': '--border-default',
  'rgba(136,192,255,0.2)': '--border-strong',
  'rgba(136,192,255,0.22)': '--border-strong',
  // ── 边框 rgba(90,213,255,X) ──
  'rgba(90,213,255,0.36)': '--border-strong',
  'rgba(90,213,255,0.35)': '--border-strong',
  'rgba(90,213,255,0.4)': '--border-strong',
  'rgba(90,213,255,0.5)': '--border-strong',
  'rgba(90,213,255,0.55)': '--border-strong',
  'rgba(90,213,255,0.28)': '--border-accent',
  'rgba(90,213,255,0.25)': '--border-accent',
  'rgba(90,213,255,0.3)': '--accent-border',
  'rgba(90,213,255,0.2)': '--accent-border',
  'rgba(90,213,255,0.12)': '--accent-surface',
  'rgba(90,213,255,0.18)': '--accent-surface',
  'rgba(90,213,255,0.08)': '--accent-surface',
  // ── 边框 rgba(148,163,184,X) slate ──
  'rgba(148,163,184,0.08)': '--border-subtle',
  'rgba(148,163,184,0.12)': '--border-default',
  // ── Accent rgba(10,132,255,X) ──
  'rgba(10,132,255,0.08)': '--accent-surface',
  'rgba(10,132,255,0.1)': '--accent-surface',
  'rgba(10,132,255,0.12)': '--accent-surface',
  'rgba(10,132,255,0.2)': '--accent-border',
  // ── 语义色 rgba ──
  'rgba(159,248,207,0.12)': '--success-surface',
  'rgba(159,248,207,0.3)': '--success-border',
  'rgba(114,255,207,0.08)': '--success-surface',
  'rgba(114,255,207,0.12)': '--success-surface',
  'rgba(255,176,112,0.12)': '--warning-surface',
  'rgba(255,176,112,0.3)': '--warning-border',
  'rgba(255,140,100,0.12)': '--danger-surface',
  'rgba(255,140,100,0.3)': '--danger-border',
  'rgba(255,100,100,0.16)': '--danger-surface',
}

function normalizeHex(input) {
  const cleaned = input.replace(/^#/, '').toLowerCase()
  if (/^[0-9a-f]{6}$/.test(cleaned)) return cleaned
  if (/^[0-9a-f]{3}$/.test(cleaned)) {
    return cleaned
      .split('')
      .map((c) => c + c)
      .join('')
  }
  if (/^[0-9a-f]{8}$/.test(cleaned)) return cleaned.slice(0, 6)
  return null
}

function normalizeRgba(input) {
  const match = input.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)/i)
  if (!match) return null
  const [, r, g, b, a] = match
  if (a !== undefined) return `rgba(${r},${g},${b},${a})`
  return `rgba(${r},${g},${b},1)`
}

function isExempt(filePath) {
  const normalized = filePath.replace(/\\/g, '/')
  return EXEMPT_PATHS.some((p) => normalized.endsWith(p))
}

function findFiles(dir, exts, results = []) {
  if (!existsSync(dir)) return results
  const entries = readdirSync(dir)
  for (const entry of entries) {
    const fullPath = join(dir, entry)
    const stat = statSync(fullPath)
    if (stat.isDirectory()) {
      if (entry === 'node_modules' || entry === 'dist' || entry === '.git') continue
      findFiles(fullPath, exts, results)
    } else {
      if (exts.some((ext) => entry.endsWith(ext))) {
        results.push(fullPath)
      }
    }
  }
  return results
}

function migrateFile(filePath) {
  const relPath = relative(FRONTEND_ROOT, filePath)
  if (isExempt(relPath)) {
    return { file: relPath, replaced: 0, skipped: 'exempt' }
  }

  const content = readFileSync(filePath, 'utf-8')
  let replaced = 0
  let result = content

  // 替换 hex 值（仅替换在 CSS 属性值位置的 hex，不替换在 var() 内的）
  // 匹配: #hex 或 #hexhex 但不在 var() 内
  const hexRegex = /#([0-9a-fA-F]{3,8})\b/g
  result = result.replace(hexRegex, (fullMatch) => {
    const hex = normalizeHex(fullMatch)
    if (!hex) return fullMatch
    const token = HEX_MAP[hex]
    if (!token) return fullMatch
    replaced++
    return `var(${token})`
  })

  // 替换 rgba 值
  const rgbaRegex = /rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*(?:,\s*[\d.]+\s*)?\)/gi
  result = result.replace(rgbaRegex, (fullMatch) => {
    const normalized = normalizeRgba(fullMatch)
    if (!normalized) return fullMatch
    const token = RGBA_MAP[normalized]
    if (!token) return fullMatch
    replaced++
    return `var(${token})`
  })

  if (replaced > 0) {
    writeFileSync(filePath, result, 'utf-8')
  }

  return { file: relPath, replaced }
}

// ═══ 主函数 ═══
function main() {
  const target = process.argv[2]
  if (!target) {
    console.error('Usage: node scripts/migrate-tokens.mjs <file-or-directory>')
    process.exit(1)
  }

  const absTarget = join(FRONTEND_ROOT, target)
  if (!existsSync(absTarget)) {
    console.error(`Path not found: ${absTarget}`)
    process.exit(1)
  }

  const stat = statSync(absTarget)
  let files
  if (stat.isDirectory()) {
    files = findFiles(absTarget, ['.vue', '.ts', '.css'])
  } else {
    files = [absTarget]
  }

  let totalReplaced = 0
  let filesModified = 0
  for (const file of files) {
    const result = migrateFile(file)
    if (result.replaced > 0) {
      console.log(`  ${result.file}: ${result.replaced} replacements`)
      totalReplaced += result.replaced
      filesModified++
    }
  }

  console.log(`\n总计: ${totalReplaced} 处替换 / ${filesModified} 文件`)
}

main()
