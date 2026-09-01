import { describe, expect, it } from 'vitest'

import {
  canRunTool,
  fieldHintFor,
  initFormValues,
  needsRasterImportHint,
  numericRangeLabel,
  phaseLabelFor,
  runDisabledReasonFor,
  sanitizeFormValues,
  validateFormValues,
} from '@/components/info-panel/tools/tool-page-model'
import type { AnalysisToolDescriptor } from '@/services/analysis-api'

function makeTool(overrides: Partial<AnalysisToolDescriptor> = {}): AnalysisToolDescriptor {
  return {
    tool_id: 'gis.buffer',
    title: '缓冲区',
    description: '',
    category: 'gis',
    input_kinds: ['vector', 'point'],
    param_schema: [],
    workflow_template_id: 'analysis_buffer',
    outputs: ['table'],
    resource_profile: 'standard',
    concurrency_key: 'layer_tool',
    enabled: true,
    ...overrides,
  }
}

function makeDisplayLayer(overrides: Record<string, unknown> = {}) {
  return {
    instanceId: 'i1',
    catalogId: 'c1',
    name: '测试层',
    isImported: false,
    isImportedRaster: false,
    ...overrides,
  } as never
}

const point = { lng: 113.3, lat: 23.1 }

describe('canRunTool / runDisabledReasonFor', () => {
  it('buffer 需要选点或后端矢量层', () => {
    const tool = makeTool()
    const ctx = {
      displayLayer: makeDisplayLayer(),
      selectedMapPoint: null,
      hasMapBBox: true,
    }
    expect(canRunTool(tool, ctx)).toBe(false)
    expect(runDisabledReasonFor(tool, ctx)).toContain('选择模式')

    expect(canRunTool(tool, { ...ctx, selectedMapPoint: point })).toBe(true)
    expect(
      canRunTool(tool, {
        ...ctx,
        displayLayer: makeDisplayLayer({ isImported: true, importedVectorBackendLayerId: 'v1' }),
      }),
    ).toBe(true)
  })

  it('栅格工具需要可读栅格/overlay 图层', () => {
    const reclassify = makeTool({ tool_id: 'gis.reclassify', input_kinds: ['raster'] })
    const ctx = {
      displayLayer: makeDisplayLayer(),
      selectedMapPoint: null,
      hasMapBBox: true,
    }
    expect(canRunTool(reclassify, ctx)).toBe(false)
    expect(
      canRunTool(reclassify, {
        ...ctx,
        displayLayer: makeDisplayLayer({ importedRasterOverlayLayerId: 'r1' }),
      }),
    ).toBe(true)
    expect(
      canRunTool(reclassify, {
        ...ctx,
        displayLayer: makeDisplayLayer({ dataState: 'catalog', catalogId: 'c-overlay' }),
      }),
    ).toBe(true)
  })

  it('watershed 还需要选点，clip 还需要视口 bbox', () => {
    const watershed = makeTool({ tool_id: 'gis.watershed' })
    const rasterLayer = makeDisplayLayer({ isImportedRaster: true })
    const ctx = { displayLayer: rasterLayer, selectedMapPoint: null, hasMapBBox: true }
    expect(canRunTool(watershed, ctx)).toBe(false)
    expect(canRunTool(watershed, { ...ctx, selectedMapPoint: point })).toBe(true)

    const clip = makeTool({ tool_id: 'gis.clip' })
    expect(canRunTool(clip, { ...ctx, selectedMapPoint: point, hasMapBBox: false })).toBe(false)
    expect(canRunTool(clip, { ...ctx, selectedMapPoint: point, hasMapBBox: true })).toBe(true)
  })

  it('未知非栅格工具在 enabled 时可运行', () => {
    const unknown = makeTool({ tool_id: 'stats.histogram', input_kinds: ['any'] })
    const ctx = { displayLayer: makeDisplayLayer(), selectedMapPoint: null, hasMapBBox: true }
    expect(canRunTool(unknown, ctx)).toBe(true)
  })
})

describe('needsRasterImportHint', () => {
  it('前端与后端的缺栅格文案均命中引导', () => {
    expect(needsRasterImportHint('需要已导入的静态栅格图层')).toBe(true)
    expect(needsRasterImportHint('天气瓦片层请先导出/导入为静态栅格后再分析')).toBe(true)
  })

  it('其他原因与空值不命中', () => {
    expect(needsRasterImportHint('需要已导入的矢量图层')).toBe(false)
    expect(needsRasterImportHint('当前图层类型「vector」不支持该工具')).toBe(false)
    expect(needsRasterImportHint('')).toBe(false)
    expect(needsRasterImportHint(null)).toBe(false)
    expect(needsRasterImportHint(undefined)).toBe(false)
  })
})

describe('initFormValues', () => {
  it('default 优先，enum 无 default 取首个选项', () => {
    const tool = makeTool({
      param_schema: [
        { key: 'distance', type: 'number', title: '距离', default: 300 },
        { key: 'mode', type: 'enum', title: '模式', options: ['a', 'b'] },
        { key: 'note', type: 'string', title: '备注' },
      ],
    })
    const values = initFormValues(tool)
    expect(values.distance).toBe(300)
    expect(values.mode).toBe('a')
    expect(values.note).toBeUndefined()
  })

  it('buffer 距离完全来自 schema default', () => {
    const tool = makeTool({
      param_schema: [
        { key: 'distance', type: 'number', title: '距离', default: 500 },
        { key: 'distance_unit', type: 'enum', title: '单位', default: 'meters', options: ['meters', 'kilometers'] },
      ],
    })
    const values = initFormValues(tool)
    expect(values.distance).toBe(500)
    expect(values.distance_unit).toBe('meters')
  })
})

describe('validateFormValues — remap / expression', () => {
  it('remap_table 格式非法时报错', () => {
    const tool = makeTool({
      tool_id: 'gis.reclassify',
      param_schema: [{ key: 'remap_table', type: 'string', title: '分级表' }],
    })
    const bad = validateFormValues(tool, { remap_table: 'bad-format' })
    expect(bad.ok).toBe(false)
    expect(bad.errors.remap_table).toContain('min-max:class')

    const good = validateFormValues(tool, { remap_table: '0-10:1,10-100:2' })
    expect(good.ok).toBe(true)
  })

  it('raster_calc expression 非空且字符白名单', () => {
    const tool = makeTool({
      tool_id: 'gis.raster_calc',
      param_schema: [{ key: 'expression', type: 'string', title: '表达式' }],
    })
    const bad = validateFormValues(tool, { expression: 'A;DROP' })
    expect(bad.ok).toBe(false)
    const good = validateFormValues(tool, { expression: '(A+1)/2' })
    expect(good.ok).toBe(true)
  })
})

describe('validateFormValues / sanitizeFormValues', () => {
  it('枚举值非法时报错，数值越界时报错', () => {
    const tool = makeTool({
      param_schema: [
        { key: 'mode', type: 'enum', title: '模式', options: ['a', 'b'] },
        { key: 'n', type: 'integer', title: 'N', min: 1, max: 10 },
      ],
    })
    const bad = validateFormValues(tool, { mode: 'c', n: 99 })
    expect(bad.ok).toBe(false)
    expect(bad.errors.mode).toContain('a, b')
    expect(bad.errors.n).toBe('最大值: 10')

    const good = validateFormValues(tool, { mode: 'a', n: 5 })
    expect(good.ok).toBe(true)
  })

  it('清洗字符串：trim + 去尖括号，空值剔除', () => {
    const out = sanitizeFormValues({ a: '  x<y>  ', b: '', c: null, d: 3 })
    expect(out).toEqual({ a: 'xy', d: 3 })
  })
})

describe('field hints', () => {
  it('clip 的 bbox 字段提示来自前端补充表', () => {
    const hint = fieldHintFor(
      { key: 'west', type: 'number', title: 'West' },
      'gis.clip',
    )
    expect(hint).toContain('留空')
  })

  it('其他工具回落到 schema description', () => {
    const hint = fieldHintFor(
      { key: 'expression', type: 'string', title: '表达式', description: '如 A*2' },
      'gis.raster_calc',
    )
    expect(hint).toBe('如 A*2')
  })

  it('数值范围小字包含 min/max 与单位', () => {
    const label = numericRangeLabel({ key: 'd', type: 'number', title: 'D', min: 1, max: 100, unit: 'm' })
    expect(label).toBe('1 ~ 100 m')
  })
})

describe('phaseLabelFor', () => {
  it('映射运行阶段文案', () => {
    expect(phaseLabelFor(undefined)).toBe('')
    expect(phaseLabelFor('idle')).toBe('')
    expect(phaseLabelFor('queued')).toBe('排队中')
    expect(phaseLabelFor('running')).toBe('运行中')
    expect(phaseLabelFor('succeeded')).toBe('已完成')
  })
})
