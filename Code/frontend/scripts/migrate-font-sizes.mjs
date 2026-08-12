#!/usr/bin/env node
/**
 * migrate-font-sizes.mjs — 将低于 12px floor 的 font-size 替换为 var(--font-size-caption)
 *
 * root font-size = 15px，所以 0.8rem = 12px (floor)。
 * 匹配并替换所有低于 floor 的 font-size 值：
 *   - 0.00rem ~ 0.79rem → var(--font-size-caption)
 *   - 1px ~ 11px        → var(--font-size-caption)
 *
 * 不替换：
 *   - 已使用 var() 的值
 *   - 豁免清单中的文件
 *
 * 用法：
 *   node scripts/migrate-font-sizes.mjs <file-or-directory>
 *   node scripts/migrate-font-sizes.mjs src/
 */

import { readFileSync, writeFileSync, readdirSync, statSync, existsSync } from 'fs'
import { join, relative, dirname } from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const FRONTEND_ROOT = join(__dirname, '..')

// ═══ 豁免清单 ═══
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
]

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

/**
 * 替换低于 floor 的 font-size 值。
 * 匹配模式：
 *   font-size: 0.00rem ~ 0.79rem
 *   font-size: 1px ~ 11px
 * 不匹配 var()、calc() 内的值。
 */
function migrateFile(filePath) {
  const relPath = relative(FRONTEND_ROOT, filePath)
  if (isExempt(relPath)) {
    return { file: relPath, replaced: 0, skipped: 'exempt' }
  }

  const content = readFileSync(filePath, 'utf-8')
  let replaced = 0
  let result = content

  // 匹配 font-size: 0.XXrem（其中 0.XX < 0.80）
  // 不匹配已经用 var() 的
  result = result.replace(/font-size:\s*(0\.\d+rem)/gi, (match, value) => {
    const num = parseFloat(value)
    if (num >= 0.8) return match // 在 floor 或以上，不替换
    replaced++
    return 'font-size: var(--font-size-caption)'
  })

  // 匹配 font-size: Npx（其中 N < 12）
  result = result.replace(/font-size:\s*(\d+)px/gi, (match, value) => {
    const num = parseInt(value)
    if (num >= 12) return match // 在 floor 或以上，不替换
    replaced++
    return 'font-size: var(--font-size-caption)'
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
    console.error('Usage: node scripts/migrate-font-sizes.mjs <file-or-directory>')
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
