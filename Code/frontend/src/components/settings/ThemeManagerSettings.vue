<script setup lang="ts">
/**
 * 主题管理（管理员）：品牌字段、默认权限模式、主题默认资源 ACL、logo。
 */
import { computed, onMounted, ref, watch } from 'vue'

import {
  createTheme,
  deleteTheme,
  listThemePermissions,
  setThemePermissions,
  updateTheme,
  uploadThemeLogo,
  type PermissionItemInput,
  type PermissionMode,
  type PermissionValue,
  type ResourceType,
  type ThemePermissionRecord,
} from '../../services/auth-api'
import { useAuthStore } from '../../stores/auth'
import AppSelect from '../ui/AppSelect.vue'

const auth = useAuthStore()

const message = ref<string | null>(null)
const error = ref<string | null>(null)
const saving = ref(false)
const selectedId = ref<number | null>(null)

const draftSlug = ref('')
const draftNameZh = ref('')
const draftFullZh = ref('')
const draftNameEn = ref('')
const draftAbbr = ref('SGFS')
const draftDescription = ref('')
const draftMode = ref<PermissionMode>('open')
const creating = ref(false)

const themePerms = ref<ThemePermissionRecord[]>([])
const permsLoading = ref(false)
const newType = ref<ResourceType>('layer')
const newId = ref('')
const newPerm = ref<PermissionValue>('allow')

const selected = computed(() => (auth.themes ?? []).find((t) => t.id === selectedId.value) ?? null)

const themeOptions = computed(() =>
  (auth.themes ?? []).map((t) => ({
    label: `${t.name_zh}${t.is_primary ? '（主入口）' : ''}`,
    value: String(t.id),
  })),
)

async function refresh() {
  error.value = null
  try {
    await auth.loadThemes()
    const list = auth.themes ?? []
    if (selectedId.value == null && list[0]) {
      selectedId.value = list[0].id
    } else if (selectedId.value != null && !list.some((t) => t.id === selectedId.value)) {
      selectedId.value = list[0]?.id ?? null
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : '加载主题失败'
    if (/404|Not Found/i.test(msg)) {
      error.value =
        '主题 API 返回 404（路由未加载）。请执行：Env\\Python312\\python.exe launch.py restart fastapi，然后硬刷新页面。'
    } else {
      error.value = msg
    }
  }
}

async function loadPerms(themeId: number) {
  permsLoading.value = true
  try {
    themePerms.value = await listThemePermissions(themeId)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载主题权限失败'
    themePerms.value = []
  } finally {
    permsLoading.value = false
  }
}

watch(selectedId, (id) => {
  if (id != null) void loadPerms(id)
  else themePerms.value = []
})

onMounted(() => {
  void refresh()
})

function fillCreateDefaults() {
  creating.value = true
  draftSlug.value = ''
  draftNameZh.value = ''
  draftFullZh.value = ''
  draftNameEn.value = ''
  draftAbbr.value = 'SGFS'
  draftDescription.value = ''
  draftMode.value = 'open'
}

/** 生成符合后端 slug 规则的标识：小写字母开头，[a-z0-9_-]，长度 2–64 */
function slugifyThemeId(raw: string): string {
  const cleaned = raw
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^[^a-z]+/, '')
    .replace(/-+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64)
  return cleaned
}

function ensureDraftSlug(): string {
  let slug = slugifyThemeId(draftSlug.value)
  if (slug.length >= 2) {
    draftSlug.value = slug
    return slug
  }
  // 仅从英文名推导；缩写默认值 SGFS 不宜当作 slug（易撞名）
  slug = slugifyThemeId(draftNameEn.value)
  if (slug.length >= 2) {
    draftSlug.value = slug
    return slug
  }
  return ''
}

function onSlugBlur() {
  if (!creating.value) return
  const slug = slugifyThemeId(draftSlug.value)
  if (slug) draftSlug.value = slug
}

function onNameEnBlur() {
  if (!creating.value || draftSlug.value.trim()) return
  const slug = slugifyThemeId(draftNameEn.value)
  if (slug.length >= 2) draftSlug.value = slug
}

const canSubmitCreate = computed(() => {
  if (!creating.value) return false
  const slug = slugifyThemeId(draftSlug.value) || slugifyThemeId(draftNameEn.value)
  return (
    slug.length >= 2 &&
    draftNameZh.value.trim().length >= 1 &&
    draftFullZh.value.trim().length >= 1 &&
    draftNameEn.value.trim().length >= 1
  )
})

async function submitCreate() {
  error.value = null
  message.value = null
  const slug = ensureDraftSlug()
  if (slug.length < 2) {
    error.value =
      '请填写 slug（至少 2 个字符，小写字母开头，仅 a-z / 0-9 / _ / -），或先填英文名以便自动生成。'
    return
  }
  if (!draftNameZh.value.trim() || !draftFullZh.value.trim() || !draftNameEn.value.trim()) {
    error.value = '请填写中文短名、中文全称与英文名'
    return
  }
  saving.value = true
  try {
    const created = await createTheme({
      slug,
      name_zh: draftNameZh.value.trim(),
      full_name_zh: draftFullZh.value.trim(),
      name_en: draftNameEn.value.trim(),
      abbr: draftAbbr.value.trim() || 'SGFS',
      description: draftDescription.value.trim(),
      default_permission_mode: draftMode.value,
    })
    await refresh()
    selectedId.value = created.id
    creating.value = false
    message.value = '主题已创建'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '创建失败'
  } finally {
    saving.value = false
  }
}

async function saveSelectedMeta() {
  if (!selected.value) return
  error.value = null
  message.value = null
  saving.value = true
  try {
    await updateTheme(selected.value.id, {
      name_zh: draftNameZh.value.trim(),
      full_name_zh: draftFullZh.value.trim(),
      name_en: draftNameEn.value.trim(),
      abbr: draftAbbr.value.trim(),
      description: draftDescription.value.trim(),
      default_permission_mode: draftMode.value,
    })
    await refresh()
    message.value = '主题信息已保存'
    if (auth.user?.theme_id === selected.value.id) {
      try {
        const me = await (await import('../../services/auth-api')).fetchAuthMe()
        auth.user = me
      } catch {
        /* ignore */
      }
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : '保存失败'
  } finally {
    saving.value = false
  }
}

watch(
  selected,
  (t) => {
    if (!t || creating.value) return
    draftNameZh.value = t.name_zh
    draftFullZh.value = t.full_name_zh
    draftNameEn.value = t.name_en
    draftAbbr.value = t.abbr
    draftDescription.value = t.description || ''
    draftMode.value = (t.default_permission_mode as PermissionMode) || 'open'
  },
  { immediate: true },
)

async function removeSelected() {
  if (!selected.value) return
  if (selected.value.is_primary) {
    error.value = '不能删除主入口主题'
    return
  }
  if (!window.confirm(`确定删除主题「${selected.value.name_zh}」？绑定用户将改挂主入口主题。`)) {
    return
  }
  saving.value = true
  error.value = null
  try {
    await deleteTheme(selected.value.id)
    selectedId.value = null
    await refresh()
    message.value = '主题已删除'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '删除失败'
  } finally {
    saving.value = false
  }
}

async function onLogoChange(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !selected.value) return
  saving.value = true
  error.value = null
  try {
    await uploadThemeLogo(selected.value.id, file)
    await refresh()
    message.value = 'Logo 已更新'
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Logo 上传失败'
  } finally {
    saving.value = false
  }
}

async function addThemePerm() {
  if (!selected.value) return
  const rid = newId.value.trim()
  if (!rid) {
    error.value = '请填写资源 ID'
    return
  }
  saving.value = true
  error.value = null
  try {
    const next: PermissionItemInput[] = [
      ...themePerms.value.map((p) => ({
        resource_type: p.resource_type as ResourceType,
        resource_id: p.resource_id,
        permission: p.permission as PermissionValue,
      })),
      { resource_type: newType.value, resource_id: rid, permission: newPerm.value },
    ]
    themePerms.value = await setThemePermissions(selected.value.id, next)
    newId.value = ''
    message.value = '主题默认权限已更新'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '更新权限失败'
  } finally {
    saving.value = false
  }
}

async function removeThemePerm(record: ThemePermissionRecord) {
  if (!selected.value) return
  saving.value = true
  error.value = null
  try {
    const next: PermissionItemInput[] = themePerms.value
      .filter((p) => p.id !== record.id)
      .map((p) => ({
        resource_type: p.resource_type as ResourceType,
        resource_id: p.resource_id,
        permission: p.permission as PermissionValue,
      }))
    themePerms.value = await setThemePermissions(selected.value.id, next)
    message.value = '已移除'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '移除失败'
  } finally {
    saving.value = false
  }
}

function onSelectTheme(val: string) {
  creating.value = false
  selectedId.value = Number(val)
}
</script>

<template>
  <section class="settings-section theme-manager">
    <h3 class="section-title">主题管理（管理员）</h3>
    <p class="section-hint">
      主题承载品牌与默认资源 ACL；用户绑定主题后继承默认权限，并可在「用户权限覆盖」中微调。
    </p>
    <p v-if="message" class="ok">{{ message }}</p>
    <p v-if="error" class="err">{{ error }}</p>

    <div class="toolbar-row">
      <AppSelect
        v-if="!creating && themeOptions.length"
        :model-value="selectedId != null ? String(selectedId) : ''"
        :options="themeOptions"
        @change="onSelectTheme"
      />
      <button type="button" class="secondary-btn" :disabled="saving" @click="fillCreateDefaults">
        新建主题
      </button>
      <button
        v-if="creating"
        type="button"
        class="secondary-btn"
        :disabled="saving"
        @click="creating = false"
      >
        取消新建
      </button>
    </div>

    <div v-if="creating" class="form-grid">
      <label class="field">
        <span class="field-label">slug（必填）</span>
        <input
          v-model="draftSlug"
          type="text"
          placeholder="如 weather-demo（小写字母开头）"
          autocomplete="off"
          @blur="onSlugBlur"
        />
      </label>
      <label class="field">
        <span class="field-label">中文短名</span>
        <input v-model="draftNameZh" type="text" placeholder="中文短名" />
      </label>
      <label class="field">
        <span class="field-label">中文全称</span>
        <input v-model="draftFullZh" type="text" placeholder="中文全称" />
      </label>
      <label class="field">
        <span class="field-label">英文名</span>
        <input
          v-model="draftNameEn"
          type="text"
          placeholder="英文名（可自动生成 slug）"
          @blur="onNameEnBlur"
        />
      </label>
      <label class="field">
        <span class="field-label">缩写</span>
        <input v-model="draftAbbr" type="text" placeholder="缩写" />
      </label>
      <AppSelect
        v-model="draftMode"
        :options="[
          { label: '开放（黑名单）', value: 'open' },
          { label: '白名单', value: 'whitelist' },
        ]"
      />
      <textarea v-model="draftDescription" rows="2" placeholder="描述" />
      <button
        type="button"
        class="primary-btn"
        :disabled="saving || !canSubmitCreate"
        @click="submitCreate"
      >
        创建
      </button>
    </div>

    <div v-else-if="selected" class="form-grid">
      <div class="meta-row">
        <span class="meta-label">slug</span>
        <code>{{ selected.slug }}</code>
        <span v-if="selected.is_primary" class="pill">主入口</span>
      </div>
      <input v-model="draftNameZh" type="text" placeholder="中文短名" />
      <input v-model="draftFullZh" type="text" placeholder="中文全称" />
      <input v-model="draftNameEn" type="text" placeholder="英文名" />
      <input v-model="draftAbbr" type="text" placeholder="缩写" />
      <AppSelect
        v-model="draftMode"
        :options="[
          { label: '开放（黑名单）', value: 'open' },
          { label: '白名单', value: 'whitelist' },
        ]"
      />
      <textarea v-model="draftDescription" rows="2" placeholder="描述" />
      <div class="logo-row">
        <img
          v-if="selected.logo_url"
          class="logo-preview"
          :src="selected.logo_url"
          alt="theme logo"
        />
        <label class="secondary-btn file-btn">
          上传 Logo
          <input type="file" accept="image/*,.svg" hidden @change="onLogoChange" />
        </label>
      </div>
      <div class="actions-row">
        <button type="button" class="primary-btn" :disabled="saving" @click="saveSelectedMeta">
          保存主题信息
        </button>
        <button
          v-if="!selected.is_primary"
          type="button"
          class="danger-btn"
          :disabled="saving"
          @click="removeSelected"
        >
          删除主题
        </button>
      </div>

      <h4 class="sub-title">主题默认资源 ACL</h4>
      <p class="section-hint">对绑定本主题的用户生效；用户覆盖优先于此处规则。</p>
      <div v-if="permsLoading" class="loading">加载权限…</div>
      <table v-else-if="themePerms.length" class="user-table">
        <thead>
          <tr>
            <th>类型</th>
            <th>资源 ID</th>
            <th>权限</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in themePerms" :key="p.id">
            <td>{{ p.resource_type }}</td>
            <td>{{ p.resource_id }}</td>
            <td>{{ p.permission }}</td>
            <td>
              <button
                type="button"
                class="danger-btn"
                :disabled="saving"
                @click="removeThemePerm(p)"
              >
                移除
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="section-hint">暂无主题默认 ACL（开放模式下等同全量可见）。</p>
      <div class="perm-form">
        <AppSelect
          v-model="newType"
          :options="[
            { label: '图层', value: 'layer' },
            { label: '工作流', value: 'workflow' },
            { label: '数据源', value: 'data_source' },
          ]"
        />
        <input v-model="newId" type="text" placeholder="resource_id" />
        <AppSelect
          v-model="newPerm"
          :options="[
            { label: '允许', value: 'allow' },
            { label: '拒绝', value: 'deny' },
          ]"
        />
        <button type="button" class="secondary-btn" :disabled="saving" @click="addThemePerm">
          添加
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.theme-manager {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  max-width: 52rem;
}

.section-title {
  margin: 0;
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-medium, 600);
  color: var(--text-primary);
}

.section-hint {
  margin: 0;
  font-size: var(--font-size-caption);
  line-height: 1.5;
  color: var(--text-secondary);
}

.ok {
  color: var(--success);
  margin: 0;
  font-size: var(--font-size-caption);
}
.err {
  color: var(--danger);
  margin: 0;
  font-size: var(--font-size-caption);
  line-height: 1.45;
}

.toolbar-row,
.actions-row,
.logo-row,
.perm-form {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  align-items: center;
}

.form-grid {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.75rem 0.85rem;
  border-radius: var(--radius-lg, 10px);
  border: 1px solid var(--border-subtle);
  background: var(--surface-1);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 0;
}

.field-label {
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
  line-height: 1.3;
}

.form-grid input,
.form-grid textarea {
  padding: 0.45rem 0.6rem;
  border: 1px solid var(--border-default);
  border-radius: 8px;
  background: var(--surface-2, var(--surface-1));
  color: var(--text-primary);
  font-family: inherit;
  font-size: var(--font-size-caption);
  line-height: 1.4;
  min-height: 2.15rem;
  box-sizing: border-box;
  width: 100%;
}

.form-grid input:focus,
.form-grid textarea:focus {
  outline: 2px solid var(--accent-focus-ring);
  border-color: var(--accent-border);
}

.meta-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: var(--font-size-caption);
  min-height: 1.6rem;
}

.meta-label {
  color: var(--text-secondary);
}

.pill {
  padding: 0.12rem 0.35rem;
  border-radius: 4px;
  background: var(--accent-surface);
  color: var(--accent-strong);
  font-size: 0.65rem;
  font-weight: 600;
}

.logo-preview {
  width: 40px;
  height: 40px;
  object-fit: contain;
  border-radius: 8px;
  border: 1px solid var(--border-subtle);
}

.file-btn {
  cursor: pointer;
  font-size: var(--font-size-caption);
}

.sub-title {
  margin: 0.45rem 0 0;
  font-size: var(--font-size-caption);
  font-weight: 600;
  color: var(--text-secondary);
  letter-spacing: 0.02em;
}

.user-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-caption);
}

.user-table th,
.user-table td {
  text-align: left;
  padding: 0.4rem 0.45rem;
  border-bottom: 1px solid var(--border-subtle);
}

.primary-btn,
.secondary-btn,
.danger-btn {
  padding: 0.42rem 0.8rem;
  border-radius: 8px;
  border: 1px solid var(--border-default);
  font-family: inherit;
  font-size: var(--font-size-caption);
  font-weight: 600;
  line-height: 1.35;
  min-height: 2.15rem;
  box-sizing: border-box;
  cursor: pointer;
}

.primary-btn {
  background: var(--accent-surface);
  color: var(--accent-strong);
  border-color: var(--accent-border);
}

.secondary-btn {
  background: var(--surface-2, var(--surface-1));
  color: var(--text-primary);
}

.danger-btn {
  background: transparent;
  color: var(--danger);
  border-color: color-mix(in srgb, var(--danger, #c44) 55%, var(--border-default));
}

.primary-btn:disabled,
.secondary-btn:disabled,
.danger-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.loading {
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}
</style>
