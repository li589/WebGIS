import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

/**
 * 「时刻钉子」（stores/ui.ts TimelinePin）。
 *
 * 2026-11-07 组合指令实测：切到 SMAP 动态、日期设 12-16、再统计 —— 图层和数值都对，
 * 页面却停在 7 月 31 日（该层 meta.default_time = 20250701_20250731）。原因是新加图层的
 * timeList 晚到时，「新加图层 → 跳最新帧」把刚设好的日期顶掉了。
 * 钉子就是这个保护窗：显式指定过的时刻，在窗内优先于图层记忆与自动落点。
 */

const LAYER_TIME_KEY = 'cgda.timeline.layer-memory'
const UNIFIED_FLAG_KEY = 'cgda.timeline.unified'
/** 与 stores/ui.ts 的 TIMELINE_PIN_TTL_MS 对齐 */
const PIN_TTL_MS = 20_000

function setupStorage(initial: Record<string, string> = {}) {
  const store = new Map<string, string>(Object.entries(initial))
  vi.stubGlobal('window', {
    localStorage: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
      clear: () => store.clear(),
    },
  })
  return store
}

async function makeUiStore() {
  const { useUiStore } = await import('@/stores/ui')
  return useUiStore()
}

function day(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y!, m! - 1, d!, 12, 0, 0, 0)
}

function keyOf(date: Date): string {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

describe('ui store 时刻钉子', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.resetModules()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('钉子优先于图层记忆：显式设过的那天不会被旧记忆顶回去', async () => {
    setupStorage({
      [UNIFIED_FLAG_KEY]: '0',
      // 用户以前手动拖到过 7 月 31 日，被记进了图层记忆
      [LAYER_TIME_KEY]: JSON.stringify({
        'method-smap-omega-doy-dynamic': { dateKey: '2025-07-31', hour: 0 },
      }),
    })
    const ui = await makeUiStore()
    ui.pinTimelineAt('method-smap-omega-doy-dynamic', day('2025-12-16'), 0)
    expect(ui.restoreLayerTime('method-smap-omega-doy-dynamic')).toBe(true)
    expect(keyOf(ui.currentDate)).toBe('2025-12-16')
  })

  it('没有钉子时照旧走图层记忆（保护窗不改变原行为）', async () => {
    setupStorage({
      [UNIFIED_FLAG_KEY]: '0',
      [LAYER_TIME_KEY]: JSON.stringify({
        'method-smap-omega-doy-dynamic': { dateKey: '2025-07-31', hour: 0 },
      }),
    })
    const ui = await makeUiStore()
    expect(ui.isTimelinePinned('method-smap-omega-doy-dynamic')).toBe(false)
    expect(ui.restoreLayerTime('method-smap-omega-doy-dynamic')).toBe(true)
    expect(keyOf(ui.currentDate)).toBe('2025-07-31')
  })

  it('钉子只对同一层生效：切到别的层时仍按那层自己的记忆落点', async () => {
    setupStorage({
      [UNIFIED_FLAG_KEY]: '0',
      [LAYER_TIME_KEY]: JSON.stringify({
        'method-fy-omega-doy-avg': { dateKey: '2025-12-15', hour: 0 },
      }),
    })
    const ui = await makeUiStore()
    ui.pinTimelineAt('method-smap-omega-doy-dynamic', day('2025-12-16'), 0)
    expect(ui.isTimelinePinned('method-fy-omega-doy-avg')).toBe(false)
    expect(ui.restoreLayerTime('method-fy-omega-doy-avg')).toBe(true)
    expect(keyOf(ui.currentDate)).toBe('2025-12-15')
  })

  it('超过保护窗自动失效：用户随后切层恢复正常落点', async () => {
    setupStorage({
      [UNIFIED_FLAG_KEY]: '0',
      [LAYER_TIME_KEY]: JSON.stringify({
        'method-smap-omega-doy-dynamic': { dateKey: '2025-07-31', hour: 0 },
      }),
    })
    const ui = await makeUiStore()
    ui.pinTimelineAt('method-smap-omega-doy-dynamic', day('2025-12-16'), 0)
    expect(ui.isTimelinePinned('method-smap-omega-doy-dynamic')).toBe(true)
    vi.advanceTimersByTime(PIN_TTL_MS + 1_000)
    expect(ui.isTimelinePinned('method-smap-omega-doy-dynamic')).toBe(false)
    expect(ui.restoreLayerTime('method-smap-omega-doy-dynamic')).toBe(true)
    expect(keyOf(ui.currentDate)).toBe('2025-07-31')
  })

  it('钉子不落 localStorage：只保护这一次操作，刷新后不该继续生效', async () => {
    const storage = setupStorage({ [UNIFIED_FLAG_KEY]: '0' })
    const ui = await makeUiStore()
    ui.pinTimelineAt('method-smap-omega-doy-dynamic', day('2025-12-16'), 0)
    for (const [k, v] of storage.entries()) {
      expect(v.includes('2025-12-16')).toBe(false)
      expect(k).not.toContain('pin')
    }
  })

  it('catalogId 或日期非法时不落钉子（不制造假保护）', async () => {
    setupStorage({ [UNIFIED_FLAG_KEY]: '0' })
    const ui = await makeUiStore()
    ui.pinTimelineAt('', day('2025-12-16'), 0)
    expect(ui.isTimelinePinned()).toBe(false)
    ui.pinTimelineAt('method-smap-omega-doy-dynamic', new Date('不是日期'), 0)
    expect(ui.isTimelinePinned()).toBe(false)
  })
})
