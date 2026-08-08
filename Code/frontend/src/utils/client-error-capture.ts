import type { App } from 'vue'

import { useLogStore } from '../stores/log'

export function installClientErrorCapture(app: App): void {
  app.config.errorHandler = (err, _instance, info) => {
    const msg = err instanceof Error ? err.message : String(err)
    try {
      useLogStore().logClientError('应用运行时错误', `${msg}\n${info}`)
    } catch {
      console.error(err)
    }
  }

  if (typeof window === 'undefined') return

  window.addEventListener('error', (event) => {
    try {
      useLogStore().logClientError(
        '脚本错误',
        `${event.message} @ ${event.filename}:${event.lineno}`,
      )
    } catch {
      /* ignore */
    }
  })

  window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason
    const msg = reason instanceof Error ? reason.message : String(reason)
    try {
      useLogStore().logClientError('未处理的 Promise 拒绝', msg)
    } catch {
      /* ignore */
    }
  })
}
