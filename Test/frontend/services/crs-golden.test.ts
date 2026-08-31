/**
 * 前后端 CRS golden（架构审查 P3-5）。
 *
 * 夹具 `fixtures/crs-golden.json` 由后端 pyproj（权威层）生成；本测试用
 * 前端 proj4 交互层（crs-transformer.transformPoint）复现同一批点对。
 * 容差：投影坐标 0.5m（相对）/ 地理坐标 1e-6° —— 锁的是**定义/轴序/基准
 * 漂移**（如 6933 角点改椭球、axis order 混淆），不是位级一致。
 *
 * 再生成夹具：仓库根运行
 * `Env/Python312/python.exe` 执行 Test/frontend/fixtures 的生成脚本逻辑
 * （见夹具 `_comment` / `generator` 字段），提交时注明 pyproj 版本。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { transformPoint } from '@/services/crs'

interface GoldenCase {
  src: string
  tgt: string
  input: [number, number]
  expected: [number, number]
}

const fixturePath = resolve(__dirname, '../fixtures/crs-golden.json')
const fixture = JSON.parse(readFileSync(fixturePath, 'utf-8')) as {
  generator: string
  cases: GoldenCase[]
}

/** 投影坐标（米制目标）用米级容差；地理坐标（度制目标）用度级容差 */
function toleranceFor(targetCrs: string): number {
  return targetCrs === 'EPSG:4326' || targetCrs === 'EPSG:4490' ? 1e-6 : 0.5
}

describe('前后端 CRS golden：proj4 复现 pyproj 基准', () => {
  it('夹具已加载且覆盖全部计划投影对', () => {
    expect(fixture.cases.length).toBeGreaterThan(50)
    const pairs = new Set(fixture.cases.map((c) => `${c.src}->${c.tgt}`))
    for (const pair of [
      'EPSG:4326->EPSG:3857',
      'EPSG:3857->EPSG:4326',
      'EPSG:4326->EPSG:6933',
      'EPSG:6933->EPSG:4326',
      'EPSG:4326->EPSG:6931',
      'EPSG:4326->EPSG:32650',
      'EPSG:4326->EPSG:4490',
      'EPSG:4326->EPSG:3408',
    ]) {
      expect(pairs.has(pair)).toBe(true)
    }
  })

  for (const c of fixture.cases) {
    it(`${c.src}→${c.tgt} (${c.input.join(', ')})`, () => {
      const [lng, lat] = c.input
      const [x, y] = transformPoint(lng, lat, c.src, c.tgt)
      const tol = toleranceFor(c.tgt)
      expect(x).toBeCloseTo(c.expected[0], tol < 1 ? 6 : 6)
      // 米制容差用绝对差；度制用 toCloseTo（~1e-6 度）
      if (tol >= 0.5) {
        expect(Math.abs(x - c.expected[0])).toBeLessThanOrEqual(
          Math.max(tol, tol * Math.max(1, Math.abs(c.expected[0])) * 1e-6),
        )
        expect(Math.abs(y - c.expected[1])).toBeLessThanOrEqual(
          Math.max(tol, tol * Math.max(1, Math.abs(c.expected[1])) * 1e-6),
        )
      } else {
        expect(x).toBeCloseTo(c.expected[0], 6)
        expect(y).toBeCloseTo(c.expected[1], 6)
      }
    })
  }
})
