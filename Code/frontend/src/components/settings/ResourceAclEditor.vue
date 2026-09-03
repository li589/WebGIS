<script setup lang="ts">
/**
 * 资源 ACL 编辑器（主题默认 ACL / 用户权限覆盖共用）。
 *
 * - 添加：资源类型（图层/图层分组/工作流/数据源）+ 资源选择器（下拉选择或手动输入 ID）
 *   + 允许/拒绝；
 * - 记录表：按资源类型分组展示，自动解析资源显示名（目录不可用时仅显示 ID），
 *   允许/拒绝徽标，单条移除；
 * - 主题模式：每次变更全量 PUT 替换；用户模式：添加走全量 PUT、移除走单条 DELETE。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import AppSelect from '../ui/AppSelect.vue'
import ResourcePickerInput from './ResourcePickerInput.vue'
import {
  fetchPermissionResourceCatalog,
  type PermissionResourceCatalog,
  type ResourceOption,
} from '../../services/permission-resources'
import {
  deletePermission,
  listUserPermissions,
  setUserPermissions,
  setThemePermissions,
  listThemePermissions,
  type PermissionItemInput,
  type PermissionRecord,
  type PermissionValue,
  type ResourceType,
  type ThemePermissionRecord,
} from '../../services/auth-api'
import { onPermissionResourcesStale } from '../../utils/layer-group-manager-bridge'

type AclMode = { kind: 'theme'; themeId: number } | { kind: 'user'; userId: number }

const props = defineProps<{
  mode: AclMode
  disabled?: boolean
}>()

const emit = defineEmits<{
  /** 记录发生变化（增/删）后触发，父级可据此刷新用户列表等 */
  changed: []
}>()

const RESOURCE_TYPE_LABELS: Record<ResourceType, string> = {
  layer: '图层',
  layer_group: '图层分组',
  workflow: '工作流',
  data_source: '数据源',
}

const PERMISSION_LABELS: Record<PermissionValue, string> = {
  allow: '允许',
  deny: '拒绝',
}

const TYPE_ORDER: ResourceType[] = ['layer', 'layer_group', 'workflow', 'data_source']

// ── 状态 ────────────────────────────────────────────────────────────────────

const records = ref<Array<PermissionRecord | ThemePermissionRecord>>([])
const catalog = ref<PermissionResourceCatalog | null>(null)
const loading = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
const message = ref<string | null>(null)

const newType = ref<ResourceType>('layer')
const newId = ref('')
const newValue = ref<PermissionValue>('allow')
let stopStaleBridge: (() => void) | null = null

// ── 加载 ────────────────────────────────────────────────────────────────────

async function loadRecords() {
  loading.value = true
  error.value = null
  try {
    if (props.mode.kind === 'theme') {
      records.value = await listThemePermissions(props.mode.themeId)
    } else {
      records.value = await listUserPermissions(props.mode.userId)
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : '权限记录加载失败'
  } finally {
    loading.value = false
  }
}

async function loadCatalog() {
  try {
    catalog.value = await fetchPermissionResourceCatalog()
  } catch {
    catalog.value = null
  }
}

watch(
  () => props.mode,
  () => {
    records.value = []
    void loadRecords()
  },
)

onMounted(() => {
  void loadRecords()
  void loadCatalog()
  stopStaleBridge = onPermissionResourcesStale(() => {
    void loadCatalog()
  })
})

onBeforeUnmount(() => {
  stopStaleBridge?.()
  stopStaleBridge = null
})

// ── 选择器数据 ──────────────────────────────────────────────────────────────

const optionsForType = computed<ResourceOption[]>(() => {
  const cat = catalog.value
  if (!cat) return []
  if (newType.value === 'layer') return cat.layers
  if (newType.value === 'layer_group') return cat.layerGroups
  if (newType.value === 'workflow') return cat.workflows
  return cat.dataSources
})

const optionsByType = computed(() => {
  const cat = catalog.value
  if (!cat) return {} as Record<ResourceType, ResourceOption[]>
  return {
    layer: cat.layers,
    layer_group: cat.layerGroups,
    workflow: cat.workflows,
    data_source: cat.dataSources,
  } as Record<ResourceType, ResourceOption[]>
})

function resolveLabel(type: string, id: string): string | null {
  const options = optionsByType.value[type as ResourceType]
  return options?.find((option) => option.id === id)?.label ?? null
}

const groupedRecords = computed(() =>
  TYPE_ORDER.map((type) => ({
    type,
    label: RESOURCE_TYPE_LABELS[type],
    items: records.value.filter((r) => r.resource_type === type),
  })).filter((group) => group.items.length > 0),
)

// ── 增删 ────────────────────────────────────────────────────────────────────

async function addPermission() {
  const rid = newId.value.trim()
  if (!rid) {
    error.value = '请输入或选择资源 ID'
    return
  }
  saving.value = true
  error.value = null
  message.value = null
  try {
    const next: PermissionItemInput[] = records.value.map((r) => ({
      resource_type: r.resource_type as ResourceType,
      resource_id: r.resource_id,
      permission: r.permission as PermissionValue,
    }))
    const newPerm: PermissionItemInput = {
      resource_type: newType.value,
      resource_id: rid,
      permission: newValue.value,
    }
    // 同 type+id 已存在则替换 permission
    const deduped = next.filter(
      (p) => !(p.resource_type === newPerm.resource_type && p.resource_id === newPerm.resource_id),
    )
    const finalList = [...deduped, newPerm]
    if (props.mode.kind === 'theme') {
      records.value = await setThemePermissions(props.mode.themeId, finalList)
    } else {
      records.value = await setUserPermissions(props.mode.userId, finalList)
    }
    newId.value = ''
    message.value = '已保存'
    emit('changed')
  } catch (err) {
    error.value = err instanceof Error ? err.message : '保存失败'
  } finally {
    saving.value = false
  }
}

async function removeRecord(record: PermissionRecord | ThemePermissionRecord) {
  saving.value = true
  error.value = null
  message.value = null
  try {
    if (props.mode.kind === 'theme') {
      // 主题权限为全量替换语义：过滤后整体 PUT
      const next: PermissionItemInput[] = records.value
        .filter((r) => r.id !== record.id)
        .map((r) => ({
          resource_type: r.resource_type as ResourceType,
          resource_id: r.resource_id,
          permission: r.permission as PermissionValue,
        }))
      records.value = await setThemePermissions(props.mode.themeId, next)
    } else {
      await deletePermission(props.mode.userId, record.id)
      records.value = records.value.filter((r) => r.id !== record.id)
    }
    message.value = '已移除'
    emit('changed')
  } catch (err) {
    error.value = err instanceof Error ? err.message : '移除失败'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="rae">
    <div class="rae-form">
      <label class="rae-field rae-field--type">
        <span>资源类型</span>
        <AppSelect
          v-model="newType"
          :options="TYPE_ORDER.map((t) => ({ label: RESOURCE_TYPE_LABELS[t], value: t }))"
        />
      </label>
      <label class="rae-field">
        <span>资源（输入或选择，选中自动填入 ID）</span>
        <ResourcePickerInput
          v-model="newId"
          :options="optionsForType"
          :disabled="disabled || saving"
        />
      </label>
      <label class="rae-field rae-field--perm">
        <span>权限</span>
        <AppSelect
          v-model="newValue"
          :options="[
            { label: '允许', value: 'allow' },
            { label: '拒绝', value: 'deny' },
          ]"
        />
      </label>
      <button
        type="button"
        class="rae-add"
        :disabled="disabled || saving || !newId.trim()"
        @click="addPermission"
      >
        添加
      </button>
    </div>
    <p class="rae-catalog-status">
      {{
        catalog
          ? '资源目录已从后端加载（图层 / 分组 / 工作流为最新目录）'
          : '后端资源目录不可用：可手动输入 ID（下拉建议为静态兜底）'
      }}
    </p>

    <p v-if="loading" class="rae-status">加载权限记录…</p>
    <p v-else-if="!records.length" class="rae-status">
      暂无权限记录（开放模式下等同全量放行；白名单模式下默认拒绝）
    </p>
    <div v-else class="rae-groups">
      <section v-for="group in groupedRecords" :key="group.type" class="rae-group">
        <h4 class="rae-group-title">
          {{ group.label }}
          <span class="rae-group-count">{{ group.items.length }}</span>
        </h4>
        <table class="rae-table">
          <tbody>
            <tr v-for="r in group.items" :key="r.id">
              <td class="rae-cell rae-cell--name">
                <span class="rae-name">{{
                  resolveLabel(r.resource_type, r.resource_id) ?? '（目录未收录）'
                }}</span>
                <code class="rae-mono">{{ r.resource_id }}</code>
              </td>
              <td class="rae-cell">
                <span :class="['rae-pill', `rae-pill--${r.permission}`]">
                  {{ PERMISSION_LABELS[r.permission as PermissionValue] || r.permission }}
                </span>
              </td>
              <td class="rae-cell rae-cell--action">
                <button
                  type="button"
                  class="rae-remove"
                  :disabled="disabled || saving"
                  @click="removeRecord(r)"
                >
                  移除
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>

    <p v-if="message" class="rae-msg rae-msg--ok">{{ message }}</p>
    <p v-if="error" class="rae-msg rae-msg--err">{{ error }}</p>
  </div>
</template>

<style scoped>
.rae {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}
.rae-form {
  display: grid;
  grid-template-columns: 8.5rem 1fr 6.5rem auto;
  gap: 0.6rem;
  align-items: end;
}
.rae-field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 0;
}
.rae-field > span {
  font-size: var(--font-size-caption);
  color: var(--text-faint);
}
.rae-add {
  height: 2.1rem;
  padding: 0 0.9rem;
  border: 1px solid var(--border-accent);
  border-radius: 6px;
  background: var(--accent-surface);
  color: var(--accent);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-medium);
  transition: background-color var(--motion-fast) var(--ease-soft);
}
.rae-add:hover:not(:disabled) {
  background: var(--accent-border);
  color: var(--text-strong);
}
.rae-add:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.rae-catalog-status {
  margin: 0;
  font-size: var(--font-size-caption);
  color: var(--text-faint);
}
.rae-status {
  margin: 0;
  font-size: var(--font-size-caption);
  color: var(--text-faint);
  text-align: center;
  padding: 0.5rem 0;
}
.rae-groups {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}
.rae-group {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.rae-group-title {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-semibold);
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.rae-group-count {
  font-size: 0.66rem;
  padding: 0.02rem 0.4rem;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  color: var(--text-faint);
}
.rae-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-caption);
}
.rae-cell {
  text-align: left;
  padding: 0.35rem 0.5rem;
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-primary);
  vertical-align: middle;
}
.rae-cell--name {
  display: table-cell;
}
.rae-cell--name .rae-name {
  display: block;
  color: var(--text-strong);
}
.rae-cell--action {
  width: 4.5rem;
}
.rae-mono {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 0.72rem;
  color: var(--text-faint);
}
.rae-pill {
  display: inline-block;
  padding: 0.1rem 0.5rem;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: var(--font-weight-medium);
  border: 1px solid currentColor;
}
.rae-pill--allow {
  color: var(--success, #4ade80);
  background: rgba(74, 222, 128, 0.08);
}
.rae-pill--deny {
  color: var(--danger, #f87171);
  background: rgba(248, 113, 113, 0.08);
}
.rae-remove {
  padding: 0.2rem 0.55rem;
  border: 1px solid var(--border-subtle);
  border-radius: 5px;
  background: var(--surface-1);
  color: var(--text-secondary);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--font-size-caption);
}
.rae-remove:hover:not(:disabled) {
  border-color: var(--danger, #f87171);
  color: var(--danger, #f87171);
}
.rae-remove:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.rae-msg {
  margin: 0;
  font-size: var(--font-size-caption);
  padding: 0.4rem 0.6rem;
  border-radius: 6px;
}
.rae-msg--ok {
  background: rgba(74, 222, 128, 0.1);
  color: var(--success, #4ade80);
}
.rae-msg--err {
  background: rgba(248, 113, 113, 0.1);
  color: var(--danger, #f87171);
}
@media (max-width: 640px) {
  .rae-form {
    grid-template-columns: 1fr;
  }
}
</style>
