<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { DATA_COPY } from '../../ui-copy'
import { exportLayer, exportLayersBatch, type ExportFormat } from '../adapters/export'
import { fetchExportEncodings, type ExportEncodingOption } from '../core/api'
import { openDataWorkspace } from '../core/workspace-store'
import { useLayersStore } from '../../stores/layers'
import { useLogStore } from '../../stores/log'

defineProps<{
  /** 嵌入数据工作台时不渲染全屏遮罩 */
  embedded?: boolean
}>()

const emit = defineEmits<{ close: [] }>()

const layersStore = useLayersStore()
const logStore = useLogStore()

const selectedIds = ref<string[]>([])
const vectorFormat = ref('geojson')
const rasterFormat = ref('geotiff')
const textEncoding = ref('auto')
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
    if (!selectedIds.value.length && layers[0]) {
      selectedIds.value = [layers[0].instanceId]
    }
    // 清理已删除图层
    const alive = new Set(layers.map((l) => l.instanceId))
    selectedIds.value = selectedIds.value.filter((id) => alive.has(id))
  },
  { immediate: true },
)

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

async function doExport() {
  if (!selectedLayers.value.length) {
    err.value = DATA_COPY.emptyExport
    return
  }
  busy.value = true
  progress.value = 0
  msg.value = DATA_COPY.processing
  err.value = ''
  try {
    const list = selectedLayers.value
    const allVector = list.every((l) => l.importedVector)
    const allRaster = list.every((l) => l.importedRaster)
    const encOpts = { encoding: textEncoding.value || 'auto' }
    if (list.length >= 2 && (allVector || allRaster)) {
      const raw = allRaster ? rasterFormat.value : vectorFormat.value
      const format = (raw === 'geotiff' ? 'tif' : raw === 'netcdf' ? 'nc' : raw) as ExportFormat
      await exportLayersBatch(
        list,
        format,
        (p, m) => {
          progress.value = p
          msg.value = m
        },
        encOpts,
      )
      msg.value = `已批导出 ${list.length} 个图层`
      logStore.logOperation(
        'export-batch',
        `批导出 ${list.length} 层`,
        `${format}/${encOpts.encoding}`,
      )
      openDataWorkspace({ tab: 'jobs' })
      return
    }
    let ok = 0
    const errors: string[] = []
    for (let i = 0; i < list.length; i++) {
      const layer = list[i]!
      const format = (
        layer.importedRaster ? rasterFormat.value : vectorFormat.value
      ) as ExportFormat
      try {
        await exportLayer(layer, format, encOpts)
        ok += 1
        logStore.logOperation('export-layer', `导出 ${layer.name}`, `${format}/${encOpts.encoding}`)
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
      err.value = errors[0] || '导出失败'
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
                <span>{{ l.name }}</span>
                <em>{{ l.importedRaster ? '栅格' : '矢量' }}</em>
              </label>
            </li>
          </ul>
          <label v-if="hasVector">
            矢量 {{ DATA_COPY.exportFormat }}
            <select v-model="vectorFormat">
              <option value="geojson">GeoJSON</option>
              <option value="csv">CSV</option>
              <option value="shp-zip">SHP (zip)</option>
            </select>
          </label>
          <label v-if="hasRaster">
            栅格 {{ DATA_COPY.exportFormat }}
            <select v-model="rasterFormat">
              <option value="geotiff">GeoTIFF</option>
              <option value="netcdf">NetCDF</option>
              <option value="png">预览 PNG</option>
            </select>
          </label>
          <label v-if="needsTextEncoding">
            {{ DATA_COPY.exportEncoding }}
            <select v-model="textEncoding">
              <option v-for="opt in encodingOptions" :key="opt.id" :value="opt.id">
                {{ opt.label }}
              </option>
            </select>
          </label>
          <p v-if="needsTextEncoding" class="enc-hint">{{ DATA_COPY.exportEncodingHint }}</p>
          <button
            class="primary-btn"
            type="button"
            :disabled="busy || !selectedIds.length"
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
  max-height: min(70vh, 32rem);
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  border-radius: 0.7rem;
  background: rgba(8, 17, 31, 0.98);
  border: 1px solid rgba(136, 192, 255, 0.16);
  box-shadow: 0 18px 48px rgba(1, 8, 16, 0.45);
  color: #d8e6f5;
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
  font-size: 0.76rem;
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
  color: #d8e6f5;
  cursor: pointer;
  font-size: 0.78rem;
  line-height: 1;
}
.close-btn:hover {
  border-color: rgba(90, 213, 255, 0.4);
  color: #5ad5ff;
}
.tab-hint {
  margin: 0.5rem 0.9rem 0;
  font-size: 0.54rem;
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
  font-size: 0.62rem;
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
  color: #5ad5ff;
  font: inherit;
  font-size: 0.56rem;
  cursor: pointer;
  padding: 0;
}
.sel-count {
  margin-left: auto;
  font-size: 0.52rem;
  color: #6a8094;
}
.enc-hint {
  margin: -0.15rem 0 0;
  font-size: 0.5rem;
  color: #7a91a8;
  line-height: 1.35;
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
  font-size: 0.58rem;
  color: #d8e6f5;
  cursor: pointer;
}
.check-row:hover {
  background: rgba(10, 132, 255, 0.08);
}
.check-row em {
  margin-left: auto;
  font-style: normal;
  color: #6a8094;
  font-size: 0.5rem;
}
label:not(.check-row) {
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
  font-size: 0.54rem;
  color: #8aa0b4;
}
select {
  border: 1px solid rgba(136, 192, 255, 0.14);
  border-radius: 0.34rem;
  padding: 0.32rem 0.4rem;
  background: rgba(4, 12, 23, 0.7);
  color: #d8e6f5;
  font: inherit;
  font-size: 0.58rem;
}
.primary-btn {
  width: fit-content;
  border: 1px solid rgba(90, 213, 255, 0.35);
  border-radius: 0.42rem;
  padding: 0.36rem 0.72rem;
  background: rgba(10, 132, 255, 0.22);
  color: #a8e8ff;
  font: inherit;
  font-size: 0.62rem;
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
  background: linear-gradient(90deg, #0a84ff, #5ad5ff);
}
.msg {
  margin: 0;
  font-size: 0.58rem;
  color: #9ec4e0;
}
.msg.error {
  color: #ffb0b0;
}
</style>
