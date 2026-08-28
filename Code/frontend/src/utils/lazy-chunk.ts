/**
 * Vite 动态 chunk 加载失败恢复。
 *
 * Gateway 重建后旧 hashed 文件消失时，浏览器若仍持有旧入口 JS，
 * `import()` 会报 Failed to fetch dynamically imported module。
 * 对这类错误做一次硬刷新（sessionStorage 防循环）。
 */

const CHUNK_RELOAD_KEY = 'cgda:chunk-reload'

const CHUNK_LOAD_ERROR_RE =
  /Failed to fetch dynamically imported module|Loading chunk [\w.-]+ failed|Importing a module script failed|error loading dynamically imported module/i

export function isChunkLoadError(err: unknown): boolean {
  if (err == null) return false
  const msg =
    err instanceof Error
      ? `${err.name} ${err.message}`
      : typeof err === 'string'
        ? err
        : String(err)
  return CHUNK_LOAD_ERROR_RE.test(msg)
}

/** 应用成功启动后清除一次刷新标记，避免下次真失败无法恢复。 */
export function clearChunkReloadFlag(): void {
  try {
    sessionStorage.removeItem(CHUNK_RELOAD_KEY)
  } catch {
    /* private mode / SSR */
  }
}

/**
 * 包装动态 import：chunk 失效时最多自动 reload 一次。
 * reload 触发后返回永不 resolve 的 Promise，避免 Vue 再渲染错误态。
 */
export async function importLazyChunk<T>(loader: () => Promise<T>): Promise<T> {
  try {
    const mod = await loader()
    clearChunkReloadFlag()
    return mod
  } catch (err) {
    if (isChunkLoadError(err) && typeof window !== 'undefined') {
      let alreadyReloaded: boolean
      try {
        alreadyReloaded = sessionStorage.getItem(CHUNK_RELOAD_KEY) === '1'
      } catch {
        alreadyReloaded = false
      }
      if (!alreadyReloaded) {
        try {
          sessionStorage.setItem(CHUNK_RELOAD_KEY, '1')
        } catch {
          /* ignore */
        }
        window.location.reload()
        return new Promise<T>(() => {
          /* pending until unload */
        })
      }
      clearChunkReloadFlag()
    }
    throw err
  }
}
