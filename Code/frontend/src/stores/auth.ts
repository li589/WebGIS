import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

import {
  createUser,
  deleteUser,
  fetchAuthConfig,
  fetchAuthMe,
  fetchPrimaryThemePublic,
  fetchThemesPublic,
  listThemes,
  listUsers,
  loginRequest,
  logoutRequest,
  updateUser,
  type AuthConfig,
  type AuthUser,
  type ThemePublic,
  type ThemePublicBrand,
  type UserRole,
} from '../services/auth-api'
import { clearBackendWriteApiKey } from '../services/backend-auth'
import {
  applyDocumentTitle,
  brandFromTheme,
  staticBrand,
  type ResolvedBrand,
} from '../composables/useResolvedBrand'
import { clearUserLocalState, setActiveStorageUserId } from '../services/user-local-isolation'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)
  const config = ref<AuthConfig | null>(null)
  const bootstrapped = ref(false)
  const bootstrapError = ref<string | null>(null)
  const users = ref<AuthUser[]>([])
  const usersLoading = ref(false)
  const primaryTheme = ref<ThemePublic | null>(null)
  const publicThemes = ref<ThemePublicBrand[]>([])
  const loginPreviewSlug = ref<string | null>(null)
  const themes = ref<ThemePublic[]>([])
  const themesLoading = ref(false)

  const LOGIN_THEME_SLUG_KEY = 'cgda-login-theme-slug'

  const isAuthenticated = computed(() => user.value !== null)
  const isAdmin = computed(() => user.value?.role === 'admin')
  const isDemo = computed(() => user.value?.role === 'demo')
  const canWrite = computed(() => user.value?.role === 'admin' || user.value?.role === 'standard')
  /** 可提交/运行工作流（含 demo；创建定义仍看 canWrite） */
  const canRunWorkflow = computed(
    () =>
      user.value?.role === 'admin' ||
      user.value?.role === 'standard' ||
      user.value?.role === 'demo',
  )
  const authRequired = computed(() => {
    if (bootstrapError.value) return true
    return config.value?.auth_required ?? true
  })

  const activeTheme = computed<ThemePublic | null>(() => {
    const fromUser = user.value?.theme
    if (fromUser) return fromUser
    return primaryTheme.value
  })

  const loginPreviewTheme = computed<ThemePublicBrand | null>(() => {
    if (user.value) return null
    const slug = loginPreviewSlug.value
    if (!slug) return null
    return publicThemes.value.find((t) => t.slug === slug) ?? null
  })

  const resolvedBrand = computed<ResolvedBrand>(() => {
    if (loginPreviewTheme.value) {
      return brandFromTheme(loginPreviewTheme.value) ?? staticBrand()
    }
    return brandFromTheme(activeTheme.value) ?? brandFromTheme(primaryTheme.value) ?? staticBrand()
  })

  watch(
    resolvedBrand,
    (brand) => {
      applyDocumentTitle(brand.fullName)
    },
    { immediate: true },
  )

  watch(
    () => user.value?.id ?? null,
    (userId) => {
      setActiveStorageUserId(userId)
    },
    { immediate: true },
  )

  async function loadPrimaryTheme() {
    try {
      const brand = await fetchPrimaryThemePublic()
      primaryTheme.value = {
        ...brand,
        default_permission_mode: 'open',
        is_primary: true,
      }
    } catch {
      primaryTheme.value = null
    }
  }

  async function loadPublicThemes() {
    try {
      const list = await fetchThemesPublic()
      publicThemes.value = Array.isArray(list) ? list : []
      if (!loginPreviewSlug.value && publicThemes.value.length === 1) {
        const only = publicThemes.value[0]?.slug
        if (only) setLoginPreviewSlug(only)
      }
    } catch {
      publicThemes.value = []
    }
  }

  function readStoredLoginThemeSlug(): string | null {
    if (typeof window === 'undefined') return null
    try {
      const raw = window.sessionStorage.getItem(LOGIN_THEME_SLUG_KEY)
      return raw && raw.trim() ? raw.trim() : null
    } catch {
      return null
    }
  }

  function setLoginPreviewSlug(slug: string | null) {
    const next = slug?.trim() || null
    loginPreviewSlug.value = next
    if (typeof window === 'undefined') return
    try {
      if (next) window.sessionStorage.setItem(LOGIN_THEME_SLUG_KEY, next)
      else window.sessionStorage.removeItem(LOGIN_THEME_SLUG_KEY)
    } catch {
      /* private mode */
    }
  }

  function initLoginPreviewSlug(routeSlug?: string | null) {
    const fromRoute = routeSlug?.trim() || null
    const fromStorage = readStoredLoginThemeSlug()
    const primary = publicThemes.value.find((t) => t.slug === primaryTheme.value?.slug)
    const fallback =
      primary?.slug ?? publicThemes.value[0]?.slug ?? primaryTheme.value?.slug ?? null
    if (publicThemes.value.length === 0) {
      setLoginPreviewSlug(fallback)
      return
    }
    const candidate = fromRoute ?? fromStorage ?? fallback
    if (!candidate) return
    if (!publicThemes.value.some((t) => t.slug === candidate)) {
      setLoginPreviewSlug(fallback)
      return
    }
    setLoginPreviewSlug(candidate)
  }

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
      void loadPrimaryTheme()
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
    const prevId = user.value?.id ?? null
    try {
      await logoutRequest()
    } finally {
      user.value = null
      clearBackendWriteApiKey()
      clearUserLocalState(prevId)
      setActiveStorageUserId(null)
    }
  }

  function clearSession() {
    const prevId = user.value?.id ?? null
    user.value = null
    clearBackendWriteApiKey()
    clearUserLocalState(prevId)
    setActiveStorageUserId(null)
  }

  async function loadUsers() {
    usersLoading.value = true
    try {
      users.value = await listUsers()
    } finally {
      usersLoading.value = false
    }
  }

  async function loadThemes() {
    themesLoading.value = true
    try {
      const data = await listThemes()
      themes.value = Array.isArray(data) ? data : []
    } catch (err) {
      themes.value = []
      throw err
    } finally {
      themesLoading.value = false
    }
  }

  async function addUser(
    username: string,
    password: string,
    role: UserRole,
    themeId?: number | null,
  ) {
    const created = await createUser({
      username,
      password,
      role,
      theme_id: themeId ?? undefined,
    })
    users.value = [...users.value, created]
    return created
  }

  async function patchUser(
    userId: number,
    patch: {
      password?: string
      role?: UserRole
      enabled?: boolean
      theme_id?: number | null
    },
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
    primaryTheme,
    publicThemes,
    loginPreviewSlug,
    loginPreviewTheme,
    themes,
    themesLoading,
    activeTheme,
    resolvedBrand,
    isAuthenticated,
    isAdmin,
    isDemo,
    canWrite,
    canRunWorkflow,
    authRequired,
    bootstrap,
    retryBootstrap,
    login,
    logout,
    clearSession,
    loadUsers,
    loadThemes,
    loadPrimaryTheme,
    loadPublicThemes,
    initLoginPreviewSlug,
    setLoginPreviewSlug,
    addUser,
    patchUser,
    removeUser,
  }
})
