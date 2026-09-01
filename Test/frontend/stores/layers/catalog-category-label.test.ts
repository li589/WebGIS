import { describe, expect, it } from 'vitest'

import {
  LAYER_CATEGORIES,
  applyResearchGroupCategoryLabel,
  resolveCategoryDisplayName,
} from '@/stores/layers/catalog'
import { resolveCategory } from '@/stores/layers/catalog-builders'

describe('research-group 分类显示名', () => {
  it('LAYER_CATEGORIES 中 research-group 默认显示为核心资产', () => {
    const cat = LAYER_CATEGORIES.find((c) => c.id === 'research-group')
    expect(cat?.name).toBe('核心资产')
  })

  it('applyResearchGroupCategoryLabel 覆盖 JSON 中的旧中文名', () => {
    const patched = applyResearchGroupCategoryLabel([
      { id: 'research-group', name: '课题组数据' },
      { id: 'climate', name: '气候与灾害' },
    ])
    expect(patched[0]?.name).toBe('核心资产')
    expect(patched[1]?.name).toBe('气候与灾害')
  })

  it('resolveCategoryDisplayName 解析 research-group', () => {
    expect(resolveCategoryDisplayName('research-group')).toBe('核心资产')
  })

  it('历史中文类别别名归并到 research-group', () => {
    expect(resolveCategory({ category: '课题组数据' } as never)).toBe('research-group')
    expect(resolveCategory({ category: '科研数据' } as never)).toBe('research-group')
    expect(resolveCategory({ category: '核心资产' } as never)).toBe('research-group')
  })
})
