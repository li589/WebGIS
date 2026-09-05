import { defineStore } from 'pinia'
import { ref, watch, onScopeDispose, type Ref } from 'vue'

export type ThemeMode = 'dark' | 'light'
export type ThemePreference = ThemeMode | 'system'

const STORAGE_KEY = 'cgda-theme'

function readInitialPreference(): ThemePreference {
  if (typeof window === 'undefined') return 'dark'
  const stored = window.localStorage.getItem(STORAGE_KEY)
  if (stored === 'light' || stored === 'dark' || stored === 'system') return stored
  // 默认跟随系统偏好
  return 'system'
}

function resolveSystemTheme(): ThemeMode {
  if (typeof window === 'undefined') return 'dark'
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

function resolveEffectiveTheme(pref: ThemePreference): ThemeMode {
  return pref === 'system' ? resolveSystemTheme() : pref
}

export interface ThemeStore {
  mode: Ref<ThemeMode>
  preference: Ref<ThemePreference>
  toggle: () => void
  setTheme: (next: ThemePreference) => void
}

export const useThemeStore = defineStore('theme', (): ThemeStore => {
  const preference = ref<ThemePreference>(readInitialPreference())
  const mode = ref<ThemeMode>(resolveEffectiveTheme(preference.value))

  function applyTheme(next: ThemeMode) {
    if (typeof document === 'undefined') return
    document.documentElement.setAttribute('data-theme', next)
  }

  // 初始化立即应用
  applyTheme(mode.value)

  // 监听偏好变化：解析实际模式 → 写 DOM + 持久化
  watch(preference, (next) => {
    const resolved = resolveEffectiveTheme(next)
    mode.value = resolved
    applyTheme(resolved)
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(STORAGE_KEY, next)
    }
  })

  // 监听系统主题变化（仅 preference='system' 时生效）
  let mediaQuery: MediaQueryList | null = null
  let mediaHandler: ((e: MediaQueryListEvent) => void) | null = null

  function setupSystemListener() {
    if (typeof window === 'undefined' || !window.matchMedia) return
    mediaQuery = window.matchMedia('(prefers-color-scheme: light)')
    mediaHandler = (e: MediaQueryListEvent) => {
      if (preference.value !== 'system') return
      const resolved: ThemeMode = e.matches ? 'light' : 'dark'
      mode.value = resolved
      applyTheme(resolved)
    }
    mediaQuery.addEventListener('change', mediaHandler)
  }

  setupSystemListener()

  // 在组件作用域销毁时清理监听器（主要用于测试和 HMR）
  onScopeDispose(() => {
    if (mediaQuery && mediaHandler) {
      mediaQuery.removeEventListener('change', mediaHandler)
    }
  })

  function toggle() {
    // toggle 在 dark/light 间切换，不经过 system
    preference.value = mode.value === 'dark' ? 'light' : 'dark'
  }

  function setTheme(next: ThemePreference) {
    preference.value = next
  }

  return { mode, preference, toggle, setTheme }
})
