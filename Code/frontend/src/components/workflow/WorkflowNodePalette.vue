<script setup lang="ts">
/**
 * WorkflowNodePalette.vue
 *
 * 节点面板：显示所有可用的节点模板，支持搜索、引擎过滤、分类折叠、收藏夹、最近使用。
 * 用户可以点击节点添加到画布，或拖拽到画布上。
 */
import { computed, ref, watch, onBeforeUnmount, toRef, type Component } from 'vue'
import {
  Star,
  Clock,
  X,
  ChevronDown,
  FolderOpen,
  Wrench,
  Satellite,
  Shuffle,
  Ruler,
  BarChart3,
  Link,
  TrendingUp,
  Sun,
  Palette,
  Settings,
  Globe,
  Map,
  Upload,
  Diamond,
} from '../ui/icons'
import { useWorkflowDefinitionsStore } from '../../stores/workflow-definitions'
import type { NodeTemplate } from '../../services/workflow-definition-api'

const emit = defineEmits<{
  addNode: [template: NodeTemplate]
}>()

const store = useWorkflowDefinitionsStore()
const nodeTemplates = toRef(store, 'nodeTemplates')
const templatesByCategory = toRef(store, 'templatesByCategory')

const searchQuery = ref('')
const activeEngineFilter = ref<string>('all')
const collapsedCategories = ref<Set<string>>(new Set())
/** 默认隐藏尚未实现的 stub 模块，避免误加入画布 */
const showStubs = ref(false)

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

/**
 * 简单防抖：延迟 ms 执行 fn；返回的句柄带 .flush() 可立即执行挂起调用。
 * 用于折叠状态持久化，避免连续点击分类时频繁写 localStorage。
 */
function debounce<TArgs extends unknown[]>(
  fn: (...args: TArgs) => void,
  ms: number,
): ((...args: TArgs) => void) & { flush: () => void } {
  let timer: ReturnType<typeof setTimeout> | null = null
  let pendingArgs: TArgs | null = null
  const debounced = (...args: TArgs) => {
    pendingArgs = args
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      timer = null
      pendingArgs = null
      fn(...args)
    }, ms)
  }
  debounced.flush = () => {
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
    if (pendingArgs) {
      const args = pendingArgs
      pendingArgs = null
      fn(...args)
    }
  }
  return debounced
}

// 收藏夹：存储 node.type 集合
const favorites = ref<Set<string>>(new Set(loadFromStorage<string[]>(FAVORITES_KEY, [])))

// 最近使用：最多 10 个 node.type
const recentTypes = ref<string[]>(loadFromStorage<string[]>(RECENT_KEY, []))

// 折叠分类：初始化时从 localStorage 读取
const savedCollapsed = loadFromStorage<string[]>(COLLAPSED_KEY, [])
collapsedCategories.value = new Set(savedCollapsed)

// 防抖持久化折叠状态（300ms），避免连续折叠/展开时频繁写 localStorage
const persistCollapsed = debounce((set: Set<string>) => {
  saveToStorage(COLLAPSED_KEY, Array.from(set))
}, 300)

// 监听折叠状态变化，持久化
watch(
  collapsedCategories,
  (set) => {
    persistCollapsed(set)
  },
  { deep: true },
)

// 组件卸载前立即刷新挂起的写入，避免丢失最后一次折叠状态
onBeforeUnmount(() => {
  persistCollapsed.flush()
})

// ─── 引擎过滤工具 ────────────────────────────────────────────────────────────
const ENGINE_FILTERS: Array<{ key: string; label: string; color: string }> = [
  { key: 'all', label: '全部', color: 'var(--accent-strong)' },
  { key: 'weather', label: '天气', color: 'var(--warning)' },
  { key: 'python_provider', label: 'Python', color: 'var(--success)' },
  { key: 'gee', label: 'GEE', color: 'var(--accent)' },
  { key: 'common', label: '通用', color: 'var(--accent-strong)' },
]

const PORT_LEGEND = [
  { color: 'var(--port-time)', label: '时间范围' },
  { color: 'var(--danger)', label: '空间范围' },
  { color: 'var(--port-numeric)', label: '数值' },
  { color: 'var(--port-text)', label: '文本' },
  { color: 'var(--accent)', label: '数据流' },
]

function getEngineOfNode(type: string, templateEngine?: string | null): string {
  const fromTpl = (templateEngine ?? '').trim()
  if (fromTpl) return fromTpl
  if (type.startsWith('weather/')) return 'weather'
  if (type.startsWith('gee/')) return 'gee'
  // Python Provider 节点类型前缀是 module/，不是 python_provider/
  if (type.startsWith('module/') || type.startsWith('python_provider/')) return 'python_provider'
  return 'common'
}

function getEngineAccentColor(nodeType: string, templateEngine?: string | null): string {
  const engine = getEngineOfNode(nodeType, templateEngine)
  const found = ENGINE_FILTERS.find((f) => f.key === engine)
  return found?.color ?? 'var(--accent-strong)'
}

// ─── 过滤后的模板（按引擎 + 搜索关键词） ────────────────────────────────────
const filteredTemplatesByCategory = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  const engineFilter = activeEngineFilter.value
  const result: Record<string, NodeTemplate[]> = {}

  for (const [category, templates] of Object.entries(templatesByCategory.value)) {
    const filtered = templates.filter((t) => {
      if (!showStubs.value && t.executable === false) return false
      // 引擎过滤（用模板 engine 字段，避免 module/* 被误判为 common）
      if (engineFilter !== 'all' && getEngineOfNode(t.type, t.engine) !== engineFilter) return false
      // 搜索过滤
      if (query) {
        const matched =
          t.title.toLowerCase().includes(query) ||
          t.type.toLowerCase().includes(query) ||
          t.description.toLowerCase().includes(query)
        if (!matched) return false
      }
      return true
    })
    if (filtered.length > 0) result[category] = filtered
  }
  return result
})

const visibleTemplateCount = computed(() =>
  Object.values(filteredTemplatesByCategory.value).reduce((n, list) => n + list.length, 0),
)

const stubCount = computed(() => nodeTemplates.value.filter((t) => t.executable === false).length)

// ─── 收藏夹节点列表 ──────────────────────────────────────────────────────────
const favoriteTemplates = computed(() => {
  if (favorites.value.size === 0) return []
  return nodeTemplates.value.filter((t) => {
    if (!favorites.value.has(t.type)) return false
    if (!showStubs.value && t.executable === false) return false
    return true
  })
})

// ─── 最近使用节点列表 ────────────────────────────────────────────────────────
const recentTemplates = computed(() => {
  if (recentTypes.value.length === 0) return []
  const result: NodeTemplate[] = []
  for (const type of recentTypes.value) {
    const tpl = nodeTemplates.value.find((t) => t.type === type)
    if (!tpl) continue
    if (!showStubs.value && tpl.executable === false) continue
    result.push(tpl)
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
const CATEGORY_ICONS: Record<string, Component> = {
  数据输入: FolderOpen,
  数据预处理: Wrench,
  遥感处理: Satellite,
  合成: Shuffle,
  反演: Ruler,
  统计分析: BarChart3,
  数据融合: Link,
  可视化: TrendingUp,
  '天气-数据抓取': Sun,
  '天气-渲染': Palette,
  '天气-处理': Settings,
  'GEE-数据': Globe,
  'GEE-处理': Wrench,
  GIS工具: Map,
  输出: Upload,
}

function getCategoryIcon(category: string): Component {
  return CATEGORY_ICONS[category] ?? Diamond
}

function handleAddNode(template: NodeTemplate) {
  if (template.executable === false) {
    return
  }
  // 更新最近使用：插入头部，去重，最多 10 个
  const type = template.type
  const filtered = recentTypes.value.filter((t) => t !== type)
  filtered.unshift(type)
  recentTypes.value = filtered.slice(0, 10)
  saveToStorage(RECENT_KEY, recentTypes.value)

  emit('addNode', template)
}

function isStub(template: NodeTemplate): boolean {
  return template.executable === false
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
      <span
        class="header-count"
        :title="`可见 ${visibleTemplateCount} / 总计 ${nodeTemplates.length}`"
      >
        {{ visibleTemplateCount }}
      </span>
    </div>

    <div class="palette-search">
      <input
        v-model="searchQuery"
        type="text"
        class="search-input"
        placeholder="搜索节点..."
        aria-label="搜索节点"
      />
      <X v-if="searchQuery" :size="14" class="search-clear" @click="searchQuery = ''" />
    </div>

    <label v-if="stubCount > 0" class="stub-toggle" title="未实现模块不可加入画布，默认隐藏">
      <input v-model="showStubs" type="checkbox" />
      <span>显示未实现（{{ stubCount }}）</span>
    </label>

    <!-- 引擎过滤标签 -->
    <div class="palette-engine-filters">
      <button
        v-for="filter in ENGINE_FILTERS"
        :key="filter.key"
        class="engine-filter-btn"
        :class="{ active: activeEngineFilter === filter.key }"
        :style="
          activeEngineFilter === filter.key
            ? { borderColor: filter.color, color: filter.color, background: filter.color + '20' }
            : {}
        "
        type="button"
        @click="activeEngineFilter = filter.key"
      >
        {{ filter.label }}
      </button>
    </div>

    <div class="port-legend" title="同色端口可连线；优先从「参数与范围」拖入时间/空间/数值模块">
      <span v-for="item in PORT_LEGEND" :key="item.label" class="port-legend-item">
        <i class="port-legend-dot" :style="{ background: item.color }" />
        {{ item.label }}
      </span>
    </div>
    <p class="flow-tip">推荐流：参数与范围 → 算法模块 → 输出</p>

    <div class="palette-content">
      <!-- 收藏夹分区 -->
      <div
        v-if="favoriteTemplates.length && !searchQuery && activeEngineFilter === 'all'"
        class="category-group favorites-group"
      >
        <button class="category-header" type="button" @click="toggleCategory('__favorites__')">
          <Star :size="14" class="category-icon" aria-hidden="true" />
          <span class="category-label">收藏</span>
          <span class="category-count">{{ favoriteTemplates.length }}</span>
          <ChevronDown
            :size="14"
            class="category-toggle"
            :class="{ collapsed: collapsedCategories.has('__favorites__') }"
          />
        </button>
        <div
          class="category-items"
          :class="{ collapsed: collapsedCategories.has('__favorites__') }"
        >
          <button
            v-for="tpl in favoriteTemplates"
            :key="tpl.type"
            class="node-item"
            :class="{ stub: isStub(tpl) }"
            type="button"
            :disabled="isStub(tpl)"
            :style="{ borderLeftColor: getEngineAccentColor(tpl.type, tpl.engine) }"
            :title="isStub(tpl) ? `${tpl.description}（未实现）` : tpl.description"
            @click="handleAddNode(tpl)"
          >
            <div class="node-item-header">
              <span class="node-item-title">{{ tpl.title }}</span>
              <span v-if="isStub(tpl)" class="node-item-stub-badge">未实现</span>
              <Star
                :size="14"
                class="node-item-favorite-btn favorited"
                title="取消收藏"
                fill="currentColor"
                @click.stop="toggleFavorite(tpl.type)"
              />
            </div>
            <div v-if="tpl.description" class="node-item-desc">{{ tpl.description }}</div>
            <div class="node-item-ports">
              <span v-if="tpl.inputs.length" class="port-count in">{{ tpl.inputs.length }} 入</span>
              <span v-if="tpl.outputs.length" class="port-count out"
                >{{ tpl.outputs.length }} 出</span
              >
            </div>
          </button>
        </div>
      </div>

      <!-- 最近使用分区 -->
      <div
        v-if="recentTemplates.length && !searchQuery && activeEngineFilter === 'all'"
        class="category-group recent-group"
      >
        <button class="category-header" type="button" @click="toggleCategory('__recent__')">
          <Clock :size="14" class="category-icon" aria-hidden="true" />
          <span class="category-label">最近使用</span>
          <span class="category-count">{{ recentTemplates.length }}</span>
          <ChevronDown
            :size="14"
            class="category-toggle"
            :class="{ collapsed: collapsedCategories.has('__recent__') }"
          />
        </button>
        <div class="category-items" :class="{ collapsed: collapsedCategories.has('__recent__') }">
          <button
            v-for="tpl in recentTemplates"
            :key="tpl.type"
            class="node-item"
            :class="{ stub: isStub(tpl) }"
            type="button"
            :disabled="isStub(tpl)"
            :style="{ borderLeftColor: getEngineAccentColor(tpl.type, tpl.engine) }"
            :title="isStub(tpl) ? `${tpl.description}（未实现）` : tpl.description"
            @click="handleAddNode(tpl)"
          >
            <div class="node-item-header">
              <span class="node-item-title">{{ tpl.title }}</span>
              <span v-if="isStub(tpl)" class="node-item-stub-badge">未实现</span>
              <Star
                :size="14"
                class="node-item-favorite-btn"
                :class="{ favorited: isFavorite(tpl.type) }"
                :fill="isFavorite(tpl.type) ? 'currentColor' : 'none'"
                :title="isFavorite(tpl.type) ? '取消收藏' : '加入收藏'"
                @click.stop="toggleFavorite(tpl.type)"
              />
            </div>
            <div v-if="tpl.description" class="node-item-desc">{{ tpl.description }}</div>
            <div class="node-item-ports">
              <span v-if="tpl.inputs.length" class="port-count in">{{ tpl.inputs.length }} 入</span>
              <span v-if="tpl.outputs.length" class="port-count out"
                >{{ tpl.outputs.length }} 出</span
              >
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
        <button class="category-header" type="button" @click="toggleCategory(String(category))">
          <span class="category-icon" aria-hidden="true">
            <component :is="getCategoryIcon(String(category))" :size="16" />
          </span>
          <span class="category-label">{{ getCategoryLabel(String(category)) }}</span>
          <span class="category-count">{{ templates.length }}</span>
          <ChevronDown
            :size="14"
            class="category-toggle"
            :class="{ collapsed: collapsedCategories.has(String(category)) }"
          />
        </button>

        <div
          class="category-items"
          :class="{ collapsed: collapsedCategories.has(String(category)) }"
        >
          <button
            v-for="tpl in templates"
            :key="tpl.type"
            class="node-item"
            :class="{ stub: isStub(tpl) }"
            type="button"
            :disabled="isStub(tpl)"
            :style="{ borderLeftColor: getEngineAccentColor(tpl.type, tpl.engine) }"
            :title="isStub(tpl) ? `${tpl.description}（未实现）` : tpl.description"
            @click="handleAddNode(tpl)"
          >
            <div class="node-item-header">
              <span class="node-item-title">{{ tpl.title }}</span>
              <span v-if="isStub(tpl)" class="node-item-stub-badge">未实现</span>
              <Star
                :size="14"
                class="node-item-favorite-btn"
                :class="{ favorited: isFavorite(tpl.type) }"
                :fill="isFavorite(tpl.type) ? 'currentColor' : 'none'"
                :title="isFavorite(tpl.type) ? '取消收藏' : '加入收藏'"
                @click.stop="toggleFavorite(tpl.type)"
              />
            </div>
            <div class="node-item-type">{{ tpl.type }}</div>
            <div v-if="tpl.description" class="node-item-desc">{{ tpl.description }}</div>
            <div class="node-item-ports">
              <span v-if="tpl.inputs.length" class="port-count in">{{ tpl.inputs.length }} 入</span>
              <span v-if="tpl.outputs.length" class="port-count out"
                >{{ tpl.outputs.length }} 出</span
              >
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
  background: var(--surface-1);
  color: var(--text-secondary);
}

.palette-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.62rem 0.72rem;
  border-bottom: 1px solid var(--border-subtle);
  font-size: var(--font-size-caption);
  font-weight: 600;
  color: var(--text-primary);
}

.header-count {
  padding: 0.1rem 0.42rem;
  border-radius: 999px;
  background: var(--accent-surface);
  color: var(--accent);
  font-size: var(--font-size-caption);
  font-weight: 700;
}

.palette-search {
  position: relative;
  padding: 0.42rem 0.62rem;
  border-bottom: 1px solid var(--border-subtle);
}

.search-input {
  width: 100%;
  padding: 0.36rem 0.52rem;
  border: 1px solid var(--border-default);
  border-radius: 0.42rem;
  background: var(--surface-raised);
  color: var(--text-primary);
  font: inherit;
  font-size: var(--font-size-caption);
}

.search-input::placeholder {
  color: var(--text-disabled);
}

.search-input:focus {
  outline: none;
  border-color: var(--border-strong);
}

.search-clear {
  position: absolute;
  right: 0.92rem;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-disabled);
  cursor: pointer;
  font-size: var(--font-size-caption);
  line-height: 1;
}

/* 引擎过滤标签栏 */
.palette-engine-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.22rem;
  padding: 0.32rem 0.62rem;
  border-bottom: 1px solid var(--border-subtle);
}

.port-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0.55rem;
  padding: 0.28rem 0.62rem 0.1rem;
}

.port-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 0.22rem;
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}

.port-legend-dot {
  width: 0.4rem;
  height: 0.4rem;
  border-radius: 50%;
  display: inline-block;
}

.flow-tip {
  margin: 0;
  padding: 0.1rem 0.62rem 0.35rem;
  font-size: var(--font-size-caption);
  color: var(--warning);
  border-bottom: 1px solid var(--border-subtle);
}

.engine-filter-btn {
  padding: 0.16rem 0.42rem;
  border: 1px solid var(--border-default);
  border-radius: 0.32rem;
  background: transparent;
  color: var(--text-faint);
  cursor: pointer;
  font: inherit;
  font-size: var(--font-size-caption);
  font-weight: 500;
  transition:
    background-color var(--motion-interactive-duration) var(--motion-interactive-ease),
    border-color var(--motion-interactive-duration) var(--motion-interactive-ease),
    color var(--motion-interactive-duration) var(--motion-interactive-ease),
    box-shadow var(--motion-interactive-duration) var(--motion-interactive-ease),
    opacity var(--motion-interactive-duration) var(--motion-interactive-ease),
    transform var(--motion-interactive-duration) var(--motion-interactive-ease);
}

.engine-filter-btn:hover {
  border-color: var(--border-strong);
  color: var(--text-primary);
}

.engine-filter-btn.active {
  font-weight: 600;
}

.palette-content {
  flex: 1;
  overflow-y: auto;
  padding: 0.32rem 0;
  scrollbar-width: thin;
  scrollbar-color: var(--border-accent) transparent;
}

.palette-content::-webkit-scrollbar {
  width: 4px;
}

.palette-content::-webkit-scrollbar-track {
  background: transparent;
}

.palette-content::-webkit-scrollbar-thumb {
  background: var(--border-accent);
  border-radius: 3px;
}

.palette-content::-webkit-scrollbar-thumb:hover {
  background: var(--border-strong);
}

.stub-toggle {
  display: flex;
  align-items: center;
  gap: 0.32rem;
  padding: 0.22rem 0.62rem;
  border-bottom: 1px solid var(--border-subtle);
  font-size: var(--font-size-caption);
  color: var(--text-muted);
  cursor: pointer;
  user-select: none;
}

.stub-toggle input {
  accent-color: var(--warning);
}

.empty-hint {
  padding: 1.4rem 0.8rem;
  text-align: center;
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
}

.category-group {
  margin-bottom: 0.16rem;
}

.category-group.favorites-group .category-header {
  color: var(--accent-warm);
}

.category-group.recent-group .category-header {
  color: var(--recent-accent);
}

.category-header {
  display: flex;
  align-items: center;
  gap: 0.36rem;
  width: 100%;
  padding: 0.36rem 0.72rem;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font: inherit;
  font-size: var(--font-size-caption);
  font-weight: 600;
  text-align: left;
  transition:
    background var(--motion-interactive-duration) var(--motion-interactive-ease),
    color var(--motion-interactive-duration) var(--motion-interactive-ease);
}

.category-header:hover {
  background: var(--border-subtle);
  color: var(--text-primary);
}

.category-icon {
  font-size: var(--font-size-caption);
  opacity: 0.8;
}

.category-label {
  flex: 1;
}

.category-count {
  padding: 0.04rem 0.32rem;
  border-radius: 999px;
  background: var(--border-subtle);
  color: var(--text-faint);
  font-size: var(--font-size-caption);
  font-weight: 600;
}

.category-toggle {
  font-size: var(--font-size-caption);
  transition: transform var(--motion-interactive-duration) var(--motion-interactive-ease);
}

.category-toggle.collapsed {
  transform: rotate(-90deg);
}

.category-items {
  display: grid;
  grid-template-rows: 1fr;
  transition:
    grid-template-rows var(--motion-base) var(--ease-standard),
    opacity var(--motion-base) var(--ease-standard);
  overflow: hidden;
  padding: 0.16rem 0.42rem;
}

.category-items.collapsed {
  grid-template-rows: 0fr;
  opacity: 0;
  padding: 0;
}

.node-item {
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
  width: 100%;
  margin-bottom: 0.18rem;
  padding: 0.36rem 0.46rem;
  border: 1px solid var(--border-subtle);
  border-left: 3px solid var(--accent-strong);
  border-radius: 0.42rem;
  background: var(--surface-sunken);
  color: var(--text-secondary);
  cursor: pointer;
  font: inherit;
  text-align: left;
  transition:
    border-color var(--motion-interactive-duration) var(--motion-interactive-ease),
    background var(--motion-interactive-duration) var(--motion-interactive-ease),
    transform var(--motion-interactive-duration) var(--motion-interactive-ease);
}

.node-item:hover {
  border-color: var(--border-accent);
  background: var(--accent-surface);
  transform: translateX(2px);
}

.node-item.stub,
.node-item:disabled {
  opacity: 0.48;
  cursor: not-allowed;
  filter: grayscale(0.35);
}

.node-item.stub:hover,
.node-item:disabled:hover {
  border-color: var(--border-subtle);
  background: var(--surface-sunken);
  transform: none;
}

.node-item-stub-badge {
  margin-left: 0.35rem;
  padding: 0.05rem 0.32rem;
  border-radius: 0.25rem;
  background: rgba(120, 120, 120, 0.35);
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  font-weight: 600;
  letter-spacing: 0.02em;
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
  font-size: var(--font-size-caption);
  font-weight: 600;
  color: var(--text-primary);
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
  color: var(--text-disabled);
  cursor: pointer;
  font-size: var(--font-size-caption);
  line-height: 1;
  transition:
    color var(--motion-interactive-duration) var(--motion-interactive-ease),
    transform var(--motion-interactive-duration) var(--motion-interactive-ease);
}

.node-item-favorite-btn:hover {
  transform: scale(1.2);
}

.node-item-favorite-btn.favorited {
  color: var(--accent-warm);
}

.node-item-type {
  font-size: var(--font-size-caption);
  color: var(--text-disabled);
  font-family: var(--font-mono);
}

.node-item-desc {
  font-size: var(--font-size-caption);
  color: var(--text-faint);
  line-height: 1.3;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.node-item-ports {
  display: flex;
  gap: 0.32rem;
  font-size: var(--font-size-caption);
}

.port-count {
  padding: 0.04rem 0.28rem;
  border-radius: 0.24rem;
  background: var(--border-subtle);
  color: var(--text-faint);
}

.port-count.in {
  border-left: 2px solid var(--border-strong);
}

.port-count.out {
  border-left: 2px solid var(--success-border);
}

@media (prefers-reduced-motion: reduce) {
  .engine-filter-btn,
  .category-header,
  .category-toggle,
  .node-item,
  .node-item-favorite-btn {
    transition: none;
  }
  .node-item:hover {
    transform: none;
  }
  .node-item-favorite-btn:hover {
    transform: none;
  }
  .category-items {
    transition: none;
  }
}
</style>
