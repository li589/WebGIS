/**
 * 绘制矢量要素 Store — 状态管理 + 草稿持久化。
 *
 * 职责：
 *   1. 管理绘制模式（polygon/rectangle/line）
 *   2. 管理已完成要素列表 + 当前绘制中的顶点
 *   3. 撤销栈管理
 *   4. 临时图层 ID 和名称管理
 *   5. 草稿持久化（pagehide/防抖 localStorage）
 *   6. 图层编辑模式标记
 */
import { ref, watch } from 'vue'
import { defineStore } from 'pinia'

export type DrawMode = 'polygon' | 'rectangle' | 'line'

export interface DrawVertex {
  lng: number
  lat: number
}

export interface DrawFeature {
  geometry: GeoJSON.Polygon | GeoJSON.LineString
  properties: Record<string, unknown>
}

const DRAFT_STORAGE_KEY = 'geo:draw-draft:v1'

interface DrawDraft {
  version: 1
  savedAt: string
  features: DrawFeature[]
  drawMode: DrawMode
  draftLayerName: string
  editingLayerId: string | null
}

function saveDraftToStorage(draft: DrawDraft): void {
  try {
    localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft))
  } catch {
    /* quota exceeded, ignore */
  }
}

function loadDraftFromStorage(): DrawDraft | null {
  try {
    const raw = localStorage.getItem(DRAFT_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as DrawDraft
    if (parsed.version !== 1) return null
    return parsed
  } catch {
    return null
  }
}

function clearDraftStorage(): void {
  try {
    localStorage.removeItem(DRAFT_STORAGE_KEY)
  } catch {
    /* ignore */
  }
}

export const useDrawStore = defineStore('draw', () => {
  const drawMode = ref<DrawMode>('polygon')
  const features = ref<DrawFeature[]>([])
  const activeVertices = ref<DrawVertex[]>([])
  const isDrawing = ref(false)
  const hoverPoint = ref<DrawVertex | null>(null)
  const selectedFeatureIndex = ref<number | null>(null)
  const undoStack = ref<DrawFeature[][]>([])

  const draftLayerId = ref<string | null>(null)
  const draftLayerName = ref<string>('')
  const editingLayerId = ref<string | null>(null)

  let draftLoaded = false

  function setDrawMode(mode: DrawMode) {
    drawMode.value = mode
  }

  function addVertex(v: DrawVertex) {
    activeVertices.value.push(v)
    isDrawing.value = true
  }

  function undoLastVertex() {
    activeVertices.value.pop()
    if (activeVertices.value.length === 0) {
      isDrawing.value = false
    }
  }

  function setHoverPoint(p: DrawVertex | null) {
    hoverPoint.value = p
  }

  function pushUndoState() {
    undoStack.value.push([...features.value])
    if (undoStack.value.length > 50) {
      undoStack.value.shift()
    }
  }

  function addFeature(feature: DrawFeature) {
    pushUndoState()
    features.value.push(feature)
  }

  function undo() {
    if (undoStack.value.length === 0) return
    const prev = undoStack.value.pop()!
    features.value = prev
  }

  function clearActiveVertices() {
    activeVertices.value = []
    isDrawing.value = false
    hoverPoint.value = null
  }

  function clearAll() {
    pushUndoState()
    features.value = []
    activeVertices.value = []
    isDrawing.value = false
    hoverPoint.value = null
    selectedFeatureIndex.value = null
    undoStack.value = []
  }

  function removeFeature(index: number) {
    pushUndoState()
    features.value.splice(index, 1)
    if (selectedFeatureIndex.value === index) {
      selectedFeatureIndex.value = null
    }
  }

  function setSelectedFeature(index: number | null) {
    selectedFeatureIndex.value = index
  }

  function updateFeatureProperties(index: number, props: Record<string, unknown>) {
    const f = features.value[index]
    if (!f) return
    f.properties = { ...f.properties, ...props }
  }

  function beginDrawSession(layerName: string) {
    draftLayerName.value = layerName || `绘制图层-${new Date().toLocaleString('zh-CN')}`
    draftLayerId.value = null
    editingLayerId.value = null
    features.value = []
    activeVertices.value = []
    isDrawing.value = false
    hoverPoint.value = null
    undoStack.value = []
  }

  function beginEditLayer(instanceId: string, existingFeatures: DrawFeature[]) {
    editingLayerId.value = instanceId
    draftLayerId.value = null
    features.value = [...existingFeatures]
    activeVertices.value = []
    isDrawing.value = false
    hoverPoint.value = null
    undoStack.value = []
  }

  function setDraftLayerId(id: string) {
    draftLayerId.value = id
  }

  function buildDraft(): DrawDraft {
    return {
      version: 1,
      savedAt: new Date().toISOString(),
      features: features.value,
      drawMode: drawMode.value,
      draftLayerName: draftLayerName.value,
      editingLayerId: editingLayerId.value,
    }
  }

  function persistDraft() {
    if (features.value.length === 0 && !editingLayerId.value) {
      clearDraftStorage()
      return
    }
    saveDraftToStorage(buildDraft())
  }

  let debounceTimer: ReturnType<typeof setTimeout> | null = null

  function scheduleDraftPersist() {
    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(persistDraft, 400)
  }

  function restoreDraft(): boolean {
    if (draftLoaded) return false
    draftLoaded = true
    const draft = loadDraftFromStorage()
    if (!draft || draft.features.length === 0) return false
    features.value = draft.features
    drawMode.value = draft.drawMode
    draftLayerName.value = draft.draftLayerName
    editingLayerId.value = draft.editingLayerId
    return true
  }

  function clearDraft() {
    clearDraftStorage()
    draftLayerId.value = null
    draftLayerName.value = ''
    editingLayerId.value = null
    features.value = []
    activeVertices.value = []
    isDrawing.value = false
    hoverPoint.value = null
    undoStack.value = []
  }

  // 要素或属性变化时防抖持久化（属性编辑不改变 length，需监听内容）
  watch(
    () => JSON.stringify(features.value),
    () => scheduleDraftPersist(),
  )

  // 页面离开时持久化
  if (typeof window !== 'undefined') {
    window.addEventListener('pagehide', () => persistDraft())
    window.addEventListener('beforeunload', (e) => {
      persistDraft()
      if (features.value.length > 0) {
        e.preventDefault()
        e.returnValue = ''
      }
    })
  }

  return {
    drawMode,
    features,
    activeVertices,
    isDrawing,
    hoverPoint,
    selectedFeatureIndex,
    undoStack,
    draftLayerId,
    draftLayerName,
    editingLayerId,
    setDrawMode,
    addVertex,
    undoLastVertex,
    setHoverPoint,
    addFeature,
    undo,
    clearActiveVertices,
    clearAll,
    removeFeature,
    setSelectedFeature,
    updateFeatureProperties,
    beginDrawSession,
    beginEditLayer,
    setDraftLayerId,
    buildDraft,
    persistDraft,
    restoreDraft,
    clearDraft,
    scheduleDraftPersist,
  }
})
