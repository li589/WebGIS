<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { DATA_COPY } from '../../ui-copy'
import AppSelect from '../../components/ui/AppSelect.vue'
import {
  exportLayer,
  exportLayersBatch,
  type ExportFormat,
  type ExportOptions,
} from '../adapters/export'
import {
  fetchExportEncodings,
  fetchImportedLayerGeojson,
  type ExportEncodingOption,
} from '../core/api'
import { dataWorkspaceExportTime, dataWorkspaceLayerId } from '../core/workspace-store'
import { useLayersStore } from '../../stores/layers'
import { useLogStore } from '../../stores/log'
import type { ActiveLayer } from '../../stores/layers/types'
import { resolveExportBasename } from '../../stores/layers/layer-naming'

defineProps<{
  /** 嵌入数据工作台时不渲染全屏遮罩 */
  embedded?: boolean
}>()

const emit = defineEmits<{ close: [] }>()

const layersStore = useLayersStore()
const logStore = useLogStore()

const selectedIds = ref<string[]>([])
const selectedTime = ref<string>('')
/** single = 单文件；multi = 所选时刻打 zip */
const timeExportMode = ref<'single' | 'multi'>('single')
const selectedTimes = ref<string[]>([])
const vectorFormat = ref('geojson')
const rasterFormat = ref('geotiff')
const textEncoding = ref('auto')
const clipToMap = ref(false)
const outputCrs = ref('')
const selectedFields = ref<string[]>([])
const encodingOptions = ref<ExportEncodingOption[]>([
  { id: 'auto', label: '自动（跟导入源编码）' },
  { id: 'utf-8', label: 'UTF-8' },
  { id: 'utf-8-sig', label: 'UTF-8 BOM（Excel）' },
  { id: 'gbk', label: 'GBK' },
  { id: 'gb18030', label: 'GB18030' },
  { id: 'big5', label: 'Big5' },
  { id: 'cp1252', label: 'Windows-1252' },
])
const busy = ref(false)
const progress = ref<number | null>(null)
const msg = ref('')
const err = ref('')

const importedLayers = computed(() =>
  layersStore.activeLayers.filter((l) => l.importedVector || l.importedRaster),
)

const selectedLayers = computed(() =>
  importedLayers.value.filter((l) => selectedIds.value.includes(l.instanceId)),
)

const hasVector = computed(() => selectedLayers.value.some((l) => l.importedVector))
const hasRaster = computed(() => selectedLayers.value.some((l) => l.importedRaster))
const needsTextEncoding = computed(
  () => hasVector.value && (vectorFormat.value === 'csv' || vectorFormat.value === 'shp-zip'),
)

function machineIdOf(layer: ActiveLayer): string {
  return (
    resolveExportBasename({
      catalogId: layer.catalogId,
      overlayLayerId: layer.importedRaster?.overlayLayerId,
      backendLayerId: layer.importedVector?.backendLayerId,
      sourceFilename: layer.importedVector?.fileName ?? layer.importedRaster?.fileName,
      displayName: layer.name,
    }) ||
    layer.catalogId ||
    layer.instanceId
  )
}

function isWorkflowProduct(layer: ActiveLayer): boolean {
  return Boolean(layer.importedRaster && layer.runGroupProductTag)
}

function timeListOf(layer: ActiveLayer | undefined): string[] {
  return layer?.importedRaster?.timeList?.filter(Boolean) ?? []
}

/** 多选栅格的公共 time_list；单选则用该层全部时刻 */
const availableTimes = computed(() => {
  const rasters = selectedLayers.value.filter((l) => l.importedRaster)
  if (!rasters.length) return [] as string[]
  if (rasters.length === 1) return timeListOf(rasters[0])
  let common: string[] | null = null
  for (const layer of rasters) {
    const times = timeListOf(layer)
    if (!times.length) return []
    common = common == null ? [...times] : common.filter((t) => times.includes(t))
  }
  return common ?? []
})

const showTimePicker = computed(() => availableTimes.value.length > 0)

const availableFields = computed(() => {
  const names = new Set<string>()
  for (const layer of selectedLayers.value) {
    const feats = layer.importedVector?.geojson?.features
    if (!feats?.length) continue
    const sample = feats.slice(0, 40)
    for (const f of sample) {
      const props = f.properties || {}
      for (const k of Object.keys(props)) names.add(k)
    }
  }
  return [...names].sort((a, b) => a.localeCompare(b))
})

const showFieldPicker = computed(() => hasVector.value && availableFields.value.length > 0)

function defaultTimeForLayer(layer: ActiveLayer | undefined): string {
  const times = timeListOf(layer)
  if (!times.length) return ''
  const preferred = dataWorkspaceExportTime.value
  if (preferred && times.includes(preferred)) return preferred
  const eff = layer?.importedRaster?.effectiveTimeLabel
  if (eff) {
    const hit = times.find((t) => eff === t || eff.startsWith(t))
    if (hit) return hit
  }
  return times[times.length - 1] ?? ''
}

onMounted(async () => {
  try {
    const list = await fetchExportEncodings()
    if (list.length) encodingOptions.value = list
  } catch {
    /* 使用本地默认列表 */
  }
})

watch(
  importedLayers,
  (layers) => {
    const preferredId = dataWorkspaceLayerId.value
    if (preferredId && layers.some((l) => l.instanceId === preferredId)) {
      selectedIds.value = [preferredId]
    } else if (!selectedIds.value.length && layers[0]) {
      selectedIds.value = [layers[0].instanceId]
    }
    const alive = new Set(layers.map((l) => l.instanceId))
    selectedIds.value = selectedIds.value.filter((id) => alive.has(id))
  },
  { immediate: true },
)

watch(
  [selectedLayers, dataWorkspaceExportTime, availableTimes],
  () => {
    if (availableTimes.value.length) {
      const preferred = dataWorkspaceExportTime.value
      const def =
        (preferred && availableTimes.value.includes(preferred)
          ? preferred
          : selectedLayers.value.length === 1
            ? defaultTimeForLayer(selectedLayers.value[0])
            : availableTimes.value[availableTimes.value.length - 1]) || ''
      selectedTime.value = def
      if (!selectedTimes.value.length && def) {
        selectedTimes.value = [def]
      } else {
        const allowed = new Set(availableTimes.value)
        selectedTimes.value = selectedTimes.value.filter((t) => allowed.has(t))
      }
    } else {
      selectedTime.value = ''
      selectedTimes.value = []
      timeExportMode.value = 'single'
    }
  },
  { immediate: true },
)

watch(availableFields, (fields) => {
  const allow = new Set(fields)
  selectedFields.value = selectedFields.value.filter((f) => allow.has(f))
})

function toggle(id: string) {
  if (selectedIds.value.includes(id)) {
    selectedIds.value = selectedIds.value.filter((x) => x !== id)
  } else {
    selectedIds.value = [...selectedIds.value, id]
  }
}

function selectAll() {
  selectedIds.value = importedLayers.value.map((l) => l.instanceId)
}

function clearSelection() {
  selectedIds.value = []
}

function toggleExportTime(t: string) {
  if (selectedTimes.value.includes(t)) {
    selectedTimes.value = selectedTimes.value.filter((x) => x !== t)
  } else {
    selectedTimes.value = [...selectedTimes.value, t]
  }
}

function selectAllExportTimes() {
  selectedTimes.value = [...availableTimes.value]
}

function clearExportTimes() {
  selectedTimes.value = []
}

function toggleField(name: string) {
  if (selectedFields.value.includes(name)) {
    selectedFields.value = selectedFields.value.filter((x) => x !== name)
  } else {
    selectedFields.value = [...selectedFields.value, name]
  }
}

function selectAllFields() {
  selectedFields.value = [...availableFields.value]
}

function clearFields() {
  selectedFields.value = []
}

function buildSharedExportOptions(): ExportOptions {
  const encoding = textEncoding.value || 'auto'
  const opts: ExportOptions = { encoding }
  if (showTimePicker.value) {
    if (timeExportMode.value === 'multi' && selectedTimes.value.length > 0) {
      const picked = selectedTimes.value.filter((t) => availableTimes.value.includes(t))
      if (picked.length > 1) {
        opts.times = picked
        opts.time = null
      } else if (picked.length === 1) {
        opts.time = picked[0]!
      }
    } else if (selectedTime.value) {
      opts.time = selectedTime.value
    }
  }
  if (clipToMap.value) {
    const bbox = layersStore.currentMapBBox
    if (bbox && Number.isFinite(bbox.west) && Number.isFinite(bbox.south)) {
      opts.bbox = {
        west: bbox.west,
        south: bbox.south,
        east: bbox.east,
        north: bbox.north,
        crs: bbox.crs || 'EPSG:4326',
      }
    }
  }
  if (outputCrs.value.trim()) {
    opts.outputCrs = outputCrs.value.trim()
  }
  if (hasVector.value && selectedFields.value.length) {
    opts.fields = [...selectedFields.value]
  }
  return opts
}

function exportOptsFor(layer: ActiveLayer): ExportOptions {
  const shared = buildSharedExportOptions()
  const times = timeListOf(layer)
  if (!times.length) return shared
  if (shared.times?.length || shared.time) return shared
  return {
    ...shared,
    time: defaultTimeForLayer(layer) || times[times.length - 1] || null,
  }
}

async function ensureFullVectorData(layers: ActiveLayer[]): Promise<void> {
  for (const layer of layers) {
    if (!layer.importedVector?.truncated || !layer.importedVector.backendLayerId) continue
    msg.value = DATA_COPY.exportLoadFullFirst
    const gj = await fetchImportedLayerGeojson(layer.importedVector.backendLayerId, false)
    layersStore.updateImportedVectorGeojson(layer.instanceId, gj, {
      featureCount: gj.features.length,
      truncated: false,
    })
  }
}

async function doExport() {
  if (!selectedLayers.value.length) {
    err.value = DATA_COPY.emptyExport
    return
  }
  if (
    showTimePicker.value &&
    timeExportMode.value === 'multi' &&
    selectedTimes.value.length === 0
  ) {
    err.value = '请至少选择一个导出时刻'
    return
  }
  if (clipToMap.value && !layersStore.currentMapBBox) {
    err.value = '当前无地图范围，无法裁剪'
    return
  }
  busy.value = true
  progress.value = 0
  msg.value = DATA_COPY.processing
  err.value = ''
  try {
    const list = selectedLayers.value
    await ensureFullVectorData(list.filter((l) => l.importedVector))
    const allVector = list.every((l) => l.importedVector)
    const allRaster = list.every((l) => l.importedRaster)
    const shared = buildSharedExportOptions()

    if (list.length >= 2 && (allVector || allRaster)) {
      const raw = allRaster ? rasterFormat.value : vectorFormat.value
      const format = (
        raw === 'geotiff' ? 'tif' : raw === 'netcdf' ? 'nc' : raw === 'matlab' ? 'mat' : raw
      ) as ExportFormat
      try {
        await exportLayersBatch(
          list,
          format,
          (p, m) => {
            progress.value = p
            msg.value = m
          },
          shared,
        )
        msg.value = `已导出 ${list.length} 个图层`
        logStore.logOperation('export-batch', `批导出 ${list.length} 层`, format)
        return
      } catch (batchErr) {
        // 批失败则逐层并汇总错误
        const errors: string[] = []
        let ok = 0
        for (let i = 0; i < list.length; i++) {
          const layer = list[i]!
          try {
            await exportLayer(layer, format, exportOptsFor(layer))
            ok += 1
          } catch (e) {
            errors.push(`${layer.name}: ${e instanceof Error ? e.message : String(e)}`)
          }
          progress.value = (i + 1) / list.length
        }
        if (ok && !errors.length) {
          msg.value = `已导出 ${ok} 个图层`
        } else if (ok) {
          msg.value = `成功 ${ok} 个`
          err.value = `失败 ${errors.length}：${errors[0]}`
        } else {
          err.value = errors[0] || (batchErr instanceof Error ? batchErr.message : String(batchErr))
          msg.value = ''
        }
        return
      }
    }

    let ok = 0
    const errors: string[] = []
    for (let i = 0; i < list.length; i++) {
      const layer = list[i]!
      const format = (
        layer.importedRaster
          ? rasterFormat.value === 'geotiff'
            ? 'tif'
            : rasterFormat.value === 'netcdf'
              ? 'nc'
              : rasterFormat.value === 'matlab'
                ? 'mat'
                : rasterFormat.value
          : vectorFormat.value
      ) as ExportFormat
      const opts = exportOptsFor(layer)
      try {
        await exportLayer(layer, format, opts)
        ok += 1
        const timeTag = opts.times?.length
          ? `@${opts.times.length}times`
          : opts.time
            ? `@${opts.time}`
            : ''
        logStore.logOperation(
          'export-layer',
          `导出 ${layer.name}`,
          `${format}/${opts.encoding}${timeTag}`,
        )
      } catch (e) {
        errors.push(`${layer.name}: ${e instanceof Error ? e.message : String(e)}`)
      }
      progress.value = (i + 1) / list.length
      msg.value = `已处理 ${i + 1}/${list.length}`
    }
    if (ok && !errors.length) {
      const stamp =
        timeExportMode.value === 'multi' && selectedTimes.value.length > 1
          ? ` · ${selectedTimes.value.length} 个时刻 (zip)`
          : selectedTime.value
            ? ` · ${selectedTime.value}`
            : ''
      msg.value = `已导出 ${ok} 个图层${stamp}`
    } else if (ok) {
      msg.value = `成功 ${ok} 个`
      err.value = `失败 ${errors.length}：${errors.join('；')}`
    } else {
      err.value = errors.join('；') || '导出失败'
      msg.value = ''
    }
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e)
    msg.value = ''
  } finally {
    busy.value = false
    progress.value = null
  }
}
</script>

<template>
  <div
    :class="embedded ? 'export-embedded-root' : 'data-panel-overlay'"
    @click.self="!embedded && emit('close')"
  >
    <div
      class="data-panel"
      :class="{ 'as-embedded': embedded }"
      role="region"
      :aria-label="DATA_COPY.exportTitle"
    >
      <header v-if="!embedded" class="data-panel-header">
        <span class="header-title">{{ DATA_COPY.exportTitle }}</span>
        <button class="close-btn" type="button" :title="DATA_COPY.close" @click="emit('close')">
          ✕
        </button>
      </header>

      <p class="tab-hint">{{ DATA_COPY.exportHint }}</p>

      <div class="data-panel-body">
        <p v-if="!importedLayers.length" class="empty">{{ DATA_COPY.emptyExport }}</p>
        <template v-else>
          <div class="sel-actions">
            <button type="button" class="link-btn" @click="selectAll">
              {{ DATA_COPY.selectAll }}
            </button>
            <button type="button" class="link-btn" @click="clearSelection">
              {{ DATA_COPY.clearSelection }}
            </button>
            <span class="sel-count">已选 {{ selectedIds.length }}</span>
          </div>
          <ul class="layer-list">
            <li v-for="l in importedLayers" :key="l.instanceId">
              <label class="check-row">
                <input
                  type="checkbox"
                  :checked="selectedIds.includes(l.instanceId)"
                  @change="toggle(l.instanceId)"
                />
                <span class="layer-main">
                  <span class="layer-name">{{ l.name }}</span>
                  <span class="layer-id"
                    >{{ DATA_COPY.exportMachineId }}: {{ machineIdOf(l) }}</span
                  >
                </span>
                <em>
                  <template v-if="isWorkflowProduct(l)"
                    >{{ DATA_COPY.exportWorkflowProduct }} ·
                  </template>
                  {{ l.importedRaster ? '栅格' : '矢量'
                  }}{{
                    l.importedRaster?.timeList?.length
                      ? ` · ${l.importedRaster.timeList.length} 块`
                      : ''
                  }}
                </em>
              </label>
            </li>
          </ul>
          <label v-if="hasVector">
            矢量 {{ DATA_COPY.exportFormat }}
            <AppSelect
              v-model="vectorFormat"
              :options="[
                { label: 'GeoJSON', value: 'geojson' },
                { label: 'CSV', value: 'csv' },
                { label: 'SHP (zip)', value: 'shp-zip' },
              ]"
            />
          </label>
          <label v-if="hasRaster">
            栅格 {{ DATA_COPY.exportFormat }}
            <AppSelect
              v-model="rasterFormat"
              :options="[
                { label: DATA_COPY.exportRasterGeotiff, value: 'geotiff' },
                { label: DATA_COPY.exportRasterMat, value: 'mat' },
                { label: DATA_COPY.exportRasterNc, value: 'netcdf' },
                { label: DATA_COPY.exportRasterPng, value: 'png' },
              ]"
            />
          </label>
          <fieldset v-if="showTimePicker" class="time-export">
            <legend>
              {{ selectedLayers.length > 1 ? DATA_COPY.exportTimeCommon : DATA_COPY.exportTime }}
            </legend>
            <div class="time-mode-row">
              <label class="radio-row">
                <input v-model="timeExportMode" type="radio" value="single" />
                {{ DATA_COPY.exportTimeModeSingle }}
              </label>
              <label class="radio-row">
                <input v-model="timeExportMode" type="radio" value="multi" />
                {{ DATA_COPY.exportTimeModeMulti }}
              </label>
            </div>
            <AppSelect
              v-if="timeExportMode === 'single'"
              v-model="selectedTime"
              :options="availableTimes.map((t) => ({ label: t, value: t }))"
            />
            <template v-else>
              <div class="sel-actions">
                <button type="button" class="link-btn" @click="selectAllExportTimes">
                  {{ DATA_COPY.exportTimeSelectAll }}
                </button>
                <button type="button" class="link-btn" @click="clearExportTimes">
                  {{ DATA_COPY.exportTimeClear }}
                </button>
                <span class="sel-count">已选 {{ selectedTimes.length }}</span>
              </div>
              <ul class="time-list">
                <li v-for="t in availableTimes" :key="t">
                  <label class="check-row">
                    <input
                      type="checkbox"
                      :checked="selectedTimes.includes(t)"
                      @change="toggleExportTime(t)"
                    />
                    <span>{{ t }}</span>
                  </label>
                </li>
              </ul>
            </template>
            <p class="enc-hint">{{ DATA_COPY.exportTimeHint }}</p>
          </fieldset>
          <label class="check-inline">
            <input v-model="clipToMap" type="checkbox" />
            {{ DATA_COPY.exportClipMap }}
          </label>
          <label>
            {{ DATA_COPY.exportOutputCrs }}
            <AppSelect
              v-model="outputCrs"
              :options="[
                { label: DATA_COPY.exportOutputCrsSource, value: '' },
                { label: 'EPSG:4326 (WGS84)', value: 'EPSG:4326' },
                { label: 'EPSG:3857 (Web Mercator)', value: 'EPSG:3857' },
              ]"
            />
          </label>
          <fieldset v-if="showFieldPicker" class="time-export">
            <legend>{{ DATA_COPY.exportFields }}</legend>
            <div class="sel-actions">
              <button type="button" class="link-btn" @click="selectAllFields">
                {{ DATA_COPY.exportFieldsAll }}
              </button>
              <button type="button" class="link-btn" @click="clearFields">
                {{ DATA_COPY.exportFieldsClear }}
              </button>
              <span class="sel-count">已选 {{ selectedFields.length || '全部' }}</span>
            </div>
            <ul class="time-list">
              <li v-for="f in availableFields" :key="f">
                <label class="check-row">
                  <input
                    type="checkbox"
                    :checked="selectedFields.includes(f)"
                    @change="toggleField(f)"
                  />
                  <span>{{ f }}</span>
                </label>
              </li>
            </ul>
            <p class="enc-hint">{{ DATA_COPY.exportFieldsHint }}</p>
          </fieldset>
          <label v-if="needsTextEncoding">
            {{ DATA_COPY.exportEncoding }}
            <AppSelect
              v-model="textEncoding"
              :options="encodingOptions.map((opt) => ({ label: opt.label, value: opt.id }))"
            />
          </label>
          <p v-if="needsTextEncoding" class="enc-hint">{{ DATA_COPY.exportEncodingHint }}</p>
          <button
            class="primary-btn"
            type="button"
            :disabled="
              busy ||
              !selectedIds.length ||
              (showTimePicker && timeExportMode === 'multi' && !selectedTimes.length)
            "
            @click="doExport"
          >
            {{ DATA_COPY.doExport }}
          </button>
        </template>
      </div>

      <footer class="data-panel-footer">
        <div v-if="progress != null" class="progress-bar">
          <div class="progress-fill" :style="{ width: `${Math.round(progress * 100)}%` }" />
        </div>
        <p v-if="err" class="msg error">{{ err }}</p>
        <p v-else-if="msg" class="msg">{{ msg }}</p>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.export-embedded-root {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
}
.data-panel.as-embedded {
  width: 100%;
  max-height: none;
  height: 100%;
  border: none;
  box-shadow: none;
  background: transparent;
  border-radius: 0;
}
.data-panel-overlay {
  position: fixed;
  inset: 0;
  z-index: 10040;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 3.5vh 1rem 2vh;
  overflow: auto;
  background: rgba(4, 10, 18, 0.55);
}
.data-panel {
  width: min(28rem, calc(100vw - 2rem));
  max-height: min(78vh, 40rem);
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  border-radius: 0.7rem;
  background: rgba(8, 17, 31, 0.98);
  border: 1px solid var(--border-default);
  box-shadow: 0 18px 48px rgba(1, 8, 16, 0.45);
  color: var(--text-primary);
}
.data-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
  flex-shrink: 0;
  padding: 0.62rem 0.8rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.1);
}
.header-title {
  font-size: var(--font-size-caption);
  font-weight: 600;
}
.close-btn {
  flex: none;
  width: 1.7rem;
  height: 1.7rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(136, 192, 255, 0.22);
  border-radius: 0.38rem;
  background: rgba(4, 12, 23, 0.72);
  color: var(--text-primary);
  cursor: pointer;
  font-size: var(--font-size-caption);
  line-height: 1;
}
.close-btn:hover {
  border-color: rgba(90, 213, 255, 0.4);
  color: var(--accent);
}
.tab-hint {
  margin: 0.5rem 0.9rem 0;
  font-size: var(--font-size-caption);
  color: #6a8094;
  line-height: 1.4;
}
.data-panel-body {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  padding: 0.75rem 0.9rem;
  min-height: 0;
  overflow: auto;
}
.empty {
  margin: 0;
  font-size: var(--font-size-caption);
  color: #8aa0b4;
}
.sel-actions {
  display: flex;
  align-items: center;
  gap: 0.55rem;
}
.link-btn {
  border: none;
  background: transparent;
  color: var(--accent);
  font: inherit;
  font-size: var(--font-size-caption);
  cursor: pointer;
  padding: 0;
}
.sel-count {
  margin-left: auto;
  font-size: var(--font-size-caption);
  color: #6a8094;
}
.enc-hint {
  margin: -0.15rem 0 0;
  font-size: var(--font-size-caption);
  color: #7a91a8;
  line-height: 1.35;
}
.time-export {
  margin: 0;
  padding: 0.45rem 0.55rem 0.5rem;
  border: 1px solid rgba(136, 192, 255, 0.12);
  border-radius: 0.4rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.time-export legend {
  padding: 0 0.25rem;
  font-size: var(--font-size-caption);
  color: #9bb4c8;
}
.time-mode-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
}
.radio-row {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-size: var(--font-size-caption);
  color: var(--text-primary);
  cursor: pointer;
}
.check-inline {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 0.4rem;
  font-size: var(--font-size-caption);
  color: var(--text-primary);
  cursor: pointer;
}
.time-list {
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: 8.5rem;
  overflow: auto;
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: 0.35rem;
}
.layer-list {
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: 12rem;
  overflow: auto;
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: 0.4rem;
}
.check-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.32rem 0.5rem;
  font-size: var(--font-size-caption);
  color: var(--text-primary);
  cursor: pointer;
}
.check-row:hover {
  background: rgba(10, 132, 255, 0.08);
}
.layer-main {
  display: flex;
  flex-direction: column;
  gap: 0.08rem;
  min-width: 0;
}
.layer-name {
  font-size: var(--font-size-caption);
}
.layer-id {
  font-size: var(--font-size-caption);
  color: #6a8094;
  word-break: break-all;
}
.check-row em {
  margin-left: auto;
  font-style: normal;
  color: #6a8094;
  font-size: var(--font-size-caption);
  flex-shrink: 0;
}
label:not(.check-row):not(.radio-row):not(.check-inline) {
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
  font-size: var(--font-size-caption);
  color: #8aa0b4;
}
select {
  border: 1px solid rgba(136, 192, 255, 0.14);
  border-radius: 0.34rem;
  padding: 0.32rem 0.4rem;
  background: rgba(4, 12, 23, 0.7);
  color: var(--text-primary);
  font: inherit;
  font-size: var(--font-size-caption);
}
.primary-btn {
  width: fit-content;
  border: 1px solid rgba(90, 213, 255, 0.35);
  border-radius: 0.42rem;
  padding: 0.36rem 0.72rem;
  background: rgba(10, 132, 255, 0.22);
  color: #a8e8ff;
  font: inherit;
  font-size: var(--font-size-caption);
  cursor: pointer;
}
.primary-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.data-panel-footer {
  padding: 0.45rem 0.9rem 0.7rem;
  border-top: 1px solid rgba(136, 192, 255, 0.1);
}
.progress-bar {
  height: 0.28rem;
  border-radius: 999px;
  background: rgba(136, 192, 255, 0.12);
  overflow: hidden;
  margin-bottom: 0.35rem;
}
.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #0a84ff, var(--accent));
}
.msg {
  margin: 0;
  font-size: var(--font-size-caption);
  color: #9ec4e0;
}
.msg.error {
  color: #ffb0b0;
}
</style>
