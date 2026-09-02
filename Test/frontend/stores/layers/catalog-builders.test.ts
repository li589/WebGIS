/**
 * 图层平台 P1：catalog-builders 运行时分组支持测试。
 *
 * 覆盖：
 * - buildCategoryIndex：按列表顺序构建索引（种子⊕自建混合）；
 * - resolveCategory：knownCategoryIds 传入时自建分组 id 有效（不再回落 research-group）；
 * - buildRuntimeLayerLibraryItem：自定义分组 accent 样式从运行时分组表解析。
 */
import { describe, expect, it } from 'vitest'

import {
  buildCategoryIndex,
  buildRuntimeLayerLibraryItem,
  resolveCategory,
} from '@/stores/layers/catalog-builders'
import type { LayerDescriptor } from '@/services/runtime-api'
import type { LayerCategory } from '@/stores/layers/types'

function makeDescriptor(category: string): LayerDescriptor {
  return {
    layer_id: 'test-layer',
    display_name: '测试图层',
    category,
  } as unknown as LayerDescriptor
}

const RUNTIME_CATEGORIES: LayerCategory[] = [
  { id: 'weather', name: '在线天气', icon: 'W', accentColor: '#67d4ff', chipTone: 'rgba(1,1,1,.1)' },
  { id: 'lab-custom', name: '课题组专用', icon: 'B', accentColor: '#7fd99a', chipTone: 'rgba(2,2,2,.1)', isCustom: true },
]

describe('buildCategoryIndex：运行时分组排序索引', () => {
  it('按列表顺序构建（自建分组可与种子混排）', () => {
    const index = buildCategoryIndex(RUNTIME_CATEGORIES)
    expect(index.get('weather')).toBe(0)
    expect(index.get('lab-custom')).toBe(1)
    expect(index.size).toBe(2)
  })
})

describe('resolveCategory：自建分组 id 有效性', () => {
  it('静态口径：未知 id 回落 research-group（兼容旧逻辑）', () => {
    expect(resolveCategory(makeDescriptor('lab-custom'))).toBe('research-group')
  })

  it('传入 knownCategoryIds 时自建分组 id 直接生效', () => {
    const ids = new Set(RUNTIME_CATEGORIES.map((c) => c.id))
    expect(resolveCategory(makeDescriptor('lab-custom'), undefined, ids)).toBe('lab-custom')
    expect(resolveCategory(makeDescriptor('weather'), undefined, ids)).toBe('weather')
  })

  it('传入 knownCategoryIds 时真正未知的 id 仍回落', () => {
    const ids = new Set(['weather'])
    expect(resolveCategory(makeDescriptor('no-such-group'), undefined, ids)).toBe('research-group')
  })
})

describe('buildRuntimeLayerLibraryItem：运行时分组样式解析', () => {
  it('自建分组图层的 accent 色取自运行时分组表', () => {
    const item = buildRuntimeLayerLibraryItem(makeDescriptor('lab-custom'), RUNTIME_CATEGORIES)
    expect(item.category).toBe('lab-custom')
    // 无 presentation/静态兜底时，取分组 accentColor
    expect(item.accentColor).toBe('#7fd99a')
    expect(item.chipTone).toBe('rgba(2,2,2,.1)')
  })

  it('未传运行时分组表时保持旧兜底行为', () => {
    const item = buildRuntimeLayerLibraryItem(makeDescriptor('lab-custom'))
    expect(item.category).toBe('research-group')
  })
})
