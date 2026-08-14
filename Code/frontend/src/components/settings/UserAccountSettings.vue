<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  createAuthToken,
  listAuthTokens,
  revokeAuthToken,
  listUserPermissions,
  setUserPermissions,
  deletePermission,
  updatePermissionMode,
  type AuthToken,
  type UserRole,
  type PermissionRecord,
  type PermissionItemInput,
  type ResourceType,
  type PermissionValue,
  type PermissionMode,
} from '../../services/auth-api'
import { useAuthStore } from '../../stores/auth'
import AppSelect from '../ui/AppSelect.vue'

const emit = defineEmits<{ close: [] }>()

const auth = useAuthStore()
const router = useRouter()

const newUsername = ref('')
const newPassword = ref('')
const newRole = ref<UserRole>('standard')
const tokenLabel = ref('')
const tokens = ref<AuthToken[]>([])
const tokensLoading = ref(false)
const createdToken = ref<string | null>(null)
const message = ref<string | null>(null)
const error = ref<string | null>(null)

// Phase B: Resource permissions state
const permUserId = ref<number | null>(null)
const permUsername = ref('')
const permRecords = ref<PermissionRecord[]>([])
const permMode = ref<PermissionMode>('open')
const permLoading = ref(false)
const newPermType = ref<ResourceType>('layer')
const newPermId = ref('')
const newPermValue = ref<PermissionValue>('deny')

const RESOURCE_TYPE_LABELS: Record<string, string> = {
  layer: '图层',
  workflow: '工作流',
  data_source: '数据源',
}

const ROLE_LABEL: Record<UserRole, string> = {
  admin: '管理员',
  standard: '标准用户',
  demo: '演示',
}

async function loadTokens() {
  tokensLoading.value = true
  try {
    tokens.value = await listAuthTokens()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载 Token 失败'
  } finally {
    tokensLoading.value = false
  }
}

onMounted(() => {
  if (auth.isAdmin) void auth.loadUsers()
  void loadTokens()
})

async function logout() {
  await auth.logout()
  emit('close')
  await router.replace('/login')
}

async function createAccount() {
  error.value = null
  message.value = null
  const username = newUsername.value.trim()
  if (!username) {
    error.value = '请输入用户名'
    return
  }
  if (newPassword.value.length < 8) {
    error.value = '密码至少需要 8 位'
    return
  }
  try {
    await auth.addUser(username, newPassword.value, newRole.value)
    message.value = '用户已创建'
    newUsername.value = ''
    newPassword.value = ''
    newRole.value = 'standard'
  } catch (err) {
    const msg = err instanceof Error ? err.message : '创建失败'
    if (msg.includes('username already exists') || msg.includes('已存在')) {
      error.value = `用户名「${username}」已存在，请换一个`
    } else if (msg.includes('400')) {
      error.value = '请求参数有误，请检查用户名和密码格式'
    } else {
      error.value = msg
    }
  }
}

async function createToken() {
  error.value = null
  createdToken.value = null
  try {
    const created = await createAuthToken({ label: tokenLabel.value || undefined })
    createdToken.value = created.token
    tokenLabel.value = ''
    await loadTokens()
    message.value = 'API Token 已创建（明文仅显示一次）'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '创建 Token 失败'
  }
}

async function revokeToken(tokenId: number) {
  error.value = null
  try {
    await revokeAuthToken(tokenId)
    await loadTokens()
    message.value = 'Token 已吊销'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '吊销失败'
  }
}

async function toggleEnabled(userId: number, enabled: boolean) {
  error.value = null
  try {
    await auth.patchUser(userId, { enabled })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '更新失败'
  }
}

async function changeRole(userId: number, role: UserRole) {
  error.value = null
  try {
    await auth.patchUser(userId, { role })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '更新失败'
  }
}

async function removeAccount(userId: number, username: string) {
  if (!window.confirm(`确定删除用户 ${username}？`)) return
  error.value = null
  try {
    await auth.removeUser(userId)
    message.value = '用户已删除'
    if (permUserId.value === userId) {
      permUserId.value = null
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : '删除失败'
  }
}

// Phase B: Resource permissions management
async function togglePermPanel(userId: number, username: string) {
  if (permUserId.value === userId) {
    permUserId.value = null
    return
  }
  permUserId.value = userId
  permUsername.value = username
  error.value = null
  message.value = null
  await loadPermissions(userId)
}

async function loadPermissions(userId: number) {
  permLoading.value = true
  try {
    permRecords.value = await listUserPermissions(userId)
    // Read permission_mode from the user object (added to UserPublic in Phase B)
    const user = auth.users.find((u) => u.id === userId)
    permMode.value = (user?.permission_mode as PermissionMode) || 'open'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载权限失败'
  } finally {
    permLoading.value = false
  }
}

async function changePermMode(mode: PermissionMode) {
  if (permUserId.value === null) return
  error.value = null
  try {
    await updatePermissionMode(permUserId.value, mode)
    permMode.value = mode
    const idx = auth.users.findIndex((u) => u.id === permUserId.value)
    if (idx >= 0) {
      const current = auth.users[idx]
      auth.users[idx] = { ...current, permission_mode: mode }
    }
    message.value =
      mode === 'whitelist'
        ? '已切换为白名单模式（仅允许记录可访问）'
        : '已切换为开放模式（无拒绝记录即可访问）'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '切换模式失败'
  }
}

async function addPermission() {
  if (permUserId.value === null) return
  const rid = newPermId.value.trim()
  if (!rid) {
    error.value = '请输入资源 ID'
    return
  }
  error.value = null
  try {
    const newPerm: PermissionItemInput = {
      resource_type: newPermType.value,
      resource_id: rid,
      permission: newPermValue.value,
    }
    const existing = permRecords.value.map((r) => ({
      resource_type: r.resource_type as ResourceType,
      resource_id: r.resource_id,
      permission: r.permission as PermissionValue,
    }))
    const result = await setUserPermissions(permUserId.value, [...existing, newPerm])
    permRecords.value = result
    newPermId.value = ''
    message.value = '权限已添加'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '添加权限失败'
  }
}

async function removePermission(permissionId: number) {
  if (permUserId.value === null) return
  error.value = null
  try {
    await deletePermission(permUserId.value, permissionId)
    permRecords.value = permRecords.value.filter((r) => r.id !== permissionId)
    message.value = '权限已删除'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '删除权限失败'
  }
}
</script>

<template>
  <div class="user-account-settings">
    <section v-if="auth.user" class="account-hero">
      <div class="account-avatar" aria-hidden="true">
        {{ auth.user.username.slice(0, 1).toUpperCase() }}
      </div>
      <div class="account-meta">
        <p class="account-name">{{ auth.user.username }}</p>
        <p class="account-role">{{ ROLE_LABEL[auth.user.role] }}</p>
      </div>
      <button type="button" class="logout-btn" @click="logout">退出登录</button>
    </section>

    <section class="settings-section">
      <h3 class="section-title">账户与登录</h3>
      <p class="section-hint">
        浏览器通过 HttpOnly 会话 Cookie 鉴权；外部脚本可使用下方个人 API
        Token，或联系管理员获取服务密钥。
      </p>
    </section>

    <section class="settings-section">
      <h3 class="section-title">个人 API Token</h3>
      <div class="create-form token-form">
        <input v-model="tokenLabel" type="text" placeholder="标签（可选）" />
        <button type="button" class="primary-btn" :disabled="!auth.canWrite" @click="createToken">
          创建 Token
        </button>
      </div>
      <p v-if="!auth.canWrite" class="section-hint">只读账户无法创建 API Token。</p>
      <p v-if="createdToken" class="ok token-plain">新 Token：{{ createdToken }}</p>
      <div v-if="tokensLoading" class="loading">加载 Token…</div>
      <table v-else-if="tokens.length" class="user-table">
        <thead>
          <tr>
            <th>用户</th>
            <th>标签</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in tokens" :key="t.id">
            <td>{{ t.username }}</td>
            <td>{{ t.label || '—' }}</td>
            <td>{{ t.created_at }}</td>
            <td>
              <button type="button" class="danger-btn" @click="revokeToken(t.id)">吊销</button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="auth.isAdmin" class="settings-section">
      <h3 class="section-title">用户管理（管理员）</h3>
      <p v-if="message" class="ok">{{ message }}</p>
      <p v-if="error" class="err">{{ error }}</p>

      <div class="create-form">
        <input v-model="newUsername" type="text" placeholder="新用户名" />
        <input v-model="newPassword" type="password" placeholder="初始密码（≥8位）" />
        <AppSelect
          v-model="newRole"
          :options="[
            { label: '管理员', value: 'admin' },
            { label: '标准用户', value: 'standard' },
            { label: '演示', value: 'demo' },
          ]"
        />
        <button type="button" class="primary-btn" @click="createAccount">创建用户</button>
      </div>

      <div v-if="auth.usersLoading" class="loading">加载用户列表…</div>
      <table v-else class="user-table">
        <thead>
          <tr>
            <th>用户名</th>
            <th>角色</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in auth.users" :key="u.id">
            <td>{{ u.username }}</td>
            <td>
              <AppSelect
                :model-value="u.role"
                :disabled="u.id === auth.user?.id"
                :options="[
                  { label: '管理员', value: 'admin' },
                  { label: '标准用户', value: 'standard' },
                  { label: '演示', value: 'demo' },
                ]"
                @change="(val) => changeRole(u.id, val as UserRole)"
              />
            </td>
            <td>
              <label class="enabled-toggle">
                <input
                  type="checkbox"
                  :checked="u.enabled"
                  :disabled="u.id === auth.user?.id"
                  @change="toggleEnabled(u.id, ($event.target as HTMLInputElement).checked)"
                />
                {{ u.enabled ? '启用' : '禁用' }}
              </label>
            </td>
            <td class="action-cell">
              <button
                v-if="u.role !== 'admin' && u.id !== auth.user?.id"
                type="button"
                class="secondary-btn perm-btn"
                :class="{ active: permUserId === u.id }"
                @click="togglePermPanel(u.id, u.username)"
              >
                权限
              </button>
              <button
                v-if="u.id !== auth.user?.id"
                type="button"
                class="danger-btn"
                @click="removeAccount(u.id, u.username)"
              >
                删除
              </button>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- Phase B: Resource permissions panel -->
      <div v-if="permUserId !== null" class="perm-panel">
        <h4 class="perm-panel-title">资源权限 — {{ permUsername }}</h4>
        <p class="section-hint">
          黑名单模式（开放）：无拒绝记录即可访问；白名单模式：仅允许记录可访问。
        </p>

        <div class="perm-mode-row">
          <span class="perm-mode-label">权限模式：</span>
          <AppSelect
            :model-value="permMode"
            :options="[
              { label: '开放（黑名单）', value: 'open' },
              { label: '白名单', value: 'whitelist' },
            ]"
            @change="(val) => changePermMode(val as PermissionMode)"
          />
        </div>

        <div class="perm-add-form">
          <AppSelect
            v-model="newPermType"
            :options="[
              { label: '图层', value: 'layer' },
              { label: '工作流', value: 'workflow' },
              { label: '数据源', value: 'data_source' },
            ]"
          />
          <input
            v-model="newPermId"
            type="text"
            placeholder="资源 ID（图层 ID / 工作流 ID / 路径）"
          />
          <AppSelect
            v-model="newPermValue"
            :options="[
              { label: '允许', value: 'allow' },
              { label: '拒绝', value: 'deny' },
            ]"
          />
          <button type="button" class="primary-btn" @click="addPermission">添加</button>
        </div>

        <div v-if="permLoading" class="loading">加载权限…</div>
        <table v-else-if="permRecords.length" class="user-table perm-table">
          <thead>
            <tr>
              <th>资源类型</th>
              <th>资源 ID</th>
              <th>权限</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in permRecords" :key="r.id">
              <td>{{ RESOURCE_TYPE_LABELS[r.resource_type] || r.resource_type }}</td>
              <td class="mono">{{ r.resource_id }}</td>
              <td>
                <span :class="r.permission === 'allow' ? 'perm-allow' : 'perm-deny'">
                  {{ r.permission === 'allow' ? '允许' : '拒绝' }}
                </span>
              </td>
              <td>
                <button type="button" class="danger-btn" @click="removePermission(r.id)">
                  移除
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="section-hint">暂无权限记录</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.user-account-settings {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.account-hero {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  padding: 0.75rem 0.8rem;
  border-radius: 0.65rem;
  border: 1px solid var(--success-surface);
  background: linear-gradient(135deg, var(--success-surface), var(--accent-surface));
}

.account-avatar {
  width: 2.2rem;
  height: 2.2rem;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 0.9rem;
  font-weight: 700;
  color: var(--success);
  background: var(--success-surface);
  border: 1px solid var(--success-border);
  flex: none;
}

.account-meta {
  flex: 1;
  min-width: 0;
}

.account-name {
  margin: 0;
  font-size: var(--font-size-caption);
  font-weight: 600;
  color: var(--text-strong);
}

.account-role {
  margin: 0.12rem 0 0;
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}

.logout-btn {
  flex: none;
  padding: 0.38rem 0.55rem;
  border-radius: 0.35rem;
  border: 1px solid var(--danger-border);
  background: var(--danger-surface);
  color: var(--danger);
  font: inherit;
  font-size: var(--font-size-caption);
  cursor: pointer;
}

.logout-btn:hover {
  background: var(--surface-hover);
}

.settings-section {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}

.section-title {
  margin: 0;
  font-size: var(--font-size-caption);
  color: var(--text-strong);
}

.section-hint {
  margin: 0;
  font-size: var(--font-size-caption);
  line-height: 1.45;
  color: var(--text-muted);
}

.create-form {
  display: grid;
  grid-template-columns: minmax(8rem, 14rem) minmax(8rem, 14rem) minmax(6rem, 8rem) auto;
  gap: 0.4rem;
  align-items: center;
}

.token-form {
  grid-template-columns: 1fr auto;
}

.create-form input,
.create-form select,
.user-table select {
  width: 100%;
  padding: 0.38rem 0.45rem;
  border: 1px solid var(--border-default);
  border-radius: 0.35rem;
  background: var(--surface-1);
  color: var(--text-strong);
  font: inherit;
  font-size: var(--font-size-caption);
}

.primary-btn,
.secondary-btn,
.danger-btn {
  padding: 0.38rem 0.55rem;
  border-radius: 0.35rem;
  border: 1px solid var(--border-accent);
  background: var(--accent-surface);
  color: var(--accent-strong);
  font: inherit;
  font-size: var(--font-size-caption);
  cursor: pointer;
}

.secondary-btn {
  align-self: flex-start;
}

.danger-btn {
  border-color: var(--danger-border);
  background: var(--danger-surface);
  color: var(--danger);
}

.user-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-caption);
  color: var(--text-primary);
}

.user-table th,
.user-table td {
  padding: 0.35rem 0.3rem;
  border-bottom: 1px solid var(--border-subtle);
  text-align: left;
}

.enabled-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}

.ok {
  margin: 0;
  color: var(--success);
  font-size: var(--font-size-caption);
}

.token-plain {
  word-break: break-all;
}

.err {
  margin: 0;
  color: var(--danger);
  font-size: var(--font-size-caption);
}

.loading {
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}

@media (max-width: 768px) {
  .create-form {
    grid-template-columns: 1fr;
  }
}

/* Phase B: Resource permissions panel */
.action-cell {
  display: flex;
  gap: 0.3rem;
}

.perm-btn.active {
  border-color: var(--accent-strong);
  background: var(--accent-strong);
  color: var(--surface-1);
}

.perm-panel {
  margin-top: 0.6rem;
  padding: 0.6rem 0.7rem;
  border: 1px solid var(--border-default);
  border-radius: 0.5rem;
  background: var(--surface-1);
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.perm-panel-title {
  margin: 0;
  font-size: var(--font-size-caption);
  font-weight: 600;
  color: var(--text-strong);
}

.perm-mode-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.perm-mode-label {
  font-size: var(--font-size-caption);
  color: var(--text-muted);
  white-space: nowrap;
}

.perm-add-form {
  display: grid;
  grid-template-columns: minmax(5rem, 7rem) 1fr minmax(4rem, 6rem) auto;
  gap: 0.35rem;
  align-items: center;
}

.perm-add-form input {
  width: 100%;
  padding: 0.38rem 0.45rem;
  border: 1px solid var(--border-default);
  border-radius: 0.35rem;
  background: var(--surface-1);
  color: var(--text-strong);
  font: inherit;
  font-size: var(--font-size-caption);
}

.perm-table .mono {
  font-family: var(--font-mono);
  font-size: 0.8em;
  word-break: break-all;
}

.perm-allow {
  color: var(--success);
  font-weight: 600;
}

.perm-deny {
  color: var(--danger);
  font-weight: 600;
}

@media (max-width: 768px) {
  .perm-add-form {
    grid-template-columns: 1fr;
  }
}
</style>
