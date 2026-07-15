/**
 * 共享 overlay 符号化元数据（侧栏 / 分析框 / 地图加载同源）。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import type { OverlaySymbologyMeta } from '../components/map/layer-symbology'

type CacheStatus = 'ok' | 'miss' | 'error'

interface CacheEntry {
  status: CacheStatus
  meta: OverlaySymbologyMeta
  fetchedAt: number
}

/** 404/无 overlay：稍后可重试（作业刚注册时常先 miss） */
const MISS_RETRY_MS = 45_000
/** 网络错误：短退避后重试 */
const ERROR_RETRY_MS = 15_000

export const useOverlaySymbologyStore = defineStore('overlay-symbology', () => {
  const metaByCatalogId = ref<Map<string, CacheEntry>>(new Map())
  const inflight = new Map<string, Promise<void>>()
  const revision = ref(0)

  function bump() {
    revision.value += 1
  }

  function write(catalogId: string, entry: CacheEntry) {
    metaByCatalogId.value = new Map(metaByCatalogId.value).set(catalogId, entry)
    bump()
  }

  function getMeta(catalogId: string): OverlaySymbologyMeta | null {
    return metaByCatalogId.value.get(catalogId)?.meta ?? null
  }

  function getEntry(catalogId: string): CacheEntry | null {
    return metaByCatalogId.value.get(catalogId) ?? null
  }

  /** 当前是否应跳过发起新的 ensureMeta */
  function shouldSkipFetch(catalogId: string): boolean {
    const entry = metaByCatalogId.value.get(catalogId)
    if (!entry) return false
    if (entry.status === 'ok') return true
    const age = Date.now() - entry.fetchedAt
    if (entry.status === 'miss') return age < MISS_RETRY_MS
    if (entry.status === 'error') return age < ERROR_RETRY_MS
    return false
  }

  /** @deprecated 使用 shouldSkipFetch；保留兼容旧调用 */
  function peekHasMeta(catalogId: string): boolean {
    return shouldSkipFetch(catalogId)
  }

  /** 地图 / 其它成功路径直接写入，覆盖 miss/error */
  function putMeta(catalogId: string, meta: OverlaySymbologyMeta) {
    if (!catalogId) return
    write(catalogId, {
      status: 'ok',
      meta: {
        palette: meta.palette,
        vmin: meta.vmin ?? null,
        vmax: meta.vmax ?? null,
        unit: meta.unit,
        opacity: meta.opacity,
      },
      fetchedAt: Date.now(),
    })
  }

  function invalidate(catalogId: string) {
    if (!metaByCatalogId.value.has(catalogId)) return
    const next = new Map(metaByCatalogId.value)
    next.delete(catalogId)
    metaByCatalogId.value = next
    bump()
  }

  async function ensureMeta(catalogId: string, options?: { force?: boolean }): Promise<OverlaySymbologyMeta | null> {
    if (!catalogId) return null
    if (!options?.force && shouldSkipFetch(catalogId)) {
      return getMeta(catalogId)
    }
    const existing = inflight.get(catalogId)
    if (existing) {
      await existing
      return getMeta(catalogId)
    }

    const task = (async () => {
      try {
        const resp = await fetch(`/overlay-bounds/${catalogId}`)
        if (resp.status === 404) {
          write(catalogId, { status: 'miss', meta: {}, fetchedAt: Date.now() })
          return
        }
        if (!resp.ok) {
          write(catalogId, { status: 'error', meta: {}, fetchedAt: Date.now() })
          return
        }
        const data = await resp.json()
        const meta = (data.meta ?? {}) as OverlaySymbologyMeta
        write(catalogId, {
          status: 'ok',
          meta: {
            palette: meta.palette,
            vmin: meta.vmin ?? null,
            vmax: meta.vmax ?? null,
            unit: meta.unit,
            opacity: meta.opacity,
          },
          fetchedAt: Date.now(),
        })
      } catch {
        write(catalogId, { status: 'error', meta: {}, fetchedAt: Date.now() })
      } finally {
        inflight.delete(catalogId)
      }
    })()

    inflight.set(catalogId, task)
    await task
    return getMeta(catalogId)
  }

  const version = computed(() => revision.value)

  return {
    metaByCatalogId,
    version,
    getMeta,
    getEntry,
    shouldSkipFetch,
    peekHasMeta,
    putMeta,
    invalidate,
    ensureMeta,
  }
})
