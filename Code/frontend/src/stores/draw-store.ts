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

/** 绘制工具栏在地图舞台（.map-stage）内的几何（px，供属性表联动定位） */
export interface DrawToolbarRect {
  x: number
  y: number
  width: number
  height: number
}

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

  // ── 绘制工具栏几何（工具栏 ↔ 属性表联动）──────────────────────────────
  // 均相对 .map-stage（工具栏与属性表共同的 offsetParent）
  const toolbarRect = ref<DrawToolbarRect | null>(null)
  const shellSize = ref({ width: 0, height: 0 })

  function setToolbarRect(rect: DrawToolbarRect | null) {
    toolbarRect.value = rect
  }

  function setShellSize(width: number, height: number) {
    shellSize.value = { width, height }
  }

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
    if (!draft) return false
    // 与 persistDraft 契约对称：空要素且非编辑会话的草稿视为已废弃，
    // 清除残留（防 localStorage 永久堆积无效草稿）。
    if (draft.features.length === 0 && !draft.editingLayerId) {
      clearDraftStorage()
      return false
    }
    features.value = draft.features
    drawMode.value = draft.drawMode
    draftLayerName.value = draft.draftLayerName
    // editingLayerId 不跨会话恢复：刷新后图层 instanceId 全部重新生成
    // （workspace-hydrate genInstanceId），旧 id 在新会话必然失效——
    // 恢复它会被 MapCanvas 孤儿安全网 watcher 误杀（clearDraft 清空
    // 未保存要素）。未保存的编辑要素降级为普通草稿保留。
    editingLayerId.value = null
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
    toolbarRect,
    shellSize,
    setToolbarRect,
    setShellSize,
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
