import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import type { TileSourceId } from '../services/api-config'

export type { TileSourceId } from '../services/api-config'

/** 地图交互模式：移动（拖动视角）/ 选择（点击选择点或图层） */
export type InteractionMode = 'move' | 'select'

export const useUiStore = defineStore('ui', () => {
  const tileSourceId = ref<TileSourceId>('esri-street')
  const analysisFocusRequest = ref<{ ids: string[]; token: number } | null>(null)

  // 时间轴相关 - 使用当前时间初始化
  const now = new Date()
  const currentHour = ref(now.getHours())
  const isPlaying = ref(false)
  const currentDate = ref(now)

  // 地图交互模式：默认为移动模式
  const interactionMode = ref<InteractionMode>('move')

  const hourLabel = computed(() => `${String(currentHour.value).padStart(2, '0')}:00`)

  // 完整时间标签：日期 + 时间
  const fullTimeLabel = computed(() => {
    const date = currentDate.value
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    const hour = String(currentHour.value).padStart(2, '0')
    return `${year}-${month}-${day} ${hour}:00`
  })

  function setTileSource(sourceId: TileSourceId) {
    tileSourceId.value = sourceId
  }

  function setHour(hour: number) {
    currentHour.value = Math.max(0, Math.min(23, Math.round(hour)))
  }

  function stepHour(delta: number) {
    const nextValue = currentHour.value + delta

    if (nextValue < 0) {
      currentHour.value = 23
      // 回退一天
      const newDate = new Date(currentDate.value)
      newDate.setDate(newDate.getDate() - 1)
      currentDate.value = newDate
      return
    }

    if (nextValue > 23) {
      currentHour.value = 0
      // 前进一天
      const newDate = new Date(currentDate.value)
      newDate.setDate(newDate.getDate() + 1)
      currentDate.value = newDate
      return
    }

    currentHour.value = nextValue
  }

  // 播放控制
  function play() {
    isPlaying.value = true
  }

  function pause() {
    isPlaying.value = false
  }

  function togglePlay() {
    isPlaying.value = !isPlaying.value
  }

  function setDate(date: Date) {
    currentDate.value = date
  }

  function setInteractionMode(mode: InteractionMode) {
    interactionMode.value = mode
  }

  function requestAnalysisFocus(ids: string[]) {
    const normalizedIds = ids.map((id) => id.trim()).filter(Boolean)
    if (!normalizedIds.length) return
    analysisFocusRequest.value = {
      ids: normalizedIds,
      token: Date.now(),
    }
  }

  function clearAnalysisFocusRequest(token?: number) {
    if (!analysisFocusRequest.value) return
    if (typeof token === 'number' && analysisFocusRequest.value.token !== token) return
    analysisFocusRequest.value = null
  }

  return {
    tileSourceId,
    analysisFocusRequest,
    currentHour,
    hourLabel,
    fullTimeLabel,
    isPlaying,
    currentDate,
    interactionMode,
    setTileSource,
    setHour,
    stepHour,
    play,
    pause,
    togglePlay,
    setDate,
    setInteractionMode,
    requestAnalysisFocus,
    clearAnalysisFocusRequest,
  }
})
