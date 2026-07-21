<script setup lang="ts">
/**
 * WorkflowList.vue
 *
 * 工作流列表侧边栏：显示模板、系统预设和用户工作流。
 * 支持选中、新建、复制、删除用户工作流、使用模板创建。
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

// 模板工作流 ID 列表（与后端 .data/workflow_definitions/system/*.json 中 is_template=true 的工作流对应）
const TEMPLATE_IDS = new Set(['gis_terrain_analysis', 'preprocess_pipeline', 'stats_analysis'])

// 模板工作流：从系统工作流中过滤出标记为模板的（按 workflow_id 识别）
const templateWorkflows = computed(() =>
  systemWorkflows.value.filter((s) => TEMPLATE_IDS.has(s.workflow_id)),
)

// 非模板的系统预设工作流
const systemWorkflowsNonTemplate = computed(() =>
  systemWorkflows.value.filter((s) => !TEMPLATE_IDS.has(s.workflow_id)),
)

// 使用模板创建新工作流
const useTemplateSourceId = ref<string | null>(null)
const useTemplateNewId = ref('')
const useTemplateNewName = ref('')

function handleUseTemplate(summary: WorkflowDefinitionSummary) {
  useTemplateSourceId.value = summary.workflow_id
  useTemplateNewId.value = `${summary.workflow_id}_instance_${Date.now().toString(36)}`
  useTemplateNewName.value = `${summary.name}（副本）`
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
    await store.duplicate(duplicateSourceId.value, duplicateNewId.value.trim(), duplicateNewName.value.trim() || undefined)
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
      <!-- 模板工作流 -->
      <section v-if="templateWorkflows.length" class="list-section">
        <h3 class="section-title">
          <span class="section-icon" aria-hidden="true">📋</span>
          <span>模板</span>
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
              <span class="template-badge">模板</span>
            </div>
            <div v-if="summary.description" class="item-desc">{{ summary.description }}</div>
            <div class="item-meta">
              <span class="meta-engine">{{ summary.engine }}</span>
              <span class="meta-nodes">{{ summary.node_count }} 节点</span>
            </div>
            <button
              class="use-template-btn"
              type="button"
              title="基于此模板创建新工作流"
              @click.stop="handleUseTemplate(summary)"
            >
              <span aria-hidden="true">⚡</span>
              <span>使用此模板</span>
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
              <span v-if="summary.readonly" class="readonly-badge" aria-label="只读">🔒</span>
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
      <section v-if="userWorkflows.length" class="list-section">
        <h3 class="section-title">
          <span class="section-icon" aria-hidden="true">◈</span>
          <span>用户工作流</span>
          <span class="section-count">{{ userWorkflows.length }}</span>
        </h3>
        <div class="section-items">
          <button
            v-for="summary in userWorkflows"
            :key="summary.workflow_id"
            class="workflow-item"
            :class="{ active: isActive(summary) }"
            type="button"
            @click="handleSelect(summary)"
          >
            <div class="item-header">
              <span class="item-title">{{ summary.name }}</span>
              <div class="item-actions">
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

      <div v-if="summaries.length === 0" class="list-empty">
        <span class="empty-icon" aria-hidden="true">◇</span>
        <span class="empty-text">暂无工作流</span>
        <span class="empty-hint">点击"新建"创建第一个工作流</span>
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
            <input v-model="duplicateNewId" type="text" class="form-input" placeholder="workflow_id" />
          </div>
          <div class="form-row">
            <label class="form-label">新名称（可选）</label>
            <input v-model="duplicateNewName" type="text" class="form-input" placeholder="显示名称" />
          </div>
        </div>
        <div class="dialog-actions">
          <button class="dialog-btn cancel" type="button" @click="cancelDuplicate">取消</button>
          <button class="dialog-btn primary" type="button" :disabled="!duplicateNewId.trim()" @click="confirmDuplicate">复制</button>
        </div>
      </div>
    </div>

    <!-- 使用模板对话框 -->
    <div v-if="useTemplateSourceId" class="dialog-overlay" @click.self="cancelUseTemplate">
      <div class="dialog">
        <h3 class="dialog-title">基于模板创建工作流</h3>
        <p class="dialog-text">
          将基于模板 "{{ useTemplateSourceId }}" 创建一个新的用户工作流副本，您可在副本上自由修改。
        </p>
        <div class="dialog-form">
          <div class="form-row">
            <label class="form-label">新工作流 ID</label>
            <input v-model="useTemplateNewId" type="text" class="form-input" placeholder="workflow_id" />
          </div>
          <div class="form-row">
            <label class="form-label">新名称（可选）</label>
            <input v-model="useTemplateNewName" type="text" class="form-input" placeholder="显示名称" />
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
  transition: border-color 0.16s ease, background 0.16s ease;
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
  transition: background 0.16s ease, border-color 0.16s ease;
}

.use-template-btn:hover {
  background: rgba(255, 184, 77, 0.16);
  border-color: rgba(255, 184, 77, 0.6);
}
</style>
