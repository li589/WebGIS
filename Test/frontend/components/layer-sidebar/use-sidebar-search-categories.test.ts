// @vitest-environment jsdom
/**
 * 图层平台 P1：useSidebarSearch 运行时分组响应性测试。
 *
 * 分组定义改为 Ref 后：管理员在分组管理中新建/删除分组，
 * 侧栏分类列表需实时跟随（不再需要刷新页面）。
 */
import { describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'

import { useSidebarSearch } from '@/components/layer-sidebar/useSidebarSearch'
import type { LayerCategory, RuntimeLayerLibraryItem } from '@/stores/layers/types'

const STATIC_CATEGORIES: LayerCategory[] = [
  { id: 'weather', name: '在线天气', icon: 'W', accentColor: '#67d4ff', chipTone: 'rgba(0,0,0,.1)' },
]

const RUNTIME_CATEGORIES: LayerCategory[] = [
  ...STATIC_CATEGORIES,
  {
    id: 'lab-custom',
    name: '课题组专用',
    icon: 'B',
    accentColor: '#7fd99a',
    chipTone: 'rgba(0,0,0,.1)',
    isCustom: true,
  },
]

function makeLibraryItem(catalogId: string, category: string): RuntimeLayerLibraryItem {
  return {
    catalogId,
    name: `图层-${catalogId}`,
    category,
    metricLabel: '指标',
    metricUnit: '',
    metricPrecision: 1,
    updateLabel: '',
    sourceLabel: '',
    accentColor: '#fff',
    accentGlow: '',
    chipTone: '',
    sources: [],
    description: '',
    engine: '',
    sourceType: '',
    renderType: '',
    runReadiness: 'ready',
    runReadinessNotes: [],
    backendStatus: '',
    supportsTime: false,
  } as unknown as RuntimeLayerLibraryItem
}

function setup(categories: LayerCategory[], items: RuntimeLayerLibraryItem[]) {
  return useSidebarSearch(ref(items), ref(categories), vi.fn())
}

describe('useSidebarSearch：运行时分组响应性', () => {
  it('自建分组出现在侧栏分类列表（按运行时顺序）', () => {
    const search = setup(RUNTIME_CATEGORIES, [
      makeLibraryItem('a', 'weather'),
      makeLibraryItem('b', 'lab-custom'),
    ])
    const ids = search.filteredLibraryByCategory.value.map((g) => g.category.id)
    expect(ids).toEqual(['weather', 'lab-custom'])
    // 成员归组正确
    const custom = search.filteredLibraryByCategory.value.find((g) => g.category.id === 'lab-custom')
    expect(custom?.items.map((i) => i.catalogId)).toEqual(['b'])
  })

  it('分组列表变更后实时跟随（新增/删除分组）', async () => {
    const categories = ref<LayerCategory[]>(STATIC_CATEGORIES)
    const search = useSidebarSearch(
      ref([makeLibraryItem('a', 'weather'), makeLibraryItem('b', 'lab-custom')]),
      categories,
      vi.fn(),
    )
    // 初始：自建分组未加载，lab-custom 图层无分组容器
    expect(search.filteredLibraryByCategory.value.map((g) => g.category.id)).toEqual(['weather'])

    // 运行时分组加载 → 自建分组出现
    categories.value = RUNTIME_CATEGORIES
    await nextTick()
    expect(search.filteredLibraryByCategory.value.map((g) => g.category.id)).toEqual([
      'weather',
      'lab-custom',
    ])

    // 分组删除 → 容器消失，图层不显示在分类下
    categories.value = STATIC_CATEGORIES
    await nextTick()
    expect(search.filteredLibraryByCategory.value.map((g) => g.category.id)).toEqual(['weather'])
  })

  it('新增分组默认展开，删除分组从展开集合移除', async () => {
    const categories = ref<LayerCategory[]>(STATIC_CATEGORIES)
    const search = useSidebarSearch(ref([]), categories, vi.fn())
    expect(search.expandedCategories.value.has('weather')).toBe(true)

    categories.value = RUNTIME_CATEGORIES
    await nextTick()
    expect(search.expandedCategories.value.has('lab-custom')).toBe(true)

    categories.value = STATIC_CATEGORIES
    await nextTick()
    expect(search.expandedCategories.value.has('lab-custom')).toBe(false)
  })
})
