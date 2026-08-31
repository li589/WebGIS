import { computed, ref, watch, type Ref } from 'vue'
import type { RuntimeLayerLibraryItem, LayerCategory } from '../../stores/layers/types'

/**
 * Extracts search and filtering logic from LayerSidebar.vue.
 *
 * Manages the library search query, category expansion state, and sub-category
 * pill filtering for the research-group category. Also prefetches weather
 * providers for visible weather layers whenever the filtered view changes.
 *
 * @param layerLibrary - ComputedRef of the full layer library items
 * @param layerCategories - Static array of layer category definitions
 * @param ensureWeatherProviders - Callback to prefetch weather providers for a catalogId
 */
export function useSidebarSearch(
  layerLibrary: Ref<RuntimeLayerLibraryItem[]>,
  layerCategories: LayerCategory[],
  ensureWeatherProviders: (catalogId: string) => Promise<void>,
) {
  const searchQuery = ref('')
  const expandedCategories = ref<Set<string>>(new Set(layerCategories.map((c) => c.id)))

  // ── Filter library items by search ────────────────────────────────────────────

  const selectedSubCategory = ref<string>('all')

  const filteredLibrary = computed(() => {
    if (!searchQuery.value.trim()) return layerLibrary.value
    const q = searchQuery.value.toLowerCase()
    return layerLibrary.value.filter(
      (item) =>
        item.name.toLowerCase().includes(q) ||
        item.category.toLowerCase().includes(q) ||
        (item.subCategory && item.subCategory.toLowerCase().includes(q)) ||
        item.sourceLabel.toLowerCase().includes(q) ||
        item.description.toLowerCase().includes(q),
    )
  })

  /** 二级分类 pills：从当前可见图层的 subCategory 去重生成（保留「全部」） */
  const researchSubCategoryPills = computed(() => {
    const values = new Set<string>()
    for (const item of filteredLibrary.value) {
      if (item.category === 'research-group' && item.subCategory?.trim()) {
        values.add(item.subCategory.trim())
      }
    }
    return ['all', ...Array.from(values).sort((a, b) => a.localeCompare(b, 'zh-CN'))]
  })

  watch(researchSubCategoryPills, (pills) => {
    if (!pills.includes(selectedSubCategory.value)) {
      selectedSubCategory.value = 'all'
    }
  })

  const filteredLibraryByCategory = computed(() => {
    const map = new Map(
      layerCategories.map((c) => [c.id, { category: c, items: [] as RuntimeLayerLibraryItem[] }]),
    )
    for (const item of filteredLibrary.value) {
      if (map.has(item.category)) {
        if (
          item.category === 'research-group' &&
          selectedSubCategory.value !== 'all' &&
          item.subCategory !== selectedSubCategory.value
        ) {
          continue
        }
        map.get(item.category)!.items.push(item)
      }
    }
    return Array.from(map.values()).filter((g) => {
      if (g.category.id === 'research-group') return true
      return g.items.length > 0
    })
  })

  function prefetchVisibleWeatherProviders() {
    for (const group of filteredLibraryByCategory.value) {
      if (group.category.id !== 'weather') continue
      for (const item of group.items) {
        void ensureWeatherProviders(item.catalogId)
      }
    }
  }

  // 仅在天气图层 catalogId 集合变化时触发预取，避免 deep watch 的性能开销
  const weatherCatalogIds = computed(() => {
    const ids: string[] = []
    for (const group of filteredLibraryByCategory.value) {
      if (group.category.id !== 'weather') continue
      for (const item of group.items) {
        ids.push(item.catalogId)
      }
    }
    return ids.join(',')
  })

  watch(weatherCatalogIds, () => prefetchVisibleWeatherProviders())

  return {
    searchQuery,
    expandedCategories,
    selectedSubCategory,
    filteredLibrary,
    researchSubCategoryPills,
    filteredLibraryByCategory,
    prefetchVisibleWeatherProviders,
  }
}
