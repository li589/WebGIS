<script setup lang="ts">
/**
 * DatasetFormDialog — 新增/编辑「可用数据集」条目。
 *
 * source=algorithm_registry 的内置条目：仅可改路径覆盖/元数据/启停，logical_name 锁定。
 * path 支持绝对路径或相对 BACKEND_DATA_ROOT。
 */

import { computed, reactive, ref, watch } from 'vue'
import type { AvailableDatasetEntry } from '../../../types/api-reexports'
import { useSettingsStore } from '../../../stores/settings'

const props = defineProps<{
  visible: boolean
  editing: AvailableDatasetEntry | null
}>()

const emit = defineEmits<{
  close: []
  saved: []
}>()

const settingsStore = useSettingsStore()

const form = reactive({
  logicalName: '',
  path: '',
  fileFormat: '',
  variables: '',
  timeRange: '',
  resolution: '',
  tags: '',
  description: '',
  enabled: true,
})

const saving = ref(false)
const errMsg = ref('')

const isBuiltin = computed(() => props.editing?.source === 'algorithm_registry')

watch(
  () => props.visible,
  (v) => {
    if (!v) return
    errMsg.value = ''
    const e = props.editing
    if (e) {
      form.logicalName = e.logical_name
      form.path = e.path || ''
      form.fileFormat = e.file_format || ''
      form.variables = (e.variables ?? []).join(', ')
      form.timeRange = e.time_range || ''
      form.resolution = e.resolution || ''
      form.tags = (e.tags ?? []).join(', ')
      form.description = e.description || ''
      form.enabled = e.enabled !== false
    } else {
      form.logicalName = ''
      form.path = ''
      form.fileFormat = ''
      form.variables = ''
      form.timeRange = ''
      form.resolution = ''
      form.tags = ''
      form.description = ''
      form.enabled = true
    }
  },
)

function splitCsv(v: string): string[] {
  return v
    .split(/[,，]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

async function save() {
  const logical = form.logicalName.trim()
  if (!logical) {
    errMsg.value = '请填写逻辑名称'
    return
  }
  const path = form.path.trim()
  if (!path) {
    errMsg.value = '请填写数据集路径（绝对路径或相对数据根）'
    return
  }
  saving.value = true
  errMsg.value = ''
  try {
    await settingsStore.saveAvailableDataset(props.editing?.dataset_id ?? null, {
      logical_name: logical,
      path,
      file_format: form.fileFormat.trim() || null,
      variables: splitCsv(form.variables),
      time_range: form.timeRange.trim() || null,
      resolution: form.resolution.trim() || null,
      tags: splitCsv(form.tags),
      description: form.description.trim() || null,
      enabled: form.enabled,
    })
    emit('saved')
    emit('close')
  } catch (e) {
    errMsg.value = (e as Error).message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div v-if="visible" class="dialog-mask" @click.self="emit('close')">
    <div class="dialog">
      <header class="dialog-head">
        <strong>{{ editing ? `编辑数据集 · ${editing.logical_name}` : '新增数据集' }}</strong>
        <button type="button" class="btn" @click="emit('close')">关闭</button>
      </header>

      <p v-if="isBuiltin" class="card-hint">
        内置（算法包注册表）条目：逻辑名称与来源不可修改，仅可覆盖路径与元数据。
      </p>

      <div class="form-grid">
        <label :class="{ span2: true }">
          <span>逻辑名称 <em class="req">*</em></span>
          <input
            v-model="form.logicalName"
            :disabled="isBuiltin"
            placeholder="例如 Soil_Moisture"
          />
        </label>
        <label class="span-2">
          <span>路径 <em class="req">*</em></span>
          <input v-model="form.path" placeholder="绝对路径，或相对 BACKEND_DATA_ROOT 的目录名" />
        </label>
        <label>
          <span>文件格式</span>
          <input v-model="form.fileFormat" placeholder="例如 HDF5 / GeoTIFF" />
        </label>
        <label>
          <span>分辨率</span>
          <input v-model="form.resolution" placeholder="例如 9km" />
        </label>
        <label>
          <span>时间范围</span>
          <input v-model="form.timeRange" placeholder="例如 2015-01 ~ 至今" />
        </label>
        <label>
          <span>变量（逗号分隔）</span>
          <input v-model="form.variables" placeholder="SM, VV, VH" />
        </label>
        <label>
          <span>标签（逗号分隔）</span>
          <input v-model="form.tags" placeholder="土壤水分, 卫星" />
        </label>
        <label class="span-2">
          <span>描述</span>
          <textarea v-model="form.description" rows="2" placeholder="数据集说明（可选）" />
        </label>
        <label class="checkbox">
          <input v-model="form.enabled" type="checkbox" />
          <span>启用（参与图层就绪与工作流数据集解析）</span>
        </label>
      </div>

      <p v-if="errMsg" class="form-error">{{ errMsg }}</p>

      <div class="form-actions">
        <button type="button" class="btn btn-primary" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped src="../settings-form.css"></style>
<style scoped>
.dialog-mask {
  position: fixed;
  inset: 0;
  background: rgb(0 0 0 / 0.42);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 60;
}
.dialog {
  width: min(34rem, 92vw);
  max-height: 86vh;
  overflow: auto;
  background: var(--surface-1);
  border: 1px solid var(--border-strong);
  border-radius: 0.6rem;
  padding: 0.8rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.dialog-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--text-strong);
  font-size: var(--font-size-body);
}
.card-hint {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  line-height: 1.45;
}
.req {
  color: var(--danger);
  font-style: normal;
}
</style>
