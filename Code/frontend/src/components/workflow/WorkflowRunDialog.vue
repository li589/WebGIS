<script setup lang="ts">
/**
 * WorkflowRunDialog.vue
 *
 * 运行工作流时的产出目标选择：
 *   1. 默认图层 — 源图层上运行，Active TOC 建计算组（不强制写 library）
 *   2. 新建图层 — 计算组 + 写入产出 registry
 * 两种模式共用「预期产出」命名面板（组标题 + 每产品图层名）。
 */
import { computed, ref, watch } from 'vue'
import { Info } from '../ui/icons'
import { useWorkflowOutputLayersStore } from '../../stores/workflow-output-layers'
import { useLayerWorkspace } from '../../stores/layers/selectors'
import { useWorkflowDefinitionsStore } from '../../stores/workflow-definitions'
import {
  defaultProductLayerNames,
  productTagDescription,
  productTagLabel,
  resolveExpectedOutputTags,
  resolveOutputNamePrefix,
} from '../../utils/workflow-expected-outputs'
import AppSelect from '../ui/AppSelect.vue'

export interface WorkflowRunProductTarget {
  name: string
  productTag: string
}

export interface WorkflowRunTarget {
  mode: 'default' | 'new'
  /** 计算组显示标题 */
  groupTitle: string
  /** 每个预期产出的图层名 + 产品标签 */
  targets: WorkflowRunProductTarget[]
  /** 兼容旧字段：单名时可用第一个 target.name */
  name?: string
  /** 运行时选定的源图层 */
  layerId?: string
}

const props = defineProps<{
  visible: boolean
  workflowId: string
  workflowName: string
  workflowDescription?: string
  linkedLayerId: string | null
  engine: string
}>()

const emit = defineEmits<{
  confirm: [target: WorkflowRunTarget]
  cancel: []
}>()

const outputStore = useWorkflowOutputLayersStore()
const workspace = useLayerWorkspace()
const workflowDefsStore = useWorkflowDefinitionsStore()

const mode = ref<'default' | 'new'>('default')
const pickedLayerId = ref('')
const groupTitle = ref('')
const productNames = ref<string[]>([])

const catalogOptions = computed(() =>
  workspace.layerLibrary.value
    .filter((l) => Boolean(l.catalogId) && !String(l.catalogId).startsWith('wf-out-'))
    .map((l) => ({
      id: l.catalogId,
      name: l.name || l.catalogId,
      engine: l.engine ?? 'general',
    })),
)

const effectiveLayerId = computed(() => props.linkedLayerId || pickedLayerId.value.trim() || null)

const outputTags = computed(() => resolveExpectedOutputTags(workflowDefsStore.currentDefinition))

const namePrefix = computed(() =>
  resolveOutputNamePrefix(workflowDefsStore.currentDefinition, props.workflowId || 'output'),
)

const existingOutputs = computed(() => {
  const layerId = effectiveLayerId.value
  if (!layerId) return []
  return outputStore.getBySourceLayerId(layerId)
})

const sourceLayerName = computed(() => {
  const layerId = effectiveLayerId.value
  if (!layerId) return '未选择图层'
  const libItem = workspace.layerLibrary.value.find((l) => l.catalogId === layerId)
  return libItem?.name ?? layerId
})

const canConfirm = computed(() => {
  if (!effectiveLayerId.value) return false
  if (!groupTitle.value.trim()) return false
  return productNames.value.every((n) => n.trim().length > 0)
})

function buildTargets(): WorkflowRunProductTarget[] {
  return productNames.value.map((name, i) => ({
    name: name.trim(),
    productTag: outputTags.value[i] || 'result',
  }))
}

function handleConfirm() {
  if (!canConfirm.value || !effectiveLayerId.value) return
  const targets = buildTargets()
  const title = groupTitle.value.trim()
  emit('confirm', {
    mode: mode.value,
    layerId: effectiveLayerId.value,
    groupTitle: title,
    targets,
    name: targets[0]?.name,
  })
}

function handleCancel() {
  emit('cancel')
}

watch(
  () => props.visible,
  (visible) => {
    if (!visible) return
    mode.value = 'default'
    pickedLayerId.value = props.linkedLayerId ?? ''
    groupTitle.value = props.workflowName
      ? `${props.workflowName} · 计算中`
      : `${props.workflowId || '工作流'} · 计算中`

    const defaults = defaultProductLayerNames(outputTags.value, namePrefix.value)
    productNames.value = defaults.map((d) => d.name)
  },
)

watch(outputTags, (tags) => {
  if (!props.visible) return
  if (productNames.value.length === tags.length) return
  const defaults = defaultProductLayerNames(tags, namePrefix.value)
  productNames.value = defaults.map((d) => d.name)
})
</script>

<template>
  <Transition name="cgda-modal">
    <div
      v-if="visible"
      class="run-dialog-overlay"
      role="presentation"
      @click.self="handleCancel"
    >
      <div class="run-dialog cgda-modal-panel" role="dialog" aria-modal="true" aria-label="运行工作流">
        <header class="dialog-header">
          <h3 class="dialog-title">运行工作流</h3>
          <p class="dialog-subtitle">{{ workflowName }} · 源图层: {{ sourceLayerName }}</p>
          <p v-if="workflowDescription" class="dialog-description">{{ workflowDescription }}</p>
        </header>

        <div class="dialog-body">
          <div v-if="!linkedLayerId" class="layer-picker">
            <label class="form-label">选择关联图层 *</label>
            <AppSelect v-model="pickedLayerId" placeholder="请选择图层目录条目">
              <option value="" disabled>请选择图层目录条目</option>
              <option v-for="opt in catalogOptions" :key="opt.id" :value="opt.id">
                {{ opt.name }}（{{ opt.engine }}）
              </option>
            </AppSelect>
            <p class="info-hint">当前工作流未绑定图层；选择后将作为本次运行的源图层。</p>
          </div>

          <div class="mode-selector">
            <label class="mode-option" :class="{ active: mode === 'default' }">
              <input v-model="mode" type="radio" value="default" />
              <span class="mode-label">
                <span class="mode-name">默认图层</span>
                <span class="mode-desc">在已添加图层中建计算组；不写入目录产出条目</span>
              </span>
            </label>
            <label class="mode-option" :class="{ active: mode === 'new' }">
              <input v-model="mode" type="radio" value="new" />
              <span class="mode-label">
                <span class="mode-name">新建图层</span>
                <span class="mode-desc">计算组 + 写入「科研数据 → 模型输出」目录条目</span>
              </span>
            </label>
          </div>

          <div v-if="mode === 'default' && existingOutputs.length > 0" class="default-mode-info">
            <p class="info-label">该源图层已有目录产出条目:</p>
            <ul class="output-list">
              <li v-for="output in existingOutputs" :key="output.localId" class="output-item">
                <span class="output-name">{{ output.name }}</span>
                <span class="output-group">[{{ output.group }}]</span>
              </li>
            </ul>
          </div>

          <div class="products-form">
            <div class="multi-info-bar">
              <Info :size="14" class="info-icon" aria-hidden="true" />
              <span class="info-text">
                将创建计算组，含 {{ productNames.length }} 个图层：{{
                  outputTags.map(productTagLabel).join(' / ')
                }}
              </span>
            </div>

            <div class="form-row">
              <label class="form-label">计算组标题</label>
              <input
                v-model="groupTitle"
                type="text"
                class="form-input"
                placeholder="显示在已添加图层中的组名"
              />
            </div>

            <div class="form-row">
              <label class="form-label">图层名称（可编辑）</label>
              <div class="multi-name-list">
                <div v-for="(_name, idx) in productNames" :key="idx" class="multi-name-row">
                  <span
                    class="multi-name-tag"
                    :title="productTagDescription(outputTags[idx] ?? '')"
                    >{{ productTagLabel(outputTags[idx]) }}</span
                  >
                  <input
                    v-model="productNames[idx]"
                    type="text"
                    class="form-input"
                    :placeholder="`${namePrefix}_${outputTags[idx]}`"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>

        <footer class="dialog-actions">
          <button class="action-btn cancel" type="button" @click="handleCancel">取消</button>
          <button
            class="action-btn confirm"
            type="button"
            :disabled="!canConfirm"
            @click="handleConfirm"
          >
            {{ mode === 'default' ? '运行' : '创建并运行' }}
          </button>
        </footer>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.run-dialog-overlay {
  position: fixed;
  inset: 0;
  z-index: 1200;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-1);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
}
.run-dialog {
  width: min(440px, 92vw);
  max-height: 86vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  border-radius: 0.9rem;
  border: 1px solid var(--border-strong);
  background: linear-gradient(180deg, var(--surface-2), var(--surface-2));
  box-shadow: 0 20px 48px rgba(1, 8, 16, 0.5);
}
.dialog-header {
  padding: 0.72rem 0.86rem 0.5rem;
  border-bottom: 1px solid var(--border-default);
}
.dialog-title {
  margin: 0;
  font-size: 0.82rem;
  color: var(--text-strong);
}
.dialog-subtitle {
  margin: 0.18rem 0 0;
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}
.dialog-description {
  margin: 0.3rem 0 0;
  font-size: var(--font-size-caption);
  line-height: 1.5;
  color: var(--text-muted);
  white-space: pre-line;
}
.dialog-body {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 0.62rem 0.86rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  scrollbar-width: thin;
  scrollbar-color: var(--border-accent) transparent;
}
.dialog-body::-webkit-scrollbar {
  width: 4px;
}
.dialog-body::-webkit-scrollbar-thumb {
  background: var(--border-accent);
  border-radius: 3px;
}
.layer-picker {
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
  padding: 0.4rem 0.5rem;
  border-radius: 0.52rem;
  background: var(--warning-surface);
  border: 1px solid var(--warning-border);
}
.mode-selector {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.mode-option {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.5rem 0.56rem;
  border-radius: 0.62rem;
  border: 1px solid var(--border-default);
  background: var(--surface-sunken);
  cursor: pointer;
  transition:
    border-color 0.18s ease,
    background 0.18s ease;
}
.mode-option:hover {
  border-color: var(--border-strong);
}
.mode-option.active {
  border-color: var(--warning-border);
  background: var(--warning-surface);
}
.mode-option input[type='radio'] {
  margin-top: 0.16rem;
  accent-color: var(--warning);
}
.mode-label {
  display: flex;
  flex-direction: column;
  gap: 0.12rem;
  min-width: 0;
}
.mode-name {
  font-size: var(--font-size-caption);
  color: var(--text-primary);
  font-weight: 600;
}
.mode-desc {
  font-size: var(--font-size-caption);
  color: var(--text-muted);
  line-height: 1.4;
}
.default-mode-info {
  padding: 0.4rem 0.5rem;
  border-radius: 0.52rem;
  background: var(--surface-sunken);
  border: 1px solid var(--border-subtle);
}
.info-label,
.info-hint {
  margin: 0;
  font-size: var(--font-size-caption);
  color: var(--text-muted);
  line-height: 1.5;
}
.existing-outputs {
  display: flex;
  flex-direction: column;
  gap: 0.24rem;
}
.output-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
}
.output-item {
  display: flex;
  gap: 0.32rem;
  font-size: var(--font-size-caption);
}
.output-name {
  color: var(--text-secondary);
}
.output-group {
  color: var(--warning);
}
.products-form {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.form-row {
  display: flex;
  flex-direction: column;
  gap: 0.22rem;
}
.form-label {
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}
.form-input,
.form-select {
  padding: 0.36rem 0.44rem;
  border-radius: 0.5rem;
  border: 1px solid var(--border-default);
  background: var(--surface-1);
  color: var(--text-primary);
  font-size: var(--font-size-caption);
  font-family: inherit;
  outline: none;
  transition: border-color 0.18s ease;
}
.form-input:focus,
.form-select:focus {
  border-color: var(--warning-border);
}
.form-input::placeholder {
  color: var(--text-faint);
}
.group-select-row {
  display: flex;
  gap: 0.36rem;
  align-items: stretch;
}
.group-select-row .form-select,
.group-select-row .form-input {
  flex: 1 1 auto;
  min-width: 0;
}
.toggle-group-btn {
  flex: 0 0 auto;
  padding: 0.32rem 0.5rem;
  border-radius: 0.5rem;
  border: 1px solid var(--border-default);
  background: var(--surface-1);
  color: var(--accent-warm);
  font-size: var(--font-size-caption);
  cursor: pointer;
  white-space: nowrap;
  transition: border-color 0.18s ease;
}
.toggle-group-btn:hover {
  border-color: var(--warning-border);
}
.multi-info-bar {
  display: flex;
  align-items: center;
  gap: 0.32rem;
  padding: 0.36rem 0.5rem;
  border-radius: 0.52rem;
  background: rgba(40, 180, 90, 0.08);
  border: 1px solid rgba(120, 255, 160, 0.18);
}
.multi-info-bar .info-icon {
  font-size: var(--font-size-caption);
  color: var(--success);
}
.multi-info-bar .info-text {
  font-size: var(--font-size-caption);
  color: var(--success);
  line-height: 1.4;
}
.multi-name-list {
  display: flex;
  flex-direction: column;
  gap: 0.36rem;
}
.multi-name-row {
  display: flex;
  align-items: center;
  gap: 0.36rem;
}
.multi-name-tag {
  flex: 0 0 auto;
  padding: 0.16rem 0.42rem;
  border-radius: 0.32rem;
  border: 1px solid rgba(120, 255, 160, 0.3);
  background: rgba(40, 180, 90, 0.12);
  color: var(--success);
  font-size: var(--font-size-caption);
  font-weight: 600;
  letter-spacing: 0.02em;
  min-width: 3rem;
  text-align: center;
}
.multi-name-row .form-input {
  flex: 1 1 auto;
  min-width: 0;
}
.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.4rem;
  padding: 0.5rem 0.86rem 0.62rem;
  border-top: 1px solid var(--border-default);
}
.action-btn {
  padding: 0.4rem 0.78rem;
  border-radius: 999px;
  border: 1px solid var(--border-strong);
  background: var(--surface-1);
  color: var(--text-secondary);
  font-size: var(--font-size-caption);
  cursor: pointer;
  transition:
    border-color var(--motion-fast) var(--ease-soft),
    background-color var(--motion-fast) var(--ease-soft),
    color var(--motion-fast) var(--ease-soft),
    transform var(--motion-press, var(--motion-fast)) var(--ease-soft);
}
.action-btn.cancel:hover {
  border-color: var(--border-strong);
  color: var(--text-primary);
  transform: translateY(-1px);
}
.action-btn.cancel:active {
  transform: translateY(1px);
}
.action-btn.confirm {
  border-color: var(--warning-border);
  background: var(--warning-surface);
  color: var(--accent-warm);
}
.action-btn.confirm:hover:not(:disabled) {
  border-color: var(--warning-border);
  background: var(--warning-border);
  color: var(--accent-warm);
  transform: translateY(-1px);
}
.action-btn.confirm:active:not(:disabled) {
  transform: translateY(1px);
}
.action-btn.confirm:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}

html.reduce-motion .action-btn:hover,
html.reduce-motion .action-btn:active {
  transform: none;
}
</style>
