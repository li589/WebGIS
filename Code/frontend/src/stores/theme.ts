import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export type ThemeMode = 'dark' | 'light'

const STORAGE_KEY = 'cgda-theme'

function readInitialTheme(): ThemeMode {
  if (typeof window === 'undefined') return 'dark'
  const stored = window.localStorage.getItem(STORAGE_KEY)
  if (stored === 'light' || stored === 'dark') return stored
  // 默认跟随系统偏好（偏好亮色时用 light，否则 dark）
  if (window.matchMedia?.('(prefers-color-scheme: light)').matches) return 'light'
  return 'dark'
}

export const useThemeStore = defineStore('theme', () => {
  const mode = ref<ThemeMode>(readInitialTheme())

  function applyTheme(next: ThemeMode) {
    if (typeof document === 'undefined') return
    document.documentElement.setAttribute('data-theme', next)
  }

  // 初始化立即应用
  applyTheme(mode.value)

  // 监听变化：写 DOM + 持久化
  watch(mode, (next) => {
    applyTheme(next)
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(STORAGE_KEY, next)
    }
  })

  function toggle() {
    mode.value = mode.value === 'dark' ? 'light' : 'dark'
  }

  function setTheme(next: ThemeMode) {
    mode.value = next
  }

  return { mode, toggle, setTheme }
})
