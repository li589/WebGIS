/**
 * 图层右键菜单能力解析（策略单一真源）。
 */
import type { ActiveLayer, ActiveLayerDisplay } from '../../stores/layers/types'
import { isPolygonEditableLayer } from '../../utils/draw-geojson-bridge'
import type { LayerContextMenuInput } from './layer-context-menu'

export interface ResolveLayerContextCapabilitiesInput {
  layer: ActiveLayerDisplay
  raw: ActiveLayer | undefined
  isWeatherLayer: (catalogId: string) => boolean
  supportsAnalysisWorkflow: (catalogId: string) => boolean
  isOverlayDisplayOnlyLayer: (catalogId: string) => boolean
  canRunCatalog: (catalogId: string) => boolean
  weatherStatus?: { errorType?: string }
}

function isDrawDraftCatalog(catalogId: string): boolean {
  return catalogId.startsWith('draw-draft-')
}

export function resolveLayerContextCapabilities(
  input: ResolveLayerContextCapabilitiesInput,
): LayerContextMenuInput {
  const { layer, raw } = input
  const weather = input.isWeatherLayer(layer.catalogId)
  const drawDraft = isDrawDraftCatalog(layer.catalogId)

  const isExportPending = Boolean(
    raw?.runGroupId &&
      !raw.importedRaster?.overlayLayerId &&
      !raw.importedVector?.backendLayerId &&
      !layer.isImported &&
      !layer.isImportedRaster,
  )

  const catalogRunnable =
    !weather &&
    !layer.isImported &&
    !layer.isImportedRaster &&
    !layer.isAdminBoundary &&
    (input.supportsAnalysisWorkflow(layer.catalogId) ||
      input.isOverlayDisplayOnlyLayer(layer.catalogId)) &&
    input.canRunCatalog(layer.catalogId)

  const canEditGeometry = Boolean(
    layer.isImported &&
      !layer.isAdminBoundary &&
      isPolygonEditableLayer(raw?.importedVector?.geometryType),
  )

  return {
    visible: layer.visible,
    isAdminBoundary: layer.isAdminBoundary,
    isImported: layer.isImported,
    isImportedRaster: layer.isImportedRaster,
    isExportPending,
    hasJobReport: Boolean(layer.jobLayer?.reportSummary),
    canRunWorkflow: catalogRunnable,
    canEditGeometry,
    canDissolveGroup: false,
    isWeatherLayer: weather,
    canRetryWeatherTiles: weather,
    canTriggerWeatherSync: weather && input.weatherStatus?.errorType === 'data-empty',
    showViewDetailsInViewGroup: !layer.isImported && !layer.isImportedRaster,
    isDrawDraft: drawDraft,
    rasterExportPanelOnly: layer.isImportedRaster,
  }
}
