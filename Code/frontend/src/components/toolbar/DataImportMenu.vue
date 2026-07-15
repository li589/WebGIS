<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useLayersStore } from '../../stores/layers'
import { useLogStore } from '../../stores/log'
import CsvImportDialog from './CsvImportDialog.vue'

const layersStore = useLayersStore()
const logStore = useLogStore()

const menuOpen = ref(false)
const importing = ref(false)
const importMsg = ref('')
const csvFile = ref<File | null>(null)

const vectorInput = ref<HTMLInputElement | null>(null)
const csvInput = ref<HTMLInputElement | null>(null)
const rasterInput = ref<HTMLInputElement | null>(null)
const triggerRef = ref<HTMLButtonElement | null>(null)
const dropdownPos = ref({ top: 0, left: 0 })

function toggleMenu() {
  if (!menuOpen.value && triggerRef.value) {
    const rect = triggerRef.value.getBoundingClientRect()
    dropdownPos.value = { top: rect.bottom + 4, left: rect.left }
  }
  menuOpen.value = !menuOpen.value
}

function closeMenu() {
  menuOpen.value = false
}

// 点击外部关闭下拉菜单（Teleport 到 body 后需要全局监听）
function handleDocumentClick(e: MouseEvent) {
  if (!menuOpen.value) return
  const target = e.target as Node
  // 点击触发按钮时不关闭（toggleMenu 会处理）
  if (triggerRef.value && triggerRef.value.contains(target)) return
  // 点击下拉菜单内部时不关闭（菜单自身有 @click.stop）
  const dropdown = document.querySelector('.import-dropdown')
  if (dropdown && dropdown.contains(target)) return
  closeMenu()
}

watch(menuOpen, (open) => {
  if (open) {
    document.addEventListener('click', handleDocumentClick, { capture: true })
  } else {
    document.removeEventListener('click', handleDocumentClick, { capture: true })
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleDocumentClick, { capture: true })
})

function pickVector() {
  closeMenu()
  vectorInput.value?.click()
}

function pickCsv() {
  closeMenu()
  csvInput.value?.click()
}

function pickRaster() {
  closeMenu()
  rasterInput.value?.click()
}

async function handleVectorFile(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  target.value = ''
  importing.value = true
  importMsg.value = '正在解析矢量文件...'

  try {
    const ext = file.name.toLowerCase().split('.').pop() ?? ''
    let geojson: GeoJSON.FeatureCollection
    let multiLayerNote = ''

    if (ext === 'geojson' || ext === 'json') {
      const text = await file.text()
      geojson = JSON.parse(text)
    } else if (ext === 'shp' || ext === 'zip') {
      const arrayBuffer = await file.arrayBuffer()
      const shpjs = (await import('shpjs')).default
      const result = await shpjs(arrayBuffer)
      const parsed = normalizeShpResult(result)
      geojson = parsed.geojson
      multiLayerNote = parsed.layerCount > 1
        ? `已合并 ZIP 内 ${parsed.layerCount} 个图层，`
        : ''
    } else {
      throw new Error(`不支持的文件格式: .${ext}，请使用 .shp / .zip / .geojson / .json`)
    }

    if (!geojson.features || !Array.isArray(geojson.features)) {
      throw new Error('文件解析后未找到有效的 features 数组')
    }

    layersStore.addImportedVectorLayer(file.name, geojson)
    importMsg.value = `${multiLayerNote}已导入 ${geojson.features.length} 个要素（可在图层列表控制）`
    logStore.logOperation('import-vector-success', `矢量导入成功: ${file.name}`, `要素数: ${geojson.features.length}`)
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    importMsg.value = `导入失败: ${msg}`
    logStore.logOperation('import-vector-fail', `矢量导入失败: ${file.name}`, msg)
  } finally {
    importing.value = false
    setTimeout(() => { importMsg.value = '' }, 3000)
  }
}

/** shp.js 可能返回 FeatureCollection、数组或按文件名索引的对象 */
function normalizeShpResult(result: unknown): { geojson: GeoJSON.FeatureCollection; layerCount: number } {
  if (Array.isArray(result)) {
    const collections = result.filter((item): item is GeoJSON.FeatureCollection =>
      Boolean(item && typeof item === 'object' && Array.isArray((item as GeoJSON.FeatureCollection).features)),
    )
    if (collections.length === 0) {
      throw new Error('ZIP/SHP 解析后未找到有效图层')
    }
    return {
      layerCount: collections.length,
      geojson: {
        type: 'FeatureCollection',
        features: collections.flatMap((c) => c.features),
      },
    }
  }
  if (result && typeof result === 'object' && Array.isArray((result as GeoJSON.FeatureCollection).features)) {
    return { layerCount: 1, geojson: result as GeoJSON.FeatureCollection }
  }
  if (result && typeof result === 'object') {
    const collections = Object.entries(result as Record<string, unknown>)
      .filter(([key, value]) =>
        !key.endsWith('_null')
        && Boolean(value && typeof value === 'object' && Array.isArray((value as GeoJSON.FeatureCollection).features)),
      )
      .map(([, value]) => value as GeoJSON.FeatureCollection)
    if (collections.length === 0) {
      throw new Error('ZIP/SHP 解析后未找到有效图层')
    }
    return {
      layerCount: collections.length,
      geojson: {
        type: 'FeatureCollection',
        features: collections.flatMap((c) => c.features),
      },
    }
  }
  throw new Error('无法识别的 SHP 解析结果')
}

function handleCsvFile(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  target.value = ''
  csvFile.value = file
}

function handleCsvDialogClose() {
  csvFile.value = null
}

function handleCsvDialogConfirm(geojson: GeoJSON.FeatureCollection, name: string) {
  layersStore.addImportedVectorLayer(name, geojson)
  csvFile.value = null
}

async function handleRasterFile(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  target.value = ''
  importing.value = true
  importMsg.value = '正在上传栅格文件...'

  try {
    const formData = new FormData()
    formData.append('file', file)

    const resp = await fetch('/import/raster', {
      method: 'POST',
      body: formData,
    })

    if (!resp.ok) {
      const text = await resp.text()
      throw new Error(`后端返回 ${resp.status}: ${text}`)
    }

    const data = await resp.json() as {
      layer_id: string
      bounds?: [number, number, number, number]
    }
    if (!data.layer_id) {
      throw new Error('后端未返回 layer_id')
    }

    layersStore.addImportedRasterLayer(file.name, data.layer_id, data.bounds)
    importMsg.value = '栅格已导入图层列表，可控制显隐与透明度'
    logStore.logOperation('import-raster-success', `栅格导入成功: ${file.name}`, `Layer ID: ${data.layer_id}`)
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    importMsg.value = `导入失败: ${msg}`
    logStore.logOperation('import-raster-fail', `栅格导入失败: ${file.name}`, msg)
  } finally {
    importing.value = false
    setTimeout(() => { importMsg.value = '' }, 3000)
  }
}
</script>

<template>
  <div class="data-import-menu">
    <button
      ref="triggerRef"
      class="import-trigger"
      :class="{ active: menuOpen }"
      type="button"
      title="导入数据"
      @click="toggleMenu"
    >
      <span class="btn-icon" aria-hidden="true">📁</span>
      <span class="btn-label">导入</span>
      <span class="caret" aria-hidden="true">▾</span>
    </button>

    <Teleport to="body">
      <div
        v-if="menuOpen"
        class="import-dropdown"
        :style="{ top: dropdownPos.top + 'px', left: dropdownPos.left + 'px' }"
        @click.stop
      >
        <button class="dropdown-item" type="button" @click="pickVector">
          <span class="item-icon" aria-hidden="true">📐</span>
          <span class="item-body">
            <span class="item-title">矢量（SHP / GeoJSON）</span>
            <span class="item-desc">点线面要素</span>
          </span>
        </button>
        <button class="dropdown-item" type="button" @click="pickCsv">
          <span class="item-icon" aria-hidden="true">📊</span>
          <span class="item-body">
            <span class="item-title">CSV 表格</span>
            <span class="item-desc">选择 XY 列生成点图层</span>
          </span>
        </button>
        <button class="dropdown-item" type="button" @click="pickRaster">
          <span class="item-icon" aria-hidden="true">🗺</span>
          <span class="item-body">
            <span class="item-title">栅格（TIF）</span>
            <span class="item-desc">上传后端转 COG，写入图层列表</span>
          </span>
        </button>
      </div>
    </Teleport>

    <!-- 状态提示 -->
    <div v-if="importMsg" class="import-toast" :class="{ error: importMsg.includes('失败') }">
      {{ importMsg }}
    </div>

    <!-- 加载遮罩 -->
    <div v-if="importing" class="import-spinner">
      <span class="spinning-icon" aria-hidden="true">↻</span>
    </div>

    <!-- 隐藏文件输入 -->
    <input ref="vectorInput" type="file" accept=".shp,.zip,.geojson,.json" hidden @change="handleVectorFile" />
    <input ref="csvInput" type="file" accept=".csv" hidden @change="handleCsvFile" />
    <input ref="rasterInput" type="file" accept=".tif,.tiff" hidden @change="handleRasterFile" />

    <!-- CSV 配置对话框 -->
    <CsvImportDialog
      v-if="csvFile"
      :file="csvFile"
      @confirm="handleCsvDialogConfirm"
      @close="handleCsvDialogClose"
    />
  </div>
</template>

<style scoped>
.data-import-menu {
  position: relative;
  display: inline-flex;
  align-items: center;
}

/* 按钮样式 — 与 ModeToolbar .tool-btn 保持一致（scoped 样式不传递到子组件，需在此定义） */
.import-trigger {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 0.24rem;
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: 0.5rem;
  padding: 0.3rem 0.46rem;
  background: rgba(4, 12, 23, 0.6);
  color: #9fb6cc;
  cursor: pointer;
  font: inherit;
  font-size: 0.62rem;
  font-weight: 500;
  white-space: nowrap;
  transition: border-color 0.18s ease, color 0.18s ease, background 0.18s ease;
}

.import-trigger:hover {
  border-color: rgba(90, 213, 255, 0.3);
  color: #5ad5ff;
  background: rgba(10, 132, 255, 0.12);
}

.import-trigger.active {
  border-color: rgba(90, 213, 255, 0.4);
  color: #5ad5ff;
  background: rgba(10, 132, 255, 0.2);
  box-shadow: inset 0 0 0 1px rgba(90, 213, 255, 0.16);
}

.btn-icon { font-size: 0.72rem; opacity: 0.9; }
.btn-label { font-size: 0.6rem; }
.caret { font-size: 0.52rem; opacity: 0.6; }

/* 下拉菜单 — Teleport 到 body，position: fixed 脱离层叠上下文 */
.import-dropdown {
  position: fixed;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  padding: 0.3rem;
  border-radius: 0.6rem;
  background: rgba(8, 18, 33, 0.96);
  border: 1px solid rgba(136, 192, 255, 0.16);
  box-shadow: 0 12px 36px rgba(1, 8, 16, 0.4);
  min-width: 11rem;
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: 0.42rem;
  padding: 0.42rem 0.5rem;
  border: none;
  border-radius: 0.42rem;
  background: transparent;
  color: #9fb6cc;
  cursor: pointer;
  font: inherit;
  text-align: left;
  transition: background 0.16s ease, color 0.16s ease;
}

.dropdown-item:hover {
  background: rgba(136, 192, 255, 0.1);
  color: #d8e6f5;
}

.item-icon { font-size: 0.8rem; flex: none; }
.item-body { display: flex; flex-direction: column; gap: 0.08rem; min-width: 0; }
.item-title { font-size: 0.62rem; font-weight: 500; }
.item-desc { font-size: 0.52rem; color: #5a7080; }

.import-toast {
  position: absolute;
  top: 100%;
  left: 0;
  margin-top: 0.32rem;
  z-index: 101;
  padding: 0.32rem 0.52rem;
  border-radius: 0.42rem;
  background: rgba(10, 132, 255, 0.2);
  border: 1px solid rgba(90, 213, 255, 0.3);
  color: #a8e8ff;
  font-size: 0.58rem;
  white-space: nowrap;
  pointer-events: none;
}

.import-toast.error {
  background: rgba(255, 77, 77, 0.16);
  border-color: rgba(255, 100, 100, 0.3);
  color: #ffb0b0;
}

.import-spinner {
  position: fixed;
  inset: 0;
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(4, 10, 18, 0.4);
  pointer-events: none;
}

.spinning-icon {
  font-size: 1.6rem;
  color: #5ad5ff;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }
</style>
