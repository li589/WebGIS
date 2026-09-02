<script setup lang="ts">
/**
 * 图层分组管理对话框（管理员个人工作区）。
 *
 * 分组 = 种子（layer_categories.json，可改名/样式，不可删除）⊕ 当前管理员
 * 个人工作区（后端 layer_groups：自建组 CRUD、重排、图层归属覆盖，按 user 隔离）。
 * 可选将当前工作区同步到主题预设，供绑定该主题的非管理员用户只读消费。
 */
import { computed, ref, watch } from 'vue'

import IconButton from '../ui/IconButton.vue'
import AppSelect from '../ui/AppSelect.vue'
import { fetchLayerCategories } from '../../services/runtime-api'
import {
  createLayerGroup,
  deleteLayerGroup,
  reorderLayerGroups,
  setLayerGroupMembers,
  syncLayerGroupsToTheme,
  updateLayerGroup,
  type LayerCategoryDef,
} from '../../services/layer-groups-api'
import { useLayerWorkspace } from '../../stores/layers/selectors'
import { useAuthStore } from '../../stores/auth'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()

const workspace = useLayerWorkspace()
const auth = useAuthStore()

// ── 本地状态 ────────────────────────────────────────────────────────────────

interface GroupRow {
  def: LayerCategoryDef
  /** 编辑态（重命名/样式） */
  editing: boolean
  draftName: string
  draftIcon: string
  draftAccent: string
  draftSubCategories: string
  /** 成员编辑态 */
  membersOpen: boolean
  memberDraft: string[] | null
}

const groups = ref<GroupRow[]>([])
const loading = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
const message = ref<string | null>(null)
const memberSearch = ref('')

// 新建分组表单
const createOpen = ref(false)
const newId = ref('')
const newName = ref('')
const newIcon = ref('')
const newAccent = ref('')

/** 可选：同步到主题预设 */
const syncThemeId = ref<string>('')
const syncingTheme = ref(false)

const themeOptions = computed(() =>
  (auth.themes ?? []).map((t) => ({
    label: t.name_zh || t.slug,
    value: String(t.id),
  })),
)

// ── 数据加载 ────────────────────────────────────────────────────────────────

async function loadGroups() {
  loading.value = true
  try {
    const response = await fetchLayerCategories()
    groups.value = response.items.map((def) => ({
      def,
      editing: false,
      draftName: def.name,
      draftIcon: def.icon ?? '',
      draftAccent: def.accent_color ?? '',
      draftSubCategories: (def.sub_categories ?? []).join('、'),
      membersOpen: false,
      memberDraft: null,
    }))
  } catch (err) {
    error.value = err instanceof Error ? err.message : '分组加载失败'
  } finally {
    loading.value = false
  }
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      error.value = null
      message.value = null
      createOpen.value = false
      syncThemeId.value = themeOptions.value[0]?.value ?? ''
      void auth.loadThemes()
      void loadGroups()
    }
  },
)

/** 保存后刷新：运行时分组（侧栏/面板）+ 目录（descriptor.category 归属覆盖） */
async function refreshRuntime() {
  try {
    await workspace.reloadLayerCategories()
  } catch {
    // 分组定义刷新失败不阻断：下一次 ensureRuntimeLayerCatalog 会重试
  }
  try {
    await workspace.ensureRuntimeLayerCatalog(true)
  } catch {
    // 目录刷新失败不阻断 UI 提示（网络异常时侧栏下次打开会重拉）
  }
}

// ── 图层库（成员选择数据源） ────────────────────────────────────────────────

const libraryItems = computed(() =>
  workspace.layerLibrary.value.map((item) => ({
    id: item.catalogId,
    name: item.name,
    category: item.category,
  })),
)

function memberOptions() {
  const q = memberSearch.value.trim().toLowerCase()
  return libraryItems.value.filter(
    (item) => !q || item.name.toLowerCase().includes(q) || item.id.toLowerCase().includes(q),
  )
}

function isMember(group: GroupRow, layerId: string): boolean {
  const draft = group.memberDraft
  if (draft) return draft.includes(layerId)
  return libraryItems.value.some((item) => item.id === layerId && item.category === group.def.id)
}

function toggleMember(group: GroupRow, layerId: string) {
  const current =
    group.memberDraft ??
    libraryItems.value.filter((i) => i.category === group.def.id).map((i) => i.id)
  group.memberDraft = current.includes(layerId)
    ? current.filter((id) => id !== layerId)
    : [...current, layerId]
}

// ── 分组操作 ────────────────────────────────────────────────────────────────

async function run(action: () => Promise<void>, okMessage: string) {
  saving.value = true
  error.value = null
  message.value = null
  try {
    await action()
    await refreshRuntime()
    message.value = okMessage
  } catch (err) {
    error.value = err instanceof Error ? err.message : '操作失败'
  } finally {
    saving.value = false
  }
}

async function applyEdit(group: GroupRow) {
  const name = group.draftName.trim()
  if (!name) {
    error.value = '分组名称不能为空'
    return
  }
  const subCategories = group.draftSubCategories
    .split(/[、,，]/)
    .map((s) => s.trim())
    .filter(Boolean)
  await run(async () => {
    await updateLayerGroup(group.def.id, {
      name,
      icon: group.draftIcon.trim() || null,
      accent_color: group.draftAccent.trim() || null,
      sub_categories: subCategories,
    })
    group.editing = false
    await loadGroups()
  }, '分组已更新')
}

function startEdit(group: GroupRow) {
  group.editing = true
  group.draftName = group.def.name
  group.draftIcon = group.def.icon ?? ''
  group.draftAccent = group.def.accent_color ?? ''
  group.draftSubCategories = (group.def.sub_categories ?? []).join('、')
}

function move(group: GroupRow, offset: -1 | 1) {
  const index = groups.value.indexOf(group)
  const target = index + offset
  if (index < 0 || target < 0 || target >= groups.value.length) return
  const next = [...groups.value]
  next.splice(target, 0, next.splice(index, 1)[0])
  void run(async () => {
    await reorderLayerGroups({ order: next.map((g) => g.def.id) })
    await loadGroups()
  }, '分组顺序已更新')
}

async function remove(group: GroupRow) {
  if (group.def.is_custom) {
    if (!window.confirm(`确定删除分组「${group.def.name}」？组内图层将回落到种子分类。`)) {
      return
    }
  } else {
    error.value = '种子分组不可删除（来自 layer_categories.json，可改名/样式）'
    return
  }
  await run(async () => {
    await deleteLayerGroup(group.def.id)
    await loadGroups()
  }, '分组已删除')
}

async function saveMembers(group: GroupRow) {
  const layerIds = group.memberDraft ?? []
  await run(async () => {
    await setLayerGroupMembers(group.def.id, { layer_ids: layerIds })
    group.membersOpen = false
    group.memberDraft = null
    await loadGroups()
  }, '分组成员已更新')
}

// ── 新建分组 ────────────────────────────────────────────────────────────────

function slugify(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^[^a-z]+/, '')
    .replace(/-+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64)
}

const canCreate = computed(
  () => slugify(newId.value).length >= 2 && newName.value.trim().length >= 1,
)

async function submitCreate() {
  const id = slugify(newId.value)
  if (!canCreate.value) {
    error.value = '分组 id 至少 2 个字符（小写字母开头，仅 a-z/0-9/-/_）'
    return
  }
  await run(async () => {
    await createLayerGroup({
      id,
      name: newName.value.trim(),
      icon: newIcon.value.trim() || null,
      accent_color: newAccent.value.trim() || null,
      sub_categories: [],
    })
    createOpen.value = false
    newId.value = ''
    newName.value = ''
    newIcon.value = ''
    newAccent.value = ''
    await loadGroups()
  }, '分组已创建')
}

function close() {
  if (saving.value || syncingTheme.value) return
  emit('close')
}

async function syncToTheme() {
  const themeId = Number(syncThemeId.value)
  if (!Number.isFinite(themeId) || themeId <= 0) {
    error.value = '请选择要同步的主题'
    return
  }
  syncingTheme.value = true
  error.value = null
  message.value = null
  try {
    await syncLayerGroupsToTheme(themeId)
    const label =
      themeOptions.value.find((t) => t.value === String(themeId))?.label ?? `主题 #${themeId}`
    message.value = `已将当前分组配置同步到「${label}」预设。若主题使用白名单 ACL，请在主题管理中为新增自建分组补 allow，否则成员图层可能不可见。`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '同步到主题失败'
  } finally {
    syncingTheme.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="lgm-overlay" @click.self="close">
      <div class="lgm-dialog" role="dialog" aria-modal="true" aria-labelledby="lgm-title">
        <header class="lgm-header">
          <div>
            <p class="lgm-kicker">图层平台</p>
            <h2 id="lgm-title" class="lgm-title">图层分组管理</h2>
            <p class="lgm-hint">
              此处配置仅影响当前管理员账号的图层库分组；种子组可改名/样式，自建组可增删排序。
              可选将当前配置同步到主题预设，供绑定该主题的用户使用。
            </p>
          </div>
          <IconButton size="sm" label="关闭" @click="close">
            <template #icon><span aria-hidden="true">×</span></template>
          </IconButton>
        </header>

        <section class="lgm-toolbar">
          <button
            type="button"
            class="lgm-btn"
            :disabled="saving"
            @click="createOpen = !createOpen"
          >
            {{ createOpen ? '收起新建' : '＋ 新建分组' }}
          </button>
          <span v-if="loading" class="lgm-status">加载中…</span>
        </section>

        <section v-if="themeOptions.length" class="lgm-theme-sync">
          <span class="lgm-theme-sync-label">同步到主题预设（可选）</span>
          <AppSelect
            :model-value="syncThemeId"
            :options="themeOptions"
            @change="syncThemeId = $event"
          />
          <button
            type="button"
            class="lgm-btn lgm-btn--primary"
            :disabled="saving || syncingTheme || !syncThemeId"
            @click="syncToTheme"
          >
            {{ syncingTheme ? '同步中…' : '同步当前分组' }}
          </button>
        </section>

        <form v-if="createOpen" class="lgm-create" @submit.prevent="submitCreate">
          <label class="lgm-field">
            <span>分组 id</span>
            <input v-model="newId" type="text" placeholder="如 lab-remote-sensing（自动转小写）" />
          </label>
          <label class="lgm-field">
            <span>名称</span>
            <input v-model="newName" type="text" placeholder="如 遥感反演专题" />
          </label>
          <label class="lgm-field lgm-field--sm">
            <span>图标字</span>
            <input v-model="newIcon" type="text" maxlength="2" placeholder="R" />
          </label>
          <label class="lgm-field lgm-field--sm">
            <span>主题色</span>
            <input v-model="newAccent" type="text" placeholder="#7fd99a" />
          </label>
          <button type="submit" class="lgm-btn lgm-btn--primary" :disabled="saving || !canCreate">
            创建
          </button>
        </form>

        <div class="lgm-list">
          <article v-for="(group, index) in groups" :key="group.def.id" class="lgm-group">
            <div v-if="!group.editing" class="lgm-group-row">
              <span
                class="lgm-group-icon"
                :style="{ '--cat-color': group.def.accent_color || 'var(--accent)' }"
              >
                {{ group.def.icon || '◈' }}
              </span>
              <div class="lgm-group-info">
                <span class="lgm-group-name">{{ group.def.name }}</span>
                <code class="lgm-group-id">{{ group.def.id }}</code>
                <span v-if="!group.def.is_custom" class="lgm-tag lgm-tag--seed">种子</span>
                <span v-else class="lgm-tag lgm-tag--custom">自建</span>
              </div>
              <div class="lgm-group-actions">
                <button
                  type="button"
                  class="lgm-icon-btn"
                  title="上移"
                  :disabled="saving || index === 0"
                  @click="move(group, -1)"
                >
                  ↑
                </button>
                <button
                  type="button"
                  class="lgm-icon-btn"
                  title="下移"
                  :disabled="saving || index === groups.length - 1"
                  @click="move(group, 1)"
                >
                  ↓
                </button>
                <button type="button" class="lgm-btn" :disabled="saving" @click="startEdit(group)">
                  编辑
                </button>
                <button
                  type="button"
                  class="lgm-btn"
                  :disabled="saving"
                  @click="group.membersOpen = !group.membersOpen"
                >
                  {{ group.membersOpen ? '收起成员' : '成员' }}
                </button>
                <button
                  type="button"
                  class="lgm-btn lgm-btn--danger"
                  :disabled="saving || !group.def.is_custom"
                  :title="group.def.is_custom ? undefined : '种子分组不可删除'"
                  @click="remove(group)"
                >
                  删除
                </button>
              </div>
            </div>

            <form v-else class="lgm-edit" @submit.prevent="applyEdit(group)">
              <label class="lgm-field">
                <span>名称</span>
                <input v-model="group.draftName" type="text" />
              </label>
              <label class="lgm-field lgm-field--sm">
                <span>图标字</span>
                <input v-model="group.draftIcon" type="text" maxlength="2" />
              </label>
              <label class="lgm-field lgm-field--sm">
                <span>主题色</span>
                <input v-model="group.draftAccent" type="text" placeholder="#ff6f91" />
              </label>
              <label class="lgm-field">
                <span>子分类（、分隔）</span>
                <input
                  v-model="group.draftSubCategories"
                  type="text"
                  placeholder="模型输入、模型输出"
                />
              </label>
              <div class="lgm-edit-actions">
                <button type="submit" class="lgm-btn lgm-btn--primary" :disabled="saving">
                  保存
                </button>
                <button
                  type="button"
                  class="lgm-btn"
                  :disabled="saving"
                  @click="group.editing = false"
                >
                  取消
                </button>
              </div>
            </form>

            <div v-if="group.membersOpen" class="lgm-members">
              <input
                v-model="memberSearch"
                class="lgm-member-search"
                type="search"
                placeholder="搜索图层（名称 / id）…"
              />
              <div class="lgm-member-list">
                <label v-for="item in memberOptions()" :key="item.id" class="lgm-member">
                  <input
                    type="checkbox"
                    :checked="isMember(group, item.id)"
                    :disabled="saving"
                    @change="toggleMember(group, item.id)"
                  />
                  <span class="lgm-member-name">{{ item.name }}</span>
                  <code class="lgm-member-id">{{ item.id }}</code>
                </label>
                <p v-if="!memberOptions().length" class="lgm-status">无匹配图层</p>
              </div>
              <div class="lgm-member-actions">
                <button
                  type="button"
                  class="lgm-btn lgm-btn--primary"
                  :disabled="saving"
                  @click="saveMembers(group)"
                >
                  保存成员
                </button>
                <button
                  type="button"
                  class="lgm-btn"
                  :disabled="saving"
                  @click="((group.membersOpen = false), (group.memberDraft = null))"
                >
                  取消
                </button>
              </div>
            </div>
          </article>
          <p v-if="!groups.length && !loading" class="lgm-status">暂无分组数据</p>
        </div>

        <p v-if="message" class="lgm-msg lgm-msg--ok">{{ message }}</p>
        <p v-if="error" class="lgm-msg lgm-msg--err">{{ error }}</p>

        <footer class="lgm-footer">
          <button type="button" class="lgm-btn" @click="close">关闭</button>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.lgm-overlay {
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
.lgm-dialog {
  width: min(720px, 100%);
  max-height: calc(100vh - 4rem);
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1.5rem 1.6rem 1.2rem;
  border: 1px solid var(--border-accent);
  border-radius: 14px;
  background: linear-gradient(165deg, var(--surface-2), var(--surface-1));
  box-shadow:
    0 30px 80px rgba(0, 0, 0, 0.5),
    0 1px 0 rgba(136, 223, 255, 0.12) inset;
  overflow: auto;
  color: var(--text-primary);
}
.lgm-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}
.lgm-kicker {
  margin: 0;
  font-size: var(--font-size-caption);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-faint);
  font-weight: var(--font-weight-medium);
}
.lgm-title {
  margin: 0.15rem 0 0;
  font-size: 1.25rem;
  font-weight: var(--font-weight-semibold);
  color: var(--text-strong);
}
.lgm-hint {
  margin: 0.35rem 0 0;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
  line-height: 1.5;
}
.lgm-toolbar {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.lgm-theme-sync {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.55rem;
  padding: 0.65rem 0.75rem;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-1);
}
.lgm-theme-sync-label {
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
  flex: 1 1 8rem;
}
.lgm-btn {
  padding: 0.35rem 0.8rem;
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  background: var(--surface-1);
  color: var(--text-secondary);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-medium);
  min-height: 1.9rem;
}
.lgm-btn:hover:not(:disabled) {
  border-color: var(--border-strong);
  color: var(--text-primary);
}
.lgm-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.lgm-btn--primary {
  border-color: var(--border-accent);
  background: var(--accent-surface);
  color: var(--accent);
}
.lgm-btn--danger {
  border-color: color-mix(in srgb, var(--danger, #c44) 45%, var(--border-subtle));
  color: var(--danger, #f87171);
}
.lgm-create,
.lgm-edit {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
  align-items: end;
  padding: 0.75rem 0.85rem;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-sunken);
}
.lgm-field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 0;
  flex: 1 1 9rem;
}
.lgm-field--sm {
  flex: 0 0 6rem;
}
.lgm-field > span {
  font-size: var(--font-size-caption);
  color: var(--text-faint);
}
.lgm-field input {
  height: 2rem;
  padding: 0 0.55rem;
  border: 1px solid var(--border-default);
  border-radius: 6px;
  background: var(--surface-1);
  color: var(--text-primary);
  font-family: inherit;
  font-size: var(--font-size-caption);
}
.lgm-field input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(90, 213, 255, 0.15);
}
.lgm-edit-actions,
.lgm-member-actions {
  display: flex;
  gap: 0.45rem;
  align-items: center;
}
.lgm-list {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}
.lgm-group {
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-sunken);
  padding: 0.55rem 0.7rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.lgm-group-row {
  display: flex;
  align-items: center;
  gap: 0.65rem;
}
.lgm-group-icon {
  width: 1.7rem;
  height: 1.7rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--cat-color, var(--accent));
  background: color-mix(in srgb, var(--cat-color, var(--accent)) 14%, transparent);
  border: 1px solid color-mix(in srgb, var(--cat-color, var(--accent)) 35%, transparent);
}
.lgm-group-info {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  min-width: 0;
  flex: 1;
  flex-wrap: wrap;
}
.lgm-group-name {
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-semibold);
  color: var(--text-strong);
}
.lgm-group-id {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 0.72rem;
  color: var(--text-faint);
}
.lgm-tag {
  font-size: 0.66rem;
  padding: 0.05rem 0.4rem;
  border-radius: 999px;
  border: 1px solid currentColor;
  font-weight: var(--font-weight-medium);
}
.lgm-tag--seed {
  color: var(--text-faint);
}
.lgm-tag--custom {
  color: var(--accent);
}
.lgm-group-actions {
  display: flex;
  gap: 0.35rem;
  align-items: center;
}
.lgm-icon-btn {
  width: 1.7rem;
  height: 1.7rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  background: var(--surface-1);
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 0.8rem;
}
.lgm-icon-btn:hover:not(:disabled) {
  border-color: var(--border-strong);
  color: var(--text-primary);
}
.lgm-icon-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.lgm-members {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  padding-top: 0.4rem;
  border-top: 1px dashed var(--border-subtle);
}
.lgm-member-search {
  height: 2rem;
  padding: 0 0.55rem;
  border: 1px solid var(--border-default);
  border-radius: 6px;
  background: var(--surface-1);
  color: var(--text-primary);
  font-family: inherit;
  font-size: var(--font-size-caption);
}
.lgm-member-list {
  max-height: 12rem;
  overflow: auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 0.3rem;
}
.lgm-member {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.25rem 0.4rem;
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  background: var(--surface-1);
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
  cursor: pointer;
}
.lgm-member input[type='checkbox'] {
  accent-color: var(--accent);
}
.lgm-member-name {
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.lgm-member-id {
  margin-left: auto;
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 0.68rem;
  color: var(--text-faint);
}
.lgm-status {
  margin: 0;
  font-size: var(--font-size-caption);
  color: var(--text-faint);
  text-align: center;
  padding: 0.4rem 0;
}
.lgm-msg {
  margin: 0;
  font-size: var(--font-size-caption);
  padding: 0.4rem 0.6rem;
  border-radius: 6px;
}
.lgm-msg--ok {
  background: rgba(74, 222, 128, 0.1);
  color: var(--success, #4ade80);
}
.lgm-msg--err {
  background: rgba(248, 113, 113, 0.1);
  color: var(--danger, #f87171);
}
.lgm-footer {
  display: flex;
  justify-content: flex-end;
}
</style>
