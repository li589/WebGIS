<script setup lang="ts">
/**
 * 底图要素提取卡片：分析面板「工具」Tab 内的前端交互工具。
 *
 * 底图为栅格瓦片，无法直接 queryRenderedFeatures，因此：
 * - 行政区提取：基于当前选点在本地行政区边界数据中做包含判断
 * - 道路提取：当前视口 bbox 经 OSM Overpass（需外部网络）
 * 提取结果自动登记后端并创建矢量图层。
 */
import { computed, ref } from 'vue'
import AppButton from '../ui/AppButton.vue'
import {
  extractAdminAreaAt,
  extractViewportRoads,
  createExtractedVectorLayer,
  type RoadClassFilter,
} from '../../services/basemap-extract'

const props = defineProps<{
  selectedMapPoint: { lng: number; lat: number } | null
  currentMapBBox: { west: number; south: number; east: number; north: number } | null
}>()

const emit = defineEmits<{
  enterSelectMode: []
}>()

const extractKind = ref<'admin' | 'roads'>('admin')
const roadClass = ref<RoadClassFilter>('major')
const busy = ref(false)
const statusMessage = ref('')
const errorMessage = ref('')
const createdLayerName = ref('')

const roadClassOptions: { value: RoadClassFilter; label: string }[] = [
  { value: 'major', label: '主要道路（高速/主干/国道）' },
  { value: 'all', label: '全部道路（含次干/支路）' },
]

const canRun = computed(() => {
  if (busy.value) return false
  if (extractKind.value === 'admin') return Boolean(props.selectedMapPoint)
  return Boolean(props.currentMapBBox)
})

const runHint = computed(() => {
  if (busy.value) return '提取中…'
  if (extractKind.value === 'admin') {
    return props.selectedMapPoint
      ? `将提取选点 (${props.selectedMapPoint.lng.toFixed(3)}, ${props.selectedMapPoint.lat.toFixed(3)}) 所在行政区`
      : '请先进入选择模式并在地图选点'
  }
  return '将提取当前视口范围内的道路（需要外部网络）'
})

async function onExtract() {
  if (!canRun.value) return
  busy.value = true
  errorMessage.value = ''
  statusMessage.value = extractKind.value === 'admin' ? '正在匹配行政区…' : '正在拉取道路要素…'
  createdLayerName.value = ''
  try {
    let name = ''
    let geojson: GeoJSON.FeatureCollection
    if (extractKind.value === 'admin') {
      const point = props.selectedMapPoint!
      const area = await extractAdminAreaAt(point.lng, point.lat)
      if (!area) {
        throw new Error('选点不在行政区边界数据覆盖范围内（当前内置广东省市级边界）')
      }
      name = `行政区-${area.name}`
      geojson = {
        type: 'FeatureCollection',
        features: [
          {
            type: 'Feature',
            properties: { name: area.name, adcode: area.adcode },
            geometry: area.geometry,
          },
        ],
      }
    } else {
      const bbox = props.currentMapBBox!
      const result = await extractViewportRoads(bbox, roadClass.value)
      if (result.geojson.features.length === 0) {
        throw new Error('当前视口内未提取到道路要素，请调整视野后重试')
      }
      name = `道路提取-${roadClass.value === 'major' ? '主要道路' : '全部道路'}`
      geojson = result.geojson
      if (result.truncated) {
        statusMessage.value = `道路要素较多，已截断至 ${geojson.features.length} 条`
      }
    }
    statusMessage.value = '正在创建矢量图层…'
    const created = await createExtractedVectorLayer(name, geojson)
    createdLayerName.value = created.name
    statusMessage.value = created.backendLayerId
      ? `已创建图层「${created.name}」并登记后端`
      : `已创建图层「${created.name}」（后端登记失败，本次会话内有效）`
  } catch (error) {
    statusMessage.value = ''
    errorMessage.value = error instanceof Error ? error.message : '提取失败，请重试'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section id="basemap-feature-extract" class="analysis-section analysis-section--extract">
    <div class="extract-kind-row">
      <button
        type="button"
        class="kind-btn"
        :class="{ active: extractKind === 'admin' }"
        @click="extractKind = 'admin'"
      >
        行政区（按选点）
      </button>
      <button
        type="button"
        class="kind-btn"
        :class="{ active: extractKind === 'roads' }"
        @click="extractKind = 'roads'"
      >
        道路（按视口）
      </button>
    </div>

    <div v-if="extractKind === 'roads'" class="extract-form">
      <label class="param-row">
        <span class="param-label">道路等级</span>
        <select v-model="roadClass" class="param-input">
          <option v-for="opt in roadClassOptions" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </option>
        </select>
      </label>
    </div>
    <div v-else-if="!selectedMapPoint" class="extract-form">
      <AppButton size="xs" variant="secondary" @click="emit('enterSelectMode')">
        进入选择模式
      </AppButton>
    </div>

    <div class="run-row">
      <AppButton size="sm" variant="primary" :disabled="!canRun" @click="onExtract">
        {{ busy ? '提取中…' : '提取并创建图层' }}
      </AppButton>
    </div>

    <p v-if="runHint" class="extract-hint">{{ runHint }}</p>
    <p v-if="statusMessage" class="extract-status">{{ statusMessage }}</p>
    <p v-if="errorMessage" class="extract-error">{{ errorMessage }}</p>
  </section>
</template>

<style scoped>
.extract-kind-row {
  display: flex;
  gap: 0.4rem;
  margin-bottom: 0.5rem;
}

.kind-btn {
  flex: 1;
  border: 1px solid var(--border-default);
  background: var(--surface-raised);
  color: var(--text-primary);
  border-radius: 0.45rem;
  padding: 0.32rem 0.5rem;
  font-size: var(--font-size-caption);
  cursor: pointer;
}

.kind-btn.active {
  border-color: var(--accent, #3b82f6);
  background: color-mix(in srgb, var(--accent, #3b82f6) 18%, transparent);
}

.extract-form {
  margin-bottom: 0.5rem;
}

.param-row {
  display: grid;
  gap: 0.2rem;
}

.param-label {
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}

.param-input {
  width: 100%;
  border: 1px solid var(--border-default);
  border-radius: 0.4rem;
  padding: 0.28rem 0.4rem;
  background: var(--surface-base, transparent);
  color: inherit;
}

.run-row {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  margin-top: 0.4rem;
}

.extract-hint,
.extract-status {
  margin: 0.35rem 0 0;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}

.extract-status {
  color: var(--success, #16a34a);
}

.extract-error {
  margin: 0.35rem 0 0;
  font-size: var(--font-size-caption);
  color: var(--danger, #b91c1c);
}
</style>
