/**
 * 分析工具子页纯逻辑：页面状态、可运行判定、表单初始化与校验。
 * 与渲染解耦，便于单测；InfoPanelToolsTab 仅做编排。
 */
import type { AnalysisToolDescriptor, AnalysisToolParamField } from '../../../services/analysis-api'
import {
  buildToolRunContext,
  hasDraftVector,
  hasPersistedVector,
  inferToolInputRequirement,
  layerHasReadableRaster,
  type ToolRunContext,
} from './tool-layer-capabilities'

export type ToolPage = { kind: 'list' } | { kind: 'tool'; toolId: string } | { kind: 'extract' }

export type { ToolRunContext }
export { buildToolRunContext }

const REMAP_SEGMENT_RE = /^\s*(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?):(\S+)\s*$/
const RASTER_EXPRESSION_RE = /^[A0-9+\-*/().,\s]+$/

export function canRunTool(tool: AnalysisToolDescriptor, ctx: ToolRunContext): boolean {
  if (!tool.enabled) return false
  const req = inferToolInputRequirement(tool)
  const hasRaster = layerHasReadableRaster(ctx.displayLayer)
  const hasVector = hasPersistedVector(ctx.displayLayer)
  const hasPoint = Boolean(ctx.selectedMapPoint)

  switch (tool.tool_id) {
    case 'gis.buffer':
      return hasPoint || hasVector
    case 'gis.vector_to_raster':
      return hasVector
    case 'gis.watershed':
      return hasRaster && hasPoint
    case 'gis.clip':
      return hasRaster && ctx.hasMapBBox
    default:
      if (req.needsRaster) return hasRaster
      if (req.needsVector) return hasVector
      return true
  }
}

export function runDisabledReasonFor(
  tool: AnalysisToolDescriptor,
  ctx: ToolRunContext,
): string | null {
  if (!tool.enabled) return tool.disabled_reason || '当前图层不可用'

  const req = inferToolInputRequirement(tool)
  const hasRaster = layerHasReadableRaster(ctx.displayLayer)
  const hasVector = hasPersistedVector(ctx.displayLayer)
  const hasPoint = Boolean(ctx.selectedMapPoint)

  switch (tool.tool_id) {
    case 'gis.buffer':
      if (hasDraftVector(ctx.displayLayer)) {
        return '绘制矢量需先保存或导入到后端后再分析，或进入选择模式在地图选点'
      }
      if (!hasPoint && !hasVector) {
        return '请先进入选择模式并在地图选点，或使用已导入且带后端 id 的矢量层'
      }
      break
    case 'gis.vector_to_raster':
      if (hasDraftVector(ctx.displayLayer)) return '绘制矢量需先保存或导入到后端后再分析'
      if (!hasVector) return '需要已导入的矢量图层'
      break
    case 'gis.watershed':
      if (!hasRaster) return '需要静态栅格或物化 overlay 图层（对当前快照分析）'
      if (!hasPoint) return '请先进入选择模式并在地图选点作为汇流点'
      break
    case 'gis.clip':
      if (!hasRaster) return '需要静态栅格或物化 overlay 图层'
      if (!ctx.hasMapBBox) return '无法获取当前视口 bbox'
      break
    default:
      if (req.needsRaster && !hasRaster) {
        return '需要静态栅格或物化 overlay 图层（对当前物化/静态快照分析）'
      }
      if (req.needsVector && !hasVector) {
        if (hasDraftVector(ctx.displayLayer)) return '绘制矢量需先保存或导入到后端后再分析'
        return '需要已导入的矢量图层'
      }
  }
  return null
}

/** 禁用原因是否指向「缺少静态栅格数据」→ 卡片应附「去导入数据」引导 */
export function needsRasterImportHint(reason: string | null | undefined): boolean {
  if (!reason) return false
  return reason.includes('静态栅格') || reason.includes('物化 overlay')
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

function validateRemapTable(raw: unknown): string | null {
  const val = String(raw ?? '').trim()
  if (!val) return '分级表不能为空'
  const segments = val.split(',')
  if (segments.length === 0) return '格式：min-max:class，逗号分隔'
  for (const seg of segments) {
    if (!REMAP_SEGMENT_RE.test(seg)) {
      return '格式：min-max:class，逗号分隔（如 0-10:1,10-100:2）'
    }
  }
  return null
}

function validateRasterExpression(raw: unknown): string | null {
  const val = String(raw ?? '').trim()
  if (!val) return '表达式不能为空'
  if (!RASTER_EXPRESSION_RE.test(val)) {
    return '表达式仅支持 A 变量与 + - * / ( ) 及数字'
  }
  return null
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

  if (
    tool.tool_id === 'gis.reclassify' &&
    values.remap_table != null &&
    values.remap_table !== ''
  ) {
    const remapErr = validateRemapTable(values.remap_table)
    if (remapErr) errors.remap_table = remapErr
  }
  if (tool.tool_id === 'gis.raster_calc' && values.expression != null && values.expression !== '') {
    const exprErr = validateRasterExpression(values.expression)
    if (exprErr) errors.expression = exprErr
  }

  return { ok: Object.keys(errors).length === 0, errors }
}

/** clip 在有视口时隐藏的 bbox 字段（由 onRun 注入） */
export const CLIP_BBOX_FIELD_KEYS = new Set(['west', 'south', 'east', 'north'])

/** 前端补充的逐字段提示（schema description 之外的交互语义） */
export const TOOL_FIELD_HINTS: Record<string, Record<string, string>> = {
  'gis.clip': {
    west: '留空则取当前地图视口',
    south: '留空则取当前地图视口',
    east: '留空则取当前地图视口',
    north: '留空则取当前地图视口',
  },
  'gis.zonal_stats': {
    zones_imported_vector_layer_id: '从下拉选择已导入矢量层（backend id）',
    zones_overlay_layer_id: '栅格分区 overlay id（高级，一般留空）',
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

export function formatMapBBoxSummary(bbox: {
  west: number
  south: number
  east: number
  north: number
}): string {
  return `W ${bbox.west.toFixed(4)} · S ${bbox.south.toFixed(4)} · E ${bbox.east.toFixed(4)} · N ${bbox.north.toFixed(4)}`
}
