<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { fetchImportedLayerGeojson, fetchImportedLayerMeta } from '../core/api'
import { exportLayer, type ExportFormat } from '../adapters/export'
import { focusImportedLayer } from '../adapters/layers'
import { dataWorkspaceLayerId, openDataWorkspace } from '../core/workspace-store'
import { useLayersStore } from '../../stores/layers'
import { useLogStore } from '../../stores/log'
import { DATA_COPY } from '../../ui-copy'

const layersStore = useLayersStore()
const logStore = useLogStore()

const meta = ref<Record<string, unknown> | null>(null)
const loading = ref(false)
const error = ref('')
const msg = ref('')

const importedLayers = computed(() =>
  layersStore.activeLayers.filter((l) => l.importedVector || l.importedRaster),
)

const selectedLayer = computed(() => {
  const id = dataWorkspaceLayerId.value
  if (!id) return importedLayers.value[0] ?? null
  return importedLayers.value.find((l) => l.instanceId === id) ?? importedLayers.value[0] ?? null
})

const backendId = computed(() => {
  const l = selectedLayer.value
  if (!l) return null
  return l.importedVector?.backendLayerId || l.importedRaster?.overlayLayerId || l.catalogId
})

const isVector = computed(() => Boolean(selectedLayer.value?.importedVector))

const styleColor = ref('#7ee0a8')
const styleWidth = ref(2)
const styleRadius = ref(4)
const styleFillOpacity = ref(0.25)

watch(
  () => selectedLayer.value?.instanceId,
  (id) => {
    if (id) dataWorkspaceLayerId.value = id
    const st = selectedLayer.value?.importedVector?.style
    styleColor.value = st?.color ?? '#7ee0a8'
    styleWidth.value = st?.width ?? 2
    styleRadius.value = st?.radius ?? 4
    styleFillOpacity.value = st?.fillOpacity ?? 0.25
    void loadMeta()
  },
  { immediate: true },
)

async function loadMeta() {
  meta.value = null
  error.value = ''
  if (!backendId.value || !isVector.value) return
  loading.value = true
  try {
    meta.value = await fetchImportedLayerMeta(backendId.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function onSelectLayer(e: Event) {
  dataWorkspaceLayerId.value = (e.target as HTMLSelectElement).value || null
}

function applyStyle() {
  if (!selectedLayer.value?.importedVector) return
  layersStore.setImportedVectorStyle(selectedLayer.value.instanceId, {
    color: styleColor.value,
    width: styleWidth.value,
    radius: styleRadius.value,
    fillOpacity: styleFillOpacity.value,
  })
  msg.value = DATA_COPY.styleApplied
}

async function loadFullGeojson() {
  if (!backendId.value || !selectedLayer.value) return
  loading.value = true
  error.value = ''
  try {
    const gj = await fetchImportedLayerGeojson(backendId.value, false)
    layersStore.updateImportedVectorGeojson(selectedLayer.value.instanceId, gj, {
      featureCount: gj.features.length,
      truncated: false,
    })
    msg.value = `已加载完整数据：${gj.features.length} 要素`
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function exportFmt(fmt: string) {
  if (!selectedLayer.value) return
  try {
    const times = selectedLayer.value.importedRaster?.timeList ?? []
    let time: string | null = null
    if (times.length) {
      const eff = selectedLayer.value.importedRaster?.effectiveTimeLabel
      time =
        (eff && times.find((t) => eff === t || eff.startsWith(t))) ||
        times[times.length - 1] ||
        null
    }
    await exportLayer(selectedLayer.value, fmt as ExportFormat, { time })
    msg.value = time ? `导出完成 · ${time}` : '导出完成'
    logStore.logOperation(
      'export-layer',
      selectedLayer.value.name ?? 'layer',
      time ? `${fmt}@${time}` : fmt,
    )
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

function openAttributes() {
  if (!selectedLayer.value) return
  focusImportedLayer(selectedLayer.value.instanceId)
  openDataWorkspace({ tab: 'attributes', layerInstanceId: selectedLayer.value.instanceId })
}

function removeLayer() {
  if (!selectedLayer.value) return
  const id = selectedLayer.value.instanceId
  layersStore.removeLayer(id)
  dataWorkspaceLayerId.value = null
  msg.value = DATA_COPY.layerRemoved
}
</script>

<template>
  <div class="details">
    <div class="row">
      <label>
        {{ DATA_COPY.attrLayer }}
        <select :value="selectedLayer?.instanceId ?? ''" @change="onSelectLayer">
          <option v-if="!importedLayers.length" value="">{{ DATA_COPY.emptyExport }}</option>
          <option v-for="l in importedLayers" :key="l.instanceId" :value="l.instanceId">
            {{ l.name }} · {{ l.importedRaster ? '栅格' : '矢量' }}
          </option>
        </select>
      </label>
    </div>

    <p v-if="!selectedLayer" class="empty">{{ DATA_COPY.emptyExport }}</p>
    <template v-else>
      <section class="card">
        <h3>{{ DATA_COPY.detailsMeta }}</h3>
        <dl>
          <div>
            <dt>名称</dt>
            <dd>{{ selectedLayer.name }}</dd>
          </div>
          <div>
            <dt>类型</dt>
            <dd>{{ isVector ? '矢量' : '栅格' }}</dd>
          </div>
          <div>
            <dt>ID</dt>
            <dd class="mono">{{ backendId }}</dd>
          </div>
          <div v-if="selectedLayer.importedVector">
            <dt>要素数</dt>
            <dd>
              {{ selectedLayer.importedVector.featureCount }}
              <span v-if="selectedLayer.importedVector.truncated" class="warn">
                （地图预览已截断）
              </span>
            </dd>
          </div>
          <div v-if="meta?.fields">
            <dt>字段</dt>
            <dd>{{ (meta.fields as string[]).join(', ') || '—' }}</dd>
          </div>
          <div v-if="meta?.geometry_types">
            <dt>几何</dt>
            <dd>{{ (meta.geometry_types as string[]).join(', ') }}</dd>
          </div>
        </dl>
        <p v-if="error" class="err">{{ error }}</p>
        <p v-else-if="msg" class="ok">{{ msg }}</p>
      </section>

      <section v-if="isVector" class="card">
        <h3>{{ DATA_COPY.detailsStyle }}</h3>
        <div class="style-grid">
          <label>
            颜色
            <input v-model="styleColor" type="color" />
          </label>
          <label>
            线宽
            <input v-model.number="styleWidth" type="number" min="0.5" max="12" step="0.5" />
          </label>
          <label>
            点半径
            <input v-model.number="styleRadius" type="number" min="1" max="20" step="1" />
          </label>
          <label>
            填充透明度
            <input v-model.number="styleFillOpacity" type="number" min="0" max="1" step="0.05" />
          </label>
        </div>
        <button class="primary-btn" type="button" @click="applyStyle">
          {{ DATA_COPY.applyStyle }}
        </button>
      </section>

      <section class="card actions">
        <h3>{{ DATA_COPY.detailsActions }}</h3>
        <div class="btn-row">
          <button
            v-if="isVector"
            class="ghost-btn"
            type="button"
            :disabled="loading"
            @click="openAttributes"
          >
            {{ DATA_COPY.openAttributes }}
          </button>
          <button
            v-if="isVector && selectedLayer.importedVector?.truncated"
            class="ghost-btn"
            type="button"
            :disabled="loading"
            @click="loadFullGeojson"
          >
            {{ DATA_COPY.loadFull }}
          </button>
          <button v-if="isVector" class="ghost-btn" type="button" @click="exportFmt('geojson')">
            GeoJSON
          </button>
          <button v-if="isVector" class="ghost-btn" type="button" @click="exportFmt('csv')">
            CSV
          </button>
          <button v-if="!isVector" class="ghost-btn" type="button" @click="exportFmt('geotiff')">
            GeoTIFF
          </button>
          <button v-if="!isVector" class="ghost-btn" type="button" @click="exportFmt('mat')">
            MAT
          </button>
          <button class="danger-btn" type="button" @click="removeLayer">
            {{ DATA_COPY.deleteLayer }}
          </button>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.details {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  min-height: 0;
  overflow: auto;
}
.row {
  display: flex;
  gap: 0.5rem;
}
label {
  display: flex;
  flex-direction: column;
  gap: 0.16rem;
  font-size: 0.58rem;
  color: #8aa0b4;
}
input,
select {
  border: 1px solid rgba(136, 192, 255, 0.16);
  border-radius: 0.34rem;
  padding: 0.28rem 0.4rem;
  background: rgba(4, 12, 23, 0.72);
  color: #d8e6f5;
  font: inherit;
  font-size: 0.62rem;
}
input[type='color'] {
  width: 3rem;
  height: 1.6rem;
  padding: 0.1rem;
}
.card {
  border: 1px solid rgba(136, 192, 255, 0.12);
  border-radius: 0.48rem;
  padding: 0.55rem 0.65rem;
  background: rgba(4, 12, 23, 0.35);
}
.card h3 {
  margin: 0 0 0.4rem;
  font-size: 0.66rem;
  font-weight: 600;
  color: #9ec4e0;
}
dl {
  margin: 0;
  display: grid;
  gap: 0.28rem;
}
dl > div {
  display: grid;
  grid-template-columns: 4.5rem 1fr;
  gap: 0.4rem;
  font-size: 0.6rem;
}
dt {
  color: #6a8094;
}
dd {
  margin: 0;
  color: #d8e6f5;
}
.mono {
  font-family: ui-monospace, monospace;
  font-size: 0.54rem;
  word-break: break-all;
}
.warn {
  color: #ffd166;
}
.style-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(7rem, 1fr));
  gap: 0.4rem;
  margin-bottom: 0.45rem;
}
.btn-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}
.ghost-btn,
.primary-btn,
.danger-btn {
  border-radius: 0.38rem;
  padding: 0.3rem 0.55rem;
  font: inherit;
  font-size: 0.6rem;
  cursor: pointer;
}
.ghost-btn {
  border: 1px solid rgba(136, 192, 255, 0.2);
  background: rgba(4, 12, 23, 0.55);
  color: #c5d8ea;
}
.primary-btn {
  border: 1px solid rgba(90, 213, 255, 0.35);
  background: rgba(10, 132, 255, 0.22);
  color: #a8e8ff;
}
.danger-btn {
  border: 1px solid rgba(255, 120, 120, 0.35);
  background: rgba(120, 20, 20, 0.25);
  color: #ffb0b0;
}
.empty,
.err,
.ok {
  margin: 0;
  font-size: 0.62rem;
}
.empty {
  color: #8aa0b4;
}
.err {
  color: #ffb0b0;
}
.ok {
  color: #9ec4e0;
}
</style>
