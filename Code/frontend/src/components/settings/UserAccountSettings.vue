<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  createAuthToken,
  listAuthTokens,
  revokeAuthToken,
  type AuthToken,
  type UserRole,
} from '../../services/auth-api'
import { useAuthStore } from '../../stores/auth'
import AppSelect from '../ui/AppSelect.vue'
import UserPermissionsDialog from './UserPermissionsDialog.vue'
import ThemeManagerSettings from './ThemeManagerSettings.vue'

const emit = defineEmits<{ close: [] }>()

const auth = useAuthStore()
const router = useRouter()

const newUsername = ref('')
const newPassword = ref('')
const newRole = ref<UserRole>('standard')
const newThemeId = ref<number | null>(null)
const tokenLabel = ref('')
const tokens = ref<AuthToken[]>([])
const tokensLoading = ref(false)
const createdToken = ref<string | null>(null)
const message = ref<string | null>(null)
const error = ref<string | null>(null)

// 权限覆盖对话框：被「操作」列的「权限覆盖」按钮打开（仅管理员）
interface UserPermDialogUser {
  id: number
  username: string
  role: UserRole
  permission_mode?: string
  theme_id?: number | null
  theme_name?: string | null
}
const permDialogUser = ref<UserPermDialogUser | null>(null)

const ROLE_LABEL: Record<UserRole, string> = {
  admin: '管理员',
  standard: '标准用户',
  demo: '演示',
}

const themeSelectOptions = computed(() =>
  (auth.themes ?? []).map((t) => ({
    label: `${t.name_zh}${t.is_primary ? '（主）' : ''}`,
    value: String(t.id),
  })),
)

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
  if (auth.isAdmin) {
    void auth.loadUsers()
    void auth.loadThemes().then(() => {
      const list = auth.themes ?? []
      const primary = list.find((t) => t.is_primary) ?? list[0]
      if (primary && newThemeId.value == null) newThemeId.value = primary.id
    })
  }
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
    await auth.addUser(username, newPassword.value, newRole.value, newThemeId.value)
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

async function changeTheme(userId: number, themeIdRaw: string) {
  error.value = null
  const themeId = Number(themeIdRaw)
  if (!Number.isFinite(themeId)) return
  try {
    await auth.patchUser(userId, { theme_id: themeId })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '更新主题失败'
  }
}

async function removeAccount(userId: number, username: string) {
  if (!window.confirm(`确定删除用户 ${username}？`)) return
  error.value = null
  try {
    await auth.removeUser(userId)
    message.value = '用户已删除'
    if (permDialogUser.value?.id === userId) {
      permDialogUser.value = null
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : '删除失败'
  }
}

/** 打开「用户权限覆盖」对话框（管理员专属） */
function openPermDialog(
  userId: number,
  username: string,
  role: UserRole,
  permissionMode?: string,
  themeId?: number | null,
) {
  if (!auth.isAdmin) return
  const theme = themeId != null ? (auth.themes ?? []).find((t) => t.id === themeId) : null
  permDialogUser.value = {
    id: userId,
    username,
    role,
    permission_mode: permissionMode,
    theme_id: themeId,
    theme_name: theme?.name_zh ?? null,
  }
}

function onPermDialogUpdated(userId: number, mode: string) {
  const idx = auth.users.findIndex((u) => u.id === userId)
  if (idx >= 0) {
    auth.users[idx] = { ...auth.users[idx], permission_mode: mode }
  }
  message.value = '用户权限已更新'
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
        <AppSelect
          v-if="themeSelectOptions.length"
          :model-value="newThemeId != null ? String(newThemeId) : ''"
          :options="themeSelectOptions"
          @change="(val) => (newThemeId = Number(val))"
        />
        <button type="button" class="primary-btn" @click="createAccount">创建用户</button>
      </div>

      <div v-if="auth.usersLoading" class="loading">加载用户列表…</div>
      <table v-else class="user-table">
        <thead>
          <tr>
            <th>用户名</th>
            <th>角色</th>
            <th>主题</th>
            <th>状态</th>
            <th>权限模式</th>
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
              <AppSelect
                v-if="themeSelectOptions.length"
                :model-value="u.theme_id != null ? String(u.theme_id) : ''"
                :options="themeSelectOptions"
                @change="(val) => changeTheme(u.id, String(val))"
              />
              <span v-else>—</span>
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
            <td class="mode-cell">
              <span :class="['mode-pill', `mode-pill--${u.permission_mode || 'open'}`]">
                {{ u.permission_mode === 'whitelist' ? '白名单' : '开放' }}
              </span>
            </td>
            <td class="action-cell">
              <button
                type="button"
                class="secondary-btn perm-btn"
                @click="openPermDialog(u.id, u.username, u.role, u.permission_mode, u.theme_id)"
              >
                权限覆盖
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
    </section>

    <ThemeManagerSettings v-if="auth.isAdmin" />

    <UserPermissionsDialog
      :open="permDialogUser !== null"
      :user="permDialogUser"
      @close="permDialogUser = null"
      @updated="onPermDialogUpdated"
    />
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
  background: var(--success-surface);
  color: var(--text-strong);
}

.account-avatar {
  width: 2.4rem;
  height: 2.4rem;
  border-radius: 50%;
  background: var(--accent);
  color: var(--surface-1);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: var(--font-weight-semibold);
  font-size: var(--font-size-body);
}

.account-meta {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  flex: 1;
}

.account-name {
  margin: 0;
  font-weight: var(--font-weight-semibold);
}

.account-role {
  margin: 0;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}

.logout-btn {
  padding: 0.35rem 0.9rem;
  border: 1px solid var(--border-subtle);
  border-radius: 0.45rem;
  background: var(--surface-1);
  color: var(--text-primary);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--font-size-caption);
  transition: background-color var(--motion-fast) var(--ease-soft);
}

.logout-btn:hover {
  background: var(--surface-hover);
}

.settings-section {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.section-title {
  margin: 0;
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-semibold);
  color: var(--text-strong);
}

.section-hint {
  margin: 0;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
  line-height: 1.5;
}

.create-form {
  display: grid;
  grid-template-columns: 1fr 1fr 10rem auto;
  gap: 0.5rem;
  align-items: center;
}

.create-form input,
.create-form select {
  height: 2rem;
  padding: 0 0.55rem;
  border: 1px solid var(--border-default);
  border-radius: 0.4rem;
  background: var(--surface-1);
  color: var(--text-primary);
  font-family: inherit;
  font-size: var(--font-size-caption);
}

.token-form {
  grid-template-columns: 1fr auto;
}

.primary-btn,
.secondary-btn,
.danger-btn {
  height: 2rem;
  padding: 0 0.9rem;
  border-radius: 0.4rem;
  cursor: pointer;
  font-family: inherit;
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-medium);
  transition: background-color var(--motion-fast) var(--ease-soft);
}

.primary-btn {
  border: 1px solid var(--accent);
  background: var(--accent);
  color: var(--surface-1);
}

.primary-btn:hover:not(:disabled) {
  background: var(--accent-border);
}

.primary-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.secondary-btn {
  border: 1px solid var(--border-default);
  background: var(--surface-1);
  color: var(--text-primary);
}

.secondary-btn:hover:not(:disabled) {
  background: var(--surface-hover);
  border-color: var(--border-accent);
}

.secondary-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.danger-btn {
  border: 1px solid var(--danger, #f87171);
  background: var(--surface-1);
  color: var(--danger, #f87171);
}

.danger-btn:hover:not(:disabled) {
  background: var(--danger, #f87171);
  color: var(--text-strong);
}

.ok {
  margin: 0;
  padding: 0.35rem 0.6rem;
  border-radius: 0.4rem;
  background: var(--success-surface);
  color: var(--success, #4ade80);
  font-size: var(--font-size-caption);
}

.err {
  margin: 0;
  padding: 0.35rem 0.6rem;
  border-radius: 0.4rem;
  background: rgba(248, 113, 113, 0.1);
  color: var(--danger, #f87171);
  font-size: var(--font-size-caption);
}

.loading {
  padding: 0.6rem;
  text-align: center;
  color: var(--text-faint);
  font-size: var(--font-size-caption);
}

.user-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-caption);
}

.user-table th,
.user-table td {
  padding: 0.4rem 0.5rem;
  border-bottom: 1px solid var(--border-subtle);
  text-align: left;
}

.user-table th {
  color: var(--text-faint);
  font-weight: var(--font-weight-medium);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-size: 0.7rem;
}

.user-table td {
  color: var(--text-primary);
  vertical-align: middle;
}

.enabled-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  cursor: pointer;
}

.enabled-toggle input[type='checkbox'] {
  margin: 0;
}

.action-cell {
  display: flex;
  gap: 0.4rem;
  align-items: center;
}

.perm-btn {
  background: var(--accent-surface);
  color: var(--accent);
  border-color: var(--border-accent);
}

.perm-btn:hover:not(:disabled) {
  background: var(--accent);
  color: var(--text-strong);
}

.mode-cell {
  color: var(--text-secondary);
}

.mode-pill {
  display: inline-block;
  padding: 0.08rem 0.5rem;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: var(--font-weight-medium);
  border: 1px solid currentColor;
}

.mode-pill--open {
  color: var(--text-secondary);
  background: var(--surface-1);
}

.mode-pill--whitelist {
  color: var(--accent);
  background: var(--accent-surface);
}

.token-plain {
  font-family: var(--font-mono, ui-monospace, monospace);
  word-break: break-all;
}
</style>
