<script setup lang="ts">
import { ref, watch } from 'vue'
import { LAYERS_COPY, INSPECT_COPY } from '../../ui-copy'
import { Info, Lock, Settings, Check } from '../ui/icons'
import type { LayerCategory, RuntimeLayerLibraryItem } from '../../stores/layers/types'
import type { WeatherProviderForLayer } from '../../services/runtime-api'
import AppSelect from '../ui/AppSelect.vue'

const props = defineProps<{
  searchQuery: string
  selectedSubCategory: string
  filteredLibraryByCategory: Array<{ category: LayerCategory; items: RuntimeLayerLibraryItem[] }>
  researchSubCategoryPills: string[]
  expandedCategories: Set<string>
  isAdded: (catalogId: string) => boolean
  weatherProvidersLoading: Record<string, boolean>
  weatherSourcePrefsValue: (catalogId: string) => string
  weatherProvidersFor: (catalogId: string) => WeatherProviderForLayer[]
  weatherProviderOptionLabel: (p: WeatherProviderForLayer) => string
  weatherSourceQualityHint: (catalogId: string) => string | null
  weatherSourceSparseHint: (catalogId: string) => boolean
  getCatalogJobStatus: (catalogId: string) => string | undefined
  getCatalogRunBlockReason: (catalogId: string) => string | null
  getCatalogAddBlockReason: (catalogId: string) => string | null
  isOverlayDisplayOnlyLayer: (catalogId: string) => boolean
  getCatalogSemanticNote: (catalogId: string) => string | null
  catalogSemanticNoteClass: (catalogId: string) => string
  getCategoryMeta: (categoryId: string) => LayerCategory | undefined
  getCategoryName: (categoryId: string) => string
  getCatalogSourceSummary: (catalogId: string) => string
  getPrimarySourceName: (catalogId: string) => string
  supportsOnlineTemporal: (catalogId: string) => boolean
}>()

const emit = defineEmits<{
  'update:searchQuery': [value: string]
  'update:selectedSubCategory': [value: string]
  ensureWeatherProviders: [catalogId: string]
  onWeatherSourceChange: [catalogId: string, value: string]
  addAllInCategory: [items: RuntimeLayerLibraryItem[]]
  addCatalogItem: [catalogId: string]
  toggleCategory: [categoryId: string]
}>()

// ── 多源合并条目的源选择状态（禁止在 render 路径里写入）──────────────────────
const selectedSourceByCatalog = ref<Record<string, string>>({})

watch(
  () => props.filteredLibraryByCategory,
  (groups) => {
    for (const group of groups) {
      for (const item of group.items) {
        if (item.sources.length <= 1) continue
        const stored = selectedSourceByCatalog.value[item.catalogId]
        if (stored && item.sources.some((s) => s.id === stored)) continue
        const firstId = item.sources[0]?.id
        if (firstId) selectedSourceByCatalog.value[item.catalogId] = firstId
      }
    }
  },
  { immediate: true, deep: true },
)

function effectiveSourceId(item: RuntimeLayerLibraryItem): string {
  if (item.sources.length <= 1) return item.catalogId
  const stored = selectedSourceByCatalog.value[item.catalogId]
  if (stored && item.sources.some((s) => s.id === stored)) return stored
  return item.sources[0]?.id ?? item.catalogId
}

function effectiveSource(item: RuntimeLayerLibraryItem) {
  const sid = effectiveSourceId(item)
  return item.sources.find((s) => s.id === sid) ?? item.sources[0]
}

function selectSource(catalogId: string, sourceId: string) {
  selectedSourceByCatalog.value[catalogId] = sourceId
}

function addCatalogItemWithSource(item: RuntimeLayerLibraryItem) {
  emit('addCatalogItem', effectiveSourceId(item))
}
</script>

<template>
  <!-- ── LIBRARY STATE ───────────────────────────────────────────────────── -->
  <!-- Search -->
  <div class="search-row">
    <input
      :value="searchQuery"
      class="search-input"
      placeholder="搜索图层..."
      type="search"
      @input="emit('update:searchQuery', ($event.target as HTMLInputElement).value)"
    />
  </div>

  <!-- Category groups -->
  <div class="library-scroll">
    <div v-for="group in filteredLibraryByCategory" :key="group.category.id" class="category-group">
      <div
        class="category-header-row"
        :style="{
          '--cat-color': getCategoryMeta(group.category.id)?.accentColor ?? 'var(--accent)',
        }"
      >
        <button
          class="category-header"
          type="button"
          @click="emit('toggleCategory', group.category.id)"
        >
          <span class="cat-icon" aria-hidden="true">{{
            getCategoryMeta(group.category.id)?.icon ?? '◈'
          }}</span>
          <span class="cat-name">{{
            getCategoryMeta(group.category.id)?.name ?? group.category.id
          }}</span>
        </button>
        <div class="cat-header-actions">
          <span class="cat-count">{{ group.items.length }}</span>
          <button
            class="cat-batch-add"
            type="button"
            title="添加此分类下所有图层"
            @click="emit('addAllInCategory', group.items)"
          >
            +全部
          </button>
          <button
            class="cat-expand"
            type="button"
            :aria-expanded="expandedCategories.has(group.category.id)"
            :title="expandedCategories.has(group.category.id) ? '收起' : '展开'"
            @click="emit('toggleCategory', group.category.id)"
          >
            <span class="cat-arrow" :class="{ expanded: expandedCategories.has(group.category.id) }"
              >▸</span
            >
          </button>
        </div>
      </div>

      <div v-if="expandedCategories.has(group.category.id)" class="category-items">
        <!-- 核心资产二级分类筛选 Pills -->
        <div
          v-if="group.category.id === 'research-group' && researchSubCategoryPills.length > 1"
          class="subcategory-pills-bar"
        >
          <button
            v-for="sub in researchSubCategoryPills"
            :key="sub"
            type="button"
            class="sub-pill"
            :class="{ active: selectedSubCategory === sub }"
            @click.stop="emit('update:selectedSubCategory', sub)"
          >
            {{ sub === 'all' ? '全部' : sub }}
          </button>
        </div>
        <div v-if="group.items.length === 0" class="empty-subcategory-hint">
          暂无匹配【{{ selectedSubCategory === 'all' ? '全部' : selectedSubCategory }}】的{{
            getCategoryName('research-group')
          }}图层
        </div>
        <div
          v-for="(item, index) in group.items"
          :key="item.catalogId"
          v-spotlight="{ color: item.accentGlow || 'rgba(56, 189, 248, 0.08)' }"
          class="library-card cgda-stagger-item"
          :class="{ added: isAdded(effectiveSourceId(item)) }"
          :style="{
            '--accent': item.accentColor,
            '--glow': item.accentGlow,
            '--stagger-i': index,
          }"
        >
          <div class="card-top">
            <div class="card-title-row">
              <strong>{{ item.name }}</strong>
              <div class="chips-group">
                <span class="card-chip" :style="{ background: item.chipTone }">{{
                  getCategoryName(item.category)
                }}</span>
                <span
                  v-if="item.subCategory"
                  class="card-chip subcategory-chip"
                  style="background: var(--surface-hover); margin-left: 4px; color: var(--accent)"
                  >{{ item.subCategory }}</span
                >
              </div>
            </div>
            <p class="card-source">{{ item.sourceLabel }}</p>
          </div>

          <!-- 数据源区域：天气图层用运行时 Provider；其它图层仍用目录静态 sources -->
          <div class="source-area">
            <template v-if="item.category === 'weather'">
              <div class="source-weather-live">
                <label class="weather-src-label">
                  <span class="src-dot" :style="{ background: item.accentColor }"></span>
                  <AppSelect
                    :model-value="weatherSourcePrefsValue(item.catalogId)"
                    :disabled="!!weatherProvidersLoading[item.catalogId]"
                    @focus="emit('ensureWeatherProviders', item.catalogId)"
                    @change="(val: string) => emit('onWeatherSourceChange', item.catalogId, val)"
                  >
                    <option value="auto">{{ INSPECT_COPY.providerAuto }}</option>
                    <option
                      v-for="p in weatherProvidersFor(item.catalogId)"
                      :key="p.provider_id"
                      :value="p.provider_id"
                      :disabled="!p.enabled"
                    >
                      {{ weatherProviderOptionLabel(p) }}
                    </option>
                  </AppSelect>
                </label>
                <p v-if="weatherSourceQualityHint(item.catalogId)" class="src-sparse-hint">
                  {{ weatherSourceQualityHint(item.catalogId) }}
                </p>
                <p v-else-if="weatherSourceSparseHint(item.catalogId)" class="src-sparse-hint">
                  点查可用；瓦片将回落到稠密数据源（Open-Meteo）
                </p>
                <p
                  v-else-if="
                    !weatherProvidersLoading[item.catalogId] &&
                    weatherProvidersFor(item.catalogId).length === 0
                  "
                  class="src-sparse-hint"
                >
                  展开或聚焦时加载可用源…
                </p>
              </div>
            </template>
            <template v-else>
              <div
                v-if="item.sources.length === 0"
                class="source-empty"
                :title="'该图层暂未接入数据源'"
              >
                <Info :size="14" class="src-empty-icon" aria-hidden="true" />
                <span>{{ LAYERS_COPY.noDataSource }}</span>
              </div>
              <div v-else-if="item.sources.length === 1" class="source-single">
                <div class="src-line">
                  <span class="src-dot" :style="{ background: item.accentColor }"></span>
                  <span class="src-name">{{ item.sources[0].name }}</span>
                </div>
                <div class="src-meta">
                  <span class="src-badge">{{ item.sources[0].updateFrequency }}</span>
                  <span class="src-coord">{{ item.sources[0].coordSys }}</span>
                  <Lock
                    v-if="item.sources[0].needsAuth"
                    :size="14"
                    class="src-auth"
                    title="需要认证"
                  />
                  <Settings
                    v-if="item.sources[0].needsBackendTransform"
                    :size="14"
                    class="src-tfm"
                    title="后端转换"
                  />
                </div>
              </div>
              <div v-else class="source-multi">
                <div class="source-selector">
                  <label class="source-selector-label">
                    <span class="src-dot" :style="{ background: item.accentColor }"></span>
                    <AppSelect
                      :model-value="effectiveSourceId(item)"
                      size="sm"
                      block
                      @change="(val: string) => selectSource(item.catalogId, val)"
                    >
                      <option v-for="src in item.sources" :key="src.id" :value="src.id">
                        {{ src.name }}{{ isAdded(src.id) ? ' ✓' : '' }}
                      </option>
                    </AppSelect>
                  </label>
                </div>
                <div class="src-meta">
                  <span class="src-badge">{{ effectiveSource(item).updateFrequency }}</span>
                  <span class="src-coord">{{ effectiveSource(item).coordSys }}</span>
                  <Lock
                    v-if="effectiveSource(item).needsAuth"
                    :size="14"
                    class="src-auth"
                    title="需要认证"
                  />
                </div>
              </div>
            </template>
          </div>

          <div class="card-actions">
            <span class="card-metric">{{ item.metricLabel }}: {{ item.metricUnit }}</span>
            <span
              v-if="supportsOnlineTemporal(effectiveSourceId(item))"
              class="online-fetch-badge"
              title="此图层支持在线获取历史时间数据"
              >在线获取</span
            >
            <button
              v-if="!isAdded(effectiveSourceId(item))"
              class="add-btn"
              :disabled="isAdded(effectiveSourceId(item))"
              :title="getCatalogAddBlockReason(effectiveSourceId(item)) ?? ''"
              @click="addCatalogItemWithSource(item)"
            >
              + 添加
            </button>
            <!-- 2026-08-25 UX 简化：添加即自动运行/加载，中间态徽标全部隐藏；
                 仅失败时可见（报错必须呈现），成功后回到「已添加」。
                 注意：徽标链必须保持 v-else-if / v-else 挂在上方 add-btn 的
                 v-if 链上——拆成独立 v-if 会让「已添加」无条件显示
                 （2026-08-25 刷新后全库假「已添加」报障根因）。 -->
            <span
              v-else-if="getCatalogJobStatus(effectiveSourceId(item)) === 'failed'"
              class="job-status-chip job-status-failed"
              :title="getCatalogRunBlockReason(effectiveSourceId(item)) ?? ''"
            >
              运行失败
            </span>
            <span v-else class="added-label">已添加 <Check :size="14" aria-hidden="true" /></span>
          </div>
          <div
            v-if="getCatalogSemanticNote(effectiveSourceId(item))"
            class="run-block-note"
            :class="catalogSemanticNoteClass(effectiveSourceId(item))"
          >
            {{ getCatalogSemanticNote(effectiveSourceId(item)) }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped src="./LayerSidebar.styles.css"></style>
