import { nextTick, watch, ref, onBeforeUnmount, type ComputedRef, type Ref } from 'vue'

import type { ActiveLayerDisplay, LayerHotspot } from '../../stores/layers/types'
import type { WeatherPointResponse } from '../../services/runtime-api'
import { useUiStore } from '../../stores/ui'
import {
  normalizeAnalysisFocusIds,
  resolveAnalysisTabForFocusIds,
  type AnalysisTabId,
} from './analysis-tab-focus'

/**
 * 面板滚动 / 焦点管理 composable。
 *
 * 从 InfoPanel.vue 提取，集中管理分析区域的滚动定位、Tab 自动切换、
 * 焦点请求处理以及卸载时的定时器清理。
 */
export function usePanelScroll(
  displayLayer: ComputedRef<ActiveLayerDisplay>,
  activeTab: Ref<AnalysisTabId>,
  hasLayerStyleSection: ComputedRef<boolean>,
  isRealtimeWeatherLayer: ComputedRef<boolean>,
  visibleHotspots: ComputedRef<LayerHotspot[]>,
  selectedHotspot: ComputedRef<LayerHotspot | null>,
  pointWeatherLoading: ComputedRef<boolean>,
  pointWeather: ComputedRef<WeatherPointResponse | null>,
  pointWeatherError: ComputedRef<string | null>,
  selectedMapPoint: ComputedRef<{ lng: number; lat: number } | null>,
) {
  // selectedMapPoint 由调用方传入以保持 API 对称性；本 composable 不直接使用。
  void selectedMapPoint

  const uiStore = useUiStore()

  const analysisScrollEl = ref<HTMLElement | null>(null)
  const topSummaryEl = ref<HTMLElement | null>(null)
  // 待清理的 setTimeout 句柄（组件卸载时统一清理，避免回调在卸载后执行）
  const pendingTimers: number[] = []

  function scrollAnalysisIntoView(selector: string) {
    const t = window.setTimeout(() => {
      const el = analysisScrollEl.value?.querySelector(selector) as HTMLElement | null
      el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 0)
    pendingTimers.push(t)
  }

  function scrollToTopSummary() {
    const t = window.setTimeout(() => {
      topSummaryEl.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 0)
    pendingTimers.push(t)
  }

  async function focusRequestedAnalysisSection(ids: string[], token: number) {
    const normalized = normalizeAnalysisFocusIds(ids)
    const tab = resolveAnalysisTabForFocusIds(normalized)
    if (tab) activeTab.value = tab
    await nextTick()
    let attempt = 0

    const tryFocus = () => {
      const container = analysisScrollEl.value
      if (!container) return
      const target = normalized
        .map((id) => {
          try {
            return container.querySelector<HTMLElement>(`#${CSS.escape(id)}`)
          } catch {
            return container.querySelector<HTMLElement>(`#${id}`)
          }
        })
        .find((element) => element !== null)
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'start' })
        uiStore.clearAnalysisFocusRequest(token)
        return
      }
      if (attempt >= 3) {
        uiStore.clearAnalysisFocusRequest(token)
        return
      }
      attempt += 1
      const retryTimer = window.setTimeout(tryFocus, 90)
      pendingTimers.push(retryTimer)
    }

    tryFocus()
  }

  // ── Watchers ──────────────────────────────────────────────────────────────

  watch(
    () => displayLayer.value?.instanceId,
    (instanceId) => {
      scrollToTopSummary()
      // 「查看报告」等显式焦点优先
      if (uiStore.analysisFocusRequest) return
      if (!instanceId) {
        if (activeTab.value === 'style') activeTab.value = 'visual'
        return
      }
      // 导入层：切到元数据并滚到导入专项（导出/属性）
      if (displayLayer.value.isImported || displayLayer.value.isImportedRaster) {
        activeTab.value = 'meta'
        void scrollAnalysisIntoView('#imported-layer')
        return
      }
      // 当前 Tab 对该层无内容时回退，避免样式空白页
      if (activeTab.value === 'style' && !hasLayerStyleSection.value) {
        activeTab.value = 'visual'
      }
    },
    { immediate: true },
  )

  watch(
    () => selectedHotspot.value?.id,
    (hotspotId) => {
      scrollToTopSummary()
      if (hotspotId) {
        activeTab.value = 'visual'
        void scrollAnalysisIntoView(`#hotspot-${hotspotId}`)
        return
      }
      if (visibleHotspots.value.length > 0) {
        activeTab.value = 'visual'
        void scrollAnalysisIntoView('#hotspot-section')
      }
    },
  )

  /** 天气点查开始或结果到达 → 图表 Tab，避免人停在工具而结果在别处 */
  watch(
    () => [pointWeatherLoading.value, !!pointWeather.value, !!pointWeatherError.value] as const,
    ([loading, hasResult, hasError], prev) => {
      if (!isRealtimeWeatherLayer.value) return
      const becameActive =
        (loading && !prev?.[0]) || (hasResult && !prev?.[1]) || (hasError && !prev?.[2])
      if (becameActive) activeTab.value = 'visual'
    },
  )

  watch(
    () => uiStore.analysisFocusRequest,
    (request) => {
      if (!request) return
      void focusRequestedAnalysisSection(request.ids, request.token)
    },
  )

  // ── 清理 ──────────────────────────────────────────────────────────────────

  function cleanupPanelScroll() {
    pendingTimers.forEach((t) => window.clearTimeout(t))
    pendingTimers.length = 0
  }

  onBeforeUnmount(() => {
    cleanupPanelScroll()
  })

  return {
    analysisScrollEl,
    topSummaryEl,
    scrollAnalysisIntoView,
    scrollToTopSummary,
    cleanupPanelScroll,
  }
}
