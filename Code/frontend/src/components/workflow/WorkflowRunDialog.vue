<script setup lang="ts">
/**
 * WorkflowRunDialog.vue
 *
 * 运行工作流时的产出目标选择对话框。
 * 用户可选择：
 *   1. 默认图层 — 直接使用工作流关联的 layer_id 运行
 *   2. 新建图层 — 在指定分组（或新建分组）中创建产出图层条目
 */
import { computed, ref, watch } from 'vue'
import { useWorkflowOutputLayersStore } from '../../stores/workflow-output-layers'
import { useLayersStore } from '../../stores/layers'

export interface WorkflowRunTarget {
  mode: 'default' | 'new'
  /** mode === 'new' 时：新建图层的名称 */
  name?: string
  /** mode === 'new' 时：分组名称 */
  group?: string
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

const mode = ref<'default' | 'new'>('default')
const newLayerName = ref('')
const selectedGroup = ref('')
const newGroupName = ref('')
const creatingNewGroup = ref(false)

/** 默认图层模式下可选的已产出数据集（同一源 layer_id 的历史产出） */
const existingOutputs = computed(() => {
  if (!props.linkedLayerId) return []
  return outputStore.getBySourceLayerId(props.linkedLayerId)
})

/** 源图层显示名 */
const sourceLayerName = computed(() => {
  if (!props.linkedLayerId) return '未关联图层'
  const libItem = layersStore.layerLibrary.find((l) => l.catalogId === props.linkedLayerId)
  return libItem?.name ?? props.linkedLayerId
})

const canConfirm = computed(() => {
  if (mode.value === 'default') return !!props.linkedLayerId
  if (mode.value === 'new') {
    if (!props.linkedLayerId) return false
    if (creatingNewGroup.value) {
      return newLayerName.value.trim().length > 0 && newGroupName.value.trim().length > 0
    }
    return newLayerName.value.trim().length > 0 && selectedGroup.value.trim().length > 0
  }
  return false
})

function handleConfirm() {
  if (!canConfirm.value) return
  const target: WorkflowRunTarget =
    mode.value === 'default'
      ? { mode: 'default' }
      : {
          mode: 'new',
          name: newLayerName.value.trim(),
          group: creatingNewGroup.value ? newGroupName.value.trim() : selectedGroup.value.trim(),
        }
  emit('confirm', target)
}

function handleCancel() {
  emit('cancel')
}

// 对话框打开时重置状态
watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      mode.value = 'default'
      newLayerName.value = props.workflowName ? `${props.workflowName} 产出` : ''
      // 默认选第一个已有分组，没有则进入新建分组模式
      if (outputStore.groups.length > 0) {
        selectedGroup.value = outputStore.groups[0]
        creatingNewGroup.value = false
      } else {
        selectedGroup.value = ''
        creatingNewGroup.value = true
        newGroupName.value = '默认分组'
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
        <div v-else class="new-layer-form">
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
                @click="creatingNewGroup = false; selectedGroup = outputStore.groups[0]"
              >
                选择已有
              </button>
            </div>
          </div>
        </div>
      </div>

      <footer class="dialog-actions">
        <button class="action-btn cancel" type="button" @click="handleCancel">取消</button>
        <button class="action-btn confirm" type="button" :disabled="!canConfirm" @click="handleConfirm">
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
  transition: border-color 0.18s ease, background 0.18s ease;
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
  transition: border-color 0.18s ease, background 0.18s ease, color 0.18s ease;
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
