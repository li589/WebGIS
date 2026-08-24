/**
 * 图层库卡片徽标链回归锁（2026-08-25 刷新后全库假「已添加」报障）。
 *
 * 根因：UX 简化时把状态徽标从 add-btn 的 v-if 链上拆成独立 v-if——
 * 「已添加」无条件渲染（无论是否添加）。本测试直接锁模板结构语义：
 * 徽标必须 v-else-if/v-else 挂在按钮链上。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const componentPath = resolve(
  __dirname,
  '../../../../Code/frontend/src/components/layer-sidebar/LayerSidebarLibrary.vue',
)
const template = readFileSync(componentPath, 'utf-8')

describe('LayerSidebarLibrary 徽标链结构', () => {
  it('失败徽标必须 v-else-if（挂在 add-btn 的 v-if 链上）', () => {
    expect(template).toContain(
      "v-else-if=\"getCatalogJobStatus(effectiveSourceId(item)) === 'failed'\"",
    )
    // 独立 v-if 的失败徽标 = 徽标链断裂 = 全库假「已添加」
    expect(template).not.toContain(
      "v-if=\"getCatalogJobStatus(effectiveSourceId(item)) === 'failed'\"",
    )
  })

  it('「已添加」必须是 v-else（链尾）而非独立 v-if', () => {
    expect(template).toContain('v-else class="added-label"')
    expect(template).not.toContain('v-if class="added-label"')
  })

  it('add-btn 保留 v-if=!isAdded（链头）', () => {
    expect(template).toMatch(/<button[^>]*v-if="!isAdded\(effectiveSourceId\(item\)\)"/s)
  })
})
