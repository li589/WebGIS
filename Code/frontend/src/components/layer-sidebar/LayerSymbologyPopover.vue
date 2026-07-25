<script setup lang="ts">
/**
 * 图层符号化浮窗：按类型展示可调指标（透明度/配色/矢量样式）与只读元信息。
 */
import { computed } from 'vue'
import type { ActiveLayerDisplay, WeatherLayerRenderHint } from '../../stores/layers/types'
import { useLayersStore } from '../../stores/layers'
import { useOverlaySymbologyStore } from '../../stores/overlay-symbology'
import { useUiStore } from '../../stores/ui'
import { LAYERS_COPY } from '../../ui-copy'
import {
  WEATHER_PALETTE_OPTIONS,
  buildWeatherLegendGradient,
  isMapLinkedPalette,
  resolveCanonicalPaletteId,
  resolveSymbologyColors,
} from '../map/layer-symbology'
import { resolveEffectiveLayerSymbology } from '../map/effective-layer-symbology'
import { buildLegendExplainer } from '../map/effective-layer-symbology'

const props = defineProps<{
  layer: ActiveLayerDisplay
  x: number
  y: number
}>()

const emit = defineEmits<{
  close: []
}>()

const layersStore = useLayersStore()
const overlaySymbologyStore = useOverlaySymbologyStore()
const uiStore = useUiStore()

const hasColorSymbology = computed(() => {
  if (props.layer.isAdminBoundary) return false
  if (props.layer.renderHint) return true
  void overlaySymbologyStore.version
  return !!overlaySymbologyStore.getMeta(props.layer.catalogId)?.palette
})

const canEditPalette = computed(() =>
  isMapLinkedPalette({
    hasRenderHint: Boolean(props.layer.renderHint),
    isImportedRaster: props.layer.isImportedRaster,
  }),
)

const title = computed(() =>
  hasColorSymbology.value ? LAYERS_COPY.symbology : LAYERS_COPY.opacity,
)

function getVmin(): string {
  if (props.layer.renderHint?.legend_ticks?.length) {
    const first = props.layer.renderHint.legend_ticks[0]
    return typeof first === 'number' ? String(first) : '—'
  }
  void overlaySymbologyStore.version
  const meta = overlaySymbologyStore.getMeta(props.layer.catalogId)
  return meta?.vmin != null ? String(meta.vmin) : '—'
}

function getVmax(): string {
  if (props.layer.renderHint?.legend_ticks?.length) {
    const last = props.layer.renderHint.legend_ticks[props.layer.renderHint.legend_ticks.length - 1]
    return typeof last === 'number' ? String(last) : '—'
  }
  void overlaySymbologyStore.version
  const meta = overlaySymbologyStore.getMeta(props.layer.catalogId)
  return meta?.vmax != null ? String(meta.vmax) : '—'
}

function getUnit(): string {
  if (props.layer.renderHint?.unit_label) return props.layer.renderHint.unit_label
  void overlaySymbologyStore.version
  return overlaySymbologyStore.getMeta(props.layer.catalogId)?.unit || ''
}

function getColorRampStyle(): Record<string, string> {
  void overlaySymbologyStore.version
  const { hint } = resolveEffectiveLayerSymbology({
    paletteOverride: props.layer.paletteOverride,
    renderHint: (props.layer.renderHint ?? null) as WeatherLayerRenderHint | null,
    overlayMeta: overlaySymbologyStore.getMeta(props.layer.catalogId),
  })
  if (hint) {
    return { background: buildWeatherLegendGradient(hint) }
  }
  const colors = resolveSymbologyColors({
    paletteOverride: props.layer.paletteOverride,
    renderHint: props.layer.renderHint,
    overlayMeta: overlaySymbologyStore.getMeta(props.layer.catalogId),
    fallbackAccent: props.layer.accentColor,
  })
  return { background: `linear-gradient(90deg, ${colors.join(', ')})` }
}

const paletteId = computed(() => {
  void overlaySymbologyStore.version
  return resolveCanonicalPaletteId(
    props.layer.paletteOverride ??
      props.layer.renderHint?.palette ??
      overlaySymbologyStore.getMeta(props.layer.catalogId)?.palette ??
      '',
  )
})

const legendExplainer = computed(() => {
  void overlaySymbologyStore.version
  const { hint } = resolveEffectiveLayerSymbology({
    paletteOverride: props.layer.paletteOverride,
    renderHint: (props.layer.renderHint ?? null) as WeatherLayerRenderHint | null,
    overlayMeta: overlaySymbologyStore.getMeta(props.layer.catalogId),
  })
  const text = buildLegendExplainer({ hint })
  return text || null
})

const showPaletteRow = computed(() => {
  void overlaySymbologyStore.version
  return Boolean(
    props.layer.renderHint || overlaySymbologyStore.getMeta(props.layer.catalogId)?.palette,
  )
})

function onOpacity(event: Event) {
  const target = event.target as HTMLInputElement
  layersStore.setLayerOpacity(props.layer.instanceId, Number(target.value) / 100)
}

function onPalette(event: Event) {
  if (!canEditPalette.value) return
  const palette = (event.target as HTMLSelectElement).value
  const defaultPalette = props.layer.renderHint?.palette ?? ''
  layersStore.setLayerPaletteOverride(
    props.layer.instanceId,
    palette === defaultPalette ? null : palette,
  )
}

const vectorStyle = computed(() => props.layer.importedVectorStyle ?? {})

function patchVectorStyle(
  patch: Partial<{ color: string; width: number; radius: number; fillOpacity: number }>,
) {
  layersStore.setImportedVectorStyle(props.layer.instanceId, patch)
}

function formatBounds(b?: [number, number, number, number] | null): string {
  if (!b || b.length < 4) return '—'
  return `${b[0].toFixed(2)}, ${b[1].toFixed(2)} → ${b[2].toFixed(2)}, ${b[3].toFixed(2)}`
}

function openInAnalysis() {
  layersStore.selectLayer(props.layer.instanceId)
  uiStore.requestAnalysisFocus(['layer-style', 'overview-section'])
  emit('close')
}
</script>

<template>
  <div
    class="sym-popover"
    :style="{ left: x + 'px', top: y + 'px', '--accent': layer.accentColor }"
    @click.stop
  >
    <div class="sym-popover-header">
      <span class="sym-popover-title">{{ title }}</span>
      <button class="sym-popover-close" type="button" @click="emit('close')">✕</button>
    </div>
    <div class="sym-popover-body">
      <div class="sym-layer-name">{{ layer.name }}</div>

      <!-- 外观 -->
      <div class="sym-section-label">{{ LAYERS_COPY.sectionAppearance }}</div>

      <template v-if="hasColorSymbology">
        <div class="sym-field-row">
          <span class="sym-field-label">{{ LAYERS_COPY.fieldLabel }}</span>
          <span class="sym-field-value">{{ layer.metricLabel || '—' }}</span>
        </div>
        <div class="sym-color-ramp" :style="getColorRampStyle()"></div>
        <div class="sym-range-row">
          <span class="sym-range-min">{{ getVmin() }}</span>
          <span class="sym-range-unit">{{ getUnit() }}</span>
          <span class="sym-range-max">{{ getVmax() }}</span>
        </div>
        <p v-if="legendExplainer" class="sym-explainer">{{ legendExplainer }}</p>

        <div v-if="showPaletteRow" class="sym-palette-row">
          <span class="sym-field-label">{{ LAYERS_COPY.paletteLabel }}</span>
          <select
            class="sym-palette-select"
            :value="paletteId"
            :disabled="!canEditPalette"
            :title="
              canEditPalette ? LAYERS_COPY.paletteTitleEdit : LAYERS_COPY.paletteTitleReadonly
            "
            @change="onPalette"
          >
            <option v-for="opt in WEATHER_PALETTE_OPTIONS" :key="opt.id" :value="opt.id">
              {{ opt.label }}
            </option>
          </select>
        </div>
        <p v-if="!canEditPalette && showPaletteRow" class="sym-palette-hint">
          {{ LAYERS_COPY.paletteHintReadonly }}
        </p>
      </template>

      <!-- 导入矢量就地样式 -->
      <template v-if="layer.isImported">
        <label class="sym-style-row">
          <span>{{ LAYERS_COPY.vectorColor }}</span>
          <input
            type="color"
            :value="vectorStyle.color || '#4fc3f7'"
            @input="patchVectorStyle({ color: ($event.target as HTMLInputElement).value })"
          />
        </label>
        <label class="sym-style-row">
          <span>{{ LAYERS_COPY.vectorWidth }}</span>
          <input
            type="range"
            min="0.5"
            max="8"
            step="0.5"
            :value="vectorStyle.width ?? 2"
            @input="
              patchVectorStyle({
                width: Number(($event.target as HTMLInputElement).value),
              })
            "
          />
          <strong>{{ vectorStyle.width ?? 2 }}</strong>
        </label>
        <label class="sym-style-row">
          <span>{{ LAYERS_COPY.vectorRadius }}</span>
          <input
            type="range"
            min="2"
            max="16"
            step="1"
            :value="vectorStyle.radius ?? 5"
            @input="
              patchVectorStyle({
                radius: Number(($event.target as HTMLInputElement).value),
              })
            "
          />
          <strong>{{ vectorStyle.radius ?? 5 }}</strong>
        </label>
        <label class="sym-style-row">
          <span>{{ LAYERS_COPY.vectorFillOpacity }}</span>
          <input
            type="range"
            min="0"
            max="100"
            :value="Math.round((vectorStyle.fillOpacity ?? 0.35) * 100)"
            @input="
              patchVectorStyle({
                fillOpacity: Number(($event.target as HTMLInputElement).value) / 100,
              })
            "
          />
          <strong>{{ Math.round((vectorStyle.fillOpacity ?? 0.35) * 100) }}%</strong>
        </label>
      </template>

      <div class="sym-opacity-row">
        <span>{{ LAYERS_COPY.opacity }}</span>
        <input
          class="sym-opacity-slider"
          type="range"
          min="0"
          max="100"
          :value="Math.round(layer.opacity * 100)"
          @input="onOpacity"
        />
        <strong>{{ Math.round(layer.opacity * 100) }}%</strong>
      </div>

      <!-- 数值范围（导入栅格 / 有色带） -->
      <template v-if="hasColorSymbology || layer.isImportedRaster">
        <div class="sym-section-label">{{ LAYERS_COPY.sectionRange }}</div>
        <div class="sym-meta-grid">
          <div v-if="getUnit()" class="sym-meta-cell">
            <span>{{ LAYERS_COPY.metricUnit }}</span>
            <strong>{{ getUnit() }}</strong>
          </div>
          <div class="sym-meta-cell">
            <span>min</span>
            <strong>{{ getVmin() }}</strong>
          </div>
          <div class="sym-meta-cell">
            <span>max</span>
            <strong>{{ getVmax() }}</strong>
          </div>
        </div>
      </template>

      <!-- 数据来源 -->
      <div class="sym-section-label">{{ LAYERS_COPY.sectionSource }}</div>
      <div class="sym-meta-grid">
        <div v-if="layer.isImported" class="sym-meta-cell">
          <span>{{ LAYERS_COPY.metricGeometry }}</span>
          <strong>{{ layer.importedGeometryType || '—' }}</strong>
        </div>
        <div v-if="layer.isImported" class="sym-meta-cell">
          <span>{{ LAYERS_COPY.metricFeatures }}</span>
          <strong>{{ layer.importedFeatureCount ?? '—' }}</strong>
        </div>
        <div v-if="layer.isImportedRaster" class="sym-meta-cell">
          <span>{{ LAYERS_COPY.metricCrs }}</span>
          <strong>{{ layer.importedRasterSourceCrs || '—' }}</strong>
        </div>
        <div v-if="layer.importedBounds || layer.importedRasterBounds" class="sym-meta-cell wide">
          <span>{{ LAYERS_COPY.metricBounds }}</span>
          <strong>{{ formatBounds(layer.importedBounds || layer.importedRasterBounds) }}</strong>
        </div>
        <div v-if="layer.importedFileName || layer.sourceLabel" class="sym-meta-cell wide">
          <span>{{ LAYERS_COPY.metricSourceFile }}</span>
          <strong>{{ layer.importedFileName || layer.sourceLabel }}</strong>
        </div>
        <div v-if="!layer.isImported && !layer.isImportedRaster" class="sym-meta-cell wide">
          <span>来源</span>
          <strong>{{ layer.sourceLabel || layer.engine || '—' }}</strong>
        </div>
      </div>

      <button class="sym-open-analysis" type="button" @click="openInAnalysis">
        {{ LAYERS_COPY.openInAnalysis }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.sym-popover {
  position: fixed;
  z-index: 10050;
  width: min(280px, calc(100vw - 16px));
  max-height: min(72vh, 520px);
  overflow: auto;
  border-radius: 0.72rem;
  border: 1px solid rgba(148, 163, 184, 0.28);
  background: linear-gradient(180deg, rgba(16, 26, 44, 0.97), rgba(10, 18, 32, 0.96));
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.45);
  color: #e2e8f0;
  font-size: 0.78rem;
}

.sym-popover-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.55rem 0.7rem;
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
}

.sym-popover-title {
  font-weight: 650;
  letter-spacing: 0.02em;
}

.sym-popover-close {
  border: none;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  font-size: 0.85rem;
}

.sym-popover-body {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  padding: 0.65rem 0.7rem 0.75rem;
}

.sym-layer-name {
  font-weight: 600;
  color: #f8fafc;
  line-height: 1.3;
}

.sym-section-label {
  margin-top: 0.25rem;
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: #94a3b8;
}

.sym-field-row,
.sym-palette-row,
.sym-opacity-row,
.sym-style-row {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}

.sym-field-label {
  color: #94a3b8;
  min-width: 2.4rem;
}

.sym-field-value {
  color: #e2e8f0;
  font-weight: 550;
}

.sym-color-ramp {
  height: 10px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: var(--accent, #38bdf8);
}

.sym-range-row {
  display: flex;
  justify-content: space-between;
  color: #94a3b8;
  font-variant-numeric: tabular-nums;
}

.sym-range-unit {
  color: #cbd5e1;
}

.sym-palette-select {
  flex: 1;
  min-width: 0;
  border-radius: 0.4rem;
  border: 1px solid rgba(148, 163, 184, 0.28);
  background: rgba(15, 23, 42, 0.7);
  color: #e2e8f0;
  padding: 0.2rem 0.35rem;
}

.sym-palette-hint,
.sym-explainer {
  margin: 0;
  color: #94a3b8;
  font-size: 0.7rem;
  line-height: 1.35;
}

.sym-opacity-slider {
  flex: 1;
  accent-color: var(--accent, #38bdf8);
}

.sym-style-row input[type='color'] {
  width: 2rem;
  height: 1.4rem;
  border: none;
  background: transparent;
  cursor: pointer;
}

.sym-style-row input[type='range'] {
  flex: 1;
  accent-color: var(--accent, #38bdf8);
}

.sym-meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.35rem;
}

.sym-meta-cell {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  padding: 0.3rem 0.4rem;
  border-radius: 0.4rem;
  background: rgba(148, 163, 184, 0.08);
}

.sym-meta-cell.wide {
  grid-column: 1 / -1;
}

.sym-meta-cell span {
  color: #94a3b8;
  font-size: 0.66rem;
}

.sym-meta-cell strong {
  font-weight: 550;
  color: #e2e8f0;
  word-break: break-all;
  font-size: 0.72rem;
}

.sym-open-analysis {
  margin-top: 0.2rem;
  border: 1px solid rgba(56, 189, 248, 0.35);
  border-radius: 0.45rem;
  background: rgba(56, 189, 248, 0.12);
  color: #7dd3fc;
  padding: 0.35rem 0.5rem;
  cursor: pointer;
  font-size: 0.75rem;
}

.sym-open-analysis:hover {
  background: rgba(56, 189, 248, 0.2);
}
</style>
