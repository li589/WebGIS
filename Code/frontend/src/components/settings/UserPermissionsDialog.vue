<script setup lang="ts">
/**
 * 用户权限配置对话框（管理员专属）
 *
 * 由设置-账户-用户管理列表的"操作"列打开，
 * 用于集中管理某用户的资源权限：
 *  - 权限模式（开放/白名单）
 *  - 数据图层（layer）显式允许/拒绝
 *  - 数据源（data_source）显式允许/拒绝
 *  - 工作流（workflow）显式允许/拒绝
 *
 * 仅当 isAdmin 时才允许打开（按钮在前一层已禁用，且后端权限点 require_admin）。
 */
import { computed, ref, watch } from 'vue'
import IconButton from '../ui/IconButton.vue'
import {
  deletePermission,
  listUserPermissions,
  setUserPermissions,
  updatePermissionMode,
  type PermissionMode,
  type PermissionItemInput,
  type PermissionRecord,
  type PermissionValue,
  type ResourceType,
} from '../../services/auth-api'

interface UserRow {
  id: number
  username: string
  role: 'admin' | 'standard' | 'demo'
  permission_mode?: string
}

const props = defineProps<{
  open: boolean
  user: UserRow | null
}>()

const emit = defineEmits<{
  close: []
  updated: [userId: number, mode: PermissionMode]
}>()

const RESOURCE_TYPE_LABELS: Record<ResourceType, string> = {
  layer: '数据图层',
  workflow: '工作流',
  data_source: '数据源',
}

const PERMISSION_LABELS: Record<PermissionValue, string> = {
  allow: '允许',
  deny: '拒绝',
}

const MODE_LABELS: Record<PermissionMode, string> = {
  open: '开放（黑名单模式：仅有拒绝记录的资源被拦截）',
  whitelist: '白名单（仅有允许记录的资源可访问）',
}

/** 常用资源 ID 建议：避免用户凭记忆手敲 catalog id */
const SUGGESTED_LAYERS: Array<{ id: string; label: string }> = [
  { id: 'wind-field', label: '风场（10m）' },
  { id: 'wind-field-80m', label: '风场（80m）' },
  { id: 'wind-field-120m', label: '风场（120m）' },
  { id: 'wind-field-180m', label: '风场（180m）' },
  { id: 'wind-field-850hPa', label: '风场（850hPa）' },
  { id: 'wind-field-500hPa', label: '风场（500hPa）' },
  { id: 'wind-field-200hPa', label: '风场（200hPa）' },
  { id: 'temperature', label: '温度（2m）' },
  { id: 'temperature-80m', label: '温度（80m）' },
  { id: 'precipitation', label: '降水' },
  { id: 'humidity', label: '湿度' },
  { id: 'visibility', label: '能见度' },
  { id: 'cloud-cover', label: '云量' },
  { id: 'pressure', label: '气压' },
  { id: 'dewpoint', label: '露点' },
  { id: 'smap-soil-moisture', label: 'SMAP 土壤水分' },
  { id: 'smap-omega', label: 'SMAP 反演 ω' },
  { id: 'modis-ndvi', label: 'MODIS NDVI' },
  { id: 'era5-soil', label: 'ERA5 土壤水分' },
]

const SUGGESTED_PROVIDERS: Array<{ id: string; label: string }> = [
  { id: 'open-meteo-local', label: 'Open-Meteo（本地）' },
  { id: 'open-meteo-online', label: 'Open-Meteo（在线）' },
  { id: 'gfs_global', label: 'GFS（全球）' },
  { id: 'ecmwf_ifs025', label: 'ECMWF IFS 0.25°' },
  { id: 'icon_seamless', label: 'ICON（融合）' },
  { id: 'era5', label: 'ERA5' },
  { id: 'smap', label: 'SMAP（NASA 资源）' },
  { id: 'modis', label: 'MODIS（NASA 资源）' },
]

const SUGGESTED_WORKFLOWS: Array<{ id: string; label: string }> = [
  { id: 'smap-soil-inversion', label: 'SMAP 土壤水分反演' },
  { id: 'modis-ndvi-inversion', label: 'MODIS NDVI 反演' },
  { id: 'era5-soil-extract', label: 'ERA5 土壤提取' },
  { id: 'terrain-shade', label: '地形阴影' },
  { id: 'rain-stats', label: '降水统计' },
]

function suggestionsFor(type: ResourceType) {
  if (type === 'layer') return SUGGESTED_LAYERS
  if (type === 'data_source') return SUGGESTED_PROVIDERS
  return SUGGESTED_WORKFLOWS
}

const records = ref<PermissionRecord[]>([])
const mode = ref<PermissionMode>('open')
const loading = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
const message = ref<string | null>(null)

const newType = ref<ResourceType>('layer')
const newId = ref('')
const newValue = ref<PermissionValue>('deny')

const isOpen = computed(() => props.open && !!props.user)
const canEdit = computed(() => {
  if (!props.user) return false
  // 当前管理员不能修改自己（避免自降级）
  return props.user.role !== 'admin'
})
const showSuggestionList = computed(() => suggestionsFor(newType.value))

async function load() {
  if (!props.user) return
  loading.value = true
  error.value = null
  try {
    records.value = await listUserPermissions(props.user.id)
    if (props.user.permission_mode === 'open' || props.user.permission_mode === 'whitelist') {
      mode.value = props.user.permission_mode
    } else {
      mode.value = 'open'
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载权限失败'
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.open, props.user?.id],
  ([open]) => {
    if (open) {
      records.value = []
      error.value = null
      message.value = null
      void load()
    }
  },
)

async function changeMode(next: PermissionMode) {
  if (!props.user) return
  saving.value = true
  error.value = null
  try {
    await updatePermissionMode(props.user.id, next)
    mode.value = next
    message.value =
      next === 'whitelist' ? '已切换为白名单模式' : '已切换为开放模式（黑名单）'
    emit('updated', props.user.id, next)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '切换模式失败'
  } finally {
    saving.value = false
  }
}

async function addPermission() {
  if (!props.user) return
  const rid = newId.value.trim()
  if (!rid) {
    error.value = '请输入资源 ID'
    return
  }
  saving.value = true
  error.value = null
  try {
    const existing: PermissionItemInput[] = records.value.map((r) => ({
      resource_type: r.resource_type as ResourceType,
      resource_id: r.resource_id,
      permission: r.permission as PermissionValue,
    }))
    const newPerm: PermissionItemInput = {
      resource_type: newType.value,
      resource_id: rid,
      permission: newValue.value,
    }
    // 避免重复：同 type+id 替换 permission
    const deduped = existing.filter(
      (p) => !(p.resource_type === newPerm.resource_type && p.resource_id === newPerm.resource_id),
    )
    records.value = await setUserPermissions(props.user.id, [...deduped, newPerm])
    newId.value = ''
    message.value = '已保存'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '保存失败'
  } finally {
    saving.value = false
  }
}

async function removePermission(id: number) {
  if (!props.user) return
  saving.value = true
  error.value = null
  try {
    await deletePermission(props.user.id, id)
    records.value = records.value.filter((r) => r.id !== id)
    message.value = '已移除'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '移除失败'
  } finally {
    saving.value = false
  }
}

function applySuggestion(id: string) {
  newId.value = id
}

function close() {
  if (saving.value) return
  emit('close')
}
</script>

<template>
  <Teleport to="body">
    <div v-if="isOpen" class="upd-overlay" @click.self="close">
      <div class="upd-dialog" role="dialog" aria-modal="true" aria-labelledby="upd-title">
        <header class="upd-header">
          <div>
            <p class="upd-kicker">用户权限配置</p>
            <h2 id="upd-title" class="upd-title">
              {{ user?.username }}<span v-if="user?.role === 'admin'" class="upd-tag">管理员</span>
            </h2>
          </div>
          <IconButton size="sm" label="关闭" @click="close">
            <template #icon>
              <span aria-hidden="true">×</span>
            </template>
          </IconButton>
        </header>

        <p v-if="!canEdit" class="upd-locked">
          管理员账户拥有全部权限，此处配置仅作查看（避免自降级锁定）。
        </p>

        <section class="upd-section">
          <h3 class="upd-h3">权限模式</h3>
          <p class="upd-hint">{{ MODE_LABELS[mode] }}</p>
          <div class="upd-mode-row">
            <button
              type="button"
              class="upd-mode-btn"
              :class="{ active: mode === 'open' }"
              :disabled="!canEdit || saving"
              @click="changeMode('open')"
            >
              开放（黑名单）
            </button>
            <button
              type="button"
              class="upd-mode-btn"
              :class="{ active: mode === 'whitelist' }"
              :disabled="!canEdit || saving"
              @click="changeMode('whitelist')"
            >
              白名单
            </button>
          </div>
        </section>

        <section class="upd-section">
          <h3 class="upd-h3">添加资源权限</h3>
          <div class="upd-form">
            <label class="upd-field">
              <span>资源类型</span>
              <select v-model="newType" :disabled="!canEdit" class="upd-select">
                <option value="layer">数据图层</option>
                <option value="data_source">数据源</option>
                <option value="workflow">工作流</option>
              </select>
            </label>
            <label class="upd-field upd-field--wide">
              <span>资源 ID</span>
              <input
                v-model="newId"
                type="text"
                :disabled="!canEdit"
                :placeholder="
                  newType === 'layer'
                    ? '如 wind-field、smap-omega'
                    : newType === 'data_source'
                      ? '如 open-meteo-local、ecmwf_ifs025'
                      : '如 smap-soil-inversion'
                "
                class="upd-input"
              />
            </label>
            <label class="upd-field">
              <span>权限</span>
              <select v-model="newValue" :disabled="!canEdit" class="upd-select">
                <option value="allow">允许</option>
                <option value="deny">拒绝</option>
              </select>
            </label>
            <button
              type="button"
              class="upd-add"
              :disabled="!canEdit || saving || !newId.trim()"
              @click="addPermission"
            >
              添加
            </button>
          </div>
          <details v-if="canEdit" class="upd-suggestions">
            <summary>常用资源 ID（点击填入）</summary>
            <div class="upd-suggestion-grid">
              <button
                v-for="s in showSuggestionList"
                :key="s.id"
                type="button"
                class="upd-suggestion"
                :class="{ active: newId === s.id }"
                @click="applySuggestion(s.id)"
              >
                <code>{{ s.id }}</code>
                <span>{{ s.label }}</span>
              </button>
            </div>
          </details>
        </section>

        <section class="upd-section">
          <h3 class="upd-h3">当前权限记录</h3>
          <p v-if="loading" class="upd-status">加载中…</p>
          <p v-else-if="!records.length" class="upd-status">暂无权限记录（默认按模式放行/拒绝）</p>
          <table v-else class="upd-table">
            <thead>
              <tr>
                <th>资源类型</th>
                <th>资源 ID</th>
                <th>权限</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in records" :key="r.id">
                <td>{{ RESOURCE_TYPE_LABELS[r.resource_type as ResourceType] || r.resource_type }}</td>
                <td><code class="upd-mono">{{ r.resource_id }}</code></td>
                <td>
                  <span :class="['upd-pill', `upd-pill--${r.permission}`]">
                    {{ PERMISSION_LABELS[r.permission as PermissionValue] || r.permission }}
                  </span>
                </td>
                <td>
                  <button
                    type="button"
                    class="upd-remove"
                    :disabled="!canEdit || saving"
                    @click="removePermission(r.id)"
                  >
                    移除
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </section>

        <p v-if="message" class="upd-msg upd-msg--ok">{{ message }}</p>
        <p v-if="error" class="upd-msg upd-msg--err">{{ error }}</p>

        <footer class="upd-footer">
          <button type="button" class="upd-secondary" @click="close">关闭</button>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.upd-overlay {
  position: fixed;
  inset: 0;
  z-index: 1100;
  background: rgba(3, 10, 20, 0.55);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2rem;
}
.upd-dialog {
  width: min(640px, 100%);
  max-height: calc(100vh - 4rem);
  display: flex;
  flex-direction: column;
  gap: 1.1rem;
  padding: 1.5rem 1.6rem 1.2rem;
  border: 1px solid var(--border-accent);
  border-radius: 14px;
  background: linear-gradient(165deg, var(--surface-2), var(--surface-1));
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.5), 0 1px 0 rgba(136, 223, 255, 0.12) inset;
  overflow: auto;
  color: var(--text-primary);
}
.upd-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}
.upd-kicker {
  margin: 0;
  font-size: var(--font-size-caption);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-faint);
  font-weight: var(--font-weight-medium);
}
.upd-title {
  margin: 0.15rem 0 0;
  font-size: 1.25rem;
  font-weight: var(--font-weight-semibold);
  color: var(--text-strong);
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.upd-tag {
  font-size: 0.7rem;
  font-weight: var(--font-weight-medium);
  padding: 0.05rem 0.45rem;
  border-radius: 999px;
  background: var(--accent-surface);
  color: var(--accent);
  border: 1px solid var(--border-accent);
}
.upd-locked {
  margin: 0;
  padding: 0.6rem 0.8rem;
  border-radius: 8px;
  background: var(--danger-surface, rgba(220, 38, 38, 0.08));
  color: var(--danger, #f87171);
  font-size: var(--font-size-caption);
}
.upd-section {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.85rem 0.95rem;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-sunken);
}
.upd-h3 {
  margin: 0;
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-semibold);
  color: var(--text-strong);
}
.upd-hint {
  margin: 0;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
  line-height: 1.5;
}
.upd-mode-row {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.25rem;
}
.upd-mode-btn {
  flex: 1;
  padding: 0.45rem 0.8rem;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-1);
  color: var(--text-secondary);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-medium);
  transition:
    background-color var(--motion-fast) var(--ease-soft),
    border-color var(--motion-fast) var(--ease-soft),
    color var(--motion-fast) var(--ease-soft);
}
.upd-mode-btn:hover:not(:disabled) {
  border-color: var(--border-strong);
  color: var(--text-primary);
}
.upd-mode-btn.active {
  border-color: var(--border-accent);
  background: var(--accent-surface);
  color: var(--accent);
}
.upd-mode-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.upd-form {
  display: grid;
  grid-template-columns: 9rem 1fr 7rem auto;
  gap: 0.6rem;
  align-items: end;
}
.upd-field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.upd-field--wide {
  grid-column: span 1;
}
.upd-field > span {
  font-size: var(--font-size-caption);
  color: var(--text-faint);
}
.upd-input,
.upd-select {
  height: 2.1rem;
  padding: 0 0.6rem;
  border: 1px solid var(--border-default);
  border-radius: 6px;
  background: var(--surface-1);
  color: var(--text-primary);
  font-family: inherit;
  font-size: var(--font-size-caption);
}
.upd-input:focus,
.upd-select:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(90, 213, 255, 0.15);
}
.upd-add {
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
.upd-add:hover:not(:disabled) {
  background: var(--accent-border);
  color: var(--text-strong);
}
.upd-add:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.upd-suggestions {
  margin-top: 0.5rem;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}
.upd-suggestions summary {
  cursor: pointer;
  padding: 0.25rem 0;
  user-select: none;
}
.upd-suggestion-grid {
  margin-top: 0.4rem;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 0.35rem;
  max-height: 8rem;
  overflow: auto;
}
.upd-suggestion {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.3rem 0.5rem;
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  background: var(--surface-1);
  color: var(--text-secondary);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--font-size-caption);
  text-align: left;
}
.upd-suggestion code {
  font-family: var(--font-mono, ui-monospace, monospace);
  color: var(--text-strong);
}
.upd-suggestion:hover {
  border-color: var(--border-accent);
  color: var(--text-primary);
}
.upd-suggestion.active {
  border-color: var(--accent);
  background: var(--accent-surface);
  color: var(--accent);
}
.upd-status {
  margin: 0;
  font-size: var(--font-size-caption);
  color: var(--text-faint);
  text-align: center;
  padding: 0.5rem 0;
}
.upd-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-caption);
}
.upd-table th,
.upd-table td {
  text-align: left;
  padding: 0.4rem 0.5rem;
  border-bottom: 1px solid var(--border-subtle);
}
.upd-table th {
  color: var(--text-faint);
  font-weight: var(--font-weight-medium);
  text-transform: uppercase;
  font-size: 0.7rem;
  letter-spacing: 0.05em;
}
.upd-table td {
  color: var(--text-primary);
}
.upd-mono {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 0.78rem;
  color: var(--text-secondary);
}
.upd-pill {
  display: inline-block;
  padding: 0.1rem 0.5rem;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: var(--font-weight-medium);
  border: 1px solid currentColor;
}
.upd-pill--allow {
  color: var(--success, #4ade80);
  background: rgba(74, 222, 128, 0.08);
}
.upd-pill--deny {
  color: var(--danger, #f87171);
  background: rgba(248, 113, 113, 0.08);
}
.upd-remove {
  padding: 0.2rem 0.55rem;
  border: 1px solid var(--border-subtle);
  border-radius: 5px;
  background: var(--surface-1);
  color: var(--text-secondary);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--font-size-caption);
}
.upd-remove:hover:not(:disabled) {
  border-color: var(--danger, #f87171);
  color: var(--danger, #f87171);
}
.upd-remove:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.upd-msg {
  margin: 0;
  font-size: var(--font-size-caption);
  padding: 0.4rem 0.6rem;
  border-radius: 6px;
}
.upd-msg--ok {
  background: rgba(74, 222, 128, 0.1);
  color: var(--success, #4ade80);
}
.upd-msg--err {
  background: rgba(248, 113, 113, 0.1);
  color: var(--danger, #f87171);
}
.upd-footer {
  display: flex;
  justify-content: flex-end;
  padding-top: 0.25rem;
}
.upd-secondary {
  padding: 0.45rem 1.2rem;
  border: 1px solid var(--border-default);
  border-radius: 6px;
  background: var(--surface-1);
  color: var(--text-primary);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-medium);
}
.upd-secondary:hover {
  border-color: var(--border-strong);
}
@media (max-width: 640px) {
  .upd-form {
    grid-template-columns: 1fr;
  }
  .upd-suggestion-grid {
    grid-template-columns: 1fr;
  }
}
</style>
