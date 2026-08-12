import { computed, type ComputedRef } from 'vue'

import type { ActiveLayerDisplay } from '../../stores/layers/types'
import type { OverlayPointValue } from '../../services/runtime-api'
import type { OverlayTimeState } from '../map/overlay-image-module'
import { useLayersStore } from '../../stores/layers'
import { formatOverlayValue } from './useWeatherPointData'

/**
 * 叠加图层 / 点值 / 时间序列 composable。
 *
 * 从 InfoPanel.vue 提取，集中管理 overlay 图层列表、像素点值映射、
 * 多层柱状图条目以及选中时序行。
 */
export function useOverlayData(
  displayLayer: ComputedRef<ActiveLayerDisplay>,
  overlayTimeStates: ComputedRef<OverlayTimeState[]>,
  overlayPointValues: ComputedRef<OverlayPointValue[]>,
  selectedOverlayTimeSeries: ComputedRef<OverlayPointValue[]>,
  selectedMapPoint: ComputedRef<{ lng: number; lat: number } | null>,
  overlayStyleMeta: ComputedRef<any>,
) {
  // overlayStyleMeta 由调用方传入以保持 API 对称性；本 composable 不直接使用。
  void overlayStyleMeta

  const layersStore = useLayersStore()

  // ── 叠加图层列表 ──────────────────────────────────────────────────────────

  const overlayLayers = computed(() => {
    const timeStateMap = new Map((overlayTimeStates.value ?? []).map((s) => [s.layerId, s]))
    return layersStore.activeLayersDisplay
      .filter((l) => l.visible && Boolean(l.importedRasterOverlayLayerId))
      .map((l) => {
        const overlayLayerId = l.importedRasterOverlayLayerId ?? l.catalogId
        const ts = timeStateMap.get(overlayLayerId)
        return {
          name: l.name,
          category: l.category,
          availabilityState: l.availabilityState,
          accentColor: l.accentColor,
          catalogId: l.catalogId,
          overlayLayerId,
          palette: ts?.palette ?? null,
          vmin: ts?.vmin ?? null,
          vmax: ts?.vmax ?? null,
          unit: ts?.unit ?? '',
          currentTime: ts?.currentTime ?? null,
          isTimeSeries: ts?.category === 'time-series',
        }
      })
  })

  // ── 叠加图层像素值查询结果 ──────────────────────────────────────────────────

  const overlayPointValueMap = computed(() => {
    const m = new Map<string, OverlayPointValue>()
    for (const v of overlayPointValues.value ?? []) {
      m.set(v.layer_id, v)
    }
    return m
  })

  // ── 多层叠加柱状图条目 ────────────────────────────────────────────────────

  const multiOverlayBarItems = computed(() => {
    const list = overlayLayers.value ?? []
    return list.map((layer) => {
      const pt = overlayPointValueMap.value.get(layer.overlayLayerId)
      const val = pt?.value ?? null
      return {
        layerId: layer.overlayLayerId,
        name: layer.name,
        category: layer.category,
        valueText: pt && pt.value !== null ? formatOverlayValue(pt) : 'N/A',
        numericValue: typeof val === 'number' && Number.isFinite(val) ? val : null,
        unit: pt?.unit || layer.unit || '',
        accentColor: layer.accentColor,
      }
    })
  })

  /** 多层叠加柱状图：有选点且存在其它可见 overlay 即可（不绑天气 section） */
  const showMultiOverlayBar = computed(
    () => !!selectedMapPoint.value && multiOverlayBarItems.value.length > 0,
  )

  // ── 选中时序栅格行 ──────────────────────────────────────────────────────────

  const selectedOverlayTimeSeriesRows = computed(() => {
    const activeTime = (overlayTimeStates.value ?? []).find(
      (s) => s.layerId === displayLayer.value.importedRasterOverlayLayerId,
    )?.currentTime
    return (selectedOverlayTimeSeries.value ?? [])
      .filter((item) => item.time)
      .map((item) => ({
        time: item.time!.replace('_', ' → '),
        metric: formatOverlayValue(item),
        numericValue:
          typeof item.value === 'number' && Number.isFinite(item.value) ? item.value : undefined,
        active: item.time === activeTime,
      }))
  })

  const showSelectedOverlayTimeSeries = computed(
    () => !!selectedMapPoint.value && selectedOverlayTimeSeriesRows.value.length > 0,
  )

  /** 汇报演示兜底：未点地图时，允许按当前选中图层默认数据点展示时序。 */
  const showDemoOverlayTimeSeries = computed(
    () => !selectedMapPoint.value && selectedOverlayTimeSeriesRows.value.length > 0,
  )

  return {
    overlayLayers,
    overlayPointValueMap,
    multiOverlayBarItems,
    showMultiOverlayBar,
    selectedOverlayTimeSeriesRows,
    showSelectedOverlayTimeSeries,
    showDemoOverlayTimeSeries,
  }
}
