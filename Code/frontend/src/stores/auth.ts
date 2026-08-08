import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  createUser,
  deleteUser,
  fetchAuthConfig,
  fetchAuthMe,
  listUsers,
  loginRequest,
  logoutRequest,
  updateUser,
  type AuthConfig,
  type AuthUser,
  type UserRole,
} from '../services/auth-api'
import { clearBackendWriteApiKey } from '../services/backend-auth'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)
  const config = ref<AuthConfig | null>(null)
  const bootstrapped = ref(false)
  const bootstrapError = ref<string | null>(null)
  const users = ref<AuthUser[]>([])
  const usersLoading = ref(false)

  const isAuthenticated = computed(() => user.value !== null)
  const isAdmin = computed(() => user.value?.role === 'admin')
  const isViewer = computed(() => user.value?.role === 'viewer')
  const canWrite = computed(() => user.value?.role === 'admin' || user.value?.role === 'operator')
  const authRequired = computed(() => {
    if (bootstrapError.value) return true
    return config.value?.auth_required ?? true
  })

  async function applyDevAutoLogin() {
    const prefill = config.value?.dev_prefill
    if (!import.meta.env.DEV || !prefill || user.value) return
    const username = prefill.username
    const password = prefill.password
    if (!username || !password) return
    try {
      await login(username, password)
    } catch {
      // Manual login fallback.
    }
  }

  async function bootstrap() {
    if (bootstrapped.value) return
    bootstrapError.value = null
    try {
      config.value = await fetchAuthConfig()
      if (!config.value.auth_required) {
        try {
          user.value = await fetchAuthMe()
        } catch {
          user.value = null
        }
        bootstrapped.value = true
        return
      }
      try {
        user.value = await fetchAuthMe()
      } catch {
        user.value = null
      }
      if (!user.value) {
        await applyDevAutoLogin()
      }
    } catch (err) {
      bootstrapError.value = err instanceof Error ? err.message : String(err)
    } finally {
      bootstrapped.value = true
    }
  }

  async function login(username: string, password: string) {
    user.value = await loginRequest(username, password)
  }

  async function logout() {
    try {
      await logoutRequest()
    } finally {
      user.value = null
      clearBackendWriteApiKey()
    }
  }

  function clearSession() {
    user.value = null
    clearBackendWriteApiKey()
  }

  async function loadUsers() {
    usersLoading.value = true
    try {
      users.value = await listUsers()
    } finally {
      usersLoading.value = false
    }
  }

  async function addUser(username: string, password: string, role: UserRole) {
    const created = await createUser({ username, password, role })
    users.value = [...users.value, created]
    return created
  }

  async function patchUser(
    userId: number,
    patch: { password?: string; role?: UserRole; enabled?: boolean },
  ) {
    const updated = await updateUser(userId, patch)
    users.value = users.value.map((u) => (u.id === userId ? updated : u))
    if (user.value?.id === userId) {
      user.value = updated
    }
    return updated
  }

  async function removeUser(userId: number) {
    await deleteUser(userId)
    users.value = users.value.filter((u) => u.id !== userId)
  }

  async function retryBootstrap() {
    bootstrapped.value = false
    bootstrapError.value = null
    await bootstrap()
  }

  return {
    user,
    config,
    bootstrapped,
    bootstrapError,
    users,
    usersLoading,
    isAuthenticated,
    isAdmin,
    isViewer,
    canWrite,
    authRequired,
    bootstrap,
    retryBootstrap,
    login,
    logout,
    clearSession,
    loadUsers,
    addUser,
    patchUser,
    removeUser,
  }
})
