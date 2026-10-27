/**
 * ondemand-frame — 「哪些图层支持拖时间轴补单日帧」+「当前正显示哪一天」。
 *
 * 为什么需要这个 store
 * ────────────────────────────────────────────────────────────────────────────
 * 用户诉求（2026-10-27）：
 *   · 勾选 / 添加图层 ⇒ 保持原来的长序列（整月合成那张），**不许自动变单日**；
 *   · 只有**自己拖时间轴**才去看那一天，且要能拖回来。
 *
 * 所以「显示哪一天」不能塞进图层的 time_list（那会让默认落点变成单日帧），
 * 只能作为一层**独立的显示覆盖**放在前端：
 *
 *   dayTag[catalogId] = '20251217'
 *
 * `useTimelineSync` 计算生效时刻时优先看它，取不到才回落 time_list 的解析结果。
 * 内存态、不持久化 ⇒ 刷新页面自动回到长序列（正是要的行为）。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { fetchNasOndemandLayers, type NasOndemandLayer } from '../../services/nas-ondemand'

export type OnDemandCoverage = { start: string; end: string }

/** `Date` → `YYYYMMDD`（本地日历日，不用 toISOString 以免时区偏一天） */
export function toCompactDate(date: Date): string {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}${m}${d}`
}

export const useOnDemandFrameStore = defineStore('ondemand-frame', () => {
  /** catalogId → NAS 取数口径 */
  const specs = ref<Record<string, NasOndemandLayer>>({})
  /** NAS 成果覆盖范围（YYYYMMDD） */
  const coverage = ref<OnDemandCoverage | null>(null)
  const loaded = ref(false)
  const loadFailed = ref(false)
  /** catalogId → 当前正在显示的单日帧标签（YYYYMMDD） */
  const dayTag = ref<Record<string, string>>({})
  /** catalogId → 正在向 NAS 请求的那一天（YYYYMMDD）；只用于「别闪回整月」 */
  const pendingTag = ref<Record<string, string>>({})

  let inflight: Promise<void> | null = null
  /** 上次拉取失败的时刻（毫秒）：失败不再永久关死这个能力，过几秒允许重试 */
  let failedAt = 0
  const RETRY_AFTER_MS = 5000
  /**
   * 最近一次拉取失败的原因（如「HTTP 403：Demo account ...」/「返回的不是 JSON」）。
   *
   * 2026-10-27 教训：只写「读不到图层登记表」这种笼统文案，排查时仍然要靠猜。
   * 把真实状态码与后端原文一起摊在界面上，一眼就能分清是权限、网关还是网络。
   */
  const lastError = ref('')

  const hasAnyLayer = computed(() => Object.keys(specs.value).length > 0)

  /**
   * 把拉取失败翻译成一句能直接拿去排查的话。
   *
   * 三种最常见的真实情形（2026-10-27 全都踩过）：
   *  * `HTTP 403` ⇒ 账号角色不够（demo 读不到配置类接口）
   *  * `HTTP 401` ⇒ 登录态还没就绪 / 已过期
   *  * `Unexpected token '<'` 一类解析错误 ⇒ 网关没转发，把前端页面 HTML 当接口返回了
   */
  function describeLoadFailure(err: unknown): string {
    const rec = (err ?? {}) as { status?: unknown; message?: unknown }
    const status = typeof rec.status === 'number' ? rec.status : 0
    const msg = typeof rec.message === 'string' ? rec.message : String(err ?? '')
    if (status === 401) return 'HTTP 401 未登录或登录已过期，请重新登录后再拖一次日期'
    if (status === 403) return `HTTP 403 账号权限不足（后端原文：${msg}）`
    if (status) return `HTTP ${status}（${msg}）`
    if (/unexpected token|not valid json|json/i.test(msg)) {
      return '接口返回的不是 JSON（多半是网关没转发 /nas-ondemand，把网页 HTML 当成了接口响应）'
    }
    return msg || '未知错误'
  }

  function specFor(catalogId: string | null | undefined): NasOndemandLayer | null {
    const id = String(catalogId || '')
    if (!id) return null
    return specs.value[id] ?? null
  }

  function isOnDemandLayer(catalogId: string | null | undefined): boolean {
    return specFor(catalogId) !== null
  }

  /** 该图层当前被"钉"在哪一天（没有则 null ⇒ 走 time_list 的正常解析） */
  function dayTagFor(catalogId: string | null | undefined): string | null {
    const id = String(catalogId || '')
    if (!id) return null
    return dayTag.value[id] ?? null
  }

  function setDayTag(catalogId: string, tag: string) {
    if (!catalogId) return
    dayTag.value = { ...dayTag.value, [catalogId]: String(tag) }
  }

  function clearDayTag(catalogId: string) {
    if (!catalogId) return
    if (!(catalogId in dayTag.value)) return
    const next = { ...dayTag.value }
    delete next[catalogId]
    dayTag.value = next
  }

  function setPendingTag(catalogId: string, tag: string) {
    if (!catalogId) return
    pendingTag.value = { ...pendingTag.value, [catalogId]: String(tag) }
  }

  function clearPendingTag(catalogId: string) {
    if (!catalogId) return
    if (!(catalogId in pendingTag.value)) return
    const next = { ...pendingTag.value }
    delete next[catalogId]
    pendingTag.value = next
  }

  /**
   * 此刻**该显示**哪张单日帧（null ⇒ 交给 time_list 的正常解析，即长序列）。
   *
   * 规则（两条，缺一不可）：
   *  1. 钉住的标签正好等于当前日期 ⇒ 显示它；
   *  2. 当前日期正在取数 ⇒ 继续显示**上一天**那张，别在 4 秒里闪回整月合成。
   *
   * 只要用户离开这一天（切图层后拖到别处、快照还原、程序化 snap），两条都不成立
   * ⇒ 自动回落长序列，不会出现「标题写 12-25、画面还是 12-02」的错位。
   */
  function displayedDayTag(catalogId: string | null | undefined, dateTag: string): string | null {
    const id = String(catalogId || '')
    if (!id) return null
    const pin = dayTag.value[id]
    if (!pin) return null
    if (pin === dateTag) return pin
    return pendingTag.value[id] === dateTag ? pin : null
  }

  /** 该日期是否在 NAS 成果覆盖范围内（覆盖范围未知时不拦，交给后端判 404） */
  function coversDate(date: Date): boolean {
    const cov = coverage.value
    if (!cov?.start || !cov?.end) return true
    const tag = toCompactDate(date)
    return tag >= cov.start && tag <= cov.end
  }

  /** 拉一次「哪些图层支持补帧」（纯读、不连 NAS），失败允许稍后重试 */
  async function ensureLoaded(): Promise<void> {
    if (loaded.value) return
    if (inflight) return inflight
    /**
     * 页面刚打开时这一步可能早于登录态就绪（401），旧逻辑会记 loadFailed 并把
     * 「按需补帧」整个会话关死 —— 用户表现就是「拖了日期一点反应都没有」。
     * 现在改成：失败只冷却几秒，之后任何一次拖动都会重新尝试。
     */
    if (loadFailed.value && Date.now() - failedAt < RETRY_AFTER_MS) return
    inflight = (async () => {
      try {
        const data = await fetchNasOndemandLayers()
        const next: Record<string, NasOndemandLayer> = {}
        for (const item of data?.layers ?? []) {
          if (item?.layer_id) next[item.layer_id] = item
        }
        specs.value = next
        if (data?.coverage?.start && data?.coverage?.end) {
          coverage.value = { ...data.coverage }
        }
        loaded.value = true
        loadFailed.value = false
        lastError.value = ''
      } catch (err) {
        loadFailed.value = true
        failedAt = Date.now()
        lastError.value = describeLoadFailure(err)
      } finally {
        inflight = null
      }
    })()
    return inflight
  }

  /**
   * 强制重拉一次登记表（忽略 `loaded` 与失败冷却）。
   *
   * 为什么需要：`ensureLoaded` 一个页面生命周期只成功读一次。后端加了新登记层并
   * 重启之后，已经打开的页面仍然拿着旧清单 ⇒「选中新图层拖日期」会被判成"不支持"
   * 而完全静默（2026-10-27 现场：SMAP 两层已登记，浏览器里还是只有风云两层）。
   * 所以拖日期时一旦发现选中的图层不在清单里，就先强制重拉一次再下结论。
   */
  async function reload(): Promise<void> {
    if (inflight) return inflight
    loaded.value = false
    loadFailed.value = false
    return ensureLoaded()
  }

  return {
    specs,
    coverage,
    loaded,
    loadFailed,
    lastError,
    dayTag,
    pendingTag,
    hasAnyLayer,
    specFor,
    isOnDemandLayer,
    dayTagFor,
    setDayTag,
    clearDayTag,
    setPendingTag,
    clearPendingTag,
    displayedDayTag,
    coversDate,
    ensureLoaded,
    reload,
  }
})
