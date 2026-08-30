<script setup lang="ts">
/**
 * DataInputPoliciesPanel — 调度策略编辑。
 * PUT 只写 runtime 覆盖（勿把合并表固化进 runtime）。
 */
import { computed, onMounted, ref } from 'vue'
import {
  fetchDataInputPolicies,
  putDataInputPolicies,
  INPUT_KEY_SOURCE_ROUTE_LOCAL_FIRST,
  INPUT_KEY_TIME_WINDOW_ALIGN,
  type DataInputPolicyItem,
  type DataInputPolicyMode,
} from '../../../services/data-input-policies-api'
import { useAuthStore } from '../../../stores/auth'

const authStore = useAuthStore()
const loading = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
const success = ref<string | null>(null)
const version = ref(1)
/** 编辑缓冲：合并表（展示）；保存时差分成 runtime */
const policies = ref<DataInputPolicyItem[]>([])
const seedPolicies = ref<DataInputPolicyItem[]>([])
const runtimeOverridePresent = ref(false)

const MODE_OPTIONS: { value: DataInputPolicyMode; label: string }[] = [
  { value: 'allow_silent', label: '静默自动' },
  { value: 'allow_with_confirm', label: '需确认' },
  { value: 'deny', label: '仅手动' },
]

const SCOPE_OPTIONS = [
  { value: '*', label: '全局 *' },
  { value: 'layer_id', label: '图层 layer_id' },
  { value: 'workflow_id', label: '工作流 workflow_id' },
  { value: 'module', label: '模块 module' },
]

const seedIdSet = computed(() => new Set(seedPolicies.value.map((p) => p.id)))

const sourceRoutePolicies = computed(() =>
  policies.value.filter((p) => p.input_key === INPUT_KEY_SOURCE_ROUTE_LOCAL_FIRST),
)
const alignPolicies = computed(() =>
  policies.value.filter((p) => p.input_key === INPUT_KEY_TIME_WINDOW_ALIGN),
)

function policyFingerprint(p: DataInputPolicyItem): string {
  return JSON.stringify({
    id: p.id,
    scope: p.scope,
    scope_id: p.scope_id ?? null,
    input_key: p.input_key,
    mode: p.mode,
    notes: p.notes ?? null,
  })
}

function isSeedUnchanged(p: DataInputPolicyItem): boolean {
  const seed = seedPolicies.value.find((s) => s.id === p.id)
  if (!seed) return false
  return policyFingerprint(seed) === policyFingerprint(p)
}

function originLabel(p: DataInputPolicyItem): string {
  if (!seedIdSet.value.has(p.id)) return 'runtime'
  if (isSeedUnchanged(p)) return 'seed'
  return '覆盖'
}

async function load() {
  loading.value = true
  error.value = null
  try {
    const doc = await fetchDataInputPolicies()
    version.value = doc.version ?? 1
    policies.value = (doc.policies ?? []).map((p) => ({ ...p }))
    seedPolicies.value = (doc.seed_policies ?? []).map((p) => ({ ...p }))
    runtimeOverridePresent.value = Boolean(doc.runtime_override_present)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function addPolicy(inputKey: string) {
  const id = `custom-${inputKey}-${Date.now().toString(36)}`
  policies.value.push({
    id,
    scope: 'layer_id',
    scope_id: '',
    input_key: inputKey,
    mode: inputKey === INPUT_KEY_SOURCE_ROUTE_LOCAL_FIRST ? 'allow_silent' : 'allow_with_confirm',
    notes: '',
  })
}

function removePolicy(id: string) {
  const existing = policies.value.find((p) => p.id === id)
  if (existing && seedIdSet.value.has(id) && isSeedUnchanged(existing)) {
    error.value =
      '种子策略不可删除；可改 mode 写成 runtime 覆盖，或在磁盘删 runtime 文件重置。'
    return
  }
  policies.value = policies.value.filter((p) => p.id !== id)
}

/** 仅收集相对 seed 有变更 / 纯 runtime 的条目 */
function buildRuntimeOverrides(cleaned: DataInputPolicyItem[]): DataInputPolicyItem[] {
  const seedById = new Map(seedPolicies.value.map((p) => [p.id, p]))
  const out: DataInputPolicyItem[] = []
  for (const p of cleaned) {
    const seed = seedById.get(p.id)
    if (!seed) {
      out.push(p)
      continue
    }
    if (policyFingerprint(seed) !== policyFingerprint(p)) {
      out.push(p)
    }
  }
  return out
}

async function save() {
  if (!authStore.isAdmin) {
    error.value = '仅管理员可保存策略'
    return
  }
  saving.value = true
  error.value = null
  success.value = null
  try {
    const cleaned = policies.value
      .map((p) => ({
        ...p,
        id: String(p.id || '').trim(),
        scope_id: p.scope === '*' ? null : String(p.scope_id || '').trim() || null,
        notes: String(p.notes || '').trim() || null,
      }))
      .filter((p) => p.id && p.input_key)
    const runtimeOnly = buildRuntimeOverrides(cleaned)
    const doc = await putDataInputPolicies({
      version: version.value,
      policies: runtimeOnly,
    })
    version.value = doc.version ?? version.value
    policies.value = (doc.policies ?? []).map((p) => ({ ...p }))
    seedPolicies.value = (doc.seed_policies ?? seedPolicies.value).map((p) => ({ ...p }))
    runtimeOverridePresent.value = Boolean(doc.runtime_override_present)
    success.value = `已保存 ${runtimeOnly.length} 条 runtime 覆盖（未固化未改动的种子）。热载生效，无需重启。`
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="policy-panel">
    <p class="hint">
      源路由：声明了本地+在线变体的图层，按覆盖自动选源。时间窗对齐：零交集时是否允许对齐到最新可用窗。
      优先级：图层 &gt; 工作流 &gt; 模块 &gt; 全局。保存只写 runtime 覆盖，不会把种子整表固化。
    </p>
    <p v-if="runtimeOverridePresent" class="runtime-badge">已存在 runtime 覆盖</p>
    <p v-if="loading" class="muted">加载中…</p>
    <p v-if="error" class="err">{{ error }}</p>
    <p v-if="success" class="ok">{{ success }}</p>

    <section class="block">
      <header class="block-head">
        <h3>源路由（本地优先）</h3>
        <button
          v-if="authStore.isAdmin"
          type="button"
          class="btn-sm"
          @click="addPolicy(INPUT_KEY_SOURCE_ROUTE_LOCAL_FIRST)"
        >
          添加特例
        </button>
      </header>
      <table v-if="sourceRoutePolicies.length" class="policy-table">
        <thead>
          <tr>
            <th>来源</th>
            <th>id</th>
            <th>scope</th>
            <th>scope_id</th>
            <th>mode</th>
            <th>notes</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in sourceRoutePolicies" :key="p.id">
            <td class="origin">{{ originLabel(p) }}</td>
            <td><input v-model="p.id" :disabled="!authStore.isAdmin || originLabel(p) === 'seed'" /></td>
            <td>
              <select v-model="p.scope" :disabled="!authStore.isAdmin">
                <option v-for="s in SCOPE_OPTIONS" :key="s.value" :value="s.value">
                  {{ s.label }}
                </option>
              </select>
            </td>
            <td>
              <input
                v-model="p.scope_id"
                :disabled="!authStore.isAdmin || p.scope === '*'"
                placeholder="layer_id / …"
              />
            </td>
            <td>
              <select v-model="p.mode" :disabled="!authStore.isAdmin">
                <option v-for="m in MODE_OPTIONS" :key="m.value" :value="m.value">
                  {{ m.label }}
                </option>
              </select>
            </td>
            <td><input v-model="p.notes" :disabled="!authStore.isAdmin" /></td>
            <td>
              <button
                v-if="authStore.isAdmin"
                type="button"
                class="btn-sm danger"
                @click="removePolicy(p.id)"
              >
                删
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted">无源路由策略条目</p>
    </section>

    <section class="block">
      <header class="block-head">
        <h3>时间窗对齐</h3>
        <button
          v-if="authStore.isAdmin"
          type="button"
          class="btn-sm"
          @click="addPolicy(INPUT_KEY_TIME_WINDOW_ALIGN)"
        >
          添加特例
        </button>
      </header>
      <table v-if="alignPolicies.length" class="policy-table">
        <thead>
          <tr>
            <th>来源</th>
            <th>id</th>
            <th>scope</th>
            <th>scope_id</th>
            <th>mode</th>
            <th>notes</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in alignPolicies" :key="p.id">
            <td class="origin">{{ originLabel(p) }}</td>
            <td><input v-model="p.id" :disabled="!authStore.isAdmin || originLabel(p) === 'seed'" /></td>
            <td>
              <select v-model="p.scope" :disabled="!authStore.isAdmin">
                <option v-for="s in SCOPE_OPTIONS" :key="s.value" :value="s.value">
                  {{ s.label }}
                </option>
              </select>
            </td>
            <td>
              <input
                v-model="p.scope_id"
                :disabled="!authStore.isAdmin || p.scope === '*'"
                placeholder="layer_id / …"
              />
            </td>
            <td>
              <select v-model="p.mode" :disabled="!authStore.isAdmin">
                <option v-for="m in MODE_OPTIONS" :key="m.value" :value="m.value">
                  {{ m.label }}
                </option>
              </select>
            </td>
            <td><input v-model="p.notes" :disabled="!authStore.isAdmin" /></td>
            <td>
              <button
                v-if="authStore.isAdmin"
                type="button"
                class="btn-sm danger"
                @click="removePolicy(p.id)"
              >
                删
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted">无时间窗对齐策略条目</p>
    </section>

    <div v-if="authStore.isAdmin" class="actions">
      <button type="button" class="btn-sm" :disabled="loading || saving" @click="load">
        重新加载
      </button>
      <button type="button" class="btn-primary" :disabled="loading || saving" @click="save">
        {{ saving ? '保存中…' : '保存 runtime 覆盖' }}
      </button>
    </div>
    <p v-else class="muted">当前角色只读；修改策略需 admin。</p>
  </div>
</template>

<style scoped>
.policy-panel {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}
.hint {
  margin: 0;
  font-size: var(--font-size-caption);
  color: var(--text-muted);
  line-height: 1.5;
}
.runtime-badge {
  margin: 0;
  font-size: var(--font-size-caption);
  color: var(--accent-strong);
}
.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.4rem;
}
.block-head h3 {
  margin: 0;
  font-size: var(--font-size-body);
  font-weight: 600;
}
.policy-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-caption);
}
.policy-table th,
.policy-table td {
  border: 1px solid var(--border-subtle);
  padding: 0.25rem 0.35rem;
  vertical-align: middle;
}
.policy-table .origin {
  white-space: nowrap;
  color: var(--text-muted);
}
.policy-table input,
.policy-table select {
  width: 100%;
  min-width: 4rem;
  font: inherit;
  background: var(--surface-raised);
  color: var(--text-primary);
  border: 1px solid var(--border-subtle);
  border-radius: 0.25rem;
  padding: 0.15rem 0.3rem;
}
.actions {
  display: flex;
  gap: 0.5rem;
  justify-content: flex-end;
}
.btn-sm,
.btn-primary {
  font-size: var(--font-size-caption);
  padding: 0.3rem 0.65rem;
  border-radius: 0.35rem;
  border: 1px solid var(--border-subtle);
  background: var(--surface-raised);
  color: var(--text-primary);
  cursor: pointer;
}
.btn-primary {
  background: var(--accent-strong);
  color: #fff;
  border-color: transparent;
}
.btn-sm.danger {
  color: var(--danger, #c44);
}
.muted {
  color: var(--text-muted);
  font-size: var(--font-size-caption);
}
.err {
  color: var(--danger, #c44);
  font-size: var(--font-size-caption);
}
.ok {
  color: var(--success, #2a8);
  font-size: var(--font-size-caption);
}
</style>
