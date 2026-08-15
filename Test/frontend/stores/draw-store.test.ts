/**
 * W3.4e：draw store 测试（node 环境 + stub localStorage/window）。
 *
 * 覆盖绘制模式/顶点管理、撤销栈（含 50 上限）、要素增删改、选中态、
 * 绘制会话与图层编辑会话、草稿 build/persist/restore/clear、
 * 防抖持久化与 beforeunload 拦截。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useDrawStore, type DrawFeature } from '@/stores/draw-store'

function feature(name: string, lng = 100, lat = 30): DrawFeature {
  return {
    geometry: { type: 'Polygon', coordinates: [[[lng, lat], [lng + 1, lat], [lng + 1, lat + 1], [lng, lat]]] },
    properties: { name },
  } as DrawFeature
}

function stubStorage() {
  const storage = new Map<string, string>()
  const listeners: Record<string, Array<(e?: { preventDefault(): void; returnValue?: string }) => void>> = {}
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => storage.get(k) ?? null,
    setItem: (k: string, v: string) => storage.set(k, v),
    removeItem: (k: string) => storage.delete(k),
  })
  vi.stubGlobal('window', {
    addEventListener: (name: string, fn: never) => (listeners[name] ??= []).push(fn),
    removeEventListener: () => undefined,
  })
  return { storage, listeners }
}

beforeEach(() => {
  vi.clearAllMocks()
  setActivePinia(createPinia())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('顶点与绘制模式', () => {
  it('addVertex 累积并置 isDrawing；undoLastVertex 清空后复位', () => {
    const store = useDrawStore()
    store.setDrawMode('rectangle')
    expect(store.drawMode).toBe('rectangle')
    expect(store.isDrawing).toBe(false)

    store.addVertex({ lng: 1, lat: 2 })
    store.addVertex({ lng: 3, lat: 4 })
    expect(store.activeVertices).toHaveLength(2)
    expect(store.isDrawing).toBe(true)

    store.undoLastVertex()
    store.undoLastVertex()
    expect(store.activeVertices).toHaveLength(0)
    expect(store.isDrawing).toBe(false)
  })

  it('setHoverPoint / clearActiveVertices 复位悬停与绘制态', () => {
    const store = useDrawStore()
    store.setHoverPoint({ lng: 5, lat: 6 })
    expect(store.hoverPoint).toEqual({ lng: 5, lat: 6 })
    store.addVertex({ lng: 1, lat: 2 })
    store.clearActiveVertices()
    expect(store.hoverPoint).toBeNull()
    expect(store.isDrawing).toBe(false)
  })
})

describe('要素与撤销栈', () => {
  it('addFeature 入栈撤销快照；undo 回退；栈空时 undo 无操作', () => {
    const store = useDrawStore()
    store.addFeature(feature('a'))
    store.addFeature(feature('b'))
    expect(store.features).toHaveLength(2)

    store.undo()
    expect(store.features.map((f) => f.properties.name)).toEqual(['a'])

    store.undo()
    expect(store.features).toHaveLength(0)

    store.undo()
    expect(store.features).toHaveLength(0)
  })

  it('撤销栈超过 50 层丢弃最旧快照', () => {
    const store = useDrawStore()
    for (let i = 0; i < 52; i++) store.addFeature(feature(`f${i}`))
    expect(store.undoStack).toHaveLength(50)
    store.undo()
    // 栈顶快照是加入 f51 前的状态（f0..f50），最旧的 snap0/snap1 已被丢弃
    expect(store.features.map((f) => f.properties.name)).toEqual(
      Array.from({ length: 51 }, (_, i) => `f${i}`),
    )
  })

  it('removeFeature 移除并清选中态；updateFeatureProperties 合并属性', () => {
    const store = useDrawStore()
    store.addFeature(feature('a'))
    store.addFeature(feature('b'))
    store.setSelectedFeature(0)
    expect(store.selectedFeatureIndex).toBe(0)

    store.removeFeature(0)
    expect(store.features).toHaveLength(1)
    expect(store.selectedFeatureIndex).toBeNull()

    store.updateFeatureProperties(0, { color: 'red' })
    expect(store.features[0].properties).toMatchObject({ name: 'b', color: 'red' })

    store.updateFeatureProperties(9, { x: 1 })
    expect(store.features[0].properties.x).toBeUndefined()
  })

  it('clearAll 归位全部状态且撤销栈清空', () => {
    const store = useDrawStore()
    store.addFeature(feature('a'))
    store.setSelectedFeature(0)
    store.clearAll()
    expect(store.features).toHaveLength(0)
    expect(store.undoStack).toHaveLength(0)
    expect(store.selectedFeatureIndex).toBeNull()
  })
})

describe('绘制会话与图层编辑', () => {
  it('beginDrawSession 使用给定名称并清空历史；空名称生成默认名', () => {
    const store = useDrawStore()
    store.addFeature(feature('old'))
    store.beginDrawSession('分析区域')
    expect(store.draftLayerName).toBe('分析区域')
    expect(store.features).toHaveLength(0)
    expect(store.editingLayerId).toBeNull()

    store.beginDrawSession('')
    expect(store.draftLayerName).toContain('绘制图层')
  })

  it('beginEditLayer 载入既有要素并标记 editingLayerId', () => {
    const store = useDrawStore()
    const existing = [feature('e1'), feature('e2')]
    store.beginEditLayer('layer-7', existing)
    expect(store.editingLayerId).toBe('layer-7')
    expect(store.features).toHaveLength(2)
    store.addFeature(feature('e3'))
    expect(existing).toHaveLength(2)
  })

  it('setDraftLayerId 记录草稿图层 id', () => {
    const store = useDrawStore()
    store.setDraftLayerId('draft-1')
    expect(store.draftLayerId).toBe('draft-1')
  })
})

describe('草稿持久化', () => {
  it('persistDraft：空要素且非编辑态时清除存储；否则写入草稿', () => {
    const { storage } = stubStorage()
    const store = useDrawStore()
    store.beginDrawSession('草稿A')
    store.addFeature(feature('a'))
    store.persistDraft()

    const raw = storage.get('geo:draw-draft:v1')
    expect(raw).toBeTruthy()
    const draft = JSON.parse(raw!) as { version: number; draftLayerName: string }
    expect(draft.version).toBe(1)
    expect(draft.draftLayerName).toBe('草稿A')

    store.clearAll()
    store.persistDraft()
    expect(storage.has('geo:draw-draft:v1')).toBe(false)
  })

  it('编辑图层会话即使无要素也持久化（保留 editingLayerId）', () => {
    const { storage } = stubStorage()
    const store = useDrawStore()
    store.beginEditLayer('layer-9', [])
    store.persistDraft()
    const draft = JSON.parse(storage.get('geo:draw-draft:v1')!) as { editingLayerId: string | null }
    expect(draft.editingLayerId).toBe('layer-9')
  })

  it('scheduleDraftPersist 防抖 400ms 后落盘', () => {
    vi.useFakeTimers()
    const { storage } = stubStorage()
    const store = useDrawStore()
    store.beginDrawSession('防抖')
    store.addFeature(feature('a'))
    store.scheduleDraftPersist()
    expect(storage.has('geo:draw-draft:v1')).toBe(false)
    vi.advanceTimersByTime(400)
    expect(storage.has('geo:draw-draft:v1')).toBe(true)
    vi.useRealTimers()
  })

  it('要素内容变化触发 watch 防抖持久化', async () => {
    vi.useFakeTimers()
    const { storage } = stubStorage()
    const store = useDrawStore()
    store.beginDrawSession('监听')
    store.addFeature(feature('a'))
    await vi.advanceTimersByTimeAsync(400)
    expect(storage.has('geo:draw-draft:v1')).toBe(true)
    vi.useRealTimers()
  })

  it('restoreDraft：首次恢复成功，二次调用返回 false；坏版本返回 False 路径', () => {
    const { storage } = stubStorage()
    const store = useDrawStore()
    store.beginDrawSession('恢复')
    store.setDrawMode('line')
    store.addFeature(feature('r1'))
    store.persistDraft()

    const store2 = useDrawStore()
    expect(store2.restoreDraft()).toBe(true)
    expect(store2.features).toHaveLength(1)
    expect(store2.drawMode).toBe('line')
    expect(store2.draftLayerName).toBe('恢复')
    expect(store2.restoreDraft()).toBe(false)

    storage.set('geo:draw-draft:v1', JSON.stringify({ version: 2 }))
    setActivePinia(createPinia())
    const store3 = useDrawStore()
    expect(store3.restoreDraft()).toBe(false)
  })

  it('clearDraft 清存储与内存状态', () => {
    const { storage } = stubStorage()
    const store = useDrawStore()
    store.beginDrawSession('清理')
    store.addFeature(feature('a'))
    store.persistDraft()
    store.clearDraft()
    expect(storage.has('geo:draw-draft:v1')).toBe(false)
    expect(store.features).toHaveLength(0)
    expect(store.draftLayerName).toBe('')
  })
})

describe('页面离开钩子', () => {
  it('beforeunload 有要素时 preventDefault 并要求确认', () => {
    const { listeners } = stubStorage()
    useDrawStore()
    const handler = listeners['beforeunload']![0]
    const e = { preventDefault: vi.fn(), returnValue: '' }
    const store = useDrawStore()
    handler(e)
    expect(e.preventDefault).not.toHaveBeenCalled()

    store.addFeature(feature('a'))
    handler(e)
    expect(e.preventDefault).toHaveBeenCalled()
    expect(e.returnValue).toBe('')
  })

  it('localStorage 异常时静默不抛错', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('quota')
      },
      setItem: () => {
        throw new Error('quota')
      },
      removeItem: () => {
        throw new Error('quota')
      },
    })
    const store = useDrawStore()
    store.beginDrawSession('配额')
    store.addFeature(feature('a'))
    expect(() => store.persistDraft()).not.toThrow()
    expect(store.restoreDraft()).toBe(false)
  })
})
