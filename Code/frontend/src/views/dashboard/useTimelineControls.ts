/**
 * useTimelineControls — 时间轴 UI 交互处理器。
 *
 * 从 DashboardView.vue 提取：step / changeHour / changeDate /
 * togglePlay / changePlayInterval / toggleUnifiedTime / toggleLayerLock。
 */
import type { ComputedRef, Ref } from 'vue'
import type { useUiStore } from '../../stores/ui'
import type { useLogStore } from '../../stores/log'

export function useTimelineControls(
  uiStore: ReturnType<typeof useUiStore>,
  logStore: ReturnType<typeof useLogStore>,
  selectedCatalogId: ComputedRef<string | null>,
  activeLayer: ComputedRef<{ name: string; catalogId?: string }>,
  hourLabel: Ref<string>,
  unifiedTimeLock: Ref<boolean>,
  isPlaying: Ref<boolean>,
) {
  function handleTimelineStep(delta: number) {
    if (!Number.isFinite(delta) || delta === 0) return
    uiStore.stepHour(delta)
    if (!unifiedTimeLock.value) uiStore.rememberLayerTime(selectedCatalogId.value)
    logStore.logOperation(
      'timeline-step',
      `时间轴${delta > 0 ? '前进' : '后退'} ${Math.abs(delta)} 小时`,
    )
  }

  function handleTimelineChange(hour: number) {
    if (!Number.isFinite(hour)) return
    uiStore.setHour(hour)
    if (!unifiedTimeLock.value) uiStore.rememberLayerTime(selectedCatalogId.value)
    logStore.logOperation('timeline-change', `时间轴跳转到 ${hourLabel.value}`)
  }

  function handleTimelineDateChange(date: Date) {
    uiStore.setDate(date)
    if (!unifiedTimeLock.value) uiStore.rememberLayerTime(selectedCatalogId.value)
    const y = date.getFullYear()
    const m = String(date.getMonth() + 1).padStart(2, '0')
    const d = String(date.getDate()).padStart(2, '0')
    logStore.logOperation('timeline-date-change', `日期切换到 ${y}-${m}-${d}`)
  }

  function handleTimelineTogglePlay() {
    uiStore.togglePlay()
    logStore.logOperation('timeline-play', isPlaying.value ? '时间轴播放' : '时间轴暂停')
  }

  function handleTimelinePlayInterval(ms: number) {
    uiStore.setPlayIntervalMs(ms)
    logStore.logOperation('timeline-play-interval', `播放间隔设为 ${ms}ms`)
  }

  function handleTimelineToggleUnified() {
    const turningOn = !unifiedTimeLock.value
    if (turningOn && selectedCatalogId.value) {
      uiStore.rememberLayerTime(selectedCatalogId.value, { force: true })
    }
    uiStore.toggleUnifiedTimeLock()
    const on = unifiedTimeLock.value
    if (!on && selectedCatalogId.value) {
      uiStore.restoreLayerTime(selectedCatalogId.value)
    }
    logStore.logOperation('timeline-unified', on ? '开启统一时间' : '关闭统一时间（分图层记忆）')
  }

  function handleToggleLayerLock() {
    const catalogId = activeLayer.value?.catalogId
    if (catalogId) {
      const willLock = !uiStore.isLayerTimeLocked(catalogId)
      if (willLock) {
        uiStore.rememberLayerTime(catalogId, { force: true })
      }
      uiStore.toggleLayerTimeLock(catalogId)
      const locked = uiStore.isLayerTimeLocked(catalogId)
      logStore.logOperation(
        'timeline-lock',
        `图层 ${activeLayer.value.name} 时间记忆锁定: ${locked ? '已锁定' : '已解锁'}`,
      )
    }
  }

  return {
    handleTimelineStep,
    handleTimelineChange,
    handleTimelineDateChange,
    handleTimelineTogglePlay,
    handleTimelinePlayInterval,
    handleTimelineToggleUnified,
    handleToggleLayerLock,
  }
}
