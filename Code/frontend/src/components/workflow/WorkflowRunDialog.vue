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
import { Info } from 'lucide-vue-next'
import { useWorkflowOutputLayersStore } from '../../stores/workflow-output-layers'
import { useLayersStore } from '../../stores/layers'
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
const layersStore = useLayersStore()
const workflowDefsStore = useWorkflowDefinitionsStore()

const mode = ref<'default' | 'new'>('default')
const pickedLayerId = ref('')
const groupTitle = ref('')
const productNames = ref<string[]>([])

const catalogOptions = computed(() =>
  layersStore.layerLibrary
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
  const libItem = layersStore.layerLibrary.find((l) => l.catalogId === layerId)
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
  <div v-if="visible" class="run-dialog-overlay" @click.self="handleCancel">
    <div class="run-dialog">
      <header class="dialog-header">
        <h3 class="dialog-title">运行工作流</h3>
        <p class="dialog-subtitle">{{ workflowName }} · 源图层: {{ sourceLayerName }}</p>
        <p v-if="workflowDescription" class="dialog-description">{{ workflowDescription }}</p>
      </header>

      <div class="dialog-body">
        <div v-if="!linkedLayerId" class="layer-picker">
          <label class="form-label">选择关联图层 *</label>
          <AppSelect
            v-model="pickedLayerId"
            placeholder="请选择图层目录条目"
          >
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
</template>

<style scoped>
.run-dialog-overlay {
  position: fixed;
  inset: 0;
  z-index: 1200;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(2, 8, 18, 0.62);
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
  border: 1px solid rgba(136, 192, 255, 0.22);
  background: linear-gradient(180deg, rgba(14, 24, 42, 0.96), rgba(8, 16, 30, 0.96));
  box-shadow: 0 20px 48px rgba(1, 8, 16, 0.5);
}
.dialog-header {
  padding: 0.72rem 0.86rem 0.5rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.12);
}
.dialog-title {
  margin: 0;
  font-size: 0.82rem;
  color: #f0f7ff;
}
.dialog-subtitle {
  margin: 0.18rem 0 0;
  font-size: var(--font-size-caption);
  color: #7f93a9;
}
.dialog-description {
  margin: 0.3rem 0 0;
  font-size: var(--font-size-caption);
  line-height: 1.5;
  color: #8aa0b6;
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
  scrollbar-color: rgba(90, 180, 255, 0.28) transparent;
}
.dialog-body::-webkit-scrollbar {
  width: 4px;
}
.dialog-body::-webkit-scrollbar-thumb {
  background: rgba(90, 180, 255, 0.26);
  border-radius: 3px;
}
.layer-picker {
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
  padding: 0.4rem 0.5rem;
  border-radius: 0.52rem;
  background: rgba(255, 184, 77, 0.06);
  border: 1px solid rgba(255, 184, 77, 0.2);
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
  border: 1px solid rgba(136, 192, 255, 0.12);
  background: rgba(8, 18, 33, 0.5);
  cursor: pointer;
  transition:
    border-color 0.18s ease,
    background 0.18s ease;
}
.mode-option:hover {
  border-color: rgba(136, 192, 255, 0.24);
}
.mode-option.active {
  border-color: rgba(255, 184, 77, 0.4);
  background: rgba(255, 184, 77, 0.08);
}
.mode-option input[type='radio'] {
  margin-top: 0.16rem;
  accent-color: #ffb84d;
}
.mode-label {
  display: flex;
  flex-direction: column;
  gap: 0.12rem;
  min-width: 0;
}
.mode-name {
  font-size: var(--font-size-caption);
  color: #eaf3fb;
  font-weight: 600;
}
.mode-desc {
  font-size: var(--font-size-caption);
  color: #8aa0b6;
  line-height: 1.4;
}
.default-mode-info {
  padding: 0.4rem 0.5rem;
  border-radius: 0.52rem;
  background: rgba(8, 18, 33, 0.4);
  border: 1px solid var(--border-subtle);
}
.info-label,
.info-hint {
  margin: 0;
  font-size: var(--font-size-caption);
  color: #8aa0b6;
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
  color: #bfd3e6;
}
.output-group {
  color: #ffb84d;
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
  color: #9eb3c8;
}
.form-input,
.form-select {
  padding: 0.36rem 0.44rem;
  border-radius: 0.5rem;
  border: 1px solid rgba(136, 192, 255, 0.18);
  background: rgba(8, 18, 33, 0.6);
  color: #eaf3fb;
  font-size: var(--font-size-caption);
  font-family: inherit;
  outline: none;
  transition: border-color 0.18s ease;
}
.form-input:focus,
.form-select:focus {
  border-color: rgba(255, 184, 77, 0.4);
}
.form-input::placeholder {
  color: #5a6f85;
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
  border: 1px solid rgba(136, 192, 255, 0.18);
  background: rgba(12, 24, 42, 0.6);
  color: #ffd38a;
  font-size: var(--font-size-caption);
  cursor: pointer;
  white-space: nowrap;
  transition: border-color 0.18s ease;
}
.toggle-group-btn:hover {
  border-color: rgba(255, 184, 77, 0.4);
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
  border-top: 1px solid rgba(136, 192, 255, 0.12);
}
.action-btn {
  padding: 0.4rem 0.78rem;
  border-radius: 999px;
  border: 1px solid rgba(136, 192, 255, 0.2);
  background: rgba(8, 18, 33, 0.6);
  color: #bfd3e6;
  font-size: var(--font-size-caption);
  cursor: pointer;
  transition:
    border-color 0.18s ease,
    background 0.18s ease,
    color 0.18s ease;
}
.action-btn.cancel:hover {
  border-color: rgba(136, 192, 255, 0.36);
  color: #eaf3fb;
}
.action-btn.confirm {
  border-color: rgba(255, 184, 77, 0.36);
  background: rgba(255, 184, 77, 0.14);
  color: #ffd38a;
}
.action-btn.confirm:hover:not(:disabled) {
  border-color: rgba(255, 184, 77, 0.56);
  background: rgba(255, 184, 77, 0.22);
  color: #fff0d4;
}
.action-btn.confirm:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}
</style>
