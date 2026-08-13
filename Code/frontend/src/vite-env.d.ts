/// <reference types="vite/client" />

import type { useThemeStore } from './stores/theme'

declare global {
  interface Window {
    /** Dev-only theme store handle for console debugging. */
    __themeStore?: ReturnType<typeof useThemeStore>
  }
}

export {}
