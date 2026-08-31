/**
 * timeline-action-banner — 顶栏下通知/确认/恢复卡状态。
 *
 * - notice：失败/缺数提示，10s 自动清除（不 cancel run）
 * - confirm：改轴后的重跑确认（不自动同意；被下一次改轴替换或用户操作关闭）
 * - recovery：本地缺数等可恢复失败（不自动消失；P0 支持切换在线重跑）
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export const NOTICE_TTL_MS = 10_000
export const TIMELINE_CONFIRM_DEBOUNCE_MS = 2_000

export type TimelineBannerAlignOffer = {
  inputKey: 'time_window_align_on_zero_intersection'
  label: string
  defaultChecked: boolean
}

export type TimelineBannerConfirm = {
  id: string
  timeKey: string
  catalogIds: string[]
  canReuse: boolean
  /** 紧凑范围文案，如「独立 · 当前」/「统一 · 3 图层」 */
  scopeLabel: string
  /** 悬停详情：图层名列表等 */
  layerHint?: string | null
  /** @deprecated 旧长文案；UI 已改用 scopeLabel + timeKey */
  message?: string
  alignOffer?: TimelineBannerAlignOffer | null
}

export type TimelineBannerNotice = {
  id: string
  message: string
  catalogId?: string | null
  tone?: 'error' | 'info'
}

export type TimelineBannerRecoveryOffer = 'switch_online' | 'open_plan'

export type TimelineBannerRecovery = {
  id: string
  catalogId: string
  message: string
  timeKey?: string | null
  offers: TimelineBannerRecoveryOffer[]
  /** 升级进计划会话后的短条文案（如「已加入计划」） */
  planHint?: string | null
}

export const useTimelineActionBannerStore = defineStore('timeline-action-banner', () => {
  const notice = ref<TimelineBannerNotice | null>(null)
  const confirm = ref<TimelineBannerConfirm | null>(null)
  const recovery = ref<TimelineBannerRecovery | null>(null)
  const alignChecked = ref(false)
  /** 程序化改轴（添加后 snap / 产物对齐）期间抑制确认卡，避免自触发循环 */
  const suppressConfirmUntil = ref(0)

  let noticeTimer: ReturnType<typeof setTimeout> | null = null

  const hasConfirm = computed(() => confirm.value !== null)
  const hasNotice = computed(() => notice.value !== null)
  const hasRecovery = computed(() => recovery.value !== null)
  const isOpen = computed(() => hasConfirm.value || hasNotice.value || hasRecovery.value)

  function isConfirmSuppressed() {
    return Date.now() < suppressConfirmUntil.value
  }

  function suppressConfirm(ms = 3_000) {
    suppressConfirmUntil.value = Date.now() + Math.max(0, ms)
    // 清除已排队的确认，避免抑制窗内仍弹出
    confirm.value = null
    alignChecked.value = false
  }

  function clearNoticeTimer() {
    if (noticeTimer) {
      clearTimeout(noticeTimer)
      noticeTimer = null
    }
  }

  function dismissNotice() {
    clearNoticeTimer()
    notice.value = null
  }

  function showNotice(payload: Omit<TimelineBannerNotice, 'id'> & { id?: string }) {
    clearNoticeTimer()
    notice.value = {
      id: payload.id ?? `notice-${Date.now()}`,
      message: payload.message,
      catalogId: payload.catalogId ?? null,
      tone: payload.tone ?? 'error',
    }
    noticeTimer = setTimeout(() => {
      notice.value = null
      noticeTimer = null
    }, NOTICE_TTL_MS)
  }

  function dismissConfirm() {
    confirm.value = null
    alignChecked.value = false
  }

  function showConfirm(payload: Omit<TimelineBannerConfirm, 'id'> & { id?: string }) {
    if (isConfirmSuppressed()) return
    // 新确认替换旧确认；不触碰 notice（失败 notice 可并存，但 UI 优先 confirm）
    confirm.value = {
      id: payload.id ?? `confirm-${Date.now()}`,
      timeKey: payload.timeKey,
      catalogIds: [...payload.catalogIds],
      canReuse: payload.canReuse,
      scopeLabel: payload.scopeLabel || (payload.message ? String(payload.message) : '时间轴'),
      layerHint: payload.layerHint ?? null,
      message: payload.message,
      alignOffer: payload.alignOffer ?? null,
    }
    alignChecked.value = Boolean(payload.alignOffer?.defaultChecked)
  }

  function setAlignChecked(value: boolean) {
    alignChecked.value = value
  }

  function dismissRecovery() {
    recovery.value = null
  }

  function showRecovery(payload: Omit<TimelineBannerRecovery, 'id'> & { id?: string }) {
    // 恢复卡不自动消失；替换旧 recovery，并清掉同主题 notice 避免叠两张
    dismissNotice()
    recovery.value = {
      id: payload.id ?? `recovery-${Date.now()}`,
      catalogId: payload.catalogId,
      message: payload.message,
      timeKey: payload.timeKey ?? null,
      offers: [...payload.offers],
      planHint: payload.planHint ?? null,
    }
  }

  function dismissAll() {
    dismissNotice()
    dismissConfirm()
    dismissRecovery()
  }

  return {
    notice,
    confirm,
    recovery,
    alignChecked,
    hasConfirm,
    hasNotice,
    hasRecovery,
    isOpen,
    showNotice,
    dismissNotice,
    showConfirm,
    dismissConfirm,
    showRecovery,
    dismissRecovery,
    setAlignChecked,
    dismissAll,
    suppressConfirm,
    isConfirmSuppressed,
  }
})
