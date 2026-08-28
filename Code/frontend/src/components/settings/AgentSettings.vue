<script setup lang="ts">
/**
 * AgentSettings — 全局(admin) / 个人 配置档分组 + 伴侣开关。
 */
import { computed, onMounted, ref, watch } from 'vue'
import {
  createAgentProfile,
  deleteAgentProfile,
  fetchAgentConfig,
  refreshAgentModels,
  setActiveAgentProfile,
  updateAgentProfile,
  useGlobalAgentProfile,
  type AgentPreset,
  type AgentProfile,
  type AgentProtocol,
  type AgentScope,
} from '../../services/agent-api'
import {
  isAgentCompanionEnabled,
  setAgentCompanionEnabled,
} from '../../services/settings-local'

const companionEnabled = ref(isAgentCompanionEnabled())

const loading = ref(false)
const saving = ref(false)
const activating = ref(false)
const refreshingModels = ref(false)
const error = ref<string | null>(null)
const savedFlash = ref(false)

const profiles = ref<AgentProfile[]>([])
const presets = ref<AgentPreset[]>([])
const activeProfileId = ref('')
const activeScope = ref<AgentScope>('global')
const canManageGlobal = ref(false)
const canManagePersonal = ref(false)
const selectedId = ref('')
const selectedScope = ref<AgentScope>('personal')
const createScope = ref<AgentScope>('personal')

const name = ref('')
const protocol = ref<AgentProtocol>('demo')
const baseUrl = ref('')
const model = ref('')
const contextIn = ref(8192)
const contextOut = ref(4096)
const apiKeyInput = ref('')
const hasApiKey = ref(false)
const clearApiKey = ref(false)
const modelOptions = ref<string[]>([])
const modelsManualHint = ref<string | null>(null)

const globalProfiles = computed(() => profiles.value.filter((p) => p.scope === 'global'))
const personalProfiles = computed(() => profiles.value.filter((p) => p.scope === 'personal'))
const selected = computed(
  () =>
    profiles.value.find((p) => p.id === selectedId.value && p.scope === selectedScope.value) ??
    null,
)
const canEditSelected = computed(() => {
  if (!selected.value) return false
  if (selected.value.scope === 'global') return canManageGlobal.value
  return canManagePersonal.value
})
const needsRemote = computed(() => protocol.value !== 'demo')
const protocolOptions: Array<{ value: AgentProtocol; label: string }> = [
  { value: 'demo', label: '演示' },
  { value: 'openai', label: 'OpenAI 兼容' },
  { value: 'anthropic', label: 'Anthropic 兼容' },
]

function onCompanionChange(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  companionEnabled.value = checked
  setAgentCompanionEnabled(checked)
}

function applyBundle(bundle: {
  active_profile_id: string
  active_scope: AgentScope
  can_manage_global: boolean
  can_manage_personal: boolean
  profiles: AgentProfile[]
  presets: AgentPreset[]
}) {
  profiles.value = bundle.profiles
  presets.value = bundle.presets
  activeProfileId.value = bundle.active_profile_id
  activeScope.value = bundle.active_scope
  canManageGlobal.value = bundle.can_manage_global
  canManagePersonal.value = bundle.can_manage_personal
  createScope.value = bundle.can_manage_personal
    ? 'personal'
    : bundle.can_manage_global
      ? 'global'
      : 'personal'
  const still =
    bundle.profiles.find((p) => p.id === selectedId.value && p.scope === selectedScope.value) ||
    bundle.profiles.find((p) => p.id === bundle.active_profile_id && p.scope === bundle.active_scope) ||
    bundle.profiles[0]
  if (still) {
    selectedId.value = still.id
    selectedScope.value = still.scope
  }
}

function applySelected(profile: AgentProfile | null) {
  if (!profile) return
  name.value = profile.name
  protocol.value = profile.protocol
  baseUrl.value = profile.base_url
  model.value = profile.model
  contextIn.value = profile.context_window_input
  contextOut.value = profile.context_window_output
  hasApiKey.value = profile.has_api_key
  apiKeyInput.value = ''
  clearApiKey.value = false
  modelsManualHint.value = null
}

watch(selected, (p) => applySelected(p), { immediate: true })

async function loadConfig() {
  loading.value = true
  error.value = null
  try {
    applyBundle(await fetchAgentConfig())
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

function onSelectProfile(p: AgentProfile) {
  selectedId.value = p.id
  selectedScope.value = p.scope
}

async function onActivate(p: AgentProfile) {
  if (p.scope === 'global' && !canManageGlobal.value) {
    // Fall back to global active by clearing personal
    activating.value = true
    error.value = null
    try {
      applyBundle(await useGlobalAgentProfile())
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      activating.value = false
    }
    return
  }
  if (p.scope === 'personal' && !canManagePersonal.value) {
    error.value = '无权切换个人配置档。'
    return
  }
  activating.value = true
  error.value = null
  try {
    applyBundle(await setActiveAgentProfile(p.id, p.scope))
    selectedId.value = p.id
    selectedScope.value = p.scope
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    activating.value = false
  }
}

async function onCreateFromPreset(presetId: string) {
  const scope = createScope.value
  if (scope === 'global' && !canManageGlobal.value) {
    error.value = '仅管理员可新建全局配置档。'
    return
  }
  if (scope === 'personal' && !canManagePersonal.value) {
    error.value = '当前账户无法新建个人配置档。'
    return
  }
  saving.value = true
  error.value = null
  try {
    const created = await createAgentProfile({ preset_id: presetId, scope })
    await loadConfig()
    selectedId.value = created.id
    selectedScope.value = created.scope
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    saving.value = false
  }
}

async function onDelete() {
  if (!selected.value || !canEditSelected.value) return
  if (selected.value.scope === 'global' && globalProfiles.value.length <= 1) {
    error.value = '不能删除最后一个全局配置档。'
    return
  }
  if (!window.confirm(`确定删除配置档「${selected.value.name}」？`)) return
  saving.value = true
  error.value = null
  try {
    applyBundle(await deleteAgentProfile(selected.value.id, selected.value.scope))
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    saving.value = false
  }
}

async function saveProfile() {
  if (!selected.value || !canEditSelected.value) {
    error.value = '无权保存此配置档。'
    return
  }
  saving.value = true
  error.value = null
  savedFlash.value = false
  try {
    const body: Parameters<typeof updateAgentProfile>[1] = {
      scope: selected.value.scope,
      name: name.value.trim(),
      protocol: protocol.value,
      base_url: baseUrl.value.trim(),
      model: model.value.trim(),
      context_window_input: Number(contextIn.value) || 8192,
      context_window_output: Number(contextOut.value) || 4096,
    }
    if (clearApiKey.value) {
      body.clear_api_key = true
    } else if (apiKeyInput.value.trim()) {
      body.api_key = apiKeyInput.value.trim()
    }
    const updated = await updateAgentProfile(selected.value.id, body)
    profiles.value = profiles.value.map((p) =>
      p.id === updated.id && p.scope === updated.scope ? updated : p,
    )
    applySelected(updated)
    savedFlash.value = true
    window.setTimeout(() => {
      savedFlash.value = false
    }, 2000)
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    saving.value = false
  }
}

async function onRefreshModels() {
  if (!selected.value) return
  refreshingModels.value = true
  error.value = null
  modelsManualHint.value = null
  try {
    const res = await refreshAgentModels(selected.value.id, selected.value.scope)
    modelOptions.value = res.models
    if (res.manual || res.error) {
      modelsManualHint.value = res.error || '该站点未提供模型列表，请手动填写模型名。'
    }
  } catch (err) {
    modelsManualHint.value = err instanceof Error ? err.message : String(err)
  } finally {
    refreshingModels.value = false
  }
}

onMounted(() => {
  void loadConfig()
})
</script>

<template>
  <div class="agent-settings">
    <section class="settings-section">
      <h3 class="section-title">地图助手（Web）</h3>
      <p class="section-hint">
        控制主前端地图上的机器人挂件。仅影响 Web 端；微信小程序不使用本配置。
      </p>
      <label class="toggle-row">
        <input type="checkbox" :checked="companionEnabled" @change="onCompanionChange" />
        <span>显示 Agent 伴侣挂件</span>
      </label>
    </section>

    <section class="settings-section">
      <h3 class="section-title">模型配置档</h3>
      <p class="section-hint">
        全局档由管理员维护；个人档仅本人可写。对话优先使用你启用的个人档，否则回退全局启用档。预设 URL 来自
        agentKits/presets/provider_catalog.json。
      </p>

      <div v-if="loading" class="status-line">加载配置中…</div>
      <div v-else class="profile-layout">
        <aside class="profile-list">
          <div class="group-label">全局（管理员）</div>
          <button
            v-for="p in globalProfiles"
            :key="`g-${p.id}`"
            type="button"
            class="profile-chip"
            :class="{
              selected: p.id === selectedId && selectedScope === 'global',
              active: p.id === activeProfileId && activeScope === 'global',
            }"
            @click="onSelectProfile(p)"
          >
            <span class="chip-name">{{ p.name }}</span>
            <span v-if="p.id === activeProfileId && activeScope === 'global'" class="chip-badge"
              >启用中</span
            >
          </button>

          <div class="group-label">我的配置</div>
          <button
            v-for="p in personalProfiles"
            :key="`p-${p.id}`"
            type="button"
            class="profile-chip"
            :class="{
              selected: p.id === selectedId && selectedScope === 'personal',
              active: p.id === activeProfileId && activeScope === 'personal',
            }"
            @click="onSelectProfile(p)"
          >
            <span class="chip-name">{{ p.name }}</span>
            <span v-if="p.id === activeProfileId && activeScope === 'personal'" class="chip-badge"
              >启用中</span
            >
          </button>
          <p v-if="!personalProfiles.length" class="status-line">暂无个人配置档</p>

          <div class="preset-create">
            <label class="field-label">从预设新建</label>
            <select
              v-if="canManageGlobal && canManagePersonal"
              v-model="createScope"
              class="field-input"
              :disabled="saving"
            >
              <option value="personal">个人</option>
              <option value="global">全局</option>
            </select>
            <select
              class="field-input"
              :disabled="saving || (!canManageGlobal && !canManagePersonal)"
              @change="
                (e) => {
                  const v = (e.target as HTMLSelectElement).value
                  if (v) void onCreateFromPreset(v)
                  ;(e.target as HTMLSelectElement).value = ''
                }
              "
            >
              <option value="">选择预设…</option>
              <option v-for="pre in presets" :key="pre.id" :value="pre.id">
                {{ pre.name }}
              </option>
            </select>
          </div>
        </aside>

        <div v-if="selected" class="profile-editor">
          <div class="editor-toolbar">
            <button
              type="button"
              class="btn-secondary"
              :disabled="
                activating ||
                (selected.id === activeProfileId && selected.scope === activeScope)
              "
              @click="onActivate(selected)"
            >
              {{
                selected.id === activeProfileId && selected.scope === activeScope
                  ? '当前已启用'
                  : selected.scope === 'global' && !canManageGlobal
                    ? '改用此全局档'
                    : '设为启用'
              }}
            </button>
            <button
              type="button"
              class="btn-danger"
              :disabled="saving || !canEditSelected"
              @click="onDelete"
            >
              删除
            </button>
          </div>

          <div class="field-grid">
            <label class="field">
              <span class="field-label">名称</span>
              <input
                v-model="name"
                type="text"
                class="field-input"
                :disabled="!canEditSelected"
              />
            </label>
            <label class="field">
              <span class="field-label">协议</span>
              <select v-model="protocol" class="field-input" :disabled="!canEditSelected">
                <option v-for="opt in protocolOptions" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </option>
              </select>
            </label>
            <template v-if="needsRemote">
              <label class="field">
                <span class="field-label">API Base URL</span>
                <input
                  v-model="baseUrl"
                  type="url"
                  class="field-input"
                  :disabled="!canEditSelected"
                />
              </label>
              <label class="field">
                <span class="field-label">模型</span>
                <div class="model-row">
                  <input
                    v-model="model"
                    type="text"
                    class="field-input"
                    list="agent-model-options"
                    :disabled="!canEditSelected"
                  />
                  <datalist id="agent-model-options">
                    <option v-for="m in modelOptions" :key="m" :value="m" />
                  </datalist>
                  <button
                    type="button"
                    class="btn-secondary"
                    :disabled="refreshingModels || !canEditSelected"
                    @click="onRefreshModels"
                  >
                    {{ refreshingModels ? '刷新中…' : '刷新模型' }}
                  </button>
                </div>
                <span v-if="modelsManualHint" class="field-hint">{{ modelsManualHint }}</span>
              </label>
              <div class="field-row-2">
                <label class="field">
                  <span class="field-label">上下文输入上限</span>
                  <input
                    v-model.number="contextIn"
                    type="number"
                    min="256"
                    class="field-input"
                    :disabled="!canEditSelected"
                  />
                </label>
                <label class="field">
                  <span class="field-label">上下文输出上限</span>
                  <input
                    v-model.number="contextOut"
                    type="number"
                    min="64"
                    class="field-input"
                    :disabled="!canEditSelected"
                  />
                </label>
              </div>
              <label class="field">
                <span class="field-label">API Key</span>
                <input
                  v-model="apiKeyInput"
                  type="password"
                  class="field-input"
                  :placeholder="hasApiKey ? '已配置（留空则不修改）' : 'Ollama 通常可留空'"
                  :disabled="!canEditSelected || clearApiKey"
                  autocomplete="off"
                />
              </label>
              <label v-if="hasApiKey" class="toggle-row">
                <input v-model="clearApiKey" type="checkbox" :disabled="!canEditSelected" />
                <span>清除已保存的 API Key</span>
              </label>
            </template>
          </div>

          <div class="actions">
            <button
              type="button"
              class="btn-save"
              :disabled="saving || !canEditSelected"
              @click="saveProfile"
            >
              {{ saving ? '保存中…' : '保存配置档' }}
            </button>
            <span v-if="savedFlash" class="flash-ok">已保存</span>
            <span v-if="!canEditSelected" class="flash-muted">无权编辑此配置档</span>
          </div>
        </div>
      </div>
      <p v-if="error" class="error-line">{{ error }}</p>
    </section>
  </div>
</template>

<style scoped>
.agent-settings {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.settings-section {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.section-title {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-strong);
}

.section-hint {
  margin: 0;
  font-size: var(--font-size-caption);
  line-height: 1.5;
  color: var(--text-muted);
}

.toggle-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--text-primary);
  font-size: 0.875rem;
  cursor: pointer;
}

.profile-layout {
  display: grid;
  grid-template-columns: minmax(140px, 220px) 1fr;
  gap: 1rem;
  align-items: start;
}

@media (max-width: 720px) {
  .profile-layout {
    grid-template-columns: 1fr;
  }
}

.profile-list {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.group-label {
  margin-top: 0.35rem;
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.profile-chip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.35rem;
  text-align: left;
  border-radius: 8px;
  border: 1px solid var(--border-default);
  background: var(--surface-1);
  color: var(--text-primary);
  padding: 0.45rem 0.55rem;
  font: inherit;
  font-size: 0.8125rem;
  cursor: pointer;
}

.profile-chip.selected {
  border-color: var(--accent-border);
  background: var(--accent-surface);
}

.chip-badge {
  flex-shrink: 0;
  font-size: 0.65rem;
  color: var(--accent-strong);
}

.preset-create {
  margin-top: 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.profile-editor {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}

.editor-toolbar {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.field-grid {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.field-row-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.65rem;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.field-label {
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}

.field-hint {
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}

.field-input {
  border-radius: 8px;
  border: 1px solid var(--border-default);
  background: var(--surface-1);
  color: var(--text-primary);
  padding: 0.45rem 0.6rem;
  font: inherit;
  font-size: 0.875rem;
}

.field-input:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.model-row {
  display: flex;
  gap: 0.5rem;
}

.model-row .field-input {
  flex: 1;
  min-width: 0;
}

.actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.btn-save,
.btn-secondary,
.btn-danger {
  border-radius: 8px;
  font-size: 0.8125rem;
  font-weight: 600;
  padding: 0.45rem 0.85rem;
  cursor: pointer;
  font: inherit;
}

.btn-save {
  border: 1px solid var(--accent-border);
  background: var(--accent-surface);
  color: var(--accent-strong);
}

.btn-secondary {
  border: 1px solid var(--border-default);
  background: var(--surface-1);
  color: var(--text-primary);
}

.btn-danger {
  border: 1px solid var(--danger, #c44);
  background: transparent;
  color: var(--danger, #c44);
}

.btn-save:disabled,
.btn-secondary:disabled,
.btn-danger:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.flash-ok {
  color: var(--success);
  font-size: var(--font-size-caption);
}

.flash-muted,
.status-line {
  color: var(--text-muted);
  font-size: var(--font-size-caption);
}

.error-line {
  margin: 0;
  color: var(--danger);
  font-size: var(--font-size-caption);
}
</style>
