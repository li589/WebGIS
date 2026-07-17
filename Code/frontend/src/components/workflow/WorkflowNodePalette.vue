<script setup lang="ts">
/**
 * WorkflowNodePalette.vue
 *
 * 节点面板：显示所有可用的节点模板，支持搜索、引擎过滤、分类折叠、收藏夹、最近使用。
 * 用户可以点击节点添加到画布，或拖拽到画布上。
 */
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useWorkflowDefinitionsStore } from '../../stores/workflow-definitions'
import type { NodeTemplate } from '../../services/workflow-definition-api'

const emit = defineEmits<{
  addNode: [template: NodeTemplate]
}>()

const store = useWorkflowDefinitionsStore()
const { nodeTemplates, templatesByCategory } = storeToRefs(store)

const searchQuery = ref('')
const activeEngineFilter = ref<string>('all')
const collapsedCategories = ref<Set<string>>(new Set())

// ─── localStorage 持久化：收藏夹/最近使用/折叠状态 ─────────────────────────
const FAVORITES_KEY = 'workflow_node_favorites'
const RECENT_KEY = 'workflow_node_recent'
const COLLAPSED_KEY = 'workflow_node_collapsed_categories'

function loadFromStorage<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return fallback
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

function saveToStorage(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // 静默失败：localStorage 满或禁用时不影响主流程
  }
}

// 收藏夹：存储 node.type 集合
const favorites = ref<Set<string>>(new Set(loadFromStorage<string[]>(FAVORITES_KEY, [])))

// 最近使用：最多 10 个 node.type
const recentTypes = ref<string[]>(loadFromStorage<string[]>(RECENT_KEY, []))

// 折叠分类：初始化时从 localStorage 读取
const savedCollapsed = loadFromStorage<string[]>(COLLAPSED_KEY, [])
collapsedCategories.value = new Set(savedCollapsed)

// 监听折叠状态变化，持久化
watch(
  collapsedCategories,
  (set) => {
    saveToStorage(COLLAPSED_KEY, Array.from(set))
  },
  { deep: true },
)

// ─── 引擎过滤工具 ────────────────────────────────────────────────────────────
const ENGINE_FILTERS: Array<{ key: string; label: string; color: string }> = [
  { key: 'all', label: '全部', color: '#88dfff' },
  { key: 'weather', label: '天气', color: '#ffb84d' },
  { key: 'python_provider', label: 'Python', color: '#78ffa0' },
  { key: 'gee', label: 'GEE', color: '#5ad5ff' },
  { key: 'common', label: '通用', color: '#88dfff' },
]

function getEngineOfNode(type: string): string {
  if (type.startsWith('weather/')) return 'weather'
  if (type.startsWith('python_provider/')) return 'python_provider'
  if (type.startsWith('gee/')) return 'gee'
  return 'common'
}

function getEngineAccentColor(nodeType: string): string {
  const engine = getEngineOfNode(nodeType)
  const found = ENGINE_FILTERS.find((f) => f.key === engine)
  return found?.color ?? '#88dfff'
}

// ─── 过滤后的模板（按引擎 + 搜索关键词） ────────────────────────────────────
const filteredTemplatesByCategory = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  const engineFilter = activeEngineFilter.value
  const result: Record<string, NodeTemplate[]> = {}

  for (const [category, templates] of Object.entries(templatesByCategory.value)) {
    const filtered = templates.filter((t) => {
      // 引擎过滤
      if (engineFilter !== 'all' && getEngineOfNode(t.type) !== engineFilter) return false
      // 搜索过滤
      if (query) {
        const matched =
          t.title.toLowerCase().includes(query)
          || t.type.toLowerCase().includes(query)
          || t.description.toLowerCase().includes(query)
        if (!matched) return false
      }
      return true
    })
    if (filtered.length > 0) result[category] = filtered
  }
  return result
})

// ─── 收藏夹节点列表 ──────────────────────────────────────────────────────────
const favoriteTemplates = computed(() => {
  if (favorites.value.size === 0) return []
  return nodeTemplates.value.filter((t) => favorites.value.has(t.type))
})

// ─── 最近使用节点列表 ────────────────────────────────────────────────────────
const recentTemplates = computed(() => {
  if (recentTypes.value.length === 0) return []
  const result: NodeTemplate[] = []
  for (const type of recentTypes.value) {
    const tpl = nodeTemplates.value.find((t) => t.type === type)
    if (tpl) result.push(tpl)
  }
  return result
})

// ─── 事件处理 ────────────────────────────────────────────────────────────────
function toggleCategory(category: string) {
  if (collapsedCategories.value.has(category)) {
    collapsedCategories.value.delete(category)
  } else {
    collapsedCategories.value.add(category)
  }
  // 触发 Set 引用变化以激活 watch（Set 内部变化不会触发 deep watch）
  collapsedCategories.value = new Set(collapsedCategories.value)
}

function getCategoryLabel(category: string): string {
  return category
}

// 功能分类图标映射（category 字段已是人类可读中文，无需 label 映射）
const CATEGORY_ICONS: Record<string, string> = {
  '数据输入': '📂',
  '数据预处理': '🔧',
  '遥感处理': '🛰',
  '合成': '🔀',
  '反演': '📐',
  '统计分析': '📊',
  '数据融合': '🔗',
  '可视化': '📈',
  '天气-数据抓取': '☀',
  '天气-渲染': '🎨',
  '天气-处理': '⚙',
  'GEE-数据': '🌍',
  'GEE-处理': '🛠',
  'GIS工具': '🗺',
  '输出': '📤',
}

function getCategoryIcon(category: string): string {
  return CATEGORY_ICONS[category] ?? '◆'
}

function handleAddNode(template: NodeTemplate) {
  // 更新最近使用：插入头部，去重，最多 10 个
  const type = template.type
  const filtered = recentTypes.value.filter((t) => t !== type)
  filtered.unshift(type)
  recentTypes.value = filtered.slice(0, 10)
  saveToStorage(RECENT_KEY, recentTypes.value)

  emit('addNode', template)
}

function toggleFavorite(type: string) {
  const newSet = new Set(favorites.value)
  if (newSet.has(type)) {
    newSet.delete(type)
  } else {
    newSet.add(type)
  }
  favorites.value = newSet
  saveToStorage(FAVORITES_KEY, Array.from(newSet))
}

function isFavorite(type: string): boolean {
  return favorites.value.has(type)
}
</script>

<template>
  <div class="node-palette">
    <div class="palette-header">
      <span class="header-title">节点库</span>
      <span class="header-count">{{ nodeTemplates.length }}</span>
    </div>

    <div class="palette-search">
      <input
        v-model="searchQuery"
        type="text"
        class="search-input"
        placeholder="搜索节点..."
        aria-label="搜索节点"
      />
      <span v-if="searchQuery" class="search-clear" @click="searchQuery = ''">✕</span>
    </div>

    <!-- 引擎过滤标签 -->
    <div class="palette-engine-filters">
      <button
        v-for="filter in ENGINE_FILTERS"
        :key="filter.key"
        class="engine-filter-btn"
        :class="{ active: activeEngineFilter === filter.key }"
        :style="activeEngineFilter === filter.key ? { borderColor: filter.color, color: filter.color, background: filter.color + '20' } : {}"
        type="button"
        @click="activeEngineFilter = filter.key"
      >
        {{ filter.label }}
      </button>
    </div>

    <div class="palette-content">
      <!-- 收藏夹分区 -->
      <div v-if="favoriteTemplates.length && !searchQuery && activeEngineFilter === 'all'" class="category-group favorites-group">
        <button
          class="category-header"
          type="button"
          @click="toggleCategory('__favorites__')"
        >
          <span class="category-icon" aria-hidden="true">★</span>
          <span class="category-label">收藏</span>
          <span class="category-count">{{ favoriteTemplates.length }}</span>
          <span class="category-toggle" :class="{ collapsed: collapsedCategories.has('__favorites__') }">▾</span>
        </button>
        <div v-if="!collapsedCategories.has('__favorites__')" class="category-items">
          <button
            v-for="tpl in favoriteTemplates"
            :key="tpl.type"
            class="node-item"
            type="button"
            :style="{ borderLeftColor: getEngineAccentColor(tpl.type) }"
            :title="tpl.description"
            @click="handleAddNode(tpl)"
          >
            <div class="node-item-header">
              <span class="node-item-title">{{ tpl.title }}</span>
              <span class="node-item-favorite-btn favorited" title="取消收藏" @click.stop="toggleFavorite(tpl.type)">★</span>
            </div>
            <div v-if="tpl.description" class="node-item-desc">{{ tpl.description }}</div>
            <div class="node-item-ports">
              <span v-if="tpl.inputs.length" class="port-count in">{{ tpl.inputs.length }} 入</span>
              <span v-if="tpl.outputs.length" class="port-count out">{{ tpl.outputs.length }} 出</span>
            </div>
          </button>
        </div>
      </div>

      <!-- 最近使用分区 -->
      <div v-if="recentTemplates.length && !searchQuery && activeEngineFilter === 'all'" class="category-group recent-group">
        <button
          class="category-header"
          type="button"
          @click="toggleCategory('__recent__')"
        >
          <span class="category-icon" aria-hidden="true">🕐</span>
          <span class="category-label">最近使用</span>
          <span class="category-count">{{ recentTemplates.length }}</span>
          <span class="category-toggle" :class="{ collapsed: collapsedCategories.has('__recent__') }">▾</span>
        </button>
        <div v-if="!collapsedCategories.has('__recent__')" class="category-items">
          <button
            v-for="tpl in recentTemplates"
            :key="tpl.type"
            class="node-item"
            type="button"
            :style="{ borderLeftColor: getEngineAccentColor(tpl.type) }"
            :title="tpl.description"
            @click="handleAddNode(tpl)"
          >
            <div class="node-item-header">
              <span class="node-item-title">{{ tpl.title }}</span>
              <span
                class="node-item-favorite-btn"
                :class="{ favorited: isFavorite(tpl.type) }"
                :title="isFavorite(tpl.type) ? '取消收藏' : '加入收藏'"
                @click.stop="toggleFavorite(tpl.type)"
              >{{ isFavorite(tpl.type) ? '★' : '☆' }}</span>
            </div>
            <div v-if="tpl.description" class="node-item-desc">{{ tpl.description }}</div>
            <div class="node-item-ports">
              <span v-if="tpl.inputs.length" class="port-count in">{{ tpl.inputs.length }} 入</span>
              <span v-if="tpl.outputs.length" class="port-count out">{{ tpl.outputs.length }} 出</span>
            </div>
          </button>
        </div>
      </div>

      <div v-if="Object.keys(filteredTemplatesByCategory).length === 0" class="empty-hint">
        <span v-if="searchQuery || activeEngineFilter !== 'all'">无匹配节点</span>
        <span v-else>暂无可用节点</span>
      </div>

      <div
        v-for="(templates, category) in filteredTemplatesByCategory"
        :key="category"
        class="category-group"
      >
        <button
          class="category-header"
          type="button"
          @click="toggleCategory(String(category))"
        >
          <span class="category-icon" aria-hidden="true">{{ getCategoryIcon(String(category)) }}</span>
          <span class="category-label">{{ getCategoryLabel(String(category)) }}</span>
          <span class="category-count">{{ templates.length }}</span>
          <span class="category-toggle" :class="{ collapsed: collapsedCategories.has(String(category)) }">▾</span>
        </button>

        <div v-if="!collapsedCategories.has(String(category))" class="category-items">
          <button
            v-for="tpl in templates"
            :key="tpl.type"
            class="node-item"
            type="button"
            :style="{ borderLeftColor: getEngineAccentColor(tpl.type) }"
            :title="tpl.description"
            @click="handleAddNode(tpl)"
          >
            <div class="node-item-header">
              <span class="node-item-title">{{ tpl.title }}</span>
              <span
                class="node-item-favorite-btn"
                :class="{ favorited: isFavorite(tpl.type) }"
                :title="isFavorite(tpl.type) ? '取消收藏' : '加入收藏'"
                @click.stop="toggleFavorite(tpl.type)"
              >{{ isFavorite(tpl.type) ? '★' : '☆' }}</span>
            </div>
            <div class="node-item-type">{{ tpl.type }}</div>
            <div v-if="tpl.description" class="node-item-desc">{{ tpl.description }}</div>
            <div class="node-item-ports">
              <span v-if="tpl.inputs.length" class="port-count in">{{ tpl.inputs.length }} 入</span>
              <span v-if="tpl.outputs.length" class="port-count out">{{ tpl.outputs.length }} 出</span>
            </div>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.node-palette {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: rgba(8, 17, 31, 0.72);
  color: #c4d6e8;
}

.palette-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.62rem 0.72rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.1);
  font-size: 0.7rem;
  font-weight: 600;
  color: #d8e6f5;
}

.header-count {
  padding: 0.1rem 0.42rem;
  border-radius: 999px;
  background: rgba(10, 132, 255, 0.18);
  color: #5ad5ff;
  font-size: 0.58rem;
  font-weight: 700;
}

.palette-search {
  position: relative;
  padding: 0.42rem 0.62rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.06);
}

.search-input {
  width: 100%;
  padding: 0.36rem 0.52rem;
  border: 1px solid rgba(136, 192, 255, 0.14);
  border-radius: 0.42rem;
  background: rgba(4, 12, 23, 0.6);
  color: #d8e6f5;
  font: inherit;
  font-size: 0.6rem;
}

.search-input::placeholder {
  color: #5a7080;
}

.search-input:focus {
  outline: none;
  border-color: rgba(90, 213, 255, 0.4);
}

.search-clear {
  position: absolute;
  right: 0.92rem;
  top: 50%;
  transform: translateY(-50%);
  color: #5a7080;
  cursor: pointer;
  font-size: 0.62rem;
  line-height: 1;
}

/* 引擎过滤标签栏 */
.palette-engine-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.22rem;
  padding: 0.32rem 0.62rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.06);
}

.engine-filter-btn {
  padding: 0.16rem 0.42rem;
  border: 1px solid rgba(136, 192, 255, 0.14);
  border-radius: 0.32rem;
  background: transparent;
  color: #6e8ba0;
  cursor: pointer;
  font: inherit;
  font-size: 0.54rem;
  font-weight: 500;
  transition: all 0.16s ease;
}

.engine-filter-btn:hover {
  border-color: rgba(136, 192, 255, 0.32);
  color: #d8e6f5;
}

.engine-filter-btn.active {
  font-weight: 600;
}

.palette-content {
  flex: 1;
  overflow-y: auto;
  padding: 0.32rem 0;
}

.empty-hint {
  padding: 1.4rem 0.8rem;
  text-align: center;
  color: #5a7080;
  font-size: 0.62rem;
}

.category-group {
  margin-bottom: 0.16rem;
}

.category-group.favorites-group .category-header {
  color: #ffd38a;
}

.category-group.recent-group .category-header {
  color: #c084fc;
}

.category-header {
  display: flex;
  align-items: center;
  gap: 0.36rem;
  width: 100%;
  padding: 0.36rem 0.72rem;
  border: none;
  background: transparent;
  color: #8aa8bf;
  cursor: pointer;
  font: inherit;
  font-size: 0.62rem;
  font-weight: 600;
  text-align: left;
  transition: background 0.16s ease, color 0.16s ease;
}

.category-header:hover {
  background: rgba(136, 192, 255, 0.06);
  color: #d8e6f5;
}

.category-icon {
  font-size: 0.72rem;
  opacity: 0.8;
}

.category-label {
  flex: 1;
}

.category-count {
  padding: 0.04rem 0.32rem;
  border-radius: 999px;
  background: rgba(136, 192, 255, 0.08);
  color: #6e8ba0;
  font-size: 0.52rem;
  font-weight: 600;
}

.category-toggle {
  font-size: 0.6rem;
  transition: transform 0.18s ease;
}

.category-toggle.collapsed {
  transform: rotate(-90deg);
}

.category-items {
  padding: 0.16rem 0.42rem;
}

.node-item {
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
  width: 100%;
  margin-bottom: 0.18rem;
  padding: 0.36rem 0.46rem;
  border: 1px solid rgba(136, 192, 255, 0.08);
  border-left: 3px solid #88dfff;
  border-radius: 0.42rem;
  background: rgba(4, 12, 23, 0.4);
  color: #c4d6e8;
  cursor: pointer;
  font: inherit;
  text-align: left;
  transition: border-color 0.16s ease, background 0.16s ease, transform 0.12s ease;
}

.node-item:hover {
  border-color: rgba(90, 213, 255, 0.32);
  background: rgba(10, 132, 255, 0.1);
  transform: translateX(2px);
}

.node-item:active {
  transform: translateX(0);
}

.node-item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.32rem;
}

.node-item-title {
  flex: 1;
  font-size: 0.62rem;
  font-weight: 600;
  color: #d8e6f5;
}

.node-item-favorite-btn {
  flex: none;
  width: 1.1rem;
  height: 1.1rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: #5a7080;
  cursor: pointer;
  font-size: 0.72rem;
  line-height: 1;
  transition: color 0.16s ease, transform 0.12s ease;
}

.node-item-favorite-btn:hover {
  transform: scale(1.2);
}

.node-item-favorite-btn.favorited {
  color: #ffd38a;
}

.node-item-type {
  font-size: 0.52rem;
  color: #5a7080;
  font-family: 'Consolas', 'Monaco', monospace;
}

.node-item-desc {
  font-size: 0.56rem;
  color: #6e8ba0;
  line-height: 1.3;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.node-item-ports {
  display: flex;
  gap: 0.32rem;
  font-size: 0.52rem;
}

.port-count {
  padding: 0.04rem 0.28rem;
  border-radius: 0.24rem;
  background: rgba(136, 192, 255, 0.06);
  color: #6e8ba0;
}

.port-count.in {
  border-left: 2px solid rgba(90, 213, 255, 0.5);
}

.port-count.out {
  border-left: 2px solid rgba(160, 255, 180, 0.5);
}
</style>
