<script setup lang="ts">
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'

import { useLayersStore } from '../stores/layers'

const emit = defineEmits<{
  selectLayer: [instanceId: string]
}>()

const layersStore = useLayersStore()

// Use storeToRefs only for reactive state
const {
  activeLayersDisplay,
  selectedInstanceId,
  sidebarView,
  activeLayerCount,
  sidebarViewLabel,
  catalogJobStatus,
} = storeToRefs(layersStore)

// Static catalog data — access directly from store (no storeToRefs needed)
const layerLibrary = layersStore.layerLibrary
const layerCategories = layersStore.layerCategories

const searchQuery = ref('')
const expandedCategories = ref<Set<string>>(new Set(layerCategories.map((c) => c.id)))
const draggedInstanceId = ref<string | null>(null)
const dragOverInstanceId = ref<string | null>(null)

// ── Filter library items by search ────────────────────────────────────────────

const filteredLibrary = computed(() => {
  if (!searchQuery.value.trim()) return layerLibrary
  const q = searchQuery.value.toLowerCase()
  return layerLibrary.filter(
    (item) =>
      item.name.toLowerCase().includes(q) ||
      item.category.toLowerCase().includes(q) ||
      item.sourceLabel.toLowerCase().includes(q),
  )
})

const filteredLibraryByCategory = computed(() => {
  const map = new Map(layerCategories.map((c) => [c.id, { category: c, items: [] as typeof layerLibrary }]))
  for (const item of filteredLibrary.value) {
    if (map.has(item.category)) {
      map.get(item.category)!.items.push(item)
    }
  }
  return Array.from(map.values()).filter((g) => g.items.length > 0)
})

// ── Check if layer already added ───────────────────────────────────────────────

function isAdded(catalogId: string): boolean {
  return activeLayersDisplay.value.some((d) => d.catalogId === catalogId && !d.isAdminBoundary)
}

/** 获取 catalogId 对应的工作流状态（用于 library 卡片自动运行反馈） */
function getCatalogJobStatus(catalogId: string): string | undefined {
  return catalogJobStatus.value.get(catalogId)
}

function isAdminAdded(): boolean {
  return activeLayersDisplay.value.some((d) => d.isAdminBoundary)
}

// ── Actions ───────────────────────────────────────────────────────────────────

function openLibrary() {
  layersStore.setSidebarView('library')
}

function openActive() {
  layersStore.setSidebarView('active')
}

function openEmpty() {
  layersStore.setSidebarView('empty')
  layersStore.selectLayer(null)
}

function addCatalogItem(catalogId: string, isAdminBoundary = false) {
  layersStore.addLayer(catalogId, isAdminBoundary)
  // 自动运行：weatherengine 支持的图层（风场全高度变体/温度/降水/气压/湿度/能见度）
  // 添加后立即触发工作流，无需用户手动点"运行工作流"
  if (!isAdminBoundary && layersStore.isWeatherEngineLayer(catalogId)) {
    // 异步触发，不阻塞 UI；失败时静默处理（用户可在 InfoPanel 手动重试）
    void layersStore.runWorkflowForCatalog(catalogId).catch((err) => {
      console.warn(`[LayerSidebar] 自动运行 ${catalogId} 工作流失败:`, err)
    })
  }
}

/** 批量添加某分类下所有未添加的图层 */
function addAllInCategory(items: { catalogId: string; isAdminBoundary?: boolean }[]) {
  for (const item of items) {
    if (!isAdded(item.catalogId) && !item.isAdminBoundary) {
      // 统一走 addCatalogItem，保证自动运行工作流的逻辑一致
      addCatalogItem(item.catalogId, false)
    }
  }
}

/** 批量显示所有图层 */
function showAllLayers() {
  layersStore.setAllLayerVisibility(true)
}

/** 批量隐藏所有图层 */
function hideAllLayers() {
  layersStore.setAllLayerVisibility(false)
}

/** 批量移除所有图层（保留行政区边界） */
function removeAllLayers() {
  layersStore.removeAllLayers(true)
}

function removeItem(instanceId: string, event: MouseEvent) {
  event.stopPropagation()
  layersStore.removeLayer(instanceId)
}

function selectItem(instanceId: string) {
  layersStore.selectLayer(instanceId)
  emit('selectLayer', instanceId)
}

function toggleVisibility(instanceId: string, event: MouseEvent) {
  event.stopPropagation()
  layersStore.toggleLayerVisibility(instanceId)
}

function changeOpacity(instanceId: string, event: Event) {
  const target = event.target as HTMLInputElement
  layersStore.setLayerOpacity(instanceId, Number(target.value) / 100)
}

function toggleCategory(categoryId: string) {
  if (expandedCategories.value.has(categoryId)) {
    expandedCategories.value.delete(categoryId)
  } else {
    expandedCategories.value.add(categoryId)
  }
}

// ── Drag to reorder ────────────────────────────────────────────────────────────

function onDragStart(instanceId: string) {
  draggedInstanceId.value = instanceId
}

function onDragOver(instanceId: string, event: DragEvent) {
  event.preventDefault()
  dragOverInstanceId.value = instanceId
}

function onDrop(targetInstanceId: string) {
  if (!draggedInstanceId.value || draggedInstanceId.value === targetInstanceId) return
  const sorted = activeLayersDisplay.value
  const fromIndex = sorted.findIndex((d) => d.instanceId === draggedInstanceId.value)
  const toIndex = sorted.findIndex((d) => d.instanceId === targetInstanceId)
  if (fromIndex === -1) {
    draggedInstanceId.value = null
    dragOverInstanceId.value = null
    return
  }
  if (toIndex !== -1) {
    layersStore.reorderLayers(fromIndex, toIndex)
  }
  draggedInstanceId.value = null
  dragOverInstanceId.value = null
}

function onDragEnd() {
  draggedInstanceId.value = null
  dragOverInstanceId.value = null
}

// ── Helper: availability chip class ───────────────────────────────────────────

function availabilityClass(state: string) {
  if (state === 'ready') return 'availability-ready'
  if (state === 'partial') return 'availability-partial'
  return 'availability-empty'
}

// ── Get category meta ─────────────────────────────────────────────────────────

function getCategoryMeta(categoryId: string) {
  return layerCategories.find((c) => c.id === categoryId)
}

function getCategoryName(categoryId: string): string {
  return layerCategories.find((c) => c.id === categoryId)?.name ?? categoryId
}

// ── 数据源选择 ─────────────────────────────────────────────────────────────────
// 友好且无冲突的方案：
//   - 0 数据源：显示 "暂无可用数据源" 提示
//   - 1 数据源：直接展示数据源信息（无展开按钮），简洁友好
//   - 多数据源：显示当前选中源 + 展开按钮，可单选切换

function getCatalogSources(catalogId: string) {
  return layerLibrary.find((l) => l.catalogId === catalogId)?.sources ?? []
}

/** 多源时记录每 catalog 用户选中的 sourceId；未选则回退首个 */
const selectedSourceByCatalog = ref<Record<string, string>>({})

function getSelectedSourceId(catalogId: string): string {
  const sources = getCatalogSources(catalogId)
  return selectedSourceByCatalog.value[catalogId] ?? sources[0]?.id ?? ''
}

function getSelectedSourceName(catalogId: string): string {
  const sources = getCatalogSources(catalogId)
  const id = getSelectedSourceId(catalogId)
  return sources.find((s) => s.id === id)?.name ?? (sources.length === 0 ? '暂无可用数据源' : '未选择')
}

function isSourceSelected(catalogId: string, sourceId: string): boolean {
  return getSelectedSourceId(catalogId) === sourceId
}

function selectSource(catalogId: string, sourceId: string) {
  selectedSourceByCatalog.value[catalogId] = sourceId
}

const sourcePickerOpen = ref<string | null>(null)

function toggleSourcePicker(catalogId: string) {
  sourcePickerOpen.value = sourcePickerOpen.value === catalogId ? null : catalogId
}
</script>

<template>
  <aside class="panel">
    <!-- ── Header ─────────────────────────────────────────────────────────── -->
    <div class="panel-topline">
      <div class="panel-header">
        <div class="header-copy">
          <h2>{{ sidebarViewLabel }}</h2>
          <p class="panel-subtitle">{{ sidebarView === 'empty' ? '开始添加图层' : sidebarView === 'library' ? '从库中选择' : `${activeLayerCount} 个图层已加载` }}</p>
        </div>
        <div class="header-actions">
          <span v-if="activeLayerCount > 0" class="badge">{{ activeLayerCount }}</span>
          <div class="view-tabs" role="tablist">
            <button
              class="view-tab"
              :class="{ active: sidebarView === 'empty' }"
              role="tab"
              title="清空"
              @click="openEmpty"
            >✕</button>
            <button
              class="view-tab"
              :class="{ active: sidebarView === 'library' }"
              role="tab"
              title="图层库"
              @click="openLibrary"
            >+</button>
            <button
              class="view-tab"
              :class="{ active: sidebarView === 'active' }"
              role="tab"
              :aria-selected="sidebarView === 'active'"
              title="已添加图层"
              @click="openActive"
            >≡</button>
          </div>
        </div>
      </div>
    </div>

    <!-- ── EMPTY STATE ─────────────────────────────────────────────────────── -->
    <div v-if="sidebarView === 'empty'" class="empty-state">
      <div class="empty-icon" aria-hidden="true">◇</div>
      <p class="empty-title">图层为空</p>
      <p class="empty-hint">点击下方按钮打开图层库，<br>添加气象、遥感或边界图层。</p>
      <button class="empty-cta" @click="openLibrary">
        <span aria-hidden="true">+</span>
        打开图层库
      </button>
    </div>

    <!-- ── LIBRARY STATE ───────────────────────────────────────────────────── -->
    <template v-else-if="sidebarView === 'library'">
      <!-- Search -->
      <div class="search-row">
        <input
          v-model="searchQuery"
          class="search-input"
          placeholder="搜索图层..."
          type="search"
        />
      </div>

      <!-- Admin boundary quick add (always visible in library) -->
      <div v-if="!isAdminAdded()" class="quick-add-row">
        <button class="quick-add-btn" @click="addCatalogItem('admin-boundary', true)">
          <span class="qa-icon" aria-hidden="true">◻</span>
          <span>行政区边界</span>
          <span class="qa-tag">叠加</span>
        </button>
      </div>

      <!-- Category groups -->
      <div class="library-scroll">
        <div
          v-for="group in filteredLibraryByCategory"
          :key="group.category.id"
          class="category-group"
        >
          <button
            class="category-header"
            :style="{ '--cat-color': getCategoryMeta(group.category.id)?.accentColor ?? '#88d8ff' }"
            @click="toggleCategory(group.category.id)"
          >
            <span class="cat-icon" aria-hidden="true">{{ getCategoryMeta(group.category.id)?.icon ?? '◈' }}</span>
            <span class="cat-name">{{ getCategoryMeta(group.category.id)?.name ?? group.category.id }}</span>
            <span class="cat-count">{{ group.items.length }}</span>
            <span class="cat-arrow" :class="{ expanded: expandedCategories.has(group.category.id) }">▸</span>
          </button>

          <!-- 批量添加按钮（展开时显示） -->
          <button
            v-if="expandedCategories.has(group.category.id)"
            class="cat-batch-add"
            :style="{ '--cat-color': getCategoryMeta(group.category.id)?.accentColor ?? '#88d8ff' }"
            title="添加此分类下所有图层"
            @click.stop="addAllInCategory(group.items)"
          >
            + 全部添加
          </button>

          <div v-if="expandedCategories.has(group.category.id)" class="category-items">
            <div
              v-for="item in group.items"
              :key="item.catalogId"
              class="library-card"
              :class="{ added: isAdded(item.catalogId) }"
              :style="{
                '--accent': item.accentColor,
                '--glow': item.accentGlow,
              }"
            >
              <div class="card-top">
                <div class="card-title-row">
                  <strong>{{ item.name }}</strong>
                  <span class="card-chip" :style="{ background: item.chipTone }">{{ getCategoryName(item.category) }}</span>
                </div>
                <p class="card-source">{{ item.sourceLabel }}</p>
              </div>

              <!-- 数据源区域：按源数量切换显示策略 -->
              <div class="source-area">
                <!-- 0 数据源 -->
                <div v-if="item.sources.length === 0" class="source-empty" :title="'该图层暂未接入数据源'">
                  <span class="src-empty-icon" aria-hidden="true">ⓘ</span>
                  <span>暂无可用数据源</span>
                </div>

                <!-- 单数据源：直接展示信息 -->
                <div v-else-if="item.sources.length === 1" class="source-single">
                  <div class="src-line">
                    <span class="src-dot" :style="{ background: item.accentColor }"></span>
                    <span class="src-name">{{ item.sources[0].name }}</span>
                  </div>
                  <div class="src-meta">
                    <span class="src-badge">{{ item.sources[0].updateFrequency }}</span>
                    <span class="src-coord">{{ item.sources[0].coordSys }}</span>
                    <span v-if="item.sources[0].needsAuth" class="src-auth" title="需要认证">🔒</span>
                    <span v-if="item.sources[0].needsBackendTransform" class="src-tfm" title="后端转换">⚙</span>
                  </div>
                </div>

                <!-- 多数据源：可展开切换 -->
                <div v-else class="source-multi">
                  <button
                    class="source-picker-btn"
                    :title="`已选：${getSelectedSourceName(item.catalogId)}（共 ${item.sources.length} 个数据源）`"
                    @click="toggleSourcePicker(item.catalogId)"
                  >
                    <span class="src-dot" :style="{ background: item.accentColor }"></span>
                    <span class="src-current">{{ getSelectedSourceName(item.catalogId) }}</span>
                    <span class="src-count">{{ item.sources.length }}</span>
                    <span class="sp-arrow" :class="{ open: sourcePickerOpen === item.catalogId }">▸</span>
                  </button>
                  <div v-if="sourcePickerOpen === item.catalogId" class="source-list">
                    <button
                      v-for="src in item.sources"
                      :key="src.id"
                      class="source-option"
                      :class="{ active: isSourceSelected(item.catalogId, src.id) }"
                      :title="src.description"
                      @click.stop="selectSource(item.catalogId, src.id)"
                    >
                      <div class="src-opt-top">
                        <span class="src-name">{{ src.name }}</span>
                        <span v-if="isSourceSelected(item.catalogId, src.id)" class="src-check" aria-hidden="true">✓</span>
                      </div>
                      <div class="src-meta">
                        <span class="src-badge">{{ src.updateFrequency }}</span>
                        <span class="src-coord">{{ src.coordSys }}</span>
                        <span v-if="src.needsAuth" class="src-auth" title="需要认证">🔒</span>
                      </div>
                    </button>
                  </div>
                </div>
              </div>

              <div class="card-actions">
                <span class="card-metric">{{ item.metricLabel }}: {{ item.metricUnit }}</span>
                <button
                  v-if="!isAdded(item.catalogId)"
                  class="add-btn"
                  :disabled="isAdded(item.catalogId)"
                  @click="addCatalogItem(item.catalogId)"
                >
                  + 添加
                </button>
                <!-- 已添加：显示工作流状态徽标 -->
                <span v-else-if="getCatalogJobStatus(item.catalogId) === 'running'" class="job-status-chip job-status-running">
                  <span class="spin-dot" aria-hidden="true"></span>运行中
                </span>
                <span v-else-if="getCatalogJobStatus(item.catalogId) === 'queued'" class="job-status-chip job-status-queued">
                  排队中
                </span>
                <span v-else-if="getCatalogJobStatus(item.catalogId) === 'succeeded'" class="job-status-chip job-status-succeeded">
                  已就绪 ✓
                </span>
                <span v-else-if="getCatalogJobStatus(item.catalogId) === 'failed'" class="job-status-chip job-status-failed">
                  运行失败
                </span>
                <span v-else class="added-label">已添加 ✓</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- ── ACTIVE STATE ───────────────────────────────────────────────────── -->
    <div v-else-if="sidebarView === 'active'" class="active-state">
      <div v-if="activeLayersDisplay.length === 0" class="no-layers">
        <p>暂无已添加图层。</p>
        <button class="empty-cta small" @click="openLibrary">去添加</button>
      </div>

      <template v-else>
        <!-- 批量操作工具栏 -->
        <div class="batch-toolbar">
          <button class="batch-btn" title="显示所有图层" @click="showAllLayers">
            <span aria-hidden="true">◉</span> 全部显示
          </button>
          <button class="batch-btn" title="隐藏所有图层" @click="hideAllLayers">
            <span aria-hidden="true">◯</span> 全部隐藏
          </button>
          <button class="batch-btn batch-btn-danger" title="移除所有图层（保留边界）" @click="removeAllLayers">
            <span aria-hidden="true">✕</span> 全部移除
          </button>
        </div>

        <!-- 图层列表：参考 ArcGIS Pro 紧凑设计，按内容高度排列，不强制撑满 -->
        <ul class="layer-list" role="listbox" aria-label="已添加图层">
          <li
            v-for="(layer, index) in activeLayersDisplay"
            :key="layer.instanceId"
            class="layer-item"
            :class="{
              active: layer.instanceId === selectedInstanceId,
              hidden: !layer.visible,
              'drag-over': layer.instanceId === dragOverInstanceId,
              expanded: layer.instanceId === selectedInstanceId,
            }"
            :style="{
              '--accent': layer.accentColor,
              '--glow': layer.accentGlow,
            }"
            draggable="true"
            role="option"
            :aria-selected="layer.instanceId === selectedInstanceId"
            @click="selectItem(layer.instanceId)"
            @dragstart="onDragStart(layer.instanceId)"
            @dragover="onDragOver(layer.instanceId, $event)"
            @drop="onDrop(layer.instanceId)"
            @dragend="onDragEnd"
          >
            <!-- 主行：紧凑单行布局 -->
            <div class="layer-row-top">
              <span class="drag-handle" title="拖动排序">☰</span>
              <button
                class="vis-btn"
                :title="layer.visible ? '隐藏图层' : '显示图层'"
                @click="toggleVisibility(layer.instanceId, $event)"
              >
                <span aria-hidden="true">{{ layer.visible ? '◉' : '◯' }}</span>
              </button>
              <span class="layer-color-dot" :style="{ background: layer.accentColor }" aria-hidden="true"></span>
              <strong class="layer-name">{{ layer.name }}</strong>
              <span class="layer-chip" :style="{ background: layer.chipTone }">{{ getCategoryName(layer.category) }}</span>
              <button
                class="del-btn"
                title="移除图层"
                @click="removeItem(layer.instanceId, $event)"
              >
                <span aria-hidden="true">✕</span>
              </button>
            </div>

            <!-- 展开内容：仅在选中时显示 -->
            <div v-if="layer.instanceId === selectedInstanceId" class="layer-expanded">
              <div class="opacity-row">
                <span class="opacity-label">透明度</span>
                <input
                  type="range"
                  class="opacity-slider"
                  min="0"
                  max="100"
                  :value="Math.round(layer.opacity * 100)"
                  :style="{ '--accent': layer.accentColor }"
                  @input="changeOpacity(layer.instanceId, $event)"
                  @pointerdown.stop
                  @mousedown.stop
                  @click.stop
                />
                <span class="opacity-value">{{ Math.round(layer.opacity * 100) }}%</span>
              </div>

              <div class="layer-meta">
                <span class="availability-chip" :class="availabilityClass(layer.availabilityState)">
                  {{ layer.availabilityLabel }}
                </span>
                <span class="order-hint">顺序 {{ index + 1 }} / {{ activeLayersDisplay.length }}</span>
              </div>

              <div v-if="layer.isAdminBoundary" class="admin-tip">
                边界层级：省市级 · 静态矢量数据
              </div>

              <div v-if="layer.jobLayer" class="job-badge-row">
                <span class="job-status-badge" :class="`job-${layer.jobLayer.status}`">
                  {{ layer.jobLayer.status === 'running' ? `运行中 ${layer.jobLayer.progress}%` : layer.jobLayer.status === 'succeeded' ? '已完成' : layer.jobLayer.status === 'failed' ? '失败' : layer.jobLayer.status }}
                </span>
                <span v-if="layer.jobLayer.reportSummary" class="job-report-hint" @click.stop>
                  查看报告
                </span>
              </div>
            </div>
          </li>
        </ul>
      </template>
    </div>

    <!-- ── Footer ──────────────────────────────────────────────────────────── -->
    <p class="panel-footnote">
      <template v-if="sidebarView === 'active'">拖动排序 · 点击查看详情</template>
      <template v-else-if="sidebarView === 'library'">选择图层添加到地图</template>
      <template v-else></template>
    </p>
  </aside>
</template>

<style scoped>
/* ── Base panel ──────────────────────────────────────────────────────────── */
.panel {
  display: flex;
  flex-direction: column;
  gap: 0.42rem;
  padding: 0.46rem;
  border: 1px solid rgba(148, 163, 184, 0.15);
  border-radius: 0.88rem;
  background: linear-gradient(180deg, rgba(13, 21, 36, 0.42), rgba(8, 15, 28, 0.3));
  backdrop-filter: blur(18px);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.03),
    0 12px 26px rgba(1, 8, 16, 0.14);
  overflow: hidden;
  width: 100%;
  height: min(100%, calc(100vh - 12rem));
  max-height: min(100%, calc(100vh - 12rem));
  box-sizing: border-box;
}

/* ── Header ──────────────────────────────────────────────────────────────── */
.panel-topline {
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
  padding: 0.08rem;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
}

.header-copy {
  min-width: 0;
}

.header-actions {
  display: inline-flex;
  align-items: center;
  gap: 0.42rem;
  flex-wrap: wrap;
  justify-content: flex-end;
}

h2 {
  margin: 0;
  color: #eef6ff;
  font-size: 0.76rem;
}

.panel-subtitle {
  margin: 0.14rem 0 0;
  color: #7f93a9;
  font-size: 0.62rem;
}

.badge {
  min-width: 1.65rem;
  padding: 0.18rem 0.34rem;
  border-radius: 999px;
  background: rgba(103, 212, 255, 0.14);
  color: #8fe7ff;
  text-align: center;
  font-size: 0.58rem;
}

/* ── View tabs ──────────────────────────────────────────────────────────── */
.view-tabs {
  display: inline-flex;
  gap: 0.22rem;
  padding: 0.14rem;
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: 999px;
  background: rgba(4, 12, 23, 0.6);
  align-self: flex-start;
}

.view-tab {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.6rem;
  height: 1.6rem;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: #6e8ba0;
  cursor: pointer;
  font-size: 0.64rem;
  transition: background-color 0.18s ease, color 0.18s ease;
}

.view-tab:hover {
  background: rgba(136, 192, 255, 0.1);
  color: #c8dff0;
}

.view-tab.active {
  background: rgba(10, 132, 255, 0.24);
  color: #5ad5ff;
  box-shadow: inset 0 0 0 1px rgba(90, 213, 255, 0.2);
}

/* ── Empty state ────────────────────────────────────────────────────────── */
.empty-state {
  display: grid;
  gap: 0.42rem;
  padding: 1.8rem 0.8rem;
  text-align: center;
  align-items: center;
}

.empty-icon {
  font-size: 2.4rem;
  color: rgba(103, 212, 255, 0.2);
  animation: pulse-glow 3s ease-in-out infinite;
}

@keyframes pulse-glow {
  0%, 100% { opacity: 0.4; transform: scale(1); }
  50% { opacity: 0.8; transform: scale(1.08); }
}

.empty-title {
  margin: 0;
  color: #c8dff0;
  font-size: 0.82rem;
  font-weight: 600;
}

.empty-hint {
  margin: 0;
  color: #7f93a9;
  font-size: 0.62rem;
  line-height: 1.45;
}

.empty-cta {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.28rem;
  padding: 0.42rem 0.9rem;
  border: 1px solid rgba(90, 213, 255, 0.3);
  border-radius: 999px;
  background: rgba(10, 132, 255, 0.24);
  color: #a8e8ff;
  cursor: pointer;
  font: inherit;
  font-size: 0.64rem;
  font-weight: 600;
  align-self: center;
  margin-top: 0.2rem;
  /* 性能优化：GPU 动画，移除内联阴影计算 */
  transition: background 0.2s ease, border-color 0.2s ease, color 0.2s ease, transform 0.18s cubic-bezier(0.25, 0.46, 0.45, 0.94);
}

.empty-cta:hover {
  background: rgba(10, 132, 255, 0.38);
  border-color: rgba(90, 213, 255, 0.5);
  color: #d0f0ff;
  transform: translateY(-2px);
}

.empty-cta.small {
  padding: 0.32rem 0.7rem;
  font-size: 0.6rem;
}

/* ── Search ─────────────────────────────────────────────────────────────── */
.search-row {
  padding: 0.12rem;
}

.search-input {
  width: 100%;
  padding: 0.34rem 0.52rem;
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: 0.68rem;
  background: rgba(4, 12, 23, 0.5);
  color: #d8e4ef;
  font: inherit;
  font-size: 0.66rem;
  outline: none;
  transition: border-color 0.18s ease, background 0.18s ease;
  box-sizing: border-box;
}

.search-input::placeholder { color: #5a7080; }

.search-input:focus {
  border-color: rgba(90, 213, 255, 0.3);
  background: rgba(4, 12, 23, 0.7);
}

.search-input::-webkit-search-cancel-button { cursor: pointer; }

/* ── Quick add row ──────────────────────────────────────────────────────── */
.quick-add-row {
  padding: 0.12rem;
}

.quick-add-btn {
  display: flex;
  align-items: center;
  gap: 0.34rem;
  width: 100%;
  padding: 0.38rem 0.5rem;
  border: 1px dashed rgba(136, 216, 255, 0.25);
  border-radius: 0.68rem;
  background: rgba(136, 216, 255, 0.04);
  color: #88d8ff;
  cursor: pointer;
  font: inherit;
  font-size: 0.64rem;
  font-weight: 500;
  transition: background 0.18s ease, border-color 0.18s ease, transform 0.16s ease;
}

.quick-add-btn:hover {
  background: rgba(136, 216, 255, 0.1);
  border-color: rgba(136, 216, 255, 0.4);
  transform: translateX(2px);
}

.qa-icon { font-size: 0.72rem; }

.qa-tag {
  margin-left: auto;
  padding: 0.08rem 0.3rem;
  border-radius: 999px;
  background: rgba(136, 216, 255, 0.12);
  color: #88d8ff;
  font-size: 0.52rem;
}

/* ── Library scroll area ────────────────────────────────────────────────── */
.library-scroll {
  overflow-y: auto;
  padding: 0 0.08rem 0 0;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

/* ── Category group ─────────────────────────────────────────────────────── */
.category-group {
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
}

.category-header {
  display: flex;
  align-items: center;
  gap: 0.32rem;
  padding: 0.3rem 0.42rem;
  border: none;
  border-radius: 0.6rem;
  background: rgba(4, 12, 23, 0.3);
  color: var(--cat-color, #88d8ff);
  cursor: pointer;
  font: inherit;
  font-size: 0.62rem;
  font-weight: 600;
  transition: background 0.16s ease, transform 0.14s ease;
  text-align: left;
}

.category-header:hover {
  background: rgba(4, 12, 23, 0.5);
  transform: translateX(2px);
}

.cat-icon { font-size: 0.7rem; }

.cat-name { flex: 1; }

.cat-count {
  padding: 0.05rem 0.22rem;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
  color: #8ea3b8;
  font-size: 0.52rem;
}

.cat-arrow {
  display: inline-block;
  transition: transform 0.18s ease;
  font-size: 0.58rem;
}

/* ── Batch add button (per category) ─────────────────────────────────────── */
.cat-batch-add {
  display: block;
  margin: 0.18rem 0 0.18rem 1.2rem;
  padding: 0.18rem 0.5rem;
  border: 1px dashed rgba(255, 255, 255, 0.14);
  border-radius: 0.42rem;
  background: transparent;
  color: var(--cat-color, #88d8ff);
  cursor: pointer;
  font: inherit;
  font-size: 0.56rem;
  font-weight: 500;
  transition: background 0.14s ease, border-color 0.14s ease;
}

.cat-batch-add:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: var(--cat-color, #88d8ff);
  border-style: solid;
}

/* ── Batch toolbar (active state) ────────────────────────────────────────── */
.batch-toolbar {
  display: flex;
  gap: 0.32rem;
  padding: 0.32rem 0.4rem;
  border: 1px solid rgba(148, 163, 184, 0.12);
  border-radius: 0.6rem;
  background: rgba(4, 12, 23, 0.32);
  margin-bottom: 0.4rem;
}

.batch-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.22rem;
  padding: 0.32rem 0.2rem;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 0.42rem;
  background: rgba(13, 24, 42, 0.4);
  color: #b8c8d8;
  cursor: pointer;
  font: inherit;
  font-size: 0.58rem;
  font-weight: 500;
  transition: background 0.14s ease, border-color 0.14s ease, color 0.14s ease;
}

.batch-btn:hover {
  background: rgba(34, 52, 78, 0.5);
  border-color: rgba(103, 212, 255, 0.34);
  color: #d8e8f8;
}

.batch-btn-danger:hover {
  background: rgba(78, 24, 34, 0.4);
  border-color: rgba(255, 111, 145, 0.4);
  color: #ffb0c0;
}

.cat-arrow.expanded { transform: rotate(90deg); }

.category-items {
  display: grid;
  gap: 0.22rem;
  padding-left: 0.42rem;
}

/* ── Library card ───────────────────────────────────────────────────────── */
.library-card {
  display: grid;
  gap: 0.32rem;
  padding: 0.46rem 0.5rem;
  border: 1px solid rgba(136, 192, 255, 0.08);
  border-radius: 0.72rem;
  background: linear-gradient(135deg, rgba(8, 18, 33, 0.6), rgba(8, 18, 33, 0.4));
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.library-card:hover {
  border-color: rgba(136, 192, 255, 0.45);
  box-shadow: 0 8px 18px -8px var(--glow);
  transform: translateY(-1px);
}

.library-card.added {
  border-color: rgba(90, 213, 255, 0.18);
  background: linear-gradient(135deg, rgba(8, 18, 33, 0.7), rgba(10, 132, 255, 0.06));
}

.card-top {
  display: grid;
  gap: 0.12rem;
  /* 与 source-area 的 padding 对齐，保证三块内容左右边距一致 */
  padding: 0 0.32rem;
}

.card-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.32rem;
}

.card-title-row strong {
  color: #f3fbff;
  font-size: 0.72rem;
  font-weight: 600;
}

.card-chip {
  padding: 0.08rem 0.28rem;
  border-radius: 999px;
  color: #d9effd;
  font-size: 0.5rem;
  flex-shrink: 0;
}

.card-source {
  margin: 0;
  color: #7f93a9;
  font-size: 0.58rem;
}

/* ── Source area (数据源区域) ──────────────────────────────────────────── */
.source-area {
  display: grid;
  gap: 0.18rem;
  padding: 0.32rem;
  border: 1px solid rgba(136, 192, 255, 0.06);
  border-radius: 0.5rem;
  background: rgba(4, 12, 23, 0.32);
}

.source-empty {
  display: flex;
  align-items: center;
  gap: 0.32rem;
  color: #6a7e8e;
  font-size: 0.56rem;
}

.src-empty-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1rem;
  height: 1rem;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.05);
  color: #8a9eb0;
  font-size: 0.62rem;
}

.source-single { display: grid; gap: 0.18rem; }

.src-line {
  display: flex;
  align-items: center;
  gap: 0.3rem;
}

.src-dot {
  width: 0.42rem;
  height: 0.42rem;
  border-radius: 50%;
  flex-shrink: 0;
  box-shadow: 0 0 6px currentColor;
}

.src-name {
  color: #d4e4f4;
  font-size: 0.6rem;
  font-weight: 500;
}

.src-meta {
  display: flex;
  align-items: center;
  gap: 0.24rem;
  flex-wrap: wrap;
  padding-left: 0.72rem;
}

.src-badge {
  padding: 0.06rem 0.28rem;
  border-radius: 999px;
  background: rgba(136, 192, 255, 0.1);
  color: #8fc8e8;
  font-size: 0.5rem;
}

.src-coord {
  color: #5a7080;
  font-size: 0.5rem;
  font-family: ui-monospace, 'SF Mono', monospace;
}

.src-auth, .src-tfm {
  color: #8a9eb0;
  font-size: 0.56rem;
}

.source-multi { display: grid; gap: 0.18rem; }

.source-picker-btn {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  width: 100%;
  padding: 0.24rem 0.36rem;
  border: 1px solid rgba(136, 192, 255, 0.12);
  border-radius: 0.44rem;
  background: rgba(4, 12, 23, 0.4);
  color: #c8dff0;
  cursor: pointer;
  font: inherit;
  font-size: 0.58rem;
  transition: background 0.16s ease, border-color 0.16s ease;
}

.source-picker-btn:hover {
  background: rgba(136, 192, 255, 0.08);
  border-color: rgba(136, 192, 255, 0.28);
}

.src-current {
  flex: 1;
  text-align: left;
  color: #d4e4f4;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.src-count {
  padding: 0.04rem 0.24rem;
  border-radius: 999px;
  background: rgba(136, 192, 255, 0.14);
  color: #8fc8e8;
  font-size: 0.48rem;
  flex-shrink: 0;
}

.sp-arrow {
  display: inline-block;
  transition: transform 0.18s ease;
  font-size: 0.5rem;
  color: #8a9eb0;
}

.sp-arrow.open { transform: rotate(90deg); }

.source-list {
  display: grid;
  gap: 0.12rem;
  padding: 0.12rem 0;
}

.source-option {
  display: grid;
  gap: 0.14rem;
  padding: 0.28rem 0.36rem;
  border: 1px solid rgba(136, 192, 255, 0.08);
  border-radius: 0.42rem;
  background: rgba(4, 12, 23, 0.3);
  color: #c8dff0;
  cursor: pointer;
  font: inherit;
  text-align: left;
  transition: background 0.14s ease, border-color 0.14s ease;
}

.source-option:hover {
  background: rgba(136, 192, 255, 0.06);
  border-color: rgba(136, 192, 255, 0.22);
}

.source-option.active {
  background: rgba(10, 132, 255, 0.1);
  border-color: rgba(90, 213, 255, 0.4);
}

.src-opt-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.32rem;
}

.src-check {
  color: #5ad5ff;
  font-size: 0.58rem;
  flex-shrink: 0;
}

/* ── Card actions ───────────────────────────────────────────────────────── */
.card-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.3rem;
  /* 与 source-area 的 padding 对齐，保证三块内容左右边距一致 */
  padding: 0 0.32rem;
}

.card-metric {
  color: #7f93a9;
  font-size: 0.56rem;
}

.add-btn {
  padding: 0.18rem 0.46rem;
  border: 1px solid rgba(90, 213, 255, 0.28);
  border-radius: 999px;
  background: rgba(10, 132, 255, 0.12);
  color: #5ad5ff;
  cursor: pointer;
  font: inherit;
  font-size: 0.58rem;
  font-weight: 600;
  transition: background 0.18s ease, border-color 0.18s ease, transform 0.16s ease;
}

.add-btn:hover:not(:disabled) {
  background: rgba(10, 132, 255, 0.24);
  border-color: rgba(90, 213, 255, 0.5);
  transform: translateY(-1px);
}

.add-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.added-label {
  color: #9ff8cf;
  font-size: 0.58rem;
  font-weight: 600;
}

/* ── 工作流状态徽标（library 卡片自动运行反馈） ──────────────────────────── */
.job-status-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.22rem;
  padding: 0.12rem 0.4rem;
  border-radius: 999px;
  font-size: 0.54rem;
  font-weight: 600;
  border: 1px solid transparent;
}

.job-status-running {
  color: #5ad5ff;
  background: rgba(10, 132, 255, 0.12);
  border-color: rgba(90, 213, 255, 0.2);
}

.job-status-queued {
  color: #d7c1ff;
  background: rgba(187, 137, 255, 0.08);
  border-color: rgba(187, 137, 255, 0.14);
}

.job-status-succeeded {
  color: #9ff8cf;
  background: rgba(114, 255, 207, 0.1);
  border-color: rgba(114, 255, 207, 0.18);
}

.job-status-failed {
  color: #ff8080;
  background: rgba(255, 80, 80, 0.1);
  border-color: rgba(255, 80, 80, 0.18);
}

.spin-dot {
  display: inline-block;
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  border: 1.5px solid rgba(90, 213, 255, 0.3);
  border-top-color: #5ad5ff;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ── Active state ───────────────────────────────────────────────────────── */
.active-state {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  flex: 1;
  /* 列表内容超出时由 layer-list 滚动 */
  min-height: 0;
  overflow: hidden;
}

.no-layers {
  display: grid;
  gap: 0.42rem;
  padding: 1.4rem 0.8rem;
  text-align: center;
  color: #7f93a9;
  font-size: 0.62rem;
}

/* 图层列表：参考 ArcGIS Pro 紧凑设计
   - 不强制撑满侧边栏高度（无 flex:1），按内容高度排列
   - 列表项较多时仍可滚动 */
.layer-list {
  display: grid;
  gap: 0.16rem;
  list-style: none;
  padding: 0;
  margin: 0;
  /* 关键：内容多时自动滚动，内容少时按内容高度排列（不撑满） */
  overflow-y: auto;
  align-content: start;
  flex: 0 1 auto;
  min-height: 0;
  padding-right: 0.08rem;
}

/* ── Layer item ────────────────────────────────────────────────────────── */
.layer-item {
  display: grid;
  /* 折叠态：无 gap，紧凑单行 */
  gap: 0;
  padding: 0.26rem 0.42rem;
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: 0.5rem;
  background: rgba(8, 18, 33, 0.5);
  color: #d8e4ef;
  cursor: pointer;
  font: inherit;
  font-size: 0.66rem;
  /* 性能优化：移除非必要的 transform 过渡，避免触发重排 */
  transition: border-color 0.2s ease, background-color 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease;
  user-select: none;
}

.layer-item:hover {
  border-color: rgba(90, 162, 255, 0.4);
  box-shadow: 0 4px 10px -8px rgba(90, 106, 128, 0.3);
}

.layer-item.active,
.layer-item.expanded {
  /* 展开态：增加 gap 和 padding 给内容呼吸感 */
  gap: 0.22rem;
  padding: 0.34rem 0.5rem;
}

.layer-item.active {
  background: rgba(90, 162, 255, 0.12);
  border-color: rgba(90, 162, 255, 0.5);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.02), 0 12px 22px -20px rgba(90, 106, 128, 0.3);
}

.layer-item.hidden {
  opacity: 0.55;
}

.layer-item.drag-over {
  border-color: rgba(90, 213, 255, 0.6);
  background: rgba(10, 132, 255, 0.08);
  transition: border-color 0.08s ease, background-color 0.08s ease;
}

/* ── Layer row top (主行紧凑布局) ──────────────────────────────────────── */
.layer-row-top {
  display: flex;
  align-items: center;
  gap: 0.24rem;
}

.drag-handle {
  color: #3d5060;
  font-size: 0.56rem;
  cursor: grab;
  flex-shrink: 0;
  transition: color 0.16s ease;
}

.drag-handle:hover { color: #8ea3b8; }
.drag-handle:active { cursor: grabbing; }

.vis-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 1.05rem;
  height: 1.05rem;
  border: none;
  border-radius: 0.36rem;
  background: transparent;
  color: #6e8ba0;
  cursor: pointer;
  font-size: 0.62rem;
  flex-shrink: 0;
  transition: color 0.16s ease, background 0.16s ease;
  padding: 0;
}

.vis-btn:hover {
  background: rgba(136, 192, 255, 0.1);
  color: #c8dff0;
}

.layer-color-dot {
  width: 0.36rem;
  height: 0.36rem;
  border-radius: 50%;
  flex-shrink: 0;
  box-shadow: 0 0 4px currentColor;
}

.layer-name {
  flex: 1;
  color: #f3fbff;
  font-size: 0.68rem;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.layer-chip {
  padding: 0.06rem 0.24rem;
  border-radius: 999px;
  color: #d9effd;
  font-size: 0.48rem;
  flex-shrink: 0;
}

.del-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 1.05rem;
  height: 1.05rem;
  border: none;
  border-radius: 0.36rem;
  background: transparent;
  color: #4a5560;
  cursor: pointer;
  font-size: 0.56rem;
  flex-shrink: 0;
  transition: color 0.16s ease, background 0.16s ease;
  padding: 0;
}

.del-btn:hover {
  background: rgba(255, 100, 100, 0.12);
  color: #ff8080;
}

/* ── Layer expanded (展开内容) ──────────────────────────────────────────── */
.layer-expanded {
  display: grid;
  gap: 0.18rem;
  padding-top: 0.18rem;
  border-top: 1px solid rgba(136, 192, 255, 0.08);
  margin-top: 0.12rem;
}

/* ── Opacity slider ────────────────────────────────────────────────────── */
.opacity-row {
  display: flex;
  align-items: center;
  gap: 0.32rem;
  padding: 0.12rem 0;
}

.opacity-label {
  color: #7f93a9;
  font-size: 0.56rem;
  flex-shrink: 0;
  width: 2.2rem;
}

.opacity-slider {
  flex: 1;
  -webkit-appearance: none;
  height: 3px;
  border-radius: 999px;
  background: rgba(136, 192, 255, 0.12);
  outline: none;
  cursor: pointer;
}

.opacity-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 0.8rem;
  height: 0.8rem;
  border-radius: 50%;
  background: var(--accent, #5ad5ff);
  box-shadow: 0 0 6px var(--accent, #5ad5ff);
  cursor: pointer;
  transition: transform 0.14s ease;
}

.opacity-slider::-webkit-slider-thumb:hover {
  transform: scale(1.2);
}

.opacity-slider::-moz-range-thumb {
  width: 0.8rem;
  height: 0.8rem;
  border: none;
  border-radius: 50%;
  background: var(--accent, #5ad5ff);
  box-shadow: 0 0 6px var(--accent, #5ad5ff);
  cursor: pointer;
}

.opacity-value {
  color: #8ea3b8;
  font-size: 0.56rem;
  width: 1.8rem;
  text-align: right;
  flex-shrink: 0;
}

/* ── Layer meta ────────────────────────────────────────────────────────── */
.layer-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.3rem;
}

.availability-chip {
  padding: 0.08rem 0.28rem;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.12);
  background: rgba(148, 163, 184, 0.08);
  font-size: 0.52rem;
}

.availability-ready { color: #9ff8cf; border-color: rgba(114, 255, 207, 0.2); background: rgba(114, 255, 207, 0.1); }
.availability-partial { color: #ffd38a; border-color: rgba(255, 196, 120, 0.18); background: rgba(255, 196, 120, 0.08); }
.availability-empty { color: #cbb8ff; border-color: rgba(187, 137, 255, 0.18); background: rgba(187, 137, 255, 0.08); }

.order-hint {
  color: #5a7080;
  font-size: 0.52rem;
}

/* ── Admin tip ─────────────────────────────────────────────────────────── */
.admin-tip {
  padding: 0.18rem 0.34rem;
  border-radius: 0.5rem;
  background: rgba(136, 216, 255, 0.06);
  border: 1px solid rgba(136, 216, 255, 0.1);
  color: #7fbbdd;
  font-size: 0.54rem;
}

/* ── Job badge ─────────────────────────────────────────────────────────── */
.job-badge-row {
  display: flex;
  align-items: center;
  gap: 0.32rem;
}

.job-status-badge {
  padding: 0.08rem 0.3rem;
  border-radius: 999px;
  font-size: 0.54rem;
  font-weight: 600;
}

.job-running {
  color: #5ad5ff;
  background: rgba(10, 132, 255, 0.12);
  border: 1px solid rgba(90, 213, 255, 0.2);
}

.job-succeeded {
  color: #9ff8cf;
  background: rgba(114, 255, 207, 0.1);
  border: 1px solid rgba(114, 255, 207, 0.18);
}

.job-failed {
  color: #ff8080;
  background: rgba(255, 80, 80, 0.1);
  border: 1px solid rgba(255, 80, 80, 0.18);
}

.job-queued, .job-cancelled {
  color: #d7c1ff;
  background: rgba(187, 137, 255, 0.08);
  border: 1px solid rgba(187, 137, 255, 0.14);
}

.job-report-hint {
  margin-left: auto;
  color: #5ad5ff;
  font-size: 0.54rem;
  cursor: pointer;
  text-decoration: underline;
  text-decoration-style: dotted;
}

/* ── Footer ─────────────────────────────────────────────────────────────── */
.panel-footnote {
  margin: 0;
  padding: 0.12rem;
  color: #7f95aa;
  line-height: 1.35;
  font-size: 0.64rem;
}
</style>
