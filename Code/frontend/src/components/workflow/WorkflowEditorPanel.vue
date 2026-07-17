<script setup lang="ts">
/**
 * WorkflowEditorPanel.vue
 *
 * 工作流编辑器主面板（精简版）：
 *   ┌──────────┬───────────────────────────┬──────────┐
 *   │ 工作流    │                           │  节点库   │
 *   │ 列表     │       LiteGraph 画布        │          │
 *   │          │                           ├──────────┤
 *   │          │                           │  属性     │
 *   │          │                           │  检查器   │
 *   └──────────┴───────────────────────────┴──────────┘
 *
 * 左右面板已拆分为 WorkflowLeftSidebar / WorkflowRightSidebar 独立组件。
 * 顶部工具栏：保存 / 排列 / 适配视图 / 清空 / 运行
 */
import { onMounted, onBeforeUnmount, ref, shallowRef, computed } from 'vue'
import { storeToRefs } from 'pinia'

import { useWorkflowDefinitionsStore } from '../../stores/workflow-definitions'
import { useUiLoadingStore } from '../../stores/ui-loading'
import { useLogStore } from '../../stores/log'

import WorkflowCanvas from './WorkflowCanvas.vue'
import WorkflowLeftSidebar from './WorkflowLeftSidebar.vue'
import WorkflowRightSidebar from './WorkflowRightSidebar.vue'
import WorkflowRunDialog, { type WorkflowRunTarget } from './WorkflowRunDialog.vue'

import type { LGraphNodeClass } from './litegraph-setup'
import type { NodeTemplate, WorkflowDefinitionNode, WorkflowDefinitionLink } from '../../services/workflow-definition-api'

const emit = defineEmits<{
  close: []
  run: [workflowId: string, linkedLayerId: string | null, target: WorkflowRunTarget]
}>()

const store = useWorkflowDefinitionsStore()
const { nodeTemplates, currentDefinition, isReadonly, error } = storeToRefs(store)
const logStore = useLogStore()

// 选中节点状态
const selectedNode = shallowRef<LGraphNodeClass | null>(null)

// 画布组件引用
const canvasRef = ref<InstanceType<typeof WorkflowCanvas> | null>(null)

// 保存状态
const saving = ref(false)
const saveError = ref<string | null>(null)
const dirty = ref(false)

// 运行状态
const running = ref(false)
const runStatus = ref<'idle' | 'submitting' | 'submitted' | 'error'>('idle')
// 运行按钮状态恢复定时器（组件销毁时需清理，避免修改已卸载组件的 ref）
let _runStatusTimer1: ReturnType<typeof setTimeout> | null = null
let _runStatusTimer2: ReturnType<typeof setTimeout> | null = null

// 运行对话框
const showRunDialog = ref(false)

// 左右面板收起状态
const leftSidebarCollapsed = ref(false)
const rightSidebarCollapsed = ref(false)

// 导入导出
const fileInputRef = ref<HTMLInputElement | null>(null)

// 新建对话框
const showCreateDialog = ref(false)
const newWorkflowId = ref('')
const newWorkflowName = ref('')
const newWorkflowDescription = ref('')
const newWorkflowEngine = ref<'general' | 'weather' | 'python_provider' | 'gee'>('general')

// 当前画布数据（未保存的修改）
const currentGraphData = ref<{ nodes: WorkflowDefinitionNode[]; links: WorkflowDefinitionLink[] } | null>(null)

const hasDefinition = computed(() => currentDefinition.value !== null)
const canSave = computed(() => hasDefinition.value && !isReadonly.value && dirty.value && !saving.value)
const canRun = computed(() => hasDefinition.value && !running.value)
const currentEngine = computed(() => currentDefinition.value?._meta?.engine ?? 'general')
const currentLinkedLayerId = computed(() => currentDefinition.value?._meta?.linked_layer_id ?? null)
const headerWorkflowLabel = computed(() => {
  if (!currentDefinition.value) return ''
  const name = currentDefinition.value.name
  return dirty.value ? `${name} *` : name
})

// ─── 生命周期 ───────────────────────────────────────────────────────────────

onMounted(async () => {
  const loading = useUiLoadingStore()
  try {
    await Promise.all([
      store.loadNodeTemplates(),
      store.loadSummaries(),
    ])
  } finally {
    // 对应 DashboardView 中 workflowEditorOpen watch 的 showImmediate
    loading.hideImmediate()
  }
})

onBeforeUnmount(() => {
  // 清理运行状态恢复定时器，避免组件销毁后修改已卸载的 ref
  if (_runStatusTimer1 !== null) {
    clearTimeout(_runStatusTimer1)
    _runStatusTimer1 = null
  }
  if (_runStatusTimer2 !== null) {
    clearTimeout(_runStatusTimer2)
    _runStatusTimer2 = null
  }
})

// ─── 事件处理 ───────────────────────────────────────────────────────────────

async function handleSelectWorkflow(workflowId: string) {
  selectedNode.value = null
  dirty.value = false
  saveError.value = null
  await store.loadDefinition(workflowId)
  logStore.logOperation('workflow-select', `选中工作流: ${workflowId}`)
}

function handleCreateWorkflow() {
  showCreateDialog.value = true
  newWorkflowId.value = `user_${Date.now()}`
  newWorkflowName.value = ''
  newWorkflowDescription.value = ''
  newWorkflowEngine.value = 'general'
}

async function confirmCreateWorkflow() {
  if (!newWorkflowId.value.trim() || !newWorkflowName.value.trim()) return
  try {
    const created = await store.createNew({
      workflow_id: newWorkflowId.value.trim(),
      name: newWorkflowName.value.trim(),
      description: newWorkflowDescription.value.trim() || undefined,
      engine: newWorkflowEngine.value,
      nodes: [],
      links: [],
    })
    showCreateDialog.value = false
    logStore.logOperation('workflow-create', `创建工作流: ${created.workflow_id}`)
    // 自动选中新建的工作流
    await store.loadDefinition(created.workflow_id)
  } catch (err) {
    console.error('[WorkflowEditorPanel] Failed to create workflow:', err)
    saveError.value = err instanceof Error ? err.message : String(err)
  }
}

function cancelCreateWorkflow() {
  showCreateDialog.value = false
}

function handleGraphChange(payload: { nodes: WorkflowDefinitionNode[]; links: WorkflowDefinitionLink[] }) {
  currentGraphData.value = payload
  if (!isReadonly.value) {
    dirty.value = true
  }
}

function handleNodeSelect(node: LGraphNodeClass | null) {
  selectedNode.value = node
}

function handleAddNode(template: NodeTemplate) {
  if (!hasDefinition.value || isReadonly.value || !canvasRef.value) return
  const node = canvasRef.value.addNodeByType(template.type)
  if (node) {
    dirty.value = true
    logStore.logOperation('workflow-add-node', `添加节点: ${template.type}`)
  }
}

function handleUpdateProperty(key: string, value: unknown) {
  if (!selectedNode.value || isReadonly.value) return
  selectedNode.value.setProperty(key, value)
  dirty.value = true
}

function handleUpdateTitle(title: string) {
  if (!selectedNode.value || isReadonly.value) return
  selectedNode.value.title = title
  dirty.value = true
}

async function handleSave() {
  if (!canSave.value || !currentDefinition.value) return
  saving.value = true
  saveError.value = null
  try {
    const payload = currentGraphData.value ?? {
      nodes: currentDefinition.value.nodes,
      links: currentDefinition.value.links,
    }
    await store.updateCurrent({
      name: currentDefinition.value.name,
      description: currentDefinition.value.description ?? undefined,
      nodes: payload.nodes,
      links: payload.links,
    })
    dirty.value = false
    logStore.logOperation('workflow-save', `保存工作流: ${currentDefinition.value.workflow_id}`)
  } catch (err) {
    console.error('[WorkflowEditorPanel] Failed to save workflow:', err)
    saveError.value = err instanceof Error ? err.message : String(err)
  } finally {
    saving.value = false
  }
}

function handleArrange() {
  canvasRef.value?.arrangeNodes()
}

function handleFitView() {
  canvasRef.value?.fitView()
}

function handleClear() {
  if (!hasDefinition.value || isReadonly.value) return
  if (!confirm('确定要清空当前画布吗？所有节点和连线将被移除。')) return
  canvasRef.value?.clearGraph()
  dirty.value = true
}

function handleRun() {
  if (!currentDefinition.value || running.value) return
  const linkedLayerId = currentDefinition.value._meta?.linked_layer_id ?? null
  if (!linkedLayerId) {
    logStore.logWorkflow('workflow-editor-error', `工作流 ${currentDefinition.value.workflow_id} 未关联图层，无法运行`)
    return
  }
  // 显示产出目标选择对话框
  showRunDialog.value = true
}

function handleRunConfirm(target: WorkflowRunTarget) {
  if (!currentDefinition.value) return
  const linkedLayerId = currentDefinition.value._meta?.linked_layer_id ?? null
  showRunDialog.value = false
  running.value = true
  runStatus.value = 'submitting'
  emit('run', currentDefinition.value.workflow_id, linkedLayerId, target)
  // 1.5s 后恢复按钮状态（实际进度由 WorkflowStatusPanel 显示）
  // 保存 timer 句柄，组件销毁时清理避免内存泄漏
  _runStatusTimer1 = setTimeout(() => {
    running.value = false
    runStatus.value = 'submitted'
    _runStatusTimer2 = setTimeout(() => { runStatus.value = 'idle' }, 2000)
  }, 1500)
}

function handleRunCancel() {
  showRunDialog.value = false
}

// ─── 导入导出 ───────────────────────────────────────────────────────────────

function handleExport() {
  if (!currentDefinition.value) return
  const graphData = canvasRef.value?.getSerializedGraph()
  const exportData = {
    workflow_id: currentDefinition.value.workflow_id,
    name: currentDefinition.value.name,
    description: currentDefinition.value.description,
    engine: currentDefinition.value._meta?.engine ?? 'general',
    nodes: graphData?.nodes ?? currentDefinition.value.nodes,
    links: graphData?.links ?? currentDefinition.value.links,
    exported_at: new Date().toISOString(),
    version: '1.0',
  }
  const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${currentDefinition.value.workflow_id}.json`
  a.click()
  URL.revokeObjectURL(url)
  logStore.logOperation('workflow-export', `导出工作流: ${currentDefinition.value.workflow_id}`)
}

function handleImportClick() {
  fileInputRef.value?.click()
}

async function handleImportFile(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.files?.length) return
  const file = input.files[0]
  try {
    const text = await file.text()
    const data = JSON.parse(text)
    if (!data.nodes || !data.links || !data.workflow_id) {
      throw new Error('无效的工作流文件格式')
    }
    // 创建新工作流（用导入的 ID 或生成新 ID）
    const newId = `imported_${Date.now()}`
    const created = await store.createNew({
      workflow_id: newId,
      name: data.name ?? file.name.replace(/\.json$/, ''),
      description: data.description ?? '导入的工作流',
      engine: data.engine ?? 'general',
      nodes: data.nodes,
      links: data.links,
    })
    await store.loadDefinition(created.workflow_id)
    dirty.value = false
    logStore.logOperation('workflow-import', `导入工作流: ${file.name} → ${newId}`)
  } catch (err) {
    console.error('[WorkflowEditorPanel] Import failed:', err)
    saveError.value = `导入失败：${err instanceof Error ? err.message : String(err)}`
  } finally {
    input.value = ''  // 重置 input 以允许重复导入同一文件
  }
}

function handleClose() {
  if (dirty.value && !isReadonly.value) {
    if (!confirm('有未保存的修改，确定要关闭吗？')) return
  }
  emit('close')
}
</script>

<template>
  <div class="editor-overlay" @click.self="handleClose">
    <div class="editor-panel">
      <!-- 顶部工具栏 -->
      <header class="editor-header">
        <div class="header-left">
          <span class="header-icon" aria-hidden="true">⬡</span>
          <span class="header-title">流配置</span>
          <span v-if="currentDefinition" class="header-sep">/</span>
          <span v-if="currentDefinition" class="header-workflow-name">{{ headerWorkflowLabel }}</span>
          <span v-if="isReadonly" class="readonly-badge">只读</span>
          <span v-if="dirty && !isReadonly" class="dirty-badge" title="有未保存的修改">● 未保存</span>
        </div>

        <div class="header-actions">
          <button
            class="header-btn"
            type="button"
            :disabled="!hasDefinition || isReadonly"
            @click="handleArrange"
            title="自动排列节点"
          >
            <span aria-hidden="true">⊞</span>
            <span>排列</span>
          </button>
          <button
            class="header-btn"
            type="button"
            :disabled="!hasDefinition"
            @click="handleFitView"
            title="适配视图"
          >
            <span aria-hidden="true">⊡</span>
            <span>适配</span>
          </button>
          <button
            class="header-btn"
            type="button"
            :disabled="!hasDefinition || isReadonly"
            @click="handleClear"
            title="清空画布"
          >
            <span aria-hidden="true">⊘</span>
            <span>清空</span>
          </button>
          <span class="action-divider"></span>
          <button
            class="header-btn"
            type="button"
            :disabled="!hasDefinition"
            @click="handleExport"
            title="导出为 JSON"
          >
            <span aria-hidden="true">⬇</span>
            <span>导出</span>
          </button>
          <button
            class="header-btn"
            type="button"
            @click="handleImportClick"
            title="从 JSON 导入"
          >
            <span aria-hidden="true">⬆</span>
            <span>导入</span>
          </button>
          <input
            ref="fileInputRef"
            type="file"
            accept=".json,application/json"
            style="display:none"
            @change="handleImportFile"
          />
          <span class="action-divider"></span>
          <button
            class="header-btn primary"
            type="button"
            :disabled="!canSave"
            @click="handleSave"
          >
            <span aria-hidden="true">{{ saving ? '◌' : '💾' }}</span>
            <span>{{ saving ? '保存中...' : '保存' }}</span>
          </button>
          <button
            class="header-btn run"
            type="button"
            :class="{ submitting: runStatus === 'submitting', submitted: runStatus === 'submitted' }"
            :disabled="!canRun"
            @click="handleRun"
            :title="runStatus === 'submitting' ? '正在提交...' : runStatus === 'submitted' ? '已提交，查看状态面板' : '运行工作流'"
          >
            <span aria-hidden="true">{{ runStatus === 'submitting' ? '◌' : runStatus === 'submitted' ? '✓' : '▶' }}</span>
            <span>{{ runStatus === 'submitting' ? '提交中...' : runStatus === 'submitted' ? '已提交' : '运行' }}</span>
          </button>
          <span class="action-divider"></span>
          <button class="header-btn close" type="button" @click="handleClose" title="关闭">
            <span aria-hidden="true">✕</span>
          </button>
        </div>
      </header>

      <!-- 错误提示 -->
      <div v-if="error || saveError" class="editor-error-bar">
        <span class="error-icon" aria-hidden="true">⚠</span>
        <span class="error-text">{{ saveError ?? error }}</span>
        <button class="error-dismiss" type="button" @click="saveError = null">✕</button>
      </div>

      <!-- 主体三栏布局 -->
      <div class="editor-body">
        <!-- 左侧：工作流列表（独立组件） -->
        <WorkflowLeftSidebar
          v-model:collapsed="leftSidebarCollapsed"
          @select="handleSelectWorkflow"
          @create="handleCreateWorkflow"
        />

        <!-- 中间：画布 -->
        <main class="editor-canvas-area">
          <div v-if="!hasDefinition" class="canvas-placeholder">
            <div class="placeholder-content">
              <span class="placeholder-icon" aria-hidden="true">⬡</span>
              <h2 class="placeholder-title">工作流编辑器</h2>
              <p class="placeholder-text">从左侧选择一个工作流，或点击"新建"创建一个</p>
              <p class="placeholder-hint">支持天气引擎、Python 处理器、GEE 三种引擎节点</p>
            </div>
          </div>
          <WorkflowCanvas
            v-else
            ref="canvasRef"
            :definition="currentDefinition"
            :node-templates="nodeTemplates"
            :readonly="isReadonly"
            @change="handleGraphChange"
            @node-select="handleNodeSelect"
          />
        </main>

        <!-- 右侧：节点库 + 属性检查器（独立组件） -->
        <WorkflowRightSidebar
          v-model:collapsed="rightSidebarCollapsed"
          :selected-node="selectedNode"
          :readonly="isReadonly"
          @add-node="handleAddNode"
          @update-property="handleUpdateProperty"
          @update-title="handleUpdateTitle"
        />
      </div>
    </div>

    <!-- 运行工作流：产出目标选择对话框 -->
    <WorkflowRunDialog
      :visible="showRunDialog"
      :workflow-id="currentDefinition?.workflow_id ?? ''"
      :workflow-name="currentDefinition?.name ?? ''"
      :linked-layer-id="currentLinkedLayerId"
      :engine="currentEngine"
      @confirm="handleRunConfirm"
      @cancel="handleRunCancel"
    />

    <!-- 新建工作流对话框 -->
    <div v-if="showCreateDialog" class="create-dialog-overlay" @click.self="cancelCreateWorkflow">
      <div class="create-dialog">
        <h3 class="dialog-title">新建工作流</h3>
        <div class="dialog-form">
          <div class="form-row">
            <label class="form-label">工作流 ID</label>
            <input v-model="newWorkflowId" type="text" class="form-input" placeholder="唯一标识符" />
          </div>
          <div class="form-row">
            <label class="form-label">名称 *</label>
            <input v-model="newWorkflowName" type="text" class="form-input" placeholder="显示名称" />
          </div>
          <div class="form-row">
            <label class="form-label">描述</label>
            <textarea v-model="newWorkflowDescription" class="form-textarea" rows="2" placeholder="可选描述"></textarea>
          </div>
          <div class="form-row">
            <label class="form-label">引擎</label>
            <select v-model="newWorkflowEngine" class="form-select">
              <option value="general">通用</option>
              <option value="weather">天气引擎</option>
              <option value="python_provider">Python 处理器</option>
              <option value="gee">GEE</option>
            </select>
          </div>
        </div>
        <div class="dialog-actions">
          <button class="dialog-btn cancel" type="button" @click="cancelCreateWorkflow">取消</button>
          <button
            class="dialog-btn primary"
            type="button"
            :disabled="!newWorkflowId.trim() || !newWorkflowName.trim()"
            @click="confirmCreateWorkflow"
          >
            创建
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.editor-overlay {
  position: fixed;
  inset: 0;
  z-index: 997;
  display: flex;
  align-items: stretch;
  justify-content: stretch;
  background: rgba(4, 10, 18, 0.85);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
}

.editor-panel {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  background: rgba(6, 13, 24, 0.98);
}

/* ── 顶部工具栏 ──────────────────────────────────────────────────── */
.editor-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.52rem 0.72rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.14);
  background: rgba(8, 17, 31, 0.9);
  flex: none;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 0.42rem;
  min-width: 0;
}

.header-icon {
  font-size: 0.92rem;
  color: #5ad5ff;
}

.header-title {
  font-size: 0.78rem;
  font-weight: 600;
  color: #d8e6f5;
}

.header-sep {
  color: #4a5a6a;
}

.header-workflow-name {
  font-size: 0.7rem;
  color: #88dfff;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.readonly-badge,
.dirty-badge {
  padding: 0.08rem 0.42rem;
  border-radius: 0.32rem;
  font-size: 0.52rem;
  font-weight: 600;
}

.readonly-badge {
  background: rgba(255, 180, 90, 0.18);
  color: #ffd9a8;
  border: 1px solid rgba(255, 180, 90, 0.2);
}

.dirty-badge {
  background: rgba(255, 220, 120, 0.18);
  color: #ffe89a;
  border: 1px solid rgba(255, 220, 120, 0.2);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 0.28rem;
}

.header-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.22rem;
  padding: 0.32rem 0.56rem;
  border: 1px solid rgba(136, 192, 255, 0.14);
  border-radius: 0.42rem;
  background: rgba(4, 12, 23, 0.6);
  color: #9fb6cc;
  cursor: pointer;
  font: inherit;
  font-size: 0.6rem;
  font-weight: 500;
  transition: all 0.16s ease;
}

.header-btn:hover:not(:disabled) {
  border-color: rgba(90, 213, 255, 0.32);
  color: #5ad5ff;
  background: rgba(10, 132, 255, 0.12);
}

.header-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.header-btn.primary {
  border-color: rgba(90, 213, 255, 0.4);
  background: rgba(10, 132, 255, 0.2);
  color: #5ad5ff;
}

.header-btn.primary:hover:not(:disabled) {
  background: rgba(10, 132, 255, 0.32);
}

.header-btn.run {
  border-color: rgba(120, 255, 160, 0.3);
  background: rgba(40, 180, 90, 0.16);
  color: #9ff8cf;
}

.header-btn.run:hover:not(:disabled) {
  background: rgba(40, 180, 90, 0.28);
}

.header-btn.run.submitting {
  border-color: rgba(255, 184, 77, 0.4);
  background: rgba(180, 130, 40, 0.2);
  color: #ffb84d;
  pointer-events: none;
}

.header-btn.run.submitted {
  border-color: rgba(120, 255, 160, 0.5);
  background: rgba(40, 180, 90, 0.28);
  color: #78ffa0;
}

.header-btn.run.submitting span:first-child,
.header-btn.run.submitted span:first-child {
  animation: spin 1s linear infinite;
}

.header-btn.run.submitted span:first-child {
  animation: none;
}

.header-btn.close {
  padding: 0.32rem 0.46rem;
  color: #6e8ba0;
}

.action-divider {
  width: 1px;
  height: 1rem;
  background: rgba(136, 192, 255, 0.14);
  margin: 0 0.18rem;
}

/* ── 错误提示栏 ──────────────────────────────────────────────────── */
.editor-error-bar {
  display: flex;
  align-items: center;
  gap: 0.42rem;
  padding: 0.36rem 0.72rem;
  border-bottom: 1px solid rgba(255, 120, 120, 0.2);
  background: rgba(90, 30, 30, 0.18);
  color: #ff9b9b;
  font-size: 0.6rem;
}

.error-icon {
  font-size: 0.72rem;
}

.error-text {
  flex: 1;
}

.error-dismiss {
  border: none;
  background: transparent;
  color: #ff9b9b;
  cursor: pointer;
  font: inherit;
  font-size: 0.62rem;
}

/* ── 主体三栏 ───────────────────────────────────────────────────── */
.editor-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.editor-canvas-area {
  flex: 1;
  position: relative;
  overflow: hidden;
  background: #0a0f1c;
  min-width: 0;
}

.canvas-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
}

.placeholder-content {
  text-align: center;
  color: #5a7080;
}

.placeholder-icon {
  font-size: 3.2rem;
  opacity: 0.3;
  display: block;
  margin-bottom: 0.72rem;
}

.placeholder-title {
  margin: 0 0 0.42rem;
  font-size: 1.1rem;
  font-weight: 600;
  color: #6e8ba0;
}

.placeholder-text {
  margin: 0 0 0.22rem;
  font-size: 0.72rem;
  color: #5a7080;
}

.placeholder-hint {
  margin: 0;
  font-size: 0.6rem;
  color: #4a5a6a;
}

/* ── 新建对话框 ──────────────────────────────────────────────────── */
.create-dialog-overlay {
  position: fixed;
  inset: 0;
  z-index: 1001;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(4, 10, 18, 0.6);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
}

.create-dialog {
  width: 24rem;
  max-width: 92vw;
  padding: 1.1rem;
  border: 1px solid rgba(136, 192, 255, 0.18);
  border-radius: 0.72rem;
  background: rgba(8, 17, 31, 0.98);
  box-shadow: 0 18px 48px rgba(1, 8, 16, 0.4);
}

.dialog-title {
  margin: 0 0 0.82rem;
  font-size: 0.82rem;
  font-weight: 600;
  color: #d8e6f5;
}

.dialog-form {
  margin-bottom: 0.82rem;
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
  margin-bottom: 0.62rem;
}

.form-label {
  font-size: 0.58rem;
  color: #6e8ba0;
  font-weight: 500;
}

.form-input,
.form-select,
.form-textarea {
  padding: 0.4rem 0.52rem;
  border: 1px solid rgba(136, 192, 255, 0.14);
  border-radius: 0.42rem;
  background: rgba(4, 12, 23, 0.6);
  color: #d8e6f5;
  font: inherit;
  font-size: 0.62rem;
}

.form-textarea {
  resize: vertical;
  min-height: 2.4rem;
  font-family: inherit;
}

.form-input:focus,
.form-select:focus,
.form-textarea:focus {
  outline: none;
  border-color: rgba(90, 213, 255, 0.4);
}

.form-select {
  cursor: pointer;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.42rem;
}

.dialog-btn {
  padding: 0.4rem 0.92rem;
  border: 1px solid rgba(136, 192, 255, 0.2);
  border-radius: 0.42rem;
  background: transparent;
  color: #c4d6e8;
  cursor: pointer;
  font: inherit;
  font-size: 0.62rem;
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

/* ── 响应式 ──────────────────────────────────────────────────────── */
@media (max-width: 800px) {
  .editor-body {
    flex-direction: column;
  }
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
