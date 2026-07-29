<script setup lang="ts">
/**
 * WorkflowRunDialog.vue
 *
 * 运行工作流时的产出目标选择对话框。
 * 用户可选择：
 *   1. 默认图层 — 直接使用工作流关联的 layer_id 运行
 *   2. 新建图层 — 在指定分组（或新建分组）中创建产出图层条目
 *   3. 多图层（multi）— 自动生成 N 个图层（仅当工作流含 omega_sf_fenkuai 等多输出节点时可用）
 */
import { computed, ref, watch } from 'vue'
import { useWorkflowOutputLayersStore } from '../../stores/workflow-output-layers'
import { useLayersStore } from '../../stores/layers'
import { useWorkflowDefinitionsStore } from '../../stores/workflow-definitions'

export interface WorkflowRunTarget {
  mode: 'default' | 'new' | 'multi'
  /** mode === 'new' 时：新建图层的名称 */
  name?: string
  /** mode === 'new' 时：分组名称 */
  group?: string
  /** mode === 'multi' 时：批量创建的图层目标列表 */
  targets?: Array<{ name: string; group: string }>
  /** 运行时选定的源图层（覆盖工作流 _meta.linked_layer_id） */
  layerId?: string
}

const props = defineProps<{
  visible: boolean
  workflowId: string
  workflowName: string
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

const mode = ref<'default' | 'new' | 'multi'>('default')
const newLayerName = ref('')
const selectedGroup = ref('')
const newGroupName = ref('')
const creatingNewGroup = ref(false)
/** 无 linked_layer_id 时由用户从目录选择 */
const pickedLayerId = ref('')

// multi 模式状态
const multiLayerNames = ref<string[]>([])
const multiGroup = ref('')
const multiCreatingNewGroup = ref(false)
const multiNewGroupName = ref('')
const sameGroupForAll = ref(true)

/** omega_sf_fenkuai 等多输出模块的输出标签 */
const MULTI_OUTPUT_TAGS = ['SM', 'VOD', 'OMEGA']

/** 可选图层目录（用于未关联时点选） */
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

/**
 * 检测当前工作流是否包含多输出节点（优先看画布当前定义）。
 */
const outputCount = computed(() => {
  const def = workflowDefsStore.currentDefinition
  if (!def) return 0
  const hasFenkuaiNode = def.nodes.some(
    (n) => n.type === 'module/omega_sf_fenkuai' || n.type?.includes('omega_sf_fenkuai'),
  )
  if (!hasFenkuaiNode) return 0
  const extraOutputs = def.extra?.outputs
  if (Array.isArray(extraOutputs) && extraOutputs.length > 1) {
    return extraOutputs.filter((t): t is string => typeof t === 'string').length
  }
  return MULTI_OUTPUT_TAGS.length
})

/** 当前工作流的输出标签列表（用于生成 multi 模式的图层名称） */
const outputTags = computed<string[]>(() => {
  const def = workflowDefsStore.currentDefinition
  if (!def) return []
  const extraOutputs = def.extra?.outputs
  if (Array.isArray(extraOutputs) && extraOutputs.length > 0) {
    return extraOutputs.filter((t): t is string => typeof t === 'string')
  }
  if (outputCount.value > 0) return [...MULTI_OUTPUT_TAGS]
  return []
})

/** 用于生成 multi 模式图层名称的前缀（从节点类型提取模块名） */
const multiNamePrefix = computed(() => {
  const def = workflowDefsStore.currentDefinition
  if (!def) return props.workflowId || 'output'
  const fenkuaiNode = def.nodes.find(
    (n) => n.type === 'module/omega_sf_fenkuai' || n.type?.includes('omega_sf_fenkuai'),
  )
  if (fenkuaiNode?.type) {
    const parts = fenkuaiNode.type.split('/')
    return parts[parts.length - 1] || 'output'
  }
  return props.workflowId || 'output'
})

/** 默认图层模式下可选的已产出数据集（同一源 layer_id 的历史产出） */
const existingOutputs = computed(() => {
  const layerId = effectiveLayerId.value
  if (!layerId) return []
  return outputStore.getBySourceLayerId(layerId)
})

/** 源图层显示名 */
const sourceLayerName = computed(() => {
  const layerId = effectiveLayerId.value
  if (!layerId) return '未选择图层'
  const libItem = layersStore.layerLibrary.find((l) => l.catalogId === layerId)
  return libItem?.name ?? layerId
})

const canConfirm = computed(() => {
  if (!effectiveLayerId.value) return false
  if (mode.value === 'default') return true
  if (mode.value === 'new') {
    if (creatingNewGroup.value) {
      return newLayerName.value.trim().length > 0 && newGroupName.value.trim().length > 0
    }
    return newLayerName.value.trim().length > 0 && selectedGroup.value.trim().length > 0
  }
  if (mode.value === 'multi') {
    const allNamesValid = multiLayerNames.value.every((n) => n.trim().length > 0)
    if (!allNamesValid) return false
    if (multiCreatingNewGroup.value) {
      return multiNewGroupName.value.trim().length > 0
    }
    return multiGroup.value.trim().length > 0
  }
  return false
})

/** multi 模式下实际使用的分组名 */
const effectiveMultiGroup = computed(() =>
  multiCreatingNewGroup.value ? multiNewGroupName.value.trim() : multiGroup.value.trim(),
)

function handleConfirm() {
  if (!canConfirm.value || !effectiveLayerId.value) return
  const layerId = effectiveLayerId.value
  if (mode.value === 'default') {
    emit('confirm', { mode: 'default', layerId })
    return
  }
  if (mode.value === 'new') {
    emit('confirm', {
      mode: 'new',
      layerId,
      name: newLayerName.value.trim(),
      group: creatingNewGroup.value ? newGroupName.value.trim() : selectedGroup.value.trim(),
    })
    return
  }
  if (mode.value === 'multi') {
    const group = effectiveMultiGroup.value
    const targets = multiLayerNames.value.map((name) => ({
      name: name.trim(),
      group,
    }))
    emit('confirm', { mode: 'multi', layerId, targets })
  }
}

function handleCancel() {
  emit('cancel')
}

function useExistingGroup() {
  creatingNewGroup.value = false
  selectedGroup.value = outputStore.groups[0]
}

function useExistingMultiGroup() {
  multiCreatingNewGroup.value = false
  if (outputStore.groups.length > 0) {
    multiGroup.value = outputStore.groups[0]
  }
}

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      mode.value = 'default'
      pickedLayerId.value = props.linkedLayerId ?? ''
      newLayerName.value = props.workflowName ? `${props.workflowName} 产出` : ''
      if (outputStore.groups.length > 0) {
        selectedGroup.value = outputStore.groups[0]
        creatingNewGroup.value = false
      } else {
        selectedGroup.value = ''
        creatingNewGroup.value = true
        newGroupName.value = '默认分组'
      }

      const tags = outputTags.value
      const prefix = multiNamePrefix.value
      multiLayerNames.value = tags.map((tag) => `${prefix}_${tag}`)
      sameGroupForAll.value = true
      if (outputStore.groups.length > 0) {
        multiGroup.value = outputStore.groups[0]
        multiCreatingNewGroup.value = false
      } else {
        multiGroup.value = ''
        multiCreatingNewGroup.value = true
        multiNewGroupName.value = '默认分组'
      }
    }
  },
)
</script>

<template>
  <div v-if="visible" class="run-dialog-overlay" @click.self="handleCancel">
    <div class="run-dialog">
      <header class="dialog-header">
        <h3 class="dialog-title">运行工作流</h3>
        <p class="dialog-subtitle">{{ workflowName }} · 源图层: {{ sourceLayerName }}</p>
      </header>

      <div class="dialog-body">
        <!-- 未关联图层时：从目录选择 -->
        <div v-if="!linkedLayerId" class="layer-picker">
          <label class="form-label">选择关联图层 *</label>
          <select v-model="pickedLayerId" class="form-select">
            <option value="" disabled>请选择图层目录条目</option>
            <option v-for="opt in catalogOptions" :key="opt.id" :value="opt.id">
              {{ opt.name }}（{{ opt.engine }}）
            </option>
          </select>
          <p class="info-hint">当前工作流未绑定图层；选择后将作为本次运行的源图层。</p>
        </div>

        <!-- 模式选择 -->
        <div class="mode-selector">
          <label class="mode-option" :class="{ active: mode === 'default' }">
            <input v-model="mode" type="radio" value="default" />
            <span class="mode-label">
              <span class="mode-name">默认图层</span>
              <span class="mode-desc">产出到工作流关联的源图层，覆盖上次结果</span>
            </span>
          </label>
          <label class="mode-option" :class="{ active: mode === 'new' }">
            <input v-model="mode" type="radio" value="new" />
            <span class="mode-label">
              <span class="mode-name">新建图层</span>
              <span class="mode-desc">在指定分组中创建新产出图层，保留历史结果</span>
            </span>
          </label>
          <label v-if="outputCount > 1" class="mode-option" :class="{ active: mode === 'multi' }">
            <input v-model="mode" type="radio" value="multi" />
            <span class="mode-label">
              <span class="mode-name">多图层自动生成</span>
              <span class="mode-desc">
                自动生成 {{ outputCount }} 个图层（{{ outputTags.join(' / ') }}），共用同一分组
              </span>
            </span>
          </label>
        </div>

        <!-- 默认图层模式：显示已有产出 -->
        <div v-if="mode === 'default'" class="default-mode-info">
          <div v-if="existingOutputs.length > 0" class="existing-outputs">
            <p class="info-label">该源图层已有产出条目:</p>
            <ul class="output-list">
              <li v-for="output in existingOutputs" :key="output.localId" class="output-item">
                <span class="output-name">{{ output.name }}</span>
                <span class="output-group">[{{ output.group }}]</span>
              </li>
            </ul>
          </div>
          <p v-else class="info-hint">将直接使用源图层运行，结果覆盖该图层当前数据。</p>
        </div>

        <!-- 新建图层模式 -->
        <div v-else-if="mode === 'new'" class="new-layer-form">
          <div class="form-row">
            <label class="form-label">图层名称</label>
            <input
              v-model="newLayerName"
              type="text"
              class="form-input"
              placeholder="输入产出图层名称"
            />
          </div>

          <div class="form-row">
            <label class="form-label">目标分组</label>
            <div v-if="!creatingNewGroup" class="group-select-row">
              <select v-model="selectedGroup" class="form-select">
                <option v-for="g in outputStore.groups" :key="g" :value="g">{{ g }}</option>
              </select>
              <button class="toggle-group-btn" type="button" @click="creatingNewGroup = true">
                + 新建分组
              </button>
            </div>
            <div v-else class="group-select-row">
              <input
                v-model="newGroupName"
                type="text"
                class="form-input"
                placeholder="输入新分组名称"
              />
              <button
                v-if="outputStore.groups.length > 0"
                class="toggle-group-btn"
                type="button"
                @click="useExistingGroup"
              >
                选择已有
              </button>
            </div>
          </div>
        </div>

        <!-- 多图层自动生成模式 -->
        <div v-else-if="mode === 'multi'" class="multi-layer-form">
          <div class="multi-info-bar">
            <span class="info-icon" aria-hidden="true">ℹ</span>
            <span class="info-text">
              将自动生成 {{ multiLayerNames.length }} 个图层，输出: {{ outputTags.join(' / ') }}
            </span>
          </div>

          <div class="form-row">
            <label class="form-label">图层名称（可编辑）</label>
            <div class="multi-name-list">
              <div v-for="(_name, idx) in multiLayerNames" :key="idx" class="multi-name-row">
                <span class="multi-name-tag">{{ outputTags[idx] }}</span>
                <input
                  v-model="multiLayerNames[idx]"
                  type="text"
                  class="form-input"
                  :placeholder="`${multiNamePrefix}_${outputTags[idx]}`"
                />
              </div>
            </div>
          </div>

          <div class="form-row">
            <label class="form-label">目标分组（所有图层共用）</label>
            <div v-if="!multiCreatingNewGroup" class="group-select-row">
              <select v-model="multiGroup" class="form-select">
                <option v-for="g in outputStore.groups" :key="g" :value="g">{{ g }}</option>
              </select>
              <button class="toggle-group-btn" type="button" @click="multiCreatingNewGroup = true">
                + 新建分组
              </button>
            </div>
            <div v-else class="group-select-row">
              <input
                v-model="multiNewGroupName"
                type="text"
                class="form-input"
                placeholder="输入新分组名称"
              />
              <button
                v-if="outputStore.groups.length > 0"
                class="toggle-group-btn"
                type="button"
                @click="useExistingMultiGroup"
              >
                选择已有
              </button>
            </div>
          </div>

          <label class="same-group-check">
            <input v-model="sameGroupForAll" type="checkbox" />
            <span class="check-label">全部使用相同分组</span>
          </label>
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
          {{ mode === 'default' ? '运行' : mode === 'multi' ? '批量创建并运行' : '创建并运行' }}
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
  font-size: 0.58rem;
  color: #7f93a9;
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
  font-size: 0.66rem;
  color: #eaf3fb;
  font-weight: 600;
}
.mode-desc {
  font-size: 0.56rem;
  color: #8aa0b6;
  line-height: 1.4;
}
.default-mode-info {
  padding: 0.4rem 0.5rem;
  border-radius: 0.52rem;
  background: rgba(8, 18, 33, 0.4);
  border: 1px solid rgba(136, 192, 255, 0.08);
}
.info-label,
.info-hint {
  margin: 0;
  font-size: 0.56rem;
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
  font-size: 0.56rem;
}
.output-name {
  color: #bfd3e6;
}
.output-group {
  color: #ffb84d;
}
.new-layer-form {
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
  font-size: 0.58rem;
  color: #9eb3c8;
}
.form-input,
.form-select {
  padding: 0.36rem 0.44rem;
  border-radius: 0.5rem;
  border: 1px solid rgba(136, 192, 255, 0.18);
  background: rgba(8, 18, 33, 0.6);
  color: #eaf3fb;
  font-size: 0.62rem;
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
  font-size: 0.56rem;
  cursor: pointer;
  white-space: nowrap;
  transition: border-color 0.18s ease;
}
.toggle-group-btn:hover {
  border-color: rgba(255, 184, 77, 0.4);
}

/* ── multi 模式样式 ──────────────────────────────────────────── */
.multi-layer-form {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
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
  font-size: 0.72rem;
  color: #9ff8cf;
}
.multi-info-bar .info-text {
  font-size: 0.56rem;
  color: #9ff8cf;
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
  color: #9ff8cf;
  font-size: 0.54rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  min-width: 3rem;
  text-align: center;
}
.multi-name-row .form-input {
  flex: 1 1 auto;
  min-width: 0;
}
.same-group-check {
  display: flex;
  align-items: center;
  gap: 0.36rem;
  cursor: pointer;
  user-select: none;
}
.same-group-check input[type='checkbox'] {
  accent-color: #ffb84d;
}
.same-group-check .check-label {
  font-size: 0.56rem;
  color: #8aa0b6;
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
  font-size: 0.62rem;
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
