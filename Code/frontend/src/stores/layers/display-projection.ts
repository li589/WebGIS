import type { RuntimeLayerDescriptor } from '../../services/runtime-api'
import { buildDefaultWeatherRenderHint } from '../../data/weather-render-hints'
import { formatClockHourLabel } from '../../utils/weather-timeline'
import { resolveWeatherTileReadyKind } from '../../utils/weather-tile-readiness'
import { buildAvailabilityState, buildCatalogFallbackItem } from './catalog-builders'
import { resolvePersistedDisplayName } from './layer-display-names'
import { buildRealLayerDisplay } from './result-adapter'
import type {
  ActiveLayer,
  ActiveLayerDisplay,
  ActiveRunLayerGroup,
  RuntimeLayerLibraryItem,
} from './types'

export interface WeatherTileDisplayBridge {
  getStats(
    catalogId: string,
  ): { visible: number; cached: number; pending: number } | null | undefined
  getLayerStatus(catalogId: string): {
    errorType?: string | null
    errorMessage?: string | null
  }
}

export interface ActiveLayersDisplayContext {
  activeLayers: ActiveLayer[]
  layerLibraryMap: Map<string, RuntimeLayerLibraryItem>
  runtimeLayerCatalog: Record<string, RuntimeLayerDescriptor | null>
  currentHour: number
  weatherTileManager: WeatherTileDisplayBridge
  isWeatherEngineLayer: (catalogId: string) => boolean
  /** 计算组状态：importedRaster 渐进产物勿在 computing 时标「完整数据」 */
  runLayerGroups?: ActiveRunLayerGroup[]
}

function isWorkflowProductComputing(
  layer: ActiveLayer,
  groups: ActiveRunLayerGroup[] | undefined,
): boolean {
  const jobStatus = layer.jobLayer?.status
  if (jobStatus === 'running' || jobStatus === 'queued' || jobStatus === 'retry_pending')
    return true
  if (layer.runGroupLocked) return true
  if (!layer.runGroupId || !groups?.length) return false
  const g = groups.find((x) => x.groupId === layer.runGroupId)
  return g?.status === 'computing'
}

/** 将 activeLayers 投影为侧栏/详情展示结构（从 layers store 热路径抽离）。 */
export function projectActiveLayersDisplay(ctx: ActiveLayersDisplayContext): ActiveLayerDisplay[] {
  return ctx.activeLayers
    .slice()
    .filter((layer) => !layer.isAdminBoundary && layer.catalogId !== 'admin-boundary')
    .sort((a, b) => b.order - a.order)
    .map((layer): ActiveLayerDisplay | null => {
      if (layer.importedVector) {
        const payload = layer.importedVector
        const persisted = resolvePersistedDisplayName(
          layer.instanceId,
          payload.backendLayerId,
          layer.catalogId,
        )
        const displayName = layer.name ?? persisted ?? payload.fileName ?? '导入图层'
        return {
          instanceId: layer.instanceId,
          catalogId: layer.catalogId,
          name: displayName,
          category: 'imported',
          description: `本地导入矢量（${payload.geometryType}）`,
          engine: 'local',
          supportsTime: false,
          runReadiness: 'ready',
          runReadinessSummary: '本地文件已加载',
          summary: `${payload.featureCount} 个要素 · ${payload.geometryType}`,
          metricLabel: '要素数',
          metricValue: String(payload.featureCount),
          trendLabel: '本地矢量叠加',
          statusLabel: '已导入',
          updateLabel: '本地文件',
          sourceLabel: payload.fileName ?? '本地导入',
          confidenceLabel: '本地数据',
          accentColor: layer.accentColor ?? '#7ee0a8',
          accentGlow: layer.accentGlow ?? 'rgba(126, 224, 168, 0.28)',
          chipTone: layer.chipTone ?? 'rgba(126, 224, 168, 0.16)',
          availabilityState: 'ready',
          availabilityLabel: '完整数据',
          availabilityDescription: `已载入 ${payload.featureCount} 个要素，可在图层列表控制显隐与导出。`,
          observationTimeLabel: '本地',
          missingFieldsLabel: '无',
          hotspots: [],
          isAdminBoundary: false,
          isImported: true,
          isImportedRaster: false,
          jobLayer: undefined,
          visible: layer.visible,
          opacity: layer.opacity,
          order: layer.order,
          dataState: 'imported',
          importedGeometryType: payload.geometryType,
          importedFeatureCount: payload.featureCount,
          importedVectorBackendLayerId: payload.backendLayerId,
          importedBounds: payload.bounds,
          importedFileName: payload.fileName,
          importedVectorStyle: payload.style,
        }
      }

      if (layer.importedRaster) {
        const payload = layer.importedRaster
        const displayName =
          layer.name ??
          resolvePersistedDisplayName(layer.instanceId, payload.overlayLayerId, layer.catalogId) ??
          payload.fileName ??
          '导入栅格'
        const hasTimes = Boolean(payload.timeList?.length)
        const timeCount = payload.timeList?.length ?? 0
        const computing = isWorkflowProductComputing(layer, ctx.runLayerGroups)
        const availabilityState = computing ? ('partial' as const) : ('ready' as const)
        const availabilityLabel = computing
          ? hasTimes
            ? `已到 ${timeCount} 个时间块`
            : '运行中'
          : hasTimes
            ? `${timeCount} 个时间块`
            : '完整数据'
        const availabilityDescription = computing
          ? hasTimes
            ? '工作流仍在计算；已到时间块可在底部时间轴查看，其余格为无数据。'
            : '工作流仍在计算，时间轴暂无可用时间块。'
          : hasTimes
            ? '时间序列已注册；底部时间轴按块覆盖日期着色。'
            : '已通过后端注册为 overlay，可在图层列表控制显隐与透明度。'
        return {
          instanceId: layer.instanceId,
          catalogId: layer.catalogId,
          name: displayName,
          category: 'imported',
          description: hasTimes ? '科学时间序列栅格（按块 / 时刻）' : '本地导入栅格（TIF overlay）',
          engine: 'local',
          supportsTime: hasTimes,
          runReadiness: 'ready',
          runReadinessSummary: computing ? '工作流计算中' : '本地栅格已注册',
          summary: hasTimes ? '时间序列栅格叠加' : '本地 TIF 栅格叠加',
          metricLabel: '类型',
          metricValue: '栅格',
          trendLabel: computing ? '工作流计算中' : hasTimes ? '科学时间序列' : '本地栅格叠加',
          statusLabel: computing ? '计算中' : '已导入',
          updateLabel: '本地文件',
          sourceLabel: payload.fileName ?? '本地导入',
          confidenceLabel: '本地数据',
          accentColor: layer.accentColor ?? '#7eb8e0',
          accentGlow: layer.accentGlow ?? 'rgba(126, 184, 224, 0.28)',
          chipTone: layer.chipTone ?? 'rgba(126, 184, 224, 0.16)',
          availabilityState,
          availabilityLabel,
          availabilityDescription,
          observationTimeLabel:
            payload.effectiveTimeLabel ||
            (hasTimes ? payload.timeList![payload.timeList!.length - 1]! : '静态'),
          missingFieldsLabel: '无',
          hotspots: [],
          isAdminBoundary: false,
          isImported: false,
          isImportedRaster: true,
          jobLayer: layer.jobLayer,
          visible: layer.visible,
          opacity: layer.opacity,
          order: layer.order,
          dataState: 'imported',
          importedRasterOverlayLayerId: payload.overlayLayerId,
          importedRasterBounds: payload.bounds,
          importedBounds: payload.bounds,
          importedRasterSourceCrs: payload.sourceCrs,
          importedRasterNativeStep:
            typeof payload.nativeStep === 'string'
              ? payload.nativeStep
              : payload.nativeStep
                ? `${payload.nativeStep.value}${payload.nativeStep.unit === 'hour' ? 'h' : payload.nativeStep.unit === 'day' ? 'd' : payload.nativeStep.unit === 'month' ? 'm' : 'yr'}`
                : undefined,
          importedRasterEffectiveTime: payload.effectiveTimeLabel,
          importedRasterTimeCount: payload.timeList?.length,
          importedFileName: payload.fileName,
          paletteOverride: layer.paletteOverride ?? null,
          vminOverride: layer.vminOverride ?? null,
          vmaxOverride: layer.vmaxOverride ?? null,
          nodataMode: layer.nodataMode ?? null,
          nodataColor: layer.nodataColor ?? null,
          runGroupId: layer.runGroupId,
          runGroupProductTag: layer.runGroupProductTag,
          runGroupLocked: layer.runGroupLocked,
        }
      }

      const item = buildCatalogFallbackItem(
        ctx.layerLibraryMap.get(layer.catalogId) ?? null,
        layer.catalogId,
      )
      const availability = buildAvailabilityState(layer, item, layer.jobLayer)
      const realDisplay = layer.jobLayer ? buildRealLayerDisplay(layer, item) : {}
      const descriptor = ctx.runtimeLayerCatalog[layer.catalogId] ?? null

      const isWeatherLayer = !layer.isAdminBoundary && ctx.isWeatherEngineLayer(layer.catalogId)
      const tileStats =
        isWeatherLayer && layer.visible ? ctx.weatherTileManager.getStats(layer.catalogId) : null
      const baseRenderHint = isWeatherLayer
        ? buildDefaultWeatherRenderHint(layer.catalogId, descriptor)
        : (layer.jobLayer?.mapLayerPayload?.renderHint ?? null)
      const weatherRenderHint =
        baseRenderHint && layer.paletteOverride
          ? { ...baseRenderHint, palette: layer.paletteOverride }
          : baseRenderHint
      let finalAvailability = availability
      if (isWeatherLayer && tileStats) {
        const layerStatus = ctx.weatherTileManager.getLayerStatus(layer.catalogId)
        if (layerStatus.errorType === 'data-empty') {
          finalAvailability = {
            state: 'empty' as const,
            label: '无有效数据',
            description: layerStatus.errorMessage || '本地模型无数据，请同步 Open-Meteo',
          }
        } else {
          const readyKind = resolveWeatherTileReadyKind(tileStats)
          if (readyKind === 'ready') {
            finalAvailability = {
              state: 'ready' as const,
              label: '完整数据',
              description: `已缓存全部 ${tileStats.visible} 个可视瓦片`,
            }
          } else if (readyKind === 'partial') {
            finalAvailability = {
              state: 'partial' as const,
              label: '加载中',
              description: `已缓存 ${tileStats.cached} / 可视 ${tileStats.visible} / 加载中 ${tileStats.pending}`,
            }
          } else {
            finalAvailability = {
              state: 'partial' as const,
              label: '等待瓦片',
              description: '正在等待瓦片调度',
            }
          }
        }
      }

      const rasterPayload = layer.importedRaster as
        import('./imported-raster').ImportedRasterPayload | undefined
      return {
        instanceId: layer.instanceId,
        catalogId: layer.catalogId,
        name: layer.isAdminBoundary
          ? '行政区边界'
          : (layer.name ??
            resolvePersistedDisplayName(layer.instanceId, layer.catalogId) ??
            item.name),
        category: layer.isAdminBoundary ? 'boundary' : item.category,
        description: layer.isAdminBoundary ? '广东省市级行政区边界叠加层。' : item.description,
        engine: layer.isAdminBoundary ? 'builtin' : item.engine,
        supportsTime: item.supportsTime,
        runReadiness: item.runReadiness,
        runReadinessSummary: item.runReadinessSummary,
        renderHint: weatherRenderHint ?? undefined,
        summary: layer.isAdminBoundary
          ? '广东省市级行政区边界叠加层'
          : (realDisplay.summary ?? item.description),
        metricLabel: layer.isAdminBoundary ? '边界层级' : item.metricLabel,
        metricValue: layer.isAdminBoundary ? '省市级' : (realDisplay.metricValue ?? '--'),
        trendLabel: layer.isAdminBoundary
          ? '静态矢量边界叠加'
          : isWeatherLayer
            ? 'tile manager 已接入'
            : (realDisplay.trendLabel ??
              (item.backendStatus === 'sample'
                ? '实验 provider 链路已接入'
                : item.supportsTime
                  ? '支持时间维度查询'
                  : '课题组数据已接入')),
        statusLabel: layer.isAdminBoundary
          ? '静态数据'
          : isWeatherLayer
            ? '瓦片数据'
            : (realDisplay.statusLabel ??
              (item.backendStatus === 'sample'
                ? '实验 Provider'
                : item.backendStatus === 'placeholder'
                  ? '占位图层'
                  : '目录已接入')),
        updateLabel: layer.isAdminBoundary ? '静态数据' : item.updateLabel,
        sourceLabel: layer.isAdminBoundary
          ? '广东省市级边界'
          : (realDisplay.sourceLabel ?? item.sourceLabel),
        confidenceLabel: layer.isAdminBoundary
          ? '置信度 100%'
          : (realDisplay.confidenceLabel ?? '以课题组数据为准'),
        accentColor: layer.accentColor ?? item.accentColor,
        accentGlow: layer.accentGlow ?? item.accentGlow,
        chipTone: layer.chipTone ?? item.chipTone,
        availabilityState: layer.isAdminBoundary ? 'ready' : finalAvailability.state,
        availabilityLabel: layer.isAdminBoundary ? '完整数据' : finalAvailability.label,
        availabilityDescription: layer.isAdminBoundary
          ? '静态矢量边界数据，已完整加载。'
          : (realDisplay.availabilityDescription ?? finalAvailability.description),
        observationTimeLabel: layer.isAdminBoundary
          ? '静态数据'
          : isWeatherLayer
            ? formatClockHourLabel(ctx.currentHour)
            : (realDisplay.observationTimeLabel ??
              (item.supportsTime ? formatClockHourLabel(ctx.currentHour) : '--')),
        missingFieldsLabel: layer.isAdminBoundary
          ? '无'
          : (realDisplay.missingFieldsLabel ?? item.runReadinessNotes[0] ?? '无'),
        hotspots: layer.isAdminBoundary ? [] : (realDisplay.hotspots ?? []),
        isAdminBoundary: layer.isAdminBoundary,
        isImported: false,
        isImportedRaster: Boolean(layer.importedRaster),
        jobLayer: layer.jobLayer,
        visible: layer.visible,
        opacity: layer.opacity,
        order: layer.order,
        dataState: layer.dataState,
        importedRasterOverlayLayerId: rasterPayload?.overlayLayerId,
        importedRasterBounds: rasterPayload?.bounds,
        importedBounds: rasterPayload?.bounds,
        importedRasterSourceCrs: rasterPayload?.sourceCrs,
        importedRasterNativeStep:
          typeof rasterPayload?.nativeStep === 'string'
            ? rasterPayload.nativeStep
            : rasterPayload?.nativeStep
              ? `${rasterPayload.nativeStep.value}${rasterPayload.nativeStep.unit === 'hour' ? 'h' : rasterPayload.nativeStep.unit === 'day' ? 'd' : rasterPayload.nativeStep.unit === 'month' ? 'm' : 'yr'}`
              : undefined,
        importedRasterEffectiveTime: rasterPayload?.effectiveTimeLabel,
        importedRasterTimeCount: rasterPayload?.timeList?.length ?? 0,
        paletteOverride: layer.paletteOverride ?? null,
        vminOverride: layer.vminOverride ?? null,
        vmaxOverride: layer.vmaxOverride ?? null,
        nodataMode: layer.nodataMode ?? null,
        nodataColor: layer.nodataColor ?? null,
        runGroupId: layer.runGroupId,
        runGroupProductTag: layer.runGroupProductTag,
        runGroupLocked: layer.runGroupLocked,
      }
    })
    .filter((d): d is ActiveLayerDisplay => d !== null)
}
