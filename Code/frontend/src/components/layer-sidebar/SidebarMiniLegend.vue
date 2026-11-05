<script setup lang="ts">
/**
 * SidebarMiniLegend — 图层面板**收起后**留在标题栏上的迷你色标。
 *
 * 2026-11-05 用户要求：「图层面板收起时保留一个小色标」。
 * 面板收起后整块内容被 `PanelDock` 折叠（0fr + inert），图例行看不到，
 * 于是把「当前选中层」的色带压缩成标题栏上的一小段，仍然能读出配色。
 *
 * 数据来源与侧栏图例完全同源（`useSidebarSymbology`），保证两处颜色一致；
 * 拿不到选中层就退到「第一个可见的、有色彩符号化的图层」，
 * 再拿不到就整块不渲染（返回 null 内容，标题栏不留空位）。
 */
import { computed } from 'vue'
import { useLayerWorkspace } from '../../stores/layers/selectors'
import { useOverlaySymbologyStore } from '../../stores/overlay-symbology'
import { useSidebarSymbology } from './useSidebarSymbology'

const workspace = useLayerWorkspace()
const overlaySymbologyStore = useOverlaySymbologyStore()
const symbology = useSidebarSymbology(overlaySymbologyStore)

/** 优先「选中的那一层」，否则取第一个可见且有色带的可见图层 */
const targetLayer = computed(() => {
  const selected = workspace.selectedLayerDisplay.value
  if (
    selected &&
    selected.visible &&
    symbology.hasColorSymbology(selected) &&
    (symbology.getSymbologyVmin(selected) || symbology.getSymbologyVmax(selected))
  ) {
    return selected
  }
  return (
    workspace.activeLayersDisplay.value.find(
      (layer) =>
        layer.visible &&
        symbology.hasColorSymbology(layer) &&
        (symbology.getSymbologyVmin(layer) || symbology.getSymbologyVmax(layer)),
    ) ?? null
  )
})

const rampStyle = computed(() =>
  targetLayer.value ? symbology.getColorRampStyle(targetLayer.value) : {},
)

/**
 * 收起态显示的是**量程**（vmin–vmax，如 0–0.6），不是刻度值。
 * 2026-11-05 起侧栏图例不再标量程起点 0（那是标尺左端，不是数据里有 0），
 * 但迷你色标这行的语义就是"这条色带代表哪一段数值"，所以仍取真实量程。
 */
const rangeLabel = computed(() => {
  const layer = targetLayer.value
  if (!layer) return ''
  const lo = symbology.getSymbologyVmin(layer)
  const hi = symbology.getSymbologyVmax(layer)
  if (!lo && !hi) return ''
  return lo && hi ? `${lo} – ${hi}` : lo || hi
})

const layerName = computed(() => targetLayer.value?.metricLabel ?? '')
</script>

<template>
  <span
    v-if="targetLayer"
    class="mini-legend"
    :title="`${layerName} ${rangeLabel}`"
    aria-hidden="true"
  >
    <span class="mini-legend__ramp" :style="rampStyle"></span>
    <span v-if="rangeLabel" class="mini-legend__range">{{ rangeLabel }}</span>
  </span>
</template>

<style scoped>
.mini-legend {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  min-width: 0;
  max-width: 11rem;
  margin-left: 0.35rem;
  /* 标题栏本身不可拖动区域较多，这里不接管指针事件 */
  pointer-events: none;
}

.mini-legend__ramp {
  flex: 0 0 auto;
  width: 3.4rem;
  height: 0.34rem;
  border-radius: 0.2rem;
  border: 1px solid var(--border-subtle);
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.16);
}

.mini-legend__range {
  flex: 0 1 auto;
  overflow: hidden;
  color: var(--text-muted);
  font-size: 0.6rem;
  font-variant-numeric: tabular-nums;
  font-family: var(--font-sans);
  white-space: nowrap;
  text-overflow: ellipsis;
}
</style>
