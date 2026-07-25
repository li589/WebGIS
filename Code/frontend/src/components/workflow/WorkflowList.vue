<script setup lang="ts">
/**
 * WorkflowList.vue
 *
 * 工作流列表侧边栏：显示模板、系统预设和用户工作流。
 * 支持选中、新建、复制、删除用户工作流、使用模板创建。
 * 支持按 category 分类过滤和标签显示。
 */
import { ref, computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useWorkflowDefinitionsStore } from '../../stores/workflow-definitions'
import type { WorkflowDefinitionSummary } from '../../services/workflow-definition-api'
import InlineLoader from '../common/InlineLoader.vue'

const emit = defineEmits<{
  select: [workflowId: string]
  create: []
}>()

const store = useWorkflowDefinitionsStore()
const { summaries, systemWorkflows, userWorkflows, currentDefinition, loading } = storeToRefs(store)

const confirmDeleteId = ref<string | null>(null)
const duplicateSourceId = ref<string | null>(null)
const duplicateNewId = ref('')
const duplicateNewName = ref('')

// ── 分类过滤 ──────────────────────────────────────────────────────────
/** 分类标签映射：后端 category → 中文显示名 + 颜色 */
const CATEGORY_LABELS: Record<string, { label: string; color: string }> = {
  inversion: { label: '反演', color: '#5ad5ff' },
  weather: { label: '天气', color: '#ffd38a' },
  data_access: { label: '数据获取', color: '#a6e3a1' },
  demo: { label: '演示', color: '#f38ba8' },
}

/** 当前选中的分类过滤器：null = 全部 */
const activeCategory = ref<string | null>(null)

/** 所有可用分类（从 summaries 中动态提取） */
const availableCategories = computed(() => {
  const cats = new Set<string>()
  for (const s of summaries.value) {
    if (s.category) cats.add(s.category)
  }
  return Array.from(cats).sort()
})

/** 分类徽章信息 */
function categoryBadge(cat: string | null | undefined) {
  if (!cat) return null
  return CATEGORY_LABELS[cat] ?? { label: cat, color: '#6e8ba0' }
}

/** 按分类过滤后的工作流列表 */
function filterByCategory(list: WorkflowDefinitionSummary[]) {
  if (!activeCategory.value) return list
  return list.filter((s) => s.category === activeCategory.value)
}

// 范例工作流：以后端 _meta.is_template 为准（不再硬编码过时 ID）
const templateWorkflows = computed(() =>
  filterByCategory(systemWorkflows.value.filter((s) => Boolean(s.is_template))),
)

// 非范例的系统预设工作流
const systemWorkflowsNonTemplate = computed(() =>
  filterByCategory(systemWorkflows.value.filter((s) => !s.is_template)),
)

// 用户工作流
const userWorkflowsFiltered = computed(() => filterByCategory(userWorkflows.value))

// 使用模板创建新工作流
const useTemplateSourceId = ref<string | null>(null)
const useTemplateNewId = ref('')
const useTemplateNewName = ref('')

function handleUseTemplate(summary: WorkflowDefinitionSummary) {
  useTemplateSourceId.value = summary.workflow_id
  useTemplateNewId.value = `${summary.workflow_id}_instance_${Date.now().toString(36)}`
  useTemplateNewName.value = `${summary.name}（范例副本）`
}

async function confirmUseTemplate() {
  if (!useTemplateSourceId.value || !useTemplateNewId.value.trim()) return
  try {
    const created = await store.duplicate(
      useTemplateSourceId.value,
      useTemplateNewId.value.trim(),
      useTemplateNewName.value.trim() || undefined,
    )
    // 自动选中新创建的工作流
    await store.loadDefinition(created.workflow_id)
    emit('select', created.workflow_id)
  } catch (err) {
    console.error('[WorkflowList] Failed to instantiate template:', err)
  } finally {
    useTemplateSourceId.value = null
    useTemplateNewId.value = ''
    useTemplateNewName.value = ''
  }
}

function cancelUseTemplate() {
  useTemplateSourceId.value = null
  useTemplateNewId.value = ''
  useTemplateNewName.value = ''
}

function handleSelect(summary: WorkflowDefinitionSummary) {
  emit('select', summary.workflow_id)
}

function handleDelete(workflowId: string) {
  confirmDeleteId.value = workflowId
}

async function confirmDelete() {
  if (!confirmDeleteId.value) return
  try {
    await store.remove(confirmDeleteId.value)
  } catch (err) {
    console.error('[WorkflowList] Failed to delete workflow:', err)
  } finally {
    confirmDeleteId.value = null
  }
}

function cancelDelete() {
  confirmDeleteId.value = null
}

function handleDuplicate(workflowId: string) {
  duplicateSourceId.value = workflowId
  // 默认新 ID 加 _copy 后缀
  duplicateNewId.value = `${workflowId}_copy`
  duplicateNewName.value = ''
}

async function confirmDuplicate() {
  if (!duplicateSourceId.value || !duplicateNewId.value.trim()) return
  try {
    await store.duplicate(
      duplicateSourceId.value,
      duplicateNewId.value.trim(),
      duplicateNewName.value.trim() || undefined,
    )
  } catch (err) {
    console.error('[WorkflowList] Failed to duplicate workflow:', err)
  } finally {
    duplicateSourceId.value = null
    duplicateNewId.value = ''
    duplicateNewName.value = ''
  }
}

function cancelDuplicate() {
  duplicateSourceId.value = null
  duplicateNewId.value = ''
  duplicateNewName.value = ''
}

function isActive(summary: WorkflowDefinitionSummary): boolean {
  return currentDefinition.value?.workflow_id === summary.workflow_id
}

function formatTime(iso: string | null): string {
  if (!iso) return '-'
  try {
    const d = new Date(iso)
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  } catch {
    return iso
  }
}
</script>

<template>
  <div class="workflow-list">
    <div class="list-header">
      <span class="header-title">工作流</span>
      <button class="new-btn" type="button" @click="emit('create')" title="新建工作流">
        <span aria-hidden="true">+</span>
        <span>新建</span>
      </button>
    </div>

    <InlineLoader v-if="loading" label="加载中..." size="sm" />

    <div v-else class="list-content">
      <!-- 分类过滤栏 -->
      <div v-if="availableCategories.length > 0" class="category-filter">
        <button
          class="cat-chip"
          :class="{ active: activeCategory === null }"
          type="button"
          @click="activeCategory = null"
        >
          全部
        </button>
        <button
          v-for="cat in availableCategories"
          :key="cat"
          class="cat-chip"
          :class="{ active: activeCategory === cat }"
          :style="
            activeCategory === cat
              ? { borderColor: categoryBadge(cat)?.color, color: categoryBadge(cat)?.color }
              : {}
          "
          type="button"
          @click="activeCategory = cat"
        >
          {{ categoryBadge(cat)?.label ?? cat }}
        </button>
      </div>

      <!-- 范例工作流 -->
      <section v-if="templateWorkflows.length" class="list-section">
        <h3 class="section-title">
          <span class="section-icon" aria-hidden="true">📋</span>
          <span>范例</span>
          <span class="section-count">{{ templateWorkflows.length }}</span>
        </h3>
        <div class="section-items">
          <button
            v-for="summary in templateWorkflows"
            :key="summary.workflow_id"
            class="workflow-item template-item"
            :class="{ active: isActive(summary) }"
            type="button"
            @click="handleSelect(summary)"
          >
            <div class="item-header">
              <span class="item-title">{{ summary.name }}</span>
              <div class="item-badges">
                <span
                  v-if="categoryBadge(summary.category)"
                  class="cat-badge"
                  :style="{
                    color: categoryBadge(summary.category)?.color,
                    borderColor: categoryBadge(summary.category)?.color,
                  }"
                  >{{ categoryBadge(summary.category)?.label }}</span
                >
                <span class="template-badge">范例</span>
              </div>
            </div>
            <div v-if="summary.description" class="item-desc">{{ summary.description }}</div>
            <div class="item-meta">
              <span class="meta-engine">{{ summary.engine }}</span>
              <span class="meta-nodes">{{ summary.node_count }} 节点</span>
            </div>
            <button
              class="use-template-btn"
              type="button"
              title="基于此范例创建新工作流"
              @click.stop="handleUseTemplate(summary)"
            >
              <span aria-hidden="true">⚡</span>
              <span>从范例新建</span>
            </button>
          </button>
        </div>
      </section>

      <!-- 系统预设工作流 -->
      <section v-if="systemWorkflowsNonTemplate.length" class="list-section">
        <h3 class="section-title">
          <span class="section-icon" aria-hidden="true">⚙</span>
          <span>系统预设</span>
          <span class="section-count">{{ systemWorkflowsNonTemplate.length }}</span>
        </h3>
        <div class="section-items">
          <button
            v-for="summary in systemWorkflowsNonTemplate"
            :key="summary.workflow_id"
            class="workflow-item"
            :class="{ active: isActive(summary) }"
            type="button"
            @click="handleSelect(summary)"
          >
            <div class="item-header">
              <span class="item-title">{{ summary.name }}</span>
              <div class="item-badges">
                <span
                  v-if="categoryBadge(summary.category)"
                  class="cat-badge"
                  :style="{
                    color: categoryBadge(summary.category)?.color,
                    borderColor: categoryBadge(summary.category)?.color,
                  }"
                  >{{ categoryBadge(summary.category)?.label }}</span
                >
                <span v-if="summary.readonly" class="readonly-badge" aria-label="只读">🔒</span>
              </div>
            </div>
            <div v-if="summary.description" class="item-desc">{{ summary.description }}</div>
            <div class="item-meta">
              <span class="meta-engine">{{ summary.engine }}</span>
              <span class="meta-nodes">{{ summary.node_count }} 节点</span>
              <span class="meta-time">{{ formatTime(summary.updated_at) }}</span>
            </div>
          </button>
        </div>
      </section>

      <!-- 用户工作流 -->
      <section v-if="userWorkflowsFiltered.length" class="list-section">
        <h3 class="section-title">
          <span class="section-icon" aria-hidden="true">◈</span>
          <span>用户工作流</span>
          <span class="section-count">{{ userWorkflowsFiltered.length }}</span>
        </h3>
        <div class="section-items">
          <button
            v-for="summary in userWorkflowsFiltered"
            :key="summary.workflow_id"
            class="workflow-item"
            :class="{ active: isActive(summary) }"
            type="button"
            @click="handleSelect(summary)"
          >
            <div class="item-header">
              <span class="item-title">{{ summary.name }}</span>
              <div class="item-actions">
                <span
                  v-if="categoryBadge(summary.category)"
                  class="cat-badge"
                  :style="{
                    color: categoryBadge(summary.category)?.color,
                    borderColor: categoryBadge(summary.category)?.color,
                  }"
                  >{{ categoryBadge(summary.category)?.label }}</span
                >
                <button
                  class="action-btn"
                  type="button"
                  title="复制"
                  @click.stop="handleDuplicate(summary.workflow_id)"
                >
                  ⧉
                </button>
                <button
                  class="action-btn danger"
                  type="button"
                  title="删除"
                  @click.stop="handleDelete(summary.workflow_id)"
                >
                  ✕
                </button>
              </div>
            </div>
            <div v-if="summary.description" class="item-desc">{{ summary.description }}</div>
            <div class="item-meta">
              <span class="meta-engine">{{ summary.engine }}</span>
              <span class="meta-nodes">{{ summary.node_count }} 节点</span>
              <span class="meta-time">{{ formatTime(summary.updated_at) }}</span>
            </div>
          </button>
        </div>
      </section>

      <div
        v-if="
          summaries.length === 0 ||
          (activeCategory &&
            !templateWorkflows.length &&
            !systemWorkflowsNonTemplate.length &&
            !userWorkflowsFiltered.length)
        "
        class="list-empty"
      >
        <span class="empty-icon" aria-hidden="true">◇</span>
        <span class="empty-text">暂无工作流</span>
        <span class="empty-hint">{{
          activeCategory ? '该分类下暂无工作流' : '点击"新建"创建第一个工作流'
        }}</span>
      </div>
    </div>

    <!-- 删除确认对话框 -->
    <div v-if="confirmDeleteId" class="dialog-overlay" @click.self="cancelDelete">
      <div class="dialog">
        <h3 class="dialog-title">确认删除</h3>
        <p class="dialog-text">确定要删除工作流 "{{ confirmDeleteId }}" 吗？此操作无法撤销。</p>
        <div class="dialog-actions">
          <button class="dialog-btn cancel" type="button" @click="cancelDelete">取消</button>
          <button class="dialog-btn danger" type="button" @click="confirmDelete">删除</button>
        </div>
      </div>
    </div>

    <!-- 复制对话框 -->
    <div v-if="duplicateSourceId" class="dialog-overlay" @click.self="cancelDuplicate">
      <div class="dialog">
        <h3 class="dialog-title">复制工作流</h3>
        <div class="dialog-form">
          <div class="form-row">
            <label class="form-label">新工作流 ID</label>
            <input
              v-model="duplicateNewId"
              type="text"
              class="form-input"
              placeholder="workflow_id"
            />
          </div>
          <div class="form-row">
            <label class="form-label">新名称（可选）</label>
            <input
              v-model="duplicateNewName"
              type="text"
              class="form-input"
              placeholder="显示名称"
            />
          </div>
        </div>
        <div class="dialog-actions">
          <button class="dialog-btn cancel" type="button" @click="cancelDuplicate">取消</button>
          <button
            class="dialog-btn primary"
            type="button"
            :disabled="!duplicateNewId.trim()"
            @click="confirmDuplicate"
          >
            复制
          </button>
        </div>
      </div>
    </div>

    <!-- 从范例新建对话框 -->
    <div v-if="useTemplateSourceId" class="dialog-overlay" @click.self="cancelUseTemplate">
      <div class="dialog">
        <h3 class="dialog-title">从范例新建工作流</h3>
        <p class="dialog-text">
          将基于范例「{{
            useTemplateSourceId
          }}」创建可编辑的用户工作流副本（保留关联图层，便于直接运行）。
        </p>
        <div class="dialog-form">
          <div class="form-row">
            <label class="form-label">新工作流 ID</label>
            <input
              v-model="useTemplateNewId"
              type="text"
              class="form-input"
              placeholder="workflow_id"
            />
          </div>
          <div class="form-row">
            <label class="form-label">新名称（可选）</label>
            <input
              v-model="useTemplateNewName"
              type="text"
              class="form-input"
              placeholder="显示名称"
            />
          </div>
        </div>
        <div class="dialog-actions">
          <button class="dialog-btn cancel" type="button" @click="cancelUseTemplate">取消</button>
          <button
            class="dialog-btn primary"
            type="button"
            :disabled="!useTemplateNewId.trim()"
            @click="confirmUseTemplate"
          >
            创建
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.workflow-list {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: rgba(8, 17, 31, 0.72);
  color: #c4d6e8;
}

.list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.62rem 0.72rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.1);
}

.header-title {
  font-size: 0.7rem;
  font-weight: 600;
  color: #d8e6f5;
}

.new-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.18rem;
  padding: 0.26rem 0.52rem;
  border: 1px solid rgba(90, 213, 255, 0.3);
  border-radius: 0.4rem;
  background: rgba(10, 132, 255, 0.14);
  color: #5ad5ff;
  cursor: pointer;
  font: inherit;
  font-size: 0.58rem;
  font-weight: 600;
  transition: background 0.16s ease;
}

.new-btn:hover {
  background: rgba(10, 132, 255, 0.24);
}

.list-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.42rem;
  padding: 2rem 1rem;
  color: #5a7080;
  font-size: 0.62rem;
  text-align: center;
}

.empty-icon {
  font-size: 1.8rem;
  opacity: 0.4;
}

.list-content {
  flex: 1;
  overflow-y: auto;
  padding: 0.42rem 0;
  scrollbar-width: thin;
  scrollbar-color: rgba(90, 180, 255, 0.28) transparent;
}

/* ── 分类过滤栏 ──────────────────────────────────────────────────── */
.category-filter {
  display: flex;
  flex-wrap: wrap;
  gap: 0.22rem;
  padding: 0.32rem 0.72rem 0.42rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.06);
  margin-bottom: 0.32rem;
}

.cat-chip {
  padding: 0.16rem 0.46rem;
  border: 1px solid rgba(136, 192, 255, 0.12);
  border-radius: 999px;
  background: transparent;
  color: #6e8ba0;
  cursor: pointer;
  font: inherit;
  font-size: 0.52rem;
  font-weight: 500;
  transition: all 0.16s ease;
  white-space: nowrap;
}

.cat-chip:hover {
  border-color: rgba(136, 192, 255, 0.3);
  color: #c4d6e8;
}

.cat-chip.active {
  border-color: rgba(90, 213, 255, 0.4);
  background: rgba(10, 132, 255, 0.14);
  color: #5ad5ff;
}

/* ── 分类徽章 ────────────────────────────────────────────────────── */
.item-badges {
  display: flex;
  align-items: center;
  gap: 0.22rem;
  flex-shrink: 0;
}

.cat-badge {
  padding: 0.02rem 0.3rem;
  border: 1px solid;
  border-radius: 0.2rem;
  font-size: 0.48rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  background: rgba(136, 192, 255, 0.04);
}

.list-content::-webkit-scrollbar {
  width: 4px;
}

.list-content::-webkit-scrollbar-track {
  background: transparent;
}

.list-content::-webkit-scrollbar-thumb {
  background: rgba(90, 180, 255, 0.26);
  border-radius: 3px;
}

.list-content::-webkit-scrollbar-thumb:hover {
  background: rgba(90, 180, 255, 0.45);
}

.list-section {
  margin-bottom: 0.32rem;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 0.32rem;
  margin: 0;
  padding: 0.32rem 0.72rem;
  font-size: 0.58rem;
  font-weight: 600;
  color: #6e8ba0;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.section-icon {
  font-size: 0.66rem;
  opacity: 0.7;
}

.section-count {
  padding: 0.02rem 0.28rem;
  border-radius: 999px;
  background: rgba(136, 192, 255, 0.06);
  color: #5a7080;
  font-size: 0.5rem;
}

.section-items {
  padding: 0 0.32rem;
}

.workflow-item {
  display: flex;
  flex-direction: column;
  gap: 0.22rem;
  width: 100%;
  margin-bottom: 0.18rem;
  padding: 0.42rem 0.52rem;
  border: 1px solid rgba(136, 192, 255, 0.08);
  border-radius: 0.42rem;
  background: rgba(4, 12, 23, 0.4);
  color: #c4d6e8;
  cursor: pointer;
  font: inherit;
  text-align: left;
  transition:
    border-color 0.16s ease,
    background 0.16s ease;
}

.workflow-item:hover {
  border-color: rgba(90, 213, 255, 0.24);
  background: rgba(10, 132, 255, 0.08);
}

.workflow-item.active {
  border-color: rgba(90, 213, 255, 0.4);
  background: rgba(10, 132, 255, 0.18);
  box-shadow: inset 0 0 0 1px rgba(90, 213, 255, 0.16);
}

.item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.32rem;
}

.item-title {
  flex: 1;
  font-size: 0.64rem;
  font-weight: 600;
  color: #d8e6f5;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.readonly-badge {
  font-size: 0.6rem;
  opacity: 0.7;
}

.item-actions {
  display: flex;
  gap: 0.18rem;
}

.action-btn {
  width: 1.2rem;
  height: 1.2rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid transparent;
  border-radius: 0.32rem;
  background: transparent;
  color: #6e8ba0;
  cursor: pointer;
  font: inherit;
  font-size: 0.56rem;
  transition: all 0.16s ease;
}

.action-btn:hover {
  border-color: rgba(136, 192, 255, 0.2);
  background: rgba(136, 192, 255, 0.08);
  color: #d8e6f5;
}

.action-btn.danger:hover {
  border-color: rgba(255, 120, 120, 0.3);
  background: rgba(255, 120, 120, 0.1);
  color: #ff9b9b;
}

.item-desc {
  font-size: 0.56rem;
  color: #6e8ba0;
  line-height: 1.3;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.item-meta {
  display: flex;
  align-items: center;
  gap: 0.32rem;
  font-size: 0.5rem;
  color: #5a7080;
}

.meta-engine {
  padding: 0.02rem 0.28rem;
  border-radius: 0.24rem;
  background: rgba(136, 192, 255, 0.06);
  color: #5ad5ff;
  font-family: 'Consolas', 'Monaco', monospace;
}

/* ── 对话框 ──────────────────────────────────────────────────────── */
.dialog-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(4, 10, 18, 0.6);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
}

.dialog {
  width: 22rem;
  max-width: 92vw;
  padding: 1rem;
  border: 1px solid rgba(136, 192, 255, 0.18);
  border-radius: 0.72rem;
  background: rgba(8, 17, 31, 0.98);
  box-shadow: 0 18px 48px rgba(1, 8, 16, 0.4);
}

.dialog-title {
  margin: 0 0 0.62rem;
  font-size: 0.78rem;
  font-weight: 600;
  color: #d8e6f5;
}

.dialog-text {
  margin: 0 0 0.72rem;
  color: #8aa8bf;
  font-size: 0.62rem;
  line-height: 1.5;
}

.dialog-form {
  margin-bottom: 0.72rem;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.42rem;
}

.dialog-btn {
  padding: 0.36rem 0.82rem;
  border: 1px solid rgba(136, 192, 255, 0.2);
  border-radius: 0.42rem;
  background: transparent;
  color: #c4d6e8;
  cursor: pointer;
  font: inherit;
  font-size: 0.6rem;
  font-weight: 500;
  transition: all 0.16s ease;
}

.dialog-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.dialog-btn.cancel:hover {
  background: rgba(136, 192, 255, 0.06);
}

.dialog-btn.primary {
  border-color: rgba(90, 213, 255, 0.4);
  background: rgba(10, 132, 255, 0.2);
  color: #5ad5ff;
}

.dialog-btn.primary:hover:not(:disabled) {
  background: rgba(10, 132, 255, 0.32);
}

.dialog-btn.danger {
  border-color: rgba(255, 120, 120, 0.3);
  background: rgba(255, 80, 80, 0.14);
  color: #ff9b9b;
}

.dialog-btn.danger:hover {
  background: rgba(255, 80, 80, 0.24);
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: 0.22rem;
  margin-bottom: 0.52rem;
}

.form-label {
  font-size: 0.56rem;
  color: #6e8ba0;
}

.form-input {
  padding: 0.36rem 0.46rem;
  border: 1px solid rgba(136, 192, 255, 0.14);
  border-radius: 0.36rem;
  background: rgba(4, 12, 23, 0.6);
  color: #d8e6f5;
  font: inherit;
  font-size: 0.6rem;
}

.form-input:focus {
  outline: none;
  border-color: rgba(90, 213, 255, 0.4);
}

/* ── 模板项样式 ──────────────────────────────────────────────────── */
.template-item {
  position: relative;
}

.template-badge {
  padding: 0.02rem 0.32rem;
  border-radius: 0.2rem;
  background: rgba(255, 184, 77, 0.16);
  color: #ffd38a;
  font-size: 0.5rem;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.use-template-btn {
  margin-top: 0.32rem;
  padding: 0.28rem 0.5rem;
  border: 1px dashed rgba(255, 184, 77, 0.4);
  border-radius: 0.32rem;
  background: rgba(255, 184, 77, 0.06);
  color: #ffd38a;
  cursor: pointer;
  font: inherit;
  font-size: 0.56rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.22rem;
  transition:
    background 0.16s ease,
    border-color 0.16s ease;
}

.use-template-btn:hover {
  background: rgba(255, 184, 77, 0.16);
  border-color: rgba(255, 184, 77, 0.6);
}
</style>
