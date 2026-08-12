<script setup lang="ts">
import { LAYERS_COPY, INSPECT_COPY } from '../../ui-copy'
import { Info, Lock, Settings } from 'lucide-vue-next'
import type { RuntimeLayerLibraryItem } from '../../stores/layers/types'
import AppSelect from '../ui/AppSelect.vue'

defineProps<{
  searchQuery: string
  selectedSubCategory: string
  filteredLibraryByCategory: Array<{ category: any; items: RuntimeLayerLibraryItem[] }>
  researchSubCategoryPills: string[]
  expandedCategories: Set<string>
  isAdded: (catalogId: string) => boolean
  weatherProvidersLoading: Record<string, boolean>
  weatherSourcePrefsValue: (catalogId: string) => string
  weatherProvidersFor: (catalogId: string) => any[]
  weatherProviderOptionLabel: (p: any) => string
  weatherSourceQualityHint: (catalogId: string) => string | null
  weatherSourceSparseHint: (catalogId: string) => boolean
  getCatalogJobStatus: (catalogId: string) => string | undefined
  getCatalogRunBlockReason: (catalogId: string) => string | null
  getCatalogSemanticNote: (catalogId: string) => string | null
  catalogSemanticNoteClass: (catalogId: string) => string
  getCategoryMeta: (categoryId: string) => any
  getCategoryName: (categoryId: string) => string
  getCatalogSourceSummary: (catalogId: string) => string
  getPrimarySourceName: (catalogId: string) => string
  orgLabel: string
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
      <div
        v-for="group in filteredLibraryByCategory"
        :key="group.category.id"
        class="category-group"
      >
        <div
          class="category-header-row"
          :style="{ '--cat-color': getCategoryMeta(group.category.id)?.accentColor ?? '#88d8ff' }"
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
              <span
                class="cat-arrow"
                :class="{ expanded: expandedCategories.has(group.category.id) }"
                >▸</span
              >
            </button>
          </div>
        </div>

        <div v-if="expandedCategories.has(group.category.id)" class="category-items">
          <!-- 课题组数据二级分类筛选 Pills -->
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
              orgLabel
            }}图层
          </div>
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
                <div class="chips-group">
                  <span class="card-chip" :style="{ background: item.chipTone }">{{
                    getCategoryName(item.category)
                  }}</span>
                  <span
                    v-if="item.subCategory"
                    class="card-chip subcategory-chip"
                    style="
                      background: rgba(255, 255, 255, 0.08);
                      margin-left: 4px;
                      color: #a4caf6;
                    "
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
                  <div class="source-summary" :title="getCatalogSourceSummary(item.catalogId)">
                    <span class="src-dot" :style="{ background: item.accentColor }"></span>
                    <span class="src-current">{{ getPrimarySourceName(item.catalogId) }}</span>
                    <span class="src-count">{{ item.sources.length }} 个候选源</span>
                  </div>
                  <div class="source-list source-list-static">
                    <div
                      v-for="src in item.sources"
                      :key="src.id"
                      class="source-option source-option-static"
                      :title="src.description"
                    >
                      <div class="src-opt-top">
                        <span class="src-name">{{ src.name }}</span>
                      </div>
                      <div class="src-meta">
                        <span class="src-badge">{{ src.updateFrequency }}</span>
                        <span class="src-coord">{{ src.coordSys }}</span>
                        <Lock v-if="src.needsAuth" :size="14" class="src-auth" title="需要认证" />
                      </div>
                    </div>
                  </div>
                </div>
              </template>
            </div>

            <div class="card-actions">
              <span class="card-metric">{{ item.metricLabel }}: {{ item.metricUnit }}</span>
              <button
                v-if="!isAdded(item.catalogId)"
                class="add-btn"
                :disabled="isAdded(item.catalogId)"
                :title="getCatalogRunBlockReason(item.catalogId) ?? ''"
                @click="emit('addCatalogItem', item.catalogId)"
              >
                + 添加
              </button>
              <!-- 已添加：显示工作流状态徽标 -->
              <span
                v-else-if="getCatalogJobStatus(item.catalogId) === 'running'"
                class="job-status-chip job-status-running"
              >
                <span class="spin-dot" aria-hidden="true"></span>运行中
              </span>
              <span
                v-else-if="getCatalogJobStatus(item.catalogId) === 'queued'"
                class="job-status-chip job-status-queued"
              >
                排队中
              </span>
              <span
                v-else-if="getCatalogJobStatus(item.catalogId) === 'retry_pending'"
                class="job-status-chip job-status-queued"
              >
                等待重试
              </span>
              <span
                v-else-if="getCatalogJobStatus(item.catalogId) === 'succeeded'"
                class="job-status-chip job-status-succeeded"
              >
                已就绪 ✓
              </span>
              <span
                v-else-if="getCatalogJobStatus(item.catalogId) === 'failed'"
                class="job-status-chip job-status-failed"
              >
                运行失败
              </span>
              <span
                v-else-if="getCatalogJobStatus(item.catalogId) === 'cancelled'"
                class="job-status-chip job-status-cancelled"
              >
                已取消
              </span>
              <span v-else class="added-label">已添加 ✓</span>
            </div>
            <div
              v-if="getCatalogSemanticNote(item.catalogId)"
              class="run-block-note"
              :class="catalogSemanticNoteClass(item.catalogId)"
            >
              {{ getCatalogSemanticNote(item.catalogId) }}
            </div>
          </div>
        </div>
      </div>
    </div>
</template>

<style scoped src="./LayerSidebar.styles.css"></style>
