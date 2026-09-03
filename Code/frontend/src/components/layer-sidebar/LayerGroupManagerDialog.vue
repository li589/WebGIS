<script setup lang="ts">
/**
 * 图层分组管理对话框（主题预设直写）。
 *
 * 编辑目标 = 选定主题的分组预设（无预设时以种子为基线，首次写入时 materialize）。
 * 支持：组增删改名/样式/排序、成员归属、主题级图层显示名覆盖。
 * 运行时预设永不写入 catalog_seeds JSON。
 */
import { computed, ref, watch } from 'vue'

import IconButton from '../ui/IconButton.vue'
import AppSelect from '../ui/AppSelect.vue'
import { fetchLayerCatalog, fetchLayerCategories } from '../../services/runtime-api'
import {
  createLayerGroup,
  deleteLayerGroup,
  putThemeLayerDisplayNames,
  reorderLayerGroups,
  setLayerGroupMembers,
  syncLayerGroupsToTheme,
  updateLayerGroup,
  fetchThemeLayerGroupPreset,
  type LayerCategoryDef,
} from '../../services/layer-groups-api'
import { useLayerWorkspace } from '../../stores/layers/selectors'
import { useAuthStore } from '../../stores/auth'
import {
  notifyPermissionResourcesStale,
} from '../../utils/layer-group-manager-bridge'

const props = defineProps<{
  open: boolean
  /** 打开时预选主题（来自主题管理「编辑分组」）。 */
  initialThemeId?: number | null
}>()
const emit = defineEmits<{ close: [] }>()

const workspace = useLayerWorkspace()
const auth = useAuthStore()

interface LibraryItem {
  id: string
  name: string
  category: string
  seedName: string
}

interface GroupRow {
  def: LayerCategoryDef
  editing: boolean
  draftName: string
  draftIcon: string
  draftAccent: string
  draftSubCategories: string
  membersOpen: boolean
  memberDraft: string[] | null
}

const groups = ref<GroupRow[]>([])
const libraryItems = ref<LibraryItem[]>([])
const displayNameDrafts = ref<Record<string, string>>({})
const loading = ref(false)
const saving = ref(false)
const importing = ref(false)
const error = ref<string | null>(null)
const message = ref<string | null>(null)
const memberSearch = ref('')
const hasPreset = ref(false)
const presetUpdatedAt = ref<string | null>(null)

const createOpen = ref(false)
const newId = ref('')
const newName = ref('')
const newIcon = ref('')
const newAccent = ref('')

/** 编辑目标主题（必选） */
const editThemeId = ref<string>('')

const themeOptions = computed(() =>
  (auth.themes ?? []).map((t) => ({
    label: `${t.name_zh || t.slug}${t.is_primary ? '（默认）' : ''}`,
    value: String(t.id),
  })),
)

const activeThemeId = computed(() => {
  const n = Number(editThemeId.value)
  return Number.isFinite(n) && n > 0 ? n : null
})

function defaultThemeIdString(): string {
  if (props.initialThemeId != null && props.initialThemeId > 0) {
    return String(props.initialThemeId)
  }
  const bound = auth.user?.theme_id
  if (bound != null && bound > 0) return String(bound)
  const primary = (auth.themes ?? []).find((t) => t.is_primary)
  if (primary) return String(primary.id)
  return themeOptions.value[0]?.value ?? ''
}

async function loadGroups() {
  const tid = activeThemeId.value
  if (tid == null) {
    error.value = '请选择编辑目标主题'
    groups.value = []
    return
  }
  loading.value = true
  try {
    const [catResp, catalog, preset] = await Promise.all([
      fetchLayerCategories({ themeId: tid }),
      fetchLayerCatalog({ themeId: tid }),
      fetchThemeLayerGroupPreset(tid),
    ])
    hasPreset.value = Boolean(preset.has_preset)
    presetUpdatedAt.value = preset.updated_at
    displayNameDrafts.value = { ...(preset.display_names || {}) }
    const assignments = preset.assignments || {}
    const seedNames = preset.seed_display_names || {}
    libraryItems.value = (catalog.items ?? []).map((item) => {
      const seedName = seedNames[item.layer_id] || item.layer_id
      const override = displayNameDrafts.value[item.layer_id]
      return {
        id: item.layer_id,
        name: (override && override.trim()) || item.display_name || seedName,
        category: assignments[item.layer_id] || item.category,
        seedName,
      }
    })
    groups.value = catResp.items.map((def) => ({
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
      void auth.loadThemes().then(() => {
        editThemeId.value = defaultThemeIdString()
        void loadGroups()
      })
    }
  },
)

watch(editThemeId, (next, prev) => {
  if (!props.open || next === prev || !next) return
  error.value = null
  message.value = null
  void loadGroups()
})

async function refreshRuntime() {
  try {
    await workspace.reloadLayerCategories()
  } catch {
    /* retry on next catalog ensure */
  }
  try {
    await workspace.ensureRuntimeLayerCatalog(true)
  } catch {
    /* non-blocking */
  }
  notifyPermissionResourcesStale()
}

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

function requireThemeId(): number {
  const tid = activeThemeId.value
  if (tid == null) throw new Error('请选择编辑目标主题')
  return tid
}

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
  const tid = requireThemeId()
  await run(async () => {
    await updateLayerGroup(
      group.def.id,
      {
        name,
        icon: group.draftIcon.trim() || null,
        accent_color: group.draftAccent.trim() || null,
        sub_categories: subCategories,
      },
      tid,
    )
    group.editing = false
    await loadGroups()
  }, '分组已更新（已写入主题预设）')
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
  const tid = requireThemeId()
  void run(async () => {
    await reorderLayerGroups({ order: next.map((g) => g.def.id) }, tid)
    await loadGroups()
  }, '分组顺序已更新')
}

async function remove(group: GroupRow) {
  if (group.def.is_custom) {
    if (!window.confirm(`确定从本主题预设删除分组「${group.def.name}」？`)) {
      return
    }
  } else {
    error.value = '种子分组不可删除（可改名/样式；种子 JSON 不变）'
    return
  }
  const tid = requireThemeId()
  await run(async () => {
    await deleteLayerGroup(group.def.id, tid)
    await loadGroups()
  }, '分组已删除')
}

async function saveMembers(group: GroupRow) {
  const layerIds = group.memberDraft ?? []
  const tid = requireThemeId()
  await run(async () => {
    await setLayerGroupMembers(group.def.id, { layer_ids: layerIds }, tid)
    group.membersOpen = false
    group.memberDraft = null
    await loadGroups()
  }, '分组成员已更新')
}

async function saveDisplayNames() {
  const tid = requireThemeId()
  await run(async () => {
    await putThemeLayerDisplayNames(tid, { ...displayNameDrafts.value })
    await loadGroups()
  }, '主题图层显示名已保存')
}

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
  const tid = requireThemeId()
  await run(async () => {
    await createLayerGroup(
      {
        id,
        name: newName.value.trim(),
        icon: newIcon.value.trim() || null,
        accent_color: newAccent.value.trim() || null,
        sub_categories: [],
      },
      tid,
    )
    createOpen.value = false
    newId.value = ''
    newName.value = ''
    newIcon.value = ''
    newAccent.value = ''
    await loadGroups()
  }, '分组已创建（已写入主题预设；白名单主题请在 ACL 中补 allow）')
}

function close() {
  if (saving.value || importing.value) return
  emit('close')
}

/** 次要：将管理员个人工作区一次性导入到当前编辑主题。 */
async function importFromPersonalWorkspace() {
  const tid = activeThemeId.value
  if (tid == null) {
    error.value = '请选择编辑目标主题'
    return
  }
  if (
    !window.confirm(
      '将用当前管理员个人工作区覆盖本主题预设（含分组与成员）。显示名覆盖会按导入结果重置为空，是否继续？',
    )
  ) {
    return
  }
  importing.value = true
  error.value = null
  message.value = null
  try {
    await syncLayerGroupsToTheme(tid)
    await refreshRuntime()
    await loadGroups()
    message.value = '已从个人工作区导入到本主题预设'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '导入失败'
  } finally {
    importing.value = false
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
              针对选定主题直接编辑分组预设（移动图层、改组名、增删组、主题显示名）。
              绑定该主题的用户只读消费此预设；运行时变更<strong>不会</strong>改写种子 JSON（gen:catalog / check:catalog 口径不变）。
            </p>
          </div>
          <IconButton size="sm" label="关闭" @click="close">
            <template #icon><span aria-hidden="true">×</span></template>
          </IconButton>
        </header>

        <section v-if="themeOptions.length" class="lgm-theme-sync">
          <span class="lgm-theme-sync-label">编辑目标主题</span>
          <AppSelect
            :model-value="editThemeId"
            :options="themeOptions"
            @change="editThemeId = $event"
          />
          <span class="lgm-status" style="padding: 0; text-align: left">
            <template v-if="hasPreset">
              已有预设{{ presetUpdatedAt ? ` · ${presetUpdatedAt}` : '' }}
            </template>
            <template v-else>尚无预设（当前为种子基线；保存任一项后将物化）</template>
          </span>
          <button
            type="button"
            class="lgm-btn"
            :disabled="saving || importing || !editThemeId"
            title="兼容迁移：用个人工作区覆盖本主题预设"
            @click="importFromPersonalWorkspace"
          >
            {{ importing ? '导入中…' : '从个人工作区导入' }}
          </button>
        </section>

        <section class="lgm-toolbar">
          <button
            type="button"
            class="lgm-btn"
            :disabled="saving || !editThemeId"
            @click="createOpen = !createOpen"
          >
            {{ createOpen ? '收起新建' : '＋ 新建分组' }}
          </button>
          <button
            type="button"
            class="lgm-btn lgm-btn--primary"
            :disabled="saving || !editThemeId"
            @click="saveDisplayNames"
          >
            保存主题显示名
          </button>
          <span v-if="loading" class="lgm-status">加载中…</span>
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
                  <input
                    class="lgm-member-rename"
                    type="text"
                    :value="displayNameDrafts[item.id] ?? ''"
                    :placeholder="item.seedName"
                    :disabled="saving"
                    title="主题显示名覆盖（空=清除覆盖）"
                    @input="
                      displayNameDrafts[item.id] = ($event.target as HTMLInputElement).value
                    "
                  />
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
  width: min(780px, 100%);
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
  flex-wrap: wrap;
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
  flex: 0 0 auto;
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
  flex-wrap: wrap;
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
  max-height: 14rem;
  overflow: auto;
  display: grid;
  grid-template-columns: 1fr;
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
  min-width: 5rem;
  max-width: 8rem;
}
.lgm-member-rename {
  flex: 1;
  min-width: 6rem;
  height: 1.6rem;
  padding: 0 0.4rem;
  border: 1px solid var(--border-default);
  border-radius: 4px;
  background: var(--surface-2);
  color: var(--text-primary);
  font-family: inherit;
  font-size: 0.72rem;
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
