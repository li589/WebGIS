#!/usr/bin/env node
/**
 * audit-ui-tokens.mjs — UI Token 审计脚本
 *
 * 扫描 src/ 下所有 .vue/.ts/.css 文件，报告：
 *   1. 硬编码 hex 颜色（排除豁免清单中的数据可视化文件）
 *   2. 低于 12px floor 的 font-size 值
 *   3. 非标准响应式断点（820/900/1100px）
 *
 * 用法：
 *   node scripts/audit-ui-tokens.mjs                 # 全量报告
 *   node scripts/audit-ui-tokens.mjs --baseline       # 基线模式（仅输出计数摘要）
 *   node scripts/audit-ui-tokens.mjs --check-font-floor # 仅检查 font-size floor
 *
 * 输出格式：文件路径:行号  值  建议Token
 */

import { readFileSync, readdirSync, statSync, existsSync } from 'fs'
import { join, relative, dirname } from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const FRONTEND_ROOT = join(__dirname, '..')
const SRC_ROOT = join(FRONTEND_ROOT, 'src')

// ═══ 豁免清单 ═══
const EXEMPT_PATHS = [
  'src/components/map/weather-render.ts',
  'src/components/map/layer-symbology.ts',
  'src/components/map/wind-particle-webgl-shaders.ts',
  'src/components/map/scalar-field-webgl-shaders.ts',
  'src/components/map/wind-particle-webgl-texture.ts',
  'src/components/map/scalar-field-webgl-texture.ts',
  'src/components/map/scalar-field-webgl-renderer.ts',
  'src/components/map/scalar-field-webgl-controller.ts',
  'src/components/workflow/litegraph-ui-overrides.css',
  'src/styles/tokens.css',
  'src/styles/token-map.ts',
]

// ═══ hex → token 映射 ═══
const HEX_TOKEN_MAP = {
  'f0faff': '--text-strong',
  'd8e6f5': '--text-primary',
  'dfeefe': '--text-primary',
  'd5e5f5': '--text-primary',
  'd9ebfb': '--text-primary',
  '9fb6cc': '--text-secondary',
  '8aa8bf': '--text-muted',
  '8cb5d9': '--text-muted',
  '6e8ba0': '--text-faint',
  '5a7080': '--text-disabled',
  '5ad5ff': '--accent',
  '88dfff': '--accent-strong',
  'ffc878': '--accent-warm',
  '9ff8cf': '--success',
  'ffb070': '--warning',
  'ff8c64': '--danger',
  '020814': '--surface-base',
  '040c17': '--surface-sunken',
  '08111f': '--surface-1',
  '0d1727': '--surface-2',
  '121e30': '--surface-3',
  '142842': '--surface-hover',
}

// ═══ 工具函数 ═══

function normalizeHex(input) {
  const cleaned = input.replace(/^#/, '').toLowerCase()
  if (/^[0-9a-f]{6}$/.test(cleaned)) return cleaned
  if (/^[0-9a-f]{3}$/.test(cleaned)) {
    return cleaned.split('').map(c => c + c).join('')
  }
  if (/^[0-9a-f]{8}$/.test(cleaned)) return cleaned.slice(0, 6)
  return null
}

function isExempt(filePath) {
  const normalized = filePath.replace(/\\/g, '/')
  return EXEMPT_PATHS.some(p => normalized.endsWith(p))
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
      if (exts.some(ext => entry.endsWith(ext))) {
        results.push(fullPath)
      }
    }
  }
  return results
}

// ═══ 审计函数 ═══

function auditHexColors(filePath, lines) {
  const findings = []
  const hexRegex = /#([0-9a-fA-F]{3,8})\b/g
  const rgbaRegex = /rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*(?:,\s*[\d.]+\s*)?\)/gi

  lines.forEach((line, idx) => {
    // 跳过注释行
    if (line.trim().startsWith('//') || line.trim().startsWith('*') || line.trim().startsWith('/*')) return

    // hex 匹配
    let match
    while ((match = hexRegex.exec(line)) !== null) {
      const fullMatch = match[0]
      const hex = normalizeHex(fullMatch)
      if (!hex) continue
      const token = HEX_TOKEN_MAP[hex]
      findings.push({
        file: relative(FRONTEND_ROOT, filePath),
        line: idx + 1,
        value: fullMatch,
        suggestion: token ? `var(${token})` : '(无精确匹配，需人工裁决)',
        type: 'hex',
      })
    }

    // rgba 匹配（仅非豁免文件）
    while ((match = rgbaRegex.exec(line)) !== null) {
      const val = match[0]
      // 跳过 box-shadow / text-shadow 中的 rgba（这些通常在 elevation token 中已定义）
      // 仅报告 <style> 段中的颜色相关属性
      if (line.includes('box-shadow') || line.includes('text-shadow')) continue
      // 检查是否为已知 token 值
      const isKnownToken = Object.values(HEX_TOKEN_MAP).some(() => false) // rgba 映射在下方
      findings.push({
        file: relative(FRONTEND_ROOT, filePath),
        line: idx + 1,
        value: val,
        suggestion: '(检查是否可用 token 替代)',
        type: 'rgba',
      })
    }
  })

  return findings
}

function auditFontSize(filePath, lines) {
  const findings = []
  // 匹配 font-size: 0.XXrem（其中 XX < 80）或 font-size: 10px/11px
  const fontRegex = /font-size:\s*(0?\.[0-7]\d*rem|0\.79\d*rem|10px|11px)/gi

  lines.forEach((line, idx) => {
    if (line.trim().startsWith('//') || line.trim().startsWith('*') || line.trim().startsWith('/*')) return
    let match
    while ((match = fontRegex.exec(line)) !== null) {
      findings.push({
        file: relative(FRONTEND_ROOT, filePath),
        line: idx + 1,
        value: match[1],
        suggestion: 'var(--font-size-caption) (0.8rem / 12px)',
        type: 'font-size',
      })
    }
  })

  return findings
}

function auditBreakpoints(filePath, lines) {
  const findings = []
  const bpRegex = /(max-width|min-width):\s*(820|900|1100)px/gi

  lines.forEach((line, idx) => {
    let match
    while ((match = bpRegex.exec(line)) !== null) {
      const px = parseInt(match[2])
      let suggestion = 'var(--bp-md) (768px)'
      if (px >= 1000) suggestion = 'var(--bp-lg) (1024px)'
      findings.push({
        file: relative(FRONTEND_ROOT, filePath),
        line: idx + 1,
        value: match[0],
        suggestion,
        type: 'breakpoint',
      })
    }
  })

  return findings
}

// ═══ 主函数 ═══

function main() {
  const args = process.argv.slice(2)
  const baselineMode = args.includes('--baseline')
  const fontFloorOnly = args.includes('--check-font-floor')

  const files = findFiles(SRC_ROOT, ['.vue', '.ts', '.css'])

  let hexFindings = []
  let fontFindings = []
  let bpFindings = []

  for (const file of files) {
    const relPath = relative(FRONTEND_ROOT, file)
    const content = readFileSync(file, 'utf-8')
    const lines = content.split('\n')

    // 断点和 font-size 在所有文件中检查
    if (!fontFloorOnly) {
      bpFindings.push(...auditBreakpoints(file, lines))
    }
    fontFindings.push(...auditFontSize(file, lines))

    // hex 仅在非豁免文件中检查
    if (!fontFloorOnly && !isExempt(relPath)) {
      hexFindings.push(...auditHexColors(file, lines))
    }
  }

  // 去重（同文件同行同值只算一次）
  const dedupe = (arr) => {
    const seen = new Set()
    return arr.filter(f => {
      const key = `${f.file}:${f.line}:${f.value}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  }

  hexFindings = dedupe(hexFindings)
  fontFindings = dedupe(fontFindings)
  bpFindings = dedupe(bpFindings)

  if (baselineMode) {
    // 基线模式：仅输出计数摘要
    console.log('═══ UI Token 审计基线 ═══')
    console.log(`硬编码 hex（排除豁免）: ${hexFindings.length} 处 / ${new Set(hexFindings.map(f => f.file)).size} 文件`)
    console.log(`低于 12px font-size: ${fontFindings.length} 处 / ${new Set(fontFindings.map(f => f.file)).size} 文件`)
    console.log(`非标断点: ${bpFindings.length} 处`)
    console.log('')

    // hex 按文件分布 Top 10
    const hexByFile = {}
    hexFindings.forEach(f => { hexByFile[f.file] = (hexByFile[f.file] || 0) + 1 })
    const sorted = Object.entries(hexByFile).sort((a, b) => b[1] - a[1]).slice(0, 10)
    console.log('hex 分布 Top 10:')
    sorted.forEach(([file, count]) => console.log(`  ${file}: ${count}`))
    return
  }

  // 详细模式
  if (!fontFloorOnly) {
    console.log('═══ 硬编码 hex 颜色 ═══')
    if (hexFindings.length === 0) {
      console.log('  (无)')
    } else {
      hexFindings.forEach(f => {
        console.log(`  ${f.file}:${f.line}  ${f.value}  → ${f.suggestion}`)
      })
    }
    console.log(`  总计: ${hexFindings.length} 处\n`)

    console.log('═══ 非标断点 ═══')
    if (bpFindings.length === 0) {
      console.log('  (无)')
    } else {
      bpFindings.forEach(f => {
        console.log(`  ${f.file}:${f.line}  ${f.value}  → ${f.suggestion}`)
      })
    }
    console.log(`  总计: ${bpFindings.length} 处\n`)
  }

  console.log('═══ 低于 12px floor 的 font-size ═══')
  if (fontFindings.length === 0) {
    console.log('  (无)')
  } else {
    const byFile = {}
    fontFindings.forEach(f => {
      if (!byFile[f.file]) byFile[f.file] = []
      byFile[f.file].push(f)
    })
    for (const [file, findings] of Object.entries(byFile)) {
      console.log(`  ${file} (${findings.length} 处):`)
      findings.forEach(f => console.log(`    L${f.line}: ${f.value}  → ${f.suggestion}`))
    }
  }
  console.log(`  总计: ${fontFindings.length} 处\n`)

  // 摘要
  console.log('═══ 摘要 ═══')
  console.log(`硬编码 hex: ${hexFindings.length} 处 / ${new Set(hexFindings.map(f => f.file)).size} 文件`)
  console.log(`低于 12px font-size: ${fontFindings.length} 处 / ${new Set(fontFindings.map(f => f.file)).size} 文件`)
  console.log(`非标断点: ${bpFindings.length} 处`)
}

main()
