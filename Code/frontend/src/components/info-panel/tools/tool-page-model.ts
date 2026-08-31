/**
 * 分析工具子页纯逻辑：页面状态、可运行判定、表单初始化与校验。
 * 与渲染解耦，便于单测；InfoPanelToolsTab 仅做编排。
 */
import type { ActiveLayerDisplay } from '../../../stores/layers/types'
import type { AnalysisToolDescriptor, AnalysisToolParamField } from '../../../services/analysis-api'

export type ToolPage = { kind: 'list' } | { kind: 'tool'; toolId: string } | { kind: 'extract' }

/** 需要已导入静态栅格图层作为输入的工具（目录真源在后端 analysis_tools.json） */
const RASTER_INPUT_TOOLS = new Set([
  'gis.clip',
  'gis.reclassify',
  'gis.zonal_stats',
  'gis.contour',
  'gis.slope_aspect',
  'gis.raster_calc',
  'gis.raster_to_vector',
  'gis.watershed',
])

export interface ToolRunContext {
  displayLayer: ActiveLayerDisplay
  selectedMapPoint: { lng: number; lat: number } | null
  hasMapBBox: boolean
}

function hasBackendVector(displayLayer: ActiveLayerDisplay): boolean {
  return Boolean(displayLayer.isImported && displayLayer.importedVectorBackendLayerId)
}

function hasImportedRaster(displayLayer: ActiveLayerDisplay): boolean {
  return Boolean(displayLayer.isImportedRaster || displayLayer.importedRasterOverlayLayerId)
}

export function canRunTool(tool: AnalysisToolDescriptor, ctx: ToolRunContext): boolean {
  if (!tool.enabled) return false
  switch (tool.tool_id) {
    case 'gis.buffer':
      return Boolean(ctx.selectedMapPoint) || hasBackendVector(ctx.displayLayer)
    case 'gis.vector_to_raster':
      return hasBackendVector(ctx.displayLayer)
    case 'gis.watershed':
      return hasImportedRaster(ctx.displayLayer) && Boolean(ctx.selectedMapPoint)
    case 'gis.clip':
      return hasImportedRaster(ctx.displayLayer) && ctx.hasMapBBox
    default:
      if (RASTER_INPUT_TOOLS.has(tool.tool_id)) return hasImportedRaster(ctx.displayLayer)
      return true
  }
}

export function runDisabledReasonFor(
  tool: AnalysisToolDescriptor,
  ctx: ToolRunContext,
): string | null {
  if (!tool.enabled) return tool.disabled_reason || '当前图层不可用'
  switch (tool.tool_id) {
    case 'gis.buffer':
      if (!ctx.selectedMapPoint && !hasBackendVector(ctx.displayLayer)) {
        return '请先进入选择模式并在地图选点，或使用已导入且带后端 id 的矢量层'
      }
      break
    case 'gis.vector_to_raster':
      if (!hasBackendVector(ctx.displayLayer)) return '需要已导入的矢量图层'
      break
    case 'gis.watershed':
      if (!hasImportedRaster(ctx.displayLayer)) return '需要已导入的静态栅格图层'
      if (!ctx.selectedMapPoint) return '请先进入选择模式并在地图选点作为汇流点'
      break
    case 'gis.clip':
      if (!hasImportedRaster(ctx.displayLayer)) return '需要已导入的静态栅格图层'
      if (!ctx.hasMapBBox) return '无法获取当前视口 bbox'
      break
    default:
      if (RASTER_INPUT_TOOLS.has(tool.tool_id) && !hasImportedRaster(ctx.displayLayer)) {
        return '需要已导入的静态栅格图层'
      }
  }
  return null
}

/** 禁用原因是否指向「缺少静态栅格数据」→ 卡片应附「去导入数据」引导 */
export function needsRasterImportHint(reason: string | null | undefined): boolean {
  if (!reason) return false
  return reason.includes('静态栅格')
}

/** 按参数 schema 初始化表单值：default 优先，enum 无 default 取首个选项。 */
export function initFormValues(tool: AnalysisToolDescriptor): Record<string, unknown> {
  const values: Record<string, unknown> = {}
  for (const field of tool.param_schema) {
    if (field.default !== undefined && field.default !== null) {
      values[field.key] = field.default
      continue
    }
    if (field.type === 'enum' && field.options && field.options.length > 0) {
      values[field.key] = field.options[0]
    }
  }
  if (tool.tool_id === 'gis.buffer' && values.distance == null) {
    values.distance = 5000
    values.distance_unit = values.distance_unit ?? 'meters'
  }
  return values
}

/** Sanitize string param values: trim whitespace and strip angle-bracket tags. */
export function sanitizeParamValue(raw: unknown): string {
  if (typeof raw !== 'string') return String(raw ?? '')
  return raw.trim().replace(/[<>]/g, '')
}

export function sanitizeFormValues(values: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(values)) {
    if (value === '' || value === null || value === undefined) continue
    out[key] = typeof value === 'string' ? sanitizeParamValue(value) : value
  }
  return out
}

export function validateFormValues(
  tool: AnalysisToolDescriptor,
  values: Record<string, unknown>,
): { ok: boolean; errors: Record<string, string> } {
  const errors: Record<string, string> = {}
  for (const field of tool.param_schema) {
    const val = values[field.key]
    if (val === undefined || val === null || val === '') continue

    if (field.options && field.options.length > 0) {
      if (!field.options.includes(String(val))) {
        errors[field.key] = `值必须在: ${field.options.join(', ')}`
        continue
      }
    }

    if (field.type === 'number' || field.type === 'integer') {
      const num = Number(val)
      if (!Number.isFinite(num)) {
        errors[field.key] = '请输入有效数字'
        continue
      }
      if (field.min != null && num < field.min) errors[field.key] = `最小值: ${field.min}`
      if (field.max != null && num > field.max) errors[field.key] = `最大值: ${field.max}`
    }
  }
  return { ok: Object.keys(errors).length === 0, errors }
}

/** 前端补充的逐字段提示（schema description 之外的交互语义） */
export const TOOL_FIELD_HINTS: Record<string, Record<string, string>> = {
  'gis.clip': {
    west: '留空则取当前地图视口',
    south: '留空则取当前地图视口',
    east: '留空则取当前地图视口',
    north: '留空则取当前地图视口',
  },
}

export function fieldHintFor(field: AnalysisToolParamField, toolId: string): string {
  return TOOL_FIELD_HINTS[toolId]?.[field.key] ?? field.description ?? ''
}

/** 数值字段的取值范围小字（如 “100 ~ 5000 m”） */
export function numericRangeLabel(field: AnalysisToolParamField): string {
  if (field.type !== 'number' && field.type !== 'integer') return ''
  if (field.min == null && field.max == null && !field.unit) return ''
  const parts: string[] = []
  if (field.min != null || field.max != null) {
    parts.push(`${field.min ?? '…'} ~ ${field.max ?? '…'}`)
  }
  if (field.unit) parts.push(field.unit)
  return parts.join(' ')
}

export function phaseLabelFor(phase: string | undefined | null): string {
  if (!phase || phase === 'idle') return ''
  const map: Record<string, string> = {
    queued: '排队中',
    submitting: '提交中',
    running: '运行中',
    succeeded: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return map[phase] || phase
}
