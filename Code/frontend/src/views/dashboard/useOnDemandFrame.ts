/**
 * useOnDemandFrame — 「用户自己拖时间轴」才去 NAS 取那一天的单日帧。
 *
 * 分工（谁触发什么，别混）
 * ────────────────────────────────────────────────────────────────────────────
 * | 触发来源                                             | 取数？ |
 * |------------------------------------------------------|--------|
 * | 打开网页 / 恢复快照 / 切图层 / 勾选图层 / 添加图层     |  不取  |
 * | 用户拖时间轴、点日期格、点日历、点上/下一天            |  取    |
 * | 播放中（自动走时）                                    |  不取  |
 *
 * 「取哪几个图层」：点选了某个补帧层 ⇒ 只取它；**没点选图层**（时间轴顶部写
 * 「未选择图层」，2026-10-27 用户实测报障的状态）⇒ 取地图上当前可见的全部补帧层。
 * 用户勾了几个层再改日期，本来就期望这几层都跟着变，不该要求他先点一下图层名。
 *
 * 最后一条是有意的：播放每秒挪一次时间，取一次数要 4~5 秒，跟着取会把 NAS
 * 打满、界面也一直卡在"上一帧"。要按天连播，先暂停再一天天拖。
 *
 * 防抖 400ms：拖动过程中日期会连续变，只取最后停住的那一天（从 12-03 一路
 * 拖到 12-20 只发 1 次请求）。
 *
 * 失败分两种，处理完全不同：
 *   · 404 = 这天 NAS 上真没有 → 清掉覆盖（回到原来的长序列）+ 明确提示；
 *   · 其它（隧道断了/超时）→ 保留当前显示的帧 + 提示"可重试"，下次拖动再来。
 */
import { onBeforeUnmount } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import { ensureNasLayerFrame } from '../../services/nas-ondemand'
import { useTimelineActionBannerStore } from '../../stores/timeline-action-banner'
import { toCompactDate, useOnDemandFrameStore } from '../../stores/layers/ondemand-frame'

/** 拖动停手多久后才真的去取（毫秒） */
const DEBOUNCE_MS = 400
/** 请求超过这么久还没回来，才提示"正在取…"（本地命中时不给用户添噪音） */
const SLOW_NOTICE_MS = 700

/** `20251217` → `2025-12-17` */
function formatTag(tag: string): string {
  const t = String(tag || '')
  if (t.length !== 8) return t
  return `${t.slice(0, 4)}-${t.slice(4, 6)}-${t.slice(6, 8)}`
}

export function useOnDemandFrame(deps: {
  selectedCatalogId: ComputedRef<string | null>
  /** 地图上当前可见的补帧层 catalogId（未点选图层时的取数对象） */
  visibleOnDemandIds: ComputedRef<string[]>
  currentDate: Ref<Date>
  isPlaying: Ref<boolean>
  /** 单日帧就绪/失效后，重算各层生效时刻（会把地图切到那一天） */
  onFrameReady: () => void
  logOperation: (tag: string, message: string) => void
}) {
  const store = useOnDemandFrameStore()
  const banner = useTimelineActionBannerStore()

  // 只读拉一次「哪些图层支持补帧」，失败就静默关掉这个能力（不影响原有行为）
  void store.ensureLoaded()

  let debounceTimer: ReturnType<typeof setTimeout> | null = null
  let noticeTimer: ReturnType<typeof setTimeout> | null = null
  let busy = false
  /** 登记表读不到时只提示一次，别每次拖日期都弹 */
  let permissionNotified = false
  /** 已经为哪些图层「强制重拉过登记表」：每层只试一次，别每次拖都打接口 */
  const reloadTried = new Set<string>()
  /** 本次页面生命周期是否已刷新过登记表（首次拖动刷一次，防页面开在后端重启之前） */
  let registryRefreshed = false
  /** 已经提示过「该图层没接入按天取数」的图层：每层只提示一次 */
  const unsupportedNotified = new Set<string>()
  /** 待取的帧（同一图层只保留最后一次落点，避免拖动时堆积） */
  const queue: Array<{ layerId: string; tag: string }> = []

  function clearTimers() {
    if (debounceTimer) {
      clearTimeout(debounceTimer)
      debounceTimer = null
    }
    if (noticeTimer) {
      clearTimeout(noticeTimer)
      noticeTimer = null
    }
  }

  function coverageText(): string {
    const cov = store.coverage
    if (!cov?.start || !cov?.end) return ''
    return `（可用的只有 ${formatTag(cov.start)} ~ ${formatTag(cov.end)}）`
  }

  /** 同一图层只保留最后一次落点；不同图层各自排队（串行执行，不并发打 NAS） */
  function enqueue(layerId: string, tag: string) {
    const i = queue.findIndex((j) => j.layerId === layerId)
    if (i >= 0) queue.splice(i, 1)
    queue.push({ layerId, tag })
  }

  async function drain() {
    if (busy) return
    busy = true
    try {
      while (queue.length > 0) {
        const job = queue.shift() as { layerId: string; tag: string }
        await request(job.layerId, job.tag)
      }
    } finally {
      busy = false
    }
  }

  async function request(layerId: string, tag: string) {
    // 标记「这一天正在取」：让上一天那张继续留在屏幕上，别在 4 秒里闪回整月合成
    store.setPendingTag(layerId, tag)
    let noticeShown = false
    noticeTimer = setTimeout(() => {
      noticeTimer = null
      noticeShown = true
      banner.showNotice({
        message: `正在从 NAS 取 ${formatTag(tag)} 的单日图…`,
        catalogId: layerId,
        tone: 'info',
      })
    }, SLOW_NOTICE_MS)

    try {
      const result = await ensureNasLayerFrame({ layerId, date: tag })
      if (noticeTimer) {
        clearTimeout(noticeTimer)
        noticeTimer = null
      }
      if (noticeShown) banner.dismissNotice()
      const applied = String(result?.time_key || tag)
      store.setDayTag(layerId, applied)
      deps.onFrameReady()
      deps.logOperation(
        'ondemand-frame',
        `时间轴取单日 ${formatTag(applied)} · ${
          result?.cached ? '本地已有' : 'NAS 取数'
        } · ${result?.elapsed_ms ?? '?'}ms`,
      )
      /**
       * 成功也要给反馈。
       *
       * 原来只有「超过 700ms 才提示正在取」，而本地命中的帧是毫秒级返回——
       * 慢提示根本来不及出现，成功后又被立刻关掉，用户看到的就是「拖完什么都没发生」。
       * 这里补一条短提示：既确认切到了哪一天，也顺带说明是本地还是 NAS 取的。
       */
      banner.showNotice({
        message: `已切到 ${formatTag(applied)} 的单日图${
          result?.cached ? '（本地已有）' : '（刚从 NAS 取回）'
        }`,
        catalogId: layerId,
        tone: 'info',
      })
    } catch (err) {
      if (noticeTimer) {
        clearTimeout(noticeTimer)
        noticeTimer = null
      }
      const status = (err as { status?: number } | null)?.status
      const raw = err instanceof Error ? err.message : String(err)
      if (status === 404) {
        // 「这天没有数据」是正常业务状态：退回原来的长序列，图层绝不能因此被冻掉
        store.clearDayTag(layerId)
        deps.onFrameReady()
        banner.showNotice({
          message: `${formatTag(tag)} 这天没有数据${coverageText()}，已退回原来的时间序列`,
          catalogId: layerId,
          tone: 'error',
        })
        deps.logOperation('ondemand-frame', `时间轴取单日 ${formatTag(tag)} · 无此日数据`)
      } else {
        banner.showNotice({
          message: `取 ${formatTag(tag)} 的单日图失败：${raw}。当前显示的图保持不变，可再拖一次重试`,
          catalogId: layerId,
          tone: 'error',
        })
        deps.logOperation(
          'ondemand-frame',
          `时间轴取单日 ${formatTag(tag)} 失败 · ${status ?? 'network'}`,
        )
      }
    } finally {
      store.clearPendingTag(layerId)
    }
  }

  /** 这次改日期该动哪几个层（点选了补帧层 ⇒ 只动它；没点选 ⇒ 动可见的补帧层） */
  function targetsForDateChange(): string[] {
    const selected = deps.selectedCatalogId.value
    if (selected) {
      // 点选了具体图层就以它为准。它不是补帧层 ⇒ 本次一个都不动，
      // 否则用户在别的图层上拖日期会莫名其妙触发 NAS 取数。
      return store.isOnDemandLayer(selected) ? [selected] : []
    }
    return deps.visibleOnDemandIds.value.filter((id) => store.isOnDemandLayer(id))
  }

  /**
   * 选中了「没登记按天取数」的图层时，把沉默换成一句人话。
   *
   * 之前这里直接 `return`，界面上既不取数也没有任何提示，用户只会觉得"拖了没反应"。
   * 现在明确说清「这个层没接」+ 哪些接了，并写进操作日志便于回溯。
   */
  function explainUnsupported(layerId: string) {
    if (unsupportedNotified.has(layerId)) return
    unsupportedNotified.add(layerId)
    banner.showNotice({
      message:
        '当前选中的图层没有接入按天取数，拖日期它不会变。' +
        '已接入的是「风云 / SMAP」平均散射约束的 土壤水分 SM 与 植被光学厚度 VOD；' +
        '等效散射 ω 的 NAS 源是年内日序气候态，尚未接入。',
      tone: 'info',
    })
    deps.logOperation(
      'ondemand-frame',
      `图层 ${layerId} 未登记为按需补帧目标，已跳过（不取数、不改图层）`,
    )
  }

  /**
   * 用户手动改了日期（唯一入口：`useTimelineControls.handleTimelineDateChange`）。
   * 程序自己挪时间轴（snap / 记忆恢复 / 快照还原）**不会**走到这里。
   */
  function notifyUserDateChange(date: Date) {
    // 播放中不取数（见文件头说明）
    if (deps.isPlaying.value) return
    if (!store.loaded) {
      // 登记表还没拉到（多半是页面刚开、登录态尚未就绪）：拉到之后再处理这次日期
      void store.ensureLoaded().then(() => {
        if (store.loaded) {
          notifyUserDateChange(date)
          return
        }
        /**
         * 拉不到就说出来，别再静默 —— 2026-10-27 的真实翻车：
         * 网关没转发 `/nas-ondemand`（返回 HTML）＋接口权限卡了 demo（403），
         * 前端两次都吞掉异常，用户只看到"怎么拖都没反应"。
         */
        if (!permissionNotified) {
          permissionNotified = true
          banner.showNotice({
            message:
              '按需取数没启用：读不到图层登记表 —— ' +
              (store.lastError || '原因未知') +
              '。截图给管理员即可定位。',
            tone: 'error',
          })
          deps.logOperation(
            'ondemand-frame',
            `图层登记表读取失败，按需取数已关闭：${store.lastError || '原因未知'}`,
          )
        }
      })
      return
    }
    const selected = deps.selectedCatalogId.value
    /**
     * 首次拖动先把登记表刷一遍（每页面一次）。
     *
     * 页面若是在「后端加完登记层、重启完成」**之前**打开的，浏览器内存里的清单就
     * 永远是旧的（只有风云两层），于是勾选 SMAP 拖日期时连"选中层不支持"这条分支
     * 都不会走到 —— 直接静默无反应。刷一次只要几百字节，比让用户靠猜划算得多。
     */
    if (!registryRefreshed) {
      registryRefreshed = true
      void store.reload().then(() => notifyUserDateChange(date))
      return
    }

    if (selected && !store.isOnDemandLayer(selected)) {
      /**
       * 选中的图层不在登记表里。两种可能，必须分开处理：
       *  1. 登记表是**旧的**（后端刚加登记、页面没重开）⇒ 强制重拉一次就能救回来；
       *  2. 真的没接入（如等效散射 ω 的 doy 气候态源）⇒ 明确告诉用户，别再静默。
       * 每层只重拉一次、只提示一次，避免每次拖动都打接口或反复弹条。
       */
      if (!reloadTried.has(selected)) {
        reloadTried.add(selected)
        void store.reload().then(() => {
          if (store.isOnDemandLayer(selected)) {
            notifyUserDateChange(date)
            return
          }
          // 重拉本身失败（登录过期 / 网关 / 网络）：说清是"读不到清单"，不是"没接入"
          if (!store.loaded) {
            banner.showNotice({
              message:
                '按需取数没启用：读不到图层登记表 —— ' +
                (store.lastError || '原因未知') +
                '。截图给管理员即可定位。',
              tone: 'error',
            })
            return
          }
          explainUnsupported(selected)
        })
        return
      }
      explainUnsupported(selected)
      return
    }

    const targets = targetsForDateChange()
    if (targets.length === 0) return

    if (!store.coversDate(date)) {
      // 明显超出成果范围：不发请求，直接说清楚，并退回长序列
      clearTimers()
      const pinned = targets.filter((id) => store.dayTagFor(id))
      if (pinned.length > 0) {
        for (const id of pinned) store.clearDayTag(id)
        deps.onFrameReady()
      }
      banner.showNotice({
        message: `这些图层没有 ${formatTag(toCompactDate(date))} 的数据${coverageText()}，已退回原来的时间序列`,
        catalogId: targets[0],
        tone: 'error',
      })
      return
    }

    const tag = toCompactDate(date)
    // 已经都是这一天的单日帧了（拖回原地/来回小幅拖），不用再取
    const todo = targets.filter((id) => store.dayTagFor(id) !== tag)
    if (todo.length === 0) return

    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => {
      debounceTimer = null
      for (const id of todo) enqueue(id, tag)
      void drain()
    }, DEBOUNCE_MS)
  }

  onBeforeUnmount(() => {
    clearTimers()
  })

  return { notifyUserDateChange }
}
