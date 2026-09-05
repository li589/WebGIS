<script setup lang="ts">
/**
 * 主题管理（管理员）：品牌字段、默认权限模式、主题默认资源 ACL、logo、
 * 图层分组预设状态（运行时预设 ≠ 种子 JSON）。
 */
import { computed, onMounted, ref, watch } from 'vue'

import {
  createTheme,
  deleteTheme,
  updateTheme,
  uploadThemeLogo,
  type LoginPalette,
  type PermissionMode,
} from '../../services/auth-api'
import {
  deleteThemeLayerGroupPreset,
  fetchThemeLayerGroupPreset,
  type ThemeLayerGroupPresetMeta,
} from '../../services/layer-groups-api'
import { useAuthStore } from '../../stores/auth'
import { requestOpenLayerGroupManager } from '../../utils/layer-group-manager-bridge'
import { LOGIN_PALETTE_OPTIONS } from '../../views/login-theme-presets'
import AppSelect from '../ui/AppSelect.vue'
import ResourceAclEditor from './ResourceAclEditor.vue'

const auth = useAuthStore()

const message = ref<string | null>(null)
const error = ref<string | null>(null)
const saving = ref(false)
const selectedId = ref<number | null>(null)
const presetMeta = ref<ThemeLayerGroupPresetMeta | null>(null)
const presetLoading = ref(false)

const draftSlug = ref('')
const draftNameZh = ref('')
const draftFullZh = ref('')
const draftNameEn = ref('')
const draftAbbr = ref('SGFS')
const draftDescription = ref('')
const draftMode = ref<PermissionMode>('open')
const draftLoginPalette = ref<LoginPalette>('cyan')
const creating = ref(false)

const loginPaletteOptions = LOGIN_PALETTE_OPTIONS.map((o) => ({
  label: o.label,
  value: o.id,
}))

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
  draftLoginPalette.value = 'cyan'
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
      login_palette: draftLoginPalette.value,
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
      login_palette: draftLoginPalette.value,
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
    draftLoginPalette.value = (t.login_palette as LoginPalette) || 'cyan'
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

function onSelectTheme(val: string) {
  creating.value = false
  selectedId.value = Number(val)
}

async function loadPresetMeta(themeId: number | null) {
  presetMeta.value = null
  if (themeId == null || themeId <= 0) return
  presetLoading.value = true
  try {
    const detail = await fetchThemeLayerGroupPreset(themeId)
    presetMeta.value = {
      theme_id: detail.theme_id,
      has_preset: detail.has_preset,
      updated_at: detail.updated_at,
      updated_by_user_id: detail.updated_by_user_id,
      display_name_count:
        detail.display_name_count ?? Object.keys(detail.display_names || {}).length,
    }
  } catch {
    presetMeta.value = {
      theme_id: themeId,
      has_preset: false,
      updated_at: null,
      updated_by_user_id: null,
      display_name_count: 0,
    }
  } finally {
    presetLoading.value = false
  }
}

watch(selectedId, (id) => {
  if (!creating.value) void loadPresetMeta(id)
})

function openGroupManagerForSelected() {
  if (selectedId.value == null) return
  requestOpenLayerGroupManager(selectedId.value)
}

async function clearSelectedPreset() {
  if (selectedId.value == null) return
  if (
    !window.confirm(
      '清除本主题的图层分组预设后，绑定用户将回落到种子分组基线（catalog_seeds）。确定清除？',
    )
  ) {
    return
  }
  saving.value = true
  error.value = null
  message.value = null
  try {
    await deleteThemeLayerGroupPreset(selectedId.value)
    await loadPresetMeta(selectedId.value)
    message.value = '已清除主题分组预设（种子 JSON 未改动）'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '清除预设失败'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section class="settings-section theme-manager">
    <h3 class="section-title">主题管理（管理员）</h3>
    <p class="section-hint">
      每个用户必须绑定一个主题（默认主主题为「星地融合土壤数据平台」/ sgfs）。主题承载品牌与默认资源
      ACL；用户覆盖优先于主题默认。图层库分组 / 主题显示名在「分组管理」中<strong
        >直接编辑本主题预设</strong
      >
      （运行时 SQLite 快照，<strong>不会</strong>改写 catalog_seeds /
      gen:catalog）。「登录页配色」只影响未登录页。
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
      <label class="field">
        <span class="field-label">登录页配色（仅登录页）</span>
        <AppSelect v-model="draftLoginPalette" :options="loginPaletteOptions" />
      </label>
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
      <label class="field">
        <span class="field-label">登录页配色（仅登录页）</span>
        <AppSelect v-model="draftLoginPalette" :options="loginPaletteOptions" />
      </label>
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

      <h4 class="sub-title">图层分组预设</h4>
      <p class="section-hint">
        绑定本主题的用户消费此预设（组结构、图层归属、主题显示名）。无预设时回落种子基线。
      </p>
      <div class="meta-row preset-meta">
        <span class="meta-label">状态</span>
        <span v-if="presetLoading">加载中…</span>
        <template v-else-if="presetMeta?.has_preset">
          <span class="pill">已配置</span>
          <span v-if="presetMeta.updated_at" class="meta-label">{{ presetMeta.updated_at }}</span>
          <span v-if="(presetMeta.display_name_count ?? 0) > 0" class="meta-label">
            显示名覆盖 {{ presetMeta.display_name_count }} 项
          </span>
        </template>
        <span v-else class="meta-label">尚无预设（种子基线）</span>
      </div>
      <div class="actions-row">
        <button
          type="button"
          class="secondary-btn"
          :disabled="saving"
          @click="openGroupManagerForSelected"
        >
          编辑本主题分组…
        </button>
        <button
          type="button"
          class="danger-btn"
          :disabled="saving || !presetMeta?.has_preset"
          @click="clearSelectedPreset"
        >
          清除预设
        </button>
      </div>

      <h4 class="sub-title">主题默认资源 ACL</h4>
      <p class="section-hint">
        对绑定本主题的用户生效；用户覆盖优先于此处规则。支持图层 / 图层分组 / 工作流 /
        数据源——图层分组规则对其成员图层生效（图层级记录优先）。
      </p>
      <ResourceAclEditor :mode="{ kind: 'theme', themeId: selected.id }" />
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
.logo-row {
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
</style>
