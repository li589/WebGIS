/**
 * 绘制图层保存 — 几何校验 + 真实异步上传 + 草稿层生命周期。
 *
 * 统一工具栏与属性表两条保存路径的校验与结果反馈，避免"保存成功"在真实
 * 结果前显示、以及草稿层移除后孤儿草稿残留。
 */
import { ref } from 'vue'
import type { DrawFeature } from '../stores/draw-store'
import { useDrawStore } from '../stores/draw-store'
import { useLayerWorkspace } from '../stores/layers/selectors'
import { importVectorMultipart } from '../data-manager/core/api'

export interface DrawValidationIssue {
  index: number
  label: string
  message: string
}

export interface DrawSaveResult {
  ok: boolean
  /** 空图层被丢弃（未上传） */
  dropped: boolean
  featureCount: number
  validationErrors: DrawValidationIssue[]
  error?: string
  layerId?: string
}

/** 保存前几何自动检查（多边形闭合/最小顶点/非法坐标） */
export function validateDrawFeatures(features: DrawFeature[]): DrawValidationIssue[] {
  const issues: DrawValidationIssue[] = []
  for (let i = 0; i < features.length; i++) {
    const f = features[i]
    const label = `要素 ${i + 1}`
    if (f.geometry.type === 'Polygon') {
      const ring = f.geometry.coordinates[0] ?? []
      if (ring.length < 4) {
        issues.push({ index: i, label, message: '面环至少需要 4 个坐标（含闭合点）' })
      } else {
        const first = ring[0]
        const last = ring[ring.length - 1]
        if (first[0] !== last[0] || first[1] !== last[1]) {
          issues.push({ index: i, label, message: '面环未闭合' })
        }
      }
    } else if (f.geometry.type === 'LineString') {
      if ((f.geometry.coordinates ?? []).length < 2) {
        issues.push({ index: i, label, message: '线至少需要 2 个顶点' })
      }
    }
    const coords =
      f.geometry.type === 'Polygon'
        ? (f.geometry.coordinates[0] ?? [])
        : (f.geometry.coordinates ?? [])
    for (const c of coords) {
      if (!Number.isFinite(c[0]) || !Number.isFinite(c[1])) {
        issues.push({ index: i, label, message: '包含非法坐标' })
        break
      }
    }
  }
  return issues
}

export function useDrawSave() {
  const drawStore = useDrawStore()
  const layersStore = useLayerWorkspace()
  const isSaving = ref(false)

  /** 先清草稿再移除草稿层：避免孤儿草稿安全网在保存流程中误触发退出绘制模式 */
  function discardDraftLayer() {
    const draftInstanceId = drawStore.draftLayerId
    drawStore.clearDraft()
    if (draftInstanceId) {
      layersStore.removeLayer(draftInstanceId)
    }
  }

  async function saveDrawLayer(): Promise<DrawSaveResult> {
    const features = drawStore.features

    // 空图层：丢弃草稿层与本地草稿，不上传
    if (features.length === 0) {
      discardDraftLayer()
      return { ok: true, dropped: true, featureCount: 0, validationErrors: [] }
    }

    const validationErrors = validateDrawFeatures(features)
    if (validationErrors.length > 0) {
      return { ok: false, dropped: false, featureCount: features.length, validationErrors }
    }

    isSaving.value = true
    try {
      const geojson: GeoJSON.FeatureCollection = {
        type: 'FeatureCollection',
        features: features.map((f) => ({
          type: 'Feature' as const,
          geometry: f.geometry,
          properties: f.properties,
        })),
      }
      const jsonStr = JSON.stringify(geojson)
      const blob = new Blob([jsonStr], { type: 'application/geo+json' })
      const fileName = drawStore.draftLayerName
        ? `${drawStore.draftLayerName.replace(/[<>:"/\\|?*]/g, '_')}.geojson`
        : `绘制图层-${Date.now()}.geojson`
      const file = new File([blob], fileName, { type: 'application/geo+json' })

      const imported = await importVectorMultipart([file])
      if (imported?.layer_id) {
        // 先清草稿再移除草稿层，最后添加正式图层（避免空壳残留）
        discardDraftLayer()
        layersStore.addImportedVectorLayer(fileName.replace(/\.geojson$/i, ''), geojson, {
          backendLayerId: imported.layer_id,
          featureCount: features.length,
        })
        return {
          ok: true,
          dropped: false,
          featureCount: features.length,
          validationErrors: [],
          layerId: imported.layer_id,
        }
      }
      return {
        ok: false,
        dropped: false,
        featureCount: features.length,
        validationErrors: [],
        error: '后端未返回图层 ID',
      }
    } catch (err) {
      return {
        ok: false,
        dropped: false,
        featureCount: features.length,
        validationErrors: [],
        error: err instanceof Error ? err.message : String(err),
      }
    } finally {
      isSaving.value = false
    }
  }

  return { isSaving, saveDrawLayer, validateDrawFeatures }
}
