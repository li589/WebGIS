/**
 * 分析面板顶部摘要纯函数（角标 / 阶段文案），便于单测。
 */
import { ANALYSIS_COPY } from '../../ui-copy/analysis'

export type AnalysisStageKind =
  | 'empty'
  | 'weather'
  | 'local'
  | 'imported_vector'
  | 'imported_raster'
  | 'boundary'
  | 'workflow'
  | 'static'

export interface AnalysisStageInput {
  hasRealSelection: boolean
  isWeather: boolean
  isImported: boolean
  isImportedRaster: boolean
  isAdminBoundary: boolean
  canRunWorkflow: boolean
}

export function resolveAnalysisStageKind(input: AnalysisStageInput): AnalysisStageKind {
  if (!input.hasRealSelection) return 'empty'
  if (input.isWeather) return 'weather'
  if (input.isAdminBoundary) return 'boundary'
  if (input.isImported) return 'imported_vector'
  if (input.isImportedRaster) return 'imported_raster'
  if (input.canRunWorkflow) return 'workflow'
  return 'static'
}

export function resolveAnalysisStageLabel(kind: AnalysisStageKind): string {
  switch (kind) {
    case 'empty':
      return ANALYSIS_COPY.stageEmpty
    case 'weather':
      return ANALYSIS_COPY.stageWeather
    case 'imported_vector':
      return ANALYSIS_COPY.stageImportedVector
    case 'imported_raster':
      return ANALYSIS_COPY.stageImportedRaster
    case 'local':
      return ANALYSIS_COPY.stageLocal
    case 'boundary':
      return ANALYSIS_COPY.stageBoundary
    case 'workflow':
      return ANALYSIS_COPY.stageWorkflow
    default:
      return ANALYSIS_COPY.stageStatic
  }
}

export function resolveAnalysisSubtitle(kind: AnalysisStageKind): string {
  switch (kind) {
    case 'empty':
      return ANALYSIS_COPY.subtitleEmpty
    case 'weather':
      return ANALYSIS_COPY.subtitleWeather
    case 'workflow':
      return ANALYSIS_COPY.subtitleWorkflow
    case 'imported_vector':
      return ANALYSIS_COPY.subtitleImportedVector
    case 'imported_raster':
      return ANALYSIS_COPY.subtitleImportedRaster
    case 'boundary':
      return ANALYSIS_COPY.subtitleBoundary
    default:
      return ANALYSIS_COPY.subtitleStatic
  }
}

/** 工作流/天气阶段旁的人类可读文案 */
export function resolveWorkflowStageCopy(options: {
  stage: string
  progress: number
  isWeather?: boolean
  tilePending?: number
  tileCached?: number
}): string {
  const { stage, progress, isWeather, tilePending = 0, tileCached = 0 } = options
  if (isWeather) {
    if (tilePending > 0) return ANALYSIS_COPY.stageLoading
    if (tileCached > 0) return ANALYSIS_COPY.stageCached
  }
  if (stage === 'idle') {
    return isWeather ? ANALYSIS_COPY.stageIdleReady : ANALYSIS_COPY.stageIdleNotRun
  }
  if (stage === 'done' || stage === 'succeeded') return ANALYSIS_COPY.stageDone
  if (stage === 'failed') return ANALYSIS_COPY.stageFailed
  if (stage === 'loading' || stage === 'running') {
    return progress > 0
      ? `${ANALYSIS_COPY.stageLoading} ${Math.round(progress)}%`
      : ANALYSIS_COPY.stageLoading
  }
  if (stage === 'cached') return ANALYSIS_COPY.stageCached
  return stage
}

/** 静态/导入层提示文案 */
export function resolveStaticLayerHint(kind: AnalysisStageKind): string {
  switch (kind) {
    case 'imported_vector':
      return ANALYSIS_COPY.staticImportedVector
    case 'imported_raster':
      return ANALYSIS_COPY.staticImportedRaster
    case 'boundary':
      return ANALYSIS_COPY.staticBoundary
    case 'local':
      return ANALYSIS_COPY.staticImported
    default:
      return ANALYSIS_COPY.staticOverlay
  }
}
