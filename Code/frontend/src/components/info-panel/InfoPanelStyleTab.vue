/** * InfoPanel 样式 Tab：透明度 / 符号化 / 调色板 / 值域 / 风场 / 天气源。 * * 从 InfoPanel.vue
模板抽取（原 1836-2245 行）。自包含组件，直接使用 composables。 */
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import AppButton from '../ui/AppButton.vue'
import AppSelect from '../ui/AppSelect.vue'
import type { ActiveLayerDisplay } from '../../stores/layers/types'
import type { WeatherPointResponse } from '../../services/runtime-api'
import type { OverlayTimeState } from '../map/overlay-image-module'
import { useLayerViewport } from '../../stores/layers/selectors'
import { windDisplayModeLabel } from '../map/wind-display-mode'
import { paletteIdsEqual } from '../map/layer-symbology'
import {
  IMPORTED_VECTOR_STYLE_DEFAULTS,
  resolveImportedVectorDefaultColor,
} from '../../stores/layers/imported-vector'
import { ANALYSIS_COPY, INSPECT_COPY, LAYERS_COPY } from '../../ui-copy'
import { openDataWorkspace } from '../../data-manager/core/workspace-store'
import { useLayerSymbology } from './useLayerSymbology'
import { useWeatherProviders } from './useWeatherProviders'
import { useImportExport } from './useImportExport'

const props = defineProps<{
  displayLayer: ActiveLayerDisplay
  isRealtimeWeatherLayer: boolean
  overlayTimeStates: OverlayTimeState[]
  pointWeather: WeatherPointResponse | null
}>()

const emit = defineEmits<{
  toggleLayerVisibility: [instanceId: string]
  setLayerOpacity: [payload: { instanceId: string; opacity: number }]
}>()

const viewport = useLayerViewport()
const { smoothRendering, setSmoothRendering } = viewport

// composables 接受 ComputedRef，需从 props 派生
const displayLayerRef = computed(() => props.displayLayer)
const isRealtimeWeatherLayerRef = computed(() => props.isRealtimeWeatherLayer)
const overlayTimeStatesRef = computed(() => props.overlayTimeStates)
const pointWeatherRef = computed(() => props.pointWeather)

const {
  weatherRenderHint,
  styleRenderHint,
  normalizedUnitLabel,
  styleFieldLabel,
  styleRangeMeta,
  weatherLegendStops,
  weatherLegendGradient,
  currentPaletteId,
  paletteOptions,
  paletteDropdownOpen,
  canEditPalette,
  rangeEditVmin,
  rangeEditVmax,
  rangeInputStep,
  nodataModeValue,
  nodataColorValue,
  handleSelectPalette,
  togglePaletteDropdown,
  tileStats,
  hasWeatherLayerAsset,
  canToggleParticleFlow,
  currentWindDisplayMode,
  legendExplainer,
  handleSetWindDisplayMode,
  particleFlowButtonDisabled,
  windStyleChipLabel,
  hasLayerStyleSection,
  hasAdvancedStyleControls,
} = useLayerSymbology(
  displayLayerRef,
  isRealtimeWeatherLayerRef,
  overlayTimeStatesRef,
  pointWeatherRef,
)

const {
  weatherProviderOptions,
  weatherProvidersLoading,
  weatherProvidersError,
  selectedWeatherProvider,
  selectedWeatherProviderSparse,
  selectedWeatherProviderHint,
  weatherProviderOptionLabel,
  cleanupWeatherProviders,
} = useWeatherProviders(displayLayerRef, isRealtimeWeatherLayerRef)

const { importedVectorStyle, patchImportedVectorStyle } = useImportExport(displayLayerRef)

// 兜底色取当前主题 --success 实色（与地图渲染同源），而非无效的 CSS 变量字符串
const importedVectorDefaultColor = computed(() => resolveImportedVectorDefaultColor())

// ── 配色下拉框动态翻转 ──────────────────────────────────────────────
const paletteDropdownRef = ref<HTMLElement | null>(null)
const dropdownOpenUp = ref(false)

watch(paletteDropdownOpen, async (open) => {
  if (!open) {
    dropdownOpenUp.value = false
    return
  }
  await nextTick()
  const el = paletteDropdownRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const spaceBelow = window.innerHeight - rect.bottom
  const dropdownH = el.offsetHeight
  dropdownOpenUp.value = spaceBelow < dropdownH + 8 && rect.top > dropdownH + 8
})

function closePaletteDropdown() {
  paletteDropdownOpen.value = false
}

let scrollContainer: Element | null = null
onMounted(() => {
  scrollContainer = document.querySelector('.panel-scroll')
  if (scrollContainer) {
    scrollContainer.addEventListener('scroll', closePaletteDropdown, { passive: true })
  }
})
onBeforeUnmount(() => {
  if (scrollContainer) {
    scrollContainer.removeEventListener('scroll', closePaletteDropdown)
  }
})

const jobLayer = computed(() => props.displayLayer.jobLayer)

function handleToggleLayerVisibility() {
  if (!props.displayLayer?.instanceId) return
  emit('toggleLayerVisibility', props.displayLayer.instanceId)
}

function handleLayerOpacityInput(event: Event) {
  if (!props.displayLayer?.instanceId) return
  const target = event.target as HTMLInputElement
  emit('setLayerOpacity', {
    instanceId: props.displayLayer.instanceId,
    opacity: Number(target.value) / 100,
  })
}

// 保留引用以便属性表入口复用
void openDataWorkspace

onBeforeUnmount(() => {
  cleanupWeatherProviders()
})
</script>

<template>
  <section
    v-if="hasLayerStyleSection"
    v-show="true"
    id="layer-style"
    class="analysis-section analysis-section--style"
  >
    <div class="section-kicker">{{ ANALYSIS_COPY.styleSectionKicker }}</div>
    <div class="weather-style-head">
      <div>
        <h3>{{ ANALYSIS_COPY.styleTitle }}</h3>
        <p>
          {{
            displayLayer.isImported
              ? ANALYSIS_COPY.staticImportedVector
              : displayLayer.isImportedRaster
                ? ANALYSIS_COPY.staticImportedRaster
                : hasAdvancedStyleControls
                  ? canEditPalette
                    ? ANALYSIS_COPY.styleHintLinked
                    : ANALYSIS_COPY.styleHintReadonly
                  : ANALYSIS_COPY.styleHintOpacityOnly
          }}
        </p>
      </div>
      <span v-if="isRealtimeWeatherLayer || canToggleParticleFlow" class="analysis-chip">{{
        windStyleChipLabel
      }}</span>
    </div>

    <div v-if="displayLayer.instanceId" class="layer-opacity-row">
      <span>{{ LAYERS_COPY.opacity }}</span>
      <input
        class="layer-opacity-slider"
        type="range"
        min="0"
        max="100"
        :value="Math.round(displayLayer.opacity * 100)"
        @input="handleLayerOpacityInput"
      />
      <strong>{{ Math.round(displayLayer.opacity * 100) }}%</strong>
    </div>

    <template v-if="styleFieldLabel || styleRangeMeta.hasRange">
      <div class="style-section-label">{{ LAYERS_COPY.sectionAppearance }}</div>
      <div v-if="styleFieldLabel" class="style-field-row">
        <span class="style-field-label">{{ LAYERS_COPY.fieldLabel }}</span>
        <strong>{{ styleFieldLabel }}</strong>
      </div>
    </template>

    <!-- 导入矢量就地样式 -->
    <div v-if="displayLayer.isImported" class="imported-vector-style">
      <label class="layer-style-row">
        <span>{{ LAYERS_COPY.vectorColor }}</span>
        <input
          type="color"
          :value="importedVectorStyle.color || importedVectorDefaultColor"
          @input="
            patchImportedVectorStyle({
              color: ($event.target as HTMLInputElement).value,
            })
          "
        />
      </label>
      <label class="layer-style-row">
        <span>{{ LAYERS_COPY.vectorWidth }}</span>
        <input
          type="range"
          min="0.5"
          max="8"
          step="0.5"
          :value="importedVectorStyle.width ?? IMPORTED_VECTOR_STYLE_DEFAULTS.width"
          @input="
            patchImportedVectorStyle({
              width: Number(($event.target as HTMLInputElement).value),
            })
          "
        />
        <strong>{{ importedVectorStyle.width ?? IMPORTED_VECTOR_STYLE_DEFAULTS.width }}</strong>
      </label>
      <label class="layer-style-row">
        <span>{{ LAYERS_COPY.vectorRadius }}</span>
        <input
          type="range"
          min="2"
          max="16"
          step="1"
          :value="importedVectorStyle.radius ?? IMPORTED_VECTOR_STYLE_DEFAULTS.radius"
          @input="
            patchImportedVectorStyle({
              radius: Number(($event.target as HTMLInputElement).value),
            })
          "
        />
        <strong>{{ importedVectorStyle.radius ?? IMPORTED_VECTOR_STYLE_DEFAULTS.radius }}</strong>
      </label>
      <label class="layer-style-row">
        <span>{{ LAYERS_COPY.vectorFillOpacity }}</span>
        <input
          type="range"
          min="0"
          max="100"
          :value="
            Math.round(
              (importedVectorStyle.fillOpacity ?? IMPORTED_VECTOR_STYLE_DEFAULTS.fillOpacity) * 100,
            )
          "
          @input="
            patchImportedVectorStyle({
              fillOpacity: Number(($event.target as HTMLInputElement).value) / 100,
            })
          "
        />
        <strong>
          {{
            Math.round(
              (importedVectorStyle.fillOpacity ?? IMPORTED_VECTOR_STYLE_DEFAULTS.fillOpacity) * 100,
            )
          }}%
        </strong>
      </label>
    </div>

    <!-- 导入栅格：CRS + 只读色带提示 -->
    <dl v-if="displayLayer.isImportedRaster" class="meta-list" style="margin-bottom: 0.55rem">
      <div>
        <dt>{{ ANALYSIS_COPY.metaCrs }}</dt>
        <dd>{{ displayLayer.importedRasterSourceCrs ?? '—' }}</dd>
      </div>
      <div v-if="displayLayer.importedFileName">
        <dt>{{ ANALYSIS_COPY.metaFile }}</dt>
        <dd>{{ displayLayer.importedFileName }}</dd>
      </div>
    </dl>

    <div
      v-if="displayLayer.instanceId && (isRealtimeWeatherLayer || canToggleParticleFlow)"
      class="weather-layer-controls"
    >
      <div v-if="canToggleParticleFlow" class="weather-layer-btn-row wind-mode-layout">
        <div class="wind-display-mode-seg" role="group" aria-label="风场显示模式">
          <button
            v-for="mode in ['particle', 'streamline', 'off'] as const"
            :key="mode"
            class="wind-mode-seg-btn"
            :class="{
              active: currentWindDisplayMode === mode,
              off: mode === 'off' && currentWindDisplayMode === 'off',
            }"
            :data-mode="mode"
            type="button"
            :disabled="mode !== 'off' && particleFlowButtonDisabled"
            :title="
              mode !== 'off' && particleFlowButtonDisabled
                ? '当前风场地图产物尚未就绪'
                : windDisplayModeLabel(mode)
            "
            @click="handleSetWindDisplayMode(mode)"
          >
            {{ windDisplayModeLabel(mode) }}
          </button>
        </div>
        <AppButton
          class="weather-visibility-btn"
          size="xs"
          variant="ghost"
          :title="displayLayer.visible ? '隐藏当前图层' : '显示当前图层'"
          @click="handleToggleLayerVisibility"
        >
          <span class="weather-layer-btn-text">{{
            displayLayer.visible ? '隐藏图层' : '显示图层'
          }}</span>
        </AppButton>
      </div>
      <AppButton
        v-else
        class="weather-visibility-btn"
        size="xs"
        variant="ghost"
        :title="displayLayer.visible ? '隐藏当前图层' : '显示当前图层'"
        @click="handleToggleLayerVisibility"
      >
        <span class="weather-layer-btn-text">{{
          displayLayer.visible ? '隐藏图层' : '显示图层'
        }}</span>
      </AppButton>
      <label v-if="isRealtimeWeatherLayer" class="weather-provider-row">
        <span class="weather-provider-label">天气数据源</span>
        <AppSelect
          v-model="selectedWeatherProvider"
          :disabled="weatherProvidersLoading"
          :title="weatherProvidersError || '自动按优先级选择已启用源；钉选后瓦片与点查均走该源'"
        >
          <option value="auto">{{ INSPECT_COPY.providerAuto }}</option>
          <option
            v-for="opt in weatherProviderOptions"
            :key="opt.provider_id"
            :value="opt.provider_id"
            :disabled="!opt.enabled"
          >
            {{ weatherProviderOptionLabel(opt) }}
          </option>
        </AppSelect>
      </label>
      <p
        v-if="isRealtimeWeatherLayer && selectedWeatherProviderHint"
        class="weather-provider-error"
      >
        {{ selectedWeatherProviderHint }}
      </p>
      <p
        v-else-if="isRealtimeWeatherLayer && selectedWeatherProviderSparse"
        class="weather-provider-error"
      >
        点查可用；瓦片将回落 dense 源（Open-Meteo）
      </p>
      <p v-if="isRealtimeWeatherLayer && weatherProvidersError" class="weather-provider-error">
        {{ weatherProvidersError }}
      </p>
      <div v-if="isRealtimeWeatherLayer" class="weather-layer-btn-row smooth-render-row">
        <span class="smooth-render-label">平滑渲染</span>
        <button
          class="smooth-toggle-switch"
          :class="{ active: smoothRendering }"
          type="button"
          role="switch"
          :aria-checked="smoothRendering"
          title="开：连续数值面（双线性插值）；关：网格色块"
          @click="setSmoothRendering(!smoothRendering)"
        >
          <span class="smooth-toggle-knob"></span>
        </button>
        <span class="smooth-render-hint">{{ smoothRendering ? '连续数值面' : '网格色块' }}</span>
      </div>
    </div>

    <div v-if="styleRenderHint" class="weather-legend-row">
      <span class="weather-legend-label">图例</span>
      <span class="weather-legend-meta">
        {{ styleRenderHint.primary_metric }} · {{ normalizedUnitLabel }}
      </span>
    </div>
    <div v-if="styleRenderHint && weatherLegendGradient" class="weather-legend-gradient-wrap">
      <div class="weather-legend-gradient" :style="{ background: weatherLegendGradient }"></div>
      <div class="weather-legend-gradient-ticks">
        <span
          v-for="stop in weatherLegendStops"
          :key="`tick-${stop.value}`"
          class="weather-legend-tick"
          >{{ stop.label }}</span
        >
      </div>
      <p v-if="legendExplainer" class="weather-legend-explainer">{{ legendExplainer }}</p>
    </div>
    <div v-else-if="styleRenderHint" class="weather-legend-strip">
      <div v-for="stop in weatherLegendStops" :key="`${stop.value}`" class="weather-legend-stop">
        <span class="weather-legend-swatch" :style="{ background: stop.color }"></span>
        <span>{{ stop.label }}</span>
      </div>
    </div>

    <div v-if="styleRangeMeta.hasRange" class="style-range-block">
      <div class="style-section-label">{{ LAYERS_COPY.sectionRange }}</div>
      <div class="style-range-grid">
        <div v-if="styleRangeMeta.unit" class="style-range-cell">
          <span>{{ LAYERS_COPY.metricUnit }}</span>
          <strong>{{ styleRangeMeta.unit }}</strong>
        </div>
        <div class="style-range-cell">
          <span>min</span>
          <input
            v-if="canEditPalette"
            v-model="rangeEditVmin"
            class="style-range-input"
            type="number"
            :step="rangeInputStep"
            title="值域下限"
          />
          <strong v-else>{{ styleRangeMeta.vmin }}</strong>
        </div>
        <div class="style-range-cell">
          <span>max</span>
          <input
            v-if="canEditPalette"
            v-model="rangeEditVmax"
            class="style-range-input"
            type="number"
            :step="rangeInputStep"
            title="值域上限"
          />
          <strong v-else>{{ styleRangeMeta.vmax }}</strong>
        </div>
      </div>
      <div v-if="canEditPalette" class="style-nodata-row">
        <span class="style-section-label">无效值 (NaN)</span>
        <AppSelect
          v-model="nodataModeValue"
          size="sm"
          :options="[
            { label: '透明', value: 'transparent' },
            { label: '固色填充', value: 'solid' },
          ]"
          title="无效像元显示"
        />
        <input
          v-if="nodataModeValue === 'solid'"
          v-model="nodataColorValue"
          class="style-nodata-color"
          type="color"
          title="NaN 填充色"
        />
      </div>
    </div>

    <div
      v-if="styleRenderHint || canEditPalette"
      class="palette-selector"
      :class="{ 'is-readonly': !canEditPalette }"
    >
      <div
        v-if="paletteDropdownOpen && canEditPalette"
        class="palette-backdrop"
        @click="paletteDropdownOpen = false"
      ></div>
      <button
        class="palette-trigger"
        type="button"
        :disabled="!canEditPalette"
        :title="canEditPalette ? '切换地图配色' : '无源预渲染栅格，不支持前端改色'"
        @click="togglePaletteDropdown"
      >
        <span class="palette-trigger-label">配色方案</span>
        <span class="palette-trigger-preview">
          <span
            v-for="(c, i) in paletteOptions.find((p) => p.id === currentPaletteId)?.colors ?? []"
            :key="i"
            class="palette-trigger-dot"
            :style="{ background: c }"
          ></span>
        </span>
        <span class="palette-trigger-name">{{
          paletteOptions.find((p) => p.id === currentPaletteId)?.label ?? '默认'
        }}</span>
        <span
          v-if="canEditPalette"
          class="palette-trigger-arrow"
          :class="{ open: paletteDropdownOpen }"
          >▾</span
        >
      </button>
      <div
        v-if="paletteDropdownOpen && canEditPalette"
        ref="paletteDropdownRef"
        class="palette-dropdown"
        :class="{ 'palette-dropdown--up': dropdownOpenUp }"
      >
        <button
          v-for="opt in paletteOptions"
          :key="opt.id"
          class="palette-option"
          :class="{ active: paletteIdsEqual(opt.id, currentPaletteId) }"
          type="button"
          @click="handleSelectPalette(opt.id)"
        >
          <span
            class="palette-option-gradient"
            :style="{ background: `linear-gradient(90deg, ${opt.colors.join(', ')})` }"
          ></span>
          <span class="palette-option-label">{{ opt.label }}</span>
          <span class="palette-option-type">{{
            opt.type === 'diverging' ? '发散' : opt.type === 'qualitative' ? '定性' : '递进'
          }}</span>
        </button>
        <button
          v-if="displayLayer?.paletteOverride"
          class="palette-option palette-reset"
          type="button"
          @click="handleSelectPalette(weatherRenderHint?.palette ?? '')"
        >
          <span class="palette-option-label">恢复默认配色</span>
        </button>
      </div>
      <p v-if="!canEditPalette" class="palette-readonly-hint">无可读源的预渲染产物，配色只读</p>
    </div>

    <div class="weather-style-meta">
      <span v-if="isRealtimeWeatherLayer && tileStats">
        瓦片：已缓存 {{ tileStats.cached }} / 可视 {{ tileStats.visible }} / 加载中
        {{ tileStats.pending }}
      </span>
      <span v-else-if="isRealtimeWeatherLayer || jobLayer">
        {{ hasWeatherLayerAsset ? '地图产物已挂载' : '尚无地图产物' }}
      </span>
    </div>

    <ul v-if="styleRenderHint?.notes?.length" class="weather-note-list">
      <li v-for="note in styleRenderHint.notes" :key="note">{{ note }}</li>
    </ul>
  </section>

  <div v-show="true" v-if="!hasLayerStyleSection" class="analysis-sparse-card">
    <p>{{ ANALYSIS_COPY.styleTabEmpty }}</p>
  </div>
</template>

<style scoped src="./InfoPanel.styles.css"></style>
