/**
 * W3.4c/W3.6：useTimelineSync 组合式函数测试。
 *
 * 重点覆盖工作流进度 seek 消费路径（W3.6 P-02）：
 *  - workflowProgressTimeSeek watch → seekTimelineToWorkflowProgressTimeKey
 *  - 同组放行 / 异组忽略 / 锁与播放互斥
 *  - 运行启动 start_at 对齐、切层记忆恢复、渐进 time_list 跟随
 *  - refreshImportedRasterEffectiveTimes、timelineSegments 基础形态
 */
import { computed, nextTick, reactive, ref, type ComputedRef, type Ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useTimelineSync } from '@/views/dashboard/useTimelineSync'
import type {
  ActiveLayer,
  ActiveRunLayerGroup,
  JobLayerItem,
} from '@/stores/layers/types'
import type { OverlayTimeState } from '@/components/map/overlay-image-module'
import type { WorkflowProgressTimeSeekHint } from '@/utils/workflow-timekey-seek'

// ── Mock selectors（闭包在调用期读取模块级引用，规避 vi.mock 提升问题）─────────

let mockActiveLayers: Ref<ActiveLayer[]>
let mockJobLayers: Ref<JobLayerItem[]>
let mockRunGroups: Ref<ActiveRunLayerGroup[]>

const workspaceCalls = {
  setCurrentHour: vi.fn(),
  isWeatherEngineLayer: vi.fn((_catalogId: string) => false),
  resolveEffectiveDescriptor: vi.fn(() => null),
  getOnlineTemporalConfig: vi.fn(() => null),
}

vi.mock('@/stores/layers/selectors', () => ({
  useLayerWorkspace: () => ({
    get activeLayers() {
      return mockActiveLayers
    },
    setCurrentHour: workspaceCalls.setCurrentHour,
    isWeatherEngineLayer: workspaceCalls.isWeatherEngineLayer,
    resolveEffectiveDescriptor: workspaceCalls.resolveEffectiveDescriptor,
    getOnlineTemporalConfig: workspaceCalls.getOnlineTemporalConfig,
  }),
  useWorkflowRun: () => ({
    get jobLayers() {
      return mockJobLayers
    },
    get runLayerGroups() {
      return mockRunGroups
    },
  }),
}))

// ── Harness ───────────────────────────────────────────────────────────────────

interface SyncHarness {
  uiStore: {
    applyDateHour: ReturnType<typeof vi.fn>
    applyTimelineFromLayerGranularity: ReturnType<typeof vi.fn>
    rememberLayerTime: ReturnType<typeof vi.fn>
    restoreLayerTime: ReturnType<typeof vi.fn>
    isLayerTimeLocked: ReturnType<typeof vi.fn>
    analysisFocusRequest: { kind: string } | null
  }
  logOperation: ReturnType<typeof vi.fn>
  getLayerStatus: ReturnType<typeof vi.fn>
  setOverlayTime: ReturnType<typeof vi.fn>
  showPanel: ReturnType<typeof vi.fn>
  weatherCoverage: Ref<null>
  selectedLayerDisplay: Ref<{ catalogId?: string; instanceId?: string } | null>
  overlayTimeStates: Ref<OverlayTimeState[]>
  currentHour: Ref<number>
  currentDate: Ref<Date>
  unifiedTimeLock: Ref<boolean>
  isPlaying: Ref<boolean>
  weatherStatusVersion: Ref<number>
  weatherActivityVersion: Ref<number>
  workflowProgressTimeSeek: Ref<WorkflowProgressTimeSeekHint | null>
  sync: ReturnType<typeof useTimelineSync>
  activeLayer: ComputedRef<{
    catalogId?: string
    name?: string
    availabilityLabel?: string
    observationTimeLabel?: string
    runReadiness?: unknown
  }>
}

let idSeq = 0

function makeLayer(overrides: Partial<ActiveLayer> = {}): ActiveLayer {
  idSeq += 1
  return {
    instanceId: `inst-${idSeq}`,
    catalogId: `cat-${idSeq}`,
    name: `Layer ${idSeq}`,
    visible: true,
    opacity: 1,
    order: idSeq,
    isAdminBoundary: false,
    dataState: 'catalog',
    ...overrides,
  }
}

function setupSync(initial: { layers?: ActiveLayer[]; selectedCatalogId?: string } = {}): SyncHarness {
  mockActiveLayers = ref(initial.layers ?? [])
  mockJobLayers = ref<JobLayerItem[]>([])
  mockRunGroups = ref<ActiveRunLayerGroup[]>([])

  const uiStore = reactive({
    applyDateHour: vi.fn(),
    applyTimelineFromLayerGranularity: vi.fn(),
    rememberLayerTime: vi.fn(),
    restoreLayerTime: vi.fn((): { date: Date; hour: number } | null => null),
    isLayerTimeLocked: vi.fn(() => false),
    analysisFocusRequest: ref<{ kind: string } | null>(null),
  })
  const logOperation = vi.fn()
  const logStore = { logOperation }
  const getLayerStatus = vi.fn(() => null)
  const weatherTileManager = { getLayerStatus }
  const weatherCoverage = ref(null)
  const setOverlayTime = vi.fn()
  const mapCanvasRef = ref({ setOverlayTime } as unknown as {
    setOverlayTime: (id: string, label: string) => void
  })
  const showPanel = vi.fn()
  const analysisPanelRef = ref({ showPanel } as unknown as { showPanel: () => void })
  const selectedLayerDisplay = ref<{ catalogId?: string; instanceId?: string } | null>(
    initial.selectedCatalogId ? { catalogId: initial.selectedCatalogId } : null,
  )
  const activeLayer = computed(() => {
    const catalogId = selectedLayerDisplay.value?.catalogId
    const layer = mockActiveLayers.value.find((l) => l.catalogId === catalogId)
    return {
      catalogId: layer?.catalogId,
      name: layer?.name,
      availabilityLabel: undefined,
      observationTimeLabel: undefined,
      runReadiness: undefined,
    }
  })
  const overlayTimeStates = ref<OverlayTimeState[]>([])
  const currentHour = ref(12)
  const currentDate = ref(new Date(Date.UTC(2026, 4, 1, 0, 0, 0)))
  const unifiedTimeLock = ref(false)
  const isPlaying = ref(false)
  const weatherStatusVersion = ref(0)
  const weatherActivityVersion = ref(0)
  const workflowProgressTimeSeek = ref<WorkflowProgressTimeSeekHint | null>(null)

  const sync = useTimelineSync(
    uiStore as unknown as Parameters<typeof useTimelineSync>[0],
    logStore as unknown as Parameters<typeof useTimelineSync>[1],
    weatherTileManager as unknown as Parameters<typeof useTimelineSync>[2],
    weatherCoverage,
    mapCanvasRef as unknown as Parameters<typeof useTimelineSync>[4],
    selectedLayerDisplay,
    activeLayer,
    overlayTimeStates,
    currentHour,
    currentDate,
    unifiedTimeLock,
    isPlaying,
    weatherStatusVersion,
    weatherActivityVersion,
    workflowProgressTimeSeek,
    analysisPanelRef as unknown as Parameters<typeof useTimelineSync>[15],
  )

  return {
    uiStore,
    logOperation,
    getLayerStatus,
    setOverlayTime,
    showPanel,
    weatherCoverage,
    selectedLayerDisplay,
    overlayTimeStates,
    currentHour,
    currentDate,
    unifiedTimeLock,
    isPlaying,
    weatherStatusVersion,
    weatherActivityVersion,
    workflowProgressTimeSeek,
    activeLayer,
    sync,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  workspaceCalls.isWeatherEngineLayer.mockReturnValue(false)
  workspaceCalls.resolveEffectiveDescriptor.mockReturnValue(null)
  workspaceCalls.getOnlineTemporalConfig.mockReturnValue(null)
})

// ── 基础 computed ─────────────────────────────────────────────────────────────

describe('基础 computed', () => {
  it('未选图层时空闲标签', () => {
    const h = setupSync()
    expect(h.sync.hasTimelineLayer.value).toBe(false)
    expect(h.sync.selectedCatalogId.value).toBeNull()
    expect(h.sync.timelineLayerName.value).toBe('未选择图层')
    expect(h.sync.timelineAvailabilityLabel.value).toBe('空闲')
    expect(h.sync.timelineObservationLabel.value).toBe('—')
  })

  it('选中图层后展示层名与占位标签', () => {
    const layer = makeLayer({ catalogId: 'cat-a', name: '土壤水分' })
    const h = setupSync({ layers: [layer], selectedCatalogId: 'cat-a' })
    expect(h.sync.hasTimelineLayer.value).toBe(true)
    expect(h.sync.timelineLayerName.value).toBe('土壤水分')
    expect(h.sync.timelineAvailabilityLabel.value).toBe('—')
  })

  it('tileForecastHour 立即同步 currentHour 到 workspace', () => {
    setupSync()
    expect(workspaceCalls.setCurrentHour).toHaveBeenCalled()
  })

  it('isLayerLocked 委托 uiStore', () => {
    const layer = makeLayer({ catalogId: 'cat-a' })
    const unlocked = setupSync({ layers: [layer], selectedCatalogId: 'cat-a' })
    expect(unlocked.sync.isLayerLocked.value).toBe(false)
    const locked = setupSync({ layers: [layer], selectedCatalogId: 'cat-a' })
    locked.uiStore.isLayerTimeLocked.mockReturnValue(true)
    expect(locked.sync.isLayerLocked.value).toBe(true)
  })
})

// ── 工作流进度 seek（W3.6 核心）────────────────────────────────────────────────

describe('workflowProgressTimeSeek 消费', () => {
  function makeScienceLayer(catalogId: string, runGroupId?: string): ActiveLayer {
    return makeLayer({
      catalogId,
      runGroupId,
      dataState: 'imported',
      importedRaster: {
        overlayLayerId: `ov-${catalogId}`,
        nativeStep: '8d',
        timeList: ['20240425_20240502', '20240501_20240508'],
      },
    })
  }

  it('hint 命中选中图层：对齐日期/粒度并 seek overlay 时间', async () => {
    const layer = makeScienceLayer('cat-run')
    const h = setupSync({ layers: [layer], selectedCatalogId: 'cat-run' })
    h.workflowProgressTimeSeek.value = {
      runId: 'run-0001-aaaa',
      catalogId: 'cat-run',
      timeKey: '20240501',
      sliceLabel: '20240501_20240508',
      at: new Date().toISOString(),
    }
    await nextTick()
    expect(h.uiStore.applyDateHour).toHaveBeenCalledTimes(1)
    const [seekDate, hour] = h.uiStore.applyDateHour.mock.calls[0] as [Date, number]
    expect(seekDate.getFullYear()).toBe(2024)
    expect(seekDate.getMonth()).toBe(4)
    expect(seekDate.getDate()).toBe(1)
    expect(hour).toBe(0)
    expect(h.uiStore.applyTimelineFromLayerGranularity).toHaveBeenCalledWith('day')
    expect(h.uiStore.rememberLayerTime).toHaveBeenCalledWith('cat-run')
    expect(h.setOverlayTime).toHaveBeenCalledWith('ov-cat-run', '20240501_20240508')
    expect(h.logOperation).toHaveBeenCalledWith(
      'timeline-seek-workflow',
      expect.stringContaining('工作流块 run-0001'),
    )
  })

  it('sliceLabel 未命中 time_list 时回退原标签', async () => {
    const layer = makeScienceLayer('cat-run')
    const h = setupSync({ layers: [layer], selectedCatalogId: 'cat-run' })
    h.workflowProgressTimeSeek.value = {
      runId: 'run-0001',
      catalogId: 'cat-run',
      timeKey: '20240510',
      sliceLabel: '20240510',
      at: new Date().toISOString(),
    }
    await nextTick()
    expect(h.setOverlayTime).toHaveBeenCalledWith('ov-cat-run', '20240510')
  })

  it('hint 属其它 catalog 且不同运行组时忽略', async () => {
    const selected = makeScienceLayer('cat-a')
    const other = makeScienceLayer('cat-b')
    const h = setupSync({ layers: [selected, other], selectedCatalogId: 'cat-a' })
    h.workflowProgressTimeSeek.value = {
      runId: 'run-1',
      catalogId: 'cat-b',
      timeKey: '20240501',
      sliceLabel: '20240501',
      at: new Date().toISOString(),
    }
    await nextTick()
    expect(h.uiStore.applyDateHour).not.toHaveBeenCalled()
    expect(h.setOverlayTime).not.toHaveBeenCalled()
  })

  it('hint 属同运行组其它成员时放行并对组内 overlay seek', async () => {
    const sm = makeScienceLayer('cat-sm', 'g1')
    const vod = makeScienceLayer('cat-vod', 'g1')
    const h = setupSync({ layers: [sm, vod], selectedCatalogId: 'cat-vod' })
    h.workflowProgressTimeSeek.value = {
      runId: 'run-1',
      catalogId: 'cat-sm',
      timeKey: '20240501',
      sliceLabel: '20240501_20240508',
      at: new Date().toISOString(),
    }
    await nextTick()
    expect(h.uiStore.applyDateHour).toHaveBeenCalledTimes(1)
    // members = 同组且有 overlay 的成员；选中成员 cat-vod 也在组内
    expect(h.setOverlayTime).toHaveBeenCalledWith('ov-cat-vod', '20240501_20240508')
  })

  it('统一时间锁 / 播放中 / 图层时间锁定时忽略', async () => {
    const layer = makeScienceLayer('cat-run')
    const hint: WorkflowProgressTimeSeekHint = {
      runId: 'run-1',
      catalogId: 'cat-run',
      timeKey: '20240501',
      sliceLabel: '20240501',
      at: new Date().toISOString(),
    }

    const lockAll = setupSync({ layers: [layer], selectedCatalogId: 'cat-run' })
    lockAll.unifiedTimeLock.value = true
    lockAll.workflowProgressTimeSeek.value = hint
    await nextTick()
    expect(lockAll.uiStore.applyDateHour).not.toHaveBeenCalled()

    const playing = setupSync({ layers: [layer], selectedCatalogId: 'cat-run' })
    playing.isPlaying.value = true
    playing.workflowProgressTimeSeek.value = hint
    await nextTick()
    expect(playing.uiStore.applyDateHour).not.toHaveBeenCalled()

    const layerLocked = setupSync({ layers: [layer], selectedCatalogId: 'cat-run' })
    layerLocked.uiStore.isLayerTimeLocked.mockReturnValue(true)
    layerLocked.workflowProgressTimeSeek.value = hint
    await nextTick()
    expect(layerLocked.uiStore.applyDateHour).not.toHaveBeenCalled()
  })

  it('非法 timeKey 不产生 seek', async () => {
    const layer = makeScienceLayer('cat-run')
    const h = setupSync({ layers: [layer], selectedCatalogId: 'cat-run' })
    h.workflowProgressTimeSeek.value = {
      runId: 'run-1',
      catalogId: 'cat-run',
      timeKey: 'garbage',
      sliceLabel: 'garbage',
      at: new Date().toISOString(),
    }
    await nextTick()
    expect(h.uiStore.applyDateHour).not.toHaveBeenCalled()
  })
})

// ── 运行启动对齐 / 切层记忆 ───────────────────────────────────────────────────

describe('运行启动与切层记忆', () => {
  it('job 带 expectedTimeRange 时轴对齐 start_at', async () => {
    const layer = makeLayer({ catalogId: 'cat-run', jobLayer: undefined })
    const h = setupSync({ layers: [layer], selectedCatalogId: 'cat-run' })
    mockJobLayers.value = [
      {
        jobId: 'run-1',
        name: 'T',
        commandType: 'analysis',
        status: 'running',
        progress: 0,
        createdAt: '',
        updatedAt: '',
        message: '',
        catalogId: 'cat-run',
        expectedTimeRange: { start_at: '20240425', end_at: '20240530' },
      },
    ]
    await nextTick()
    await nextTick()
    expect(h.uiStore.applyDateHour).toHaveBeenCalledTimes(1)
    const [alignDate, hour] = h.uiStore.applyDateHour.mock.calls[0] as [Date, number]
    expect(alignDate.getDate()).toBe(25)
    expect(alignDate.getMonth()).toBe(3)
    expect(hour).toBe(0)
  })

  it('切层时按图层形态切换粒度并恢复记忆时刻', async () => {
    const science = makeLayer({
      catalogId: 'cat-science',
      dataState: 'imported',
      importedRaster: {
        overlayLayerId: 'ov-1',
        nativeStep: '8d',
        timeList: ['20240425_20240502', '20240501_20240508'],
      },
    })
    const h = setupSync({ layers: [science] })
    h.selectedLayerDisplay.value = { catalogId: 'cat-science' }
    await nextTick()
    expect(h.uiStore.applyTimelineFromLayerGranularity).toHaveBeenCalledWith('day')
    // restoreLayerTime 返回 null 且存在科学切片 → snap 到最新切片
    expect(h.uiStore.applyDateHour).toHaveBeenCalled()
  })

  it('记忆时刻可恢复时仅记录日志不强制 snap', async () => {
    const science = makeLayer({
      catalogId: 'cat-science',
      dataState: 'imported',
      importedRaster: {
        overlayLayerId: 'ov-1',
        nativeStep: '8d',
        timeList: ['20260425_20260502'],
      },
    })
    const h = setupSync({ layers: [science] })
    h.uiStore.restoreLayerTime.mockReturnValue({ date: new Date(), hour: 6 })
    h.selectedLayerDisplay.value = { catalogId: 'cat-science' }
    await nextTick()
    expect(h.logOperation).toHaveBeenCalledWith(
      'timeline-restore-layer',
      expect.stringContaining('cat-science'),
    )
    expect(h.uiStore.applyDateHour).not.toHaveBeenCalled()
  })

  it('普通目录图层无 spec 时回落小时粒度', async () => {
    const plain = makeLayer({ catalogId: 'cat-plain' })
    const h = setupSync({ layers: [plain] })
    h.selectedLayerDisplay.value = { catalogId: 'cat-plain' }
    await nextTick()
    expect(h.uiStore.applyTimelineFromLayerGranularity).toHaveBeenCalledWith('hour')
  })
})

// ── refreshImportedRasterEffectiveTimes ───────────────────────────────────────

describe('refreshImportedRasterEffectiveTimes', () => {
  it('从 overlay time-series 状态补全 timeList 与 nativeStep 并下发时间', () => {
    const layer = makeLayer({
      catalogId: 'cat-1',
      dataState: 'imported',
      importedRaster: { overlayLayerId: 'ov-9', nativeStep: null },
    })
    const h = setupSync({ layers: [layer], selectedCatalogId: 'cat-1' })
    h.overlayTimeStates.value = [
      {
        layerId: 'ov-9',
        category: 'time-series',
        timeList: ['20240425_20240502'],
        currentTime: null,
        palette: 'viridis',
        unit: '',
        vmin: null,
        vmax: null,
        opacity: 1,
        bounds: null,
      },
    ]
    h.sync.refreshImportedRasterEffectiveTimes()
    expect(layer.importedRaster!.timeList).toEqual(['20240425_20240502'])
    expect(layer.importedRaster!.nativeStep).toBe('8d')
    expect(layer.importedRaster!.effectiveTimeLabel).toBeTruthy()
    expect(h.setOverlayTime).toHaveBeenCalledWith('ov-9', expect.any(String))
  })

  it('无切片可解析时不下发 overlay 时间', () => {
    const layer = makeLayer({
      catalogId: 'cat-1',
      dataState: 'imported',
      importedRaster: { overlayLayerId: 'ov-x', nativeStep: null },
    })
    const h = setupSync({ layers: [layer] })
    h.sync.refreshImportedRasterEffectiveTimes()
    expect(h.setOverlayTime).not.toHaveBeenCalled()
  })
})

// ── timelineSegments / 粒度 ───────────────────────────────────────────────────

describe('timelineSegments 与 activeLayerGranularity', () => {
  it('未选图层返回时钟日段', () => {
    const h = setupSync()
    expect(h.sync.timelineSegments.value.length).toBeGreaterThan(0)
  })

  it('科学图层粒度由 nativeStep 决定', () => {
    const layer = makeLayer({
      catalogId: 'cat-sci',
      dataState: 'imported',
      importedRaster: { overlayLayerId: 'ov-1', nativeStep: '8d', timeList: ['20240501'] },
    })
    const h = setupSync({ layers: [layer], selectedCatalogId: 'cat-sci' })
    expect(h.sync.activeLayerGranularity.value).toBe('day')
  })

  it('导入栅格无时间列表为 static', () => {
    const layer = makeLayer({
      catalogId: 'cat-img',
      dataState: 'imported',
      importedRaster: { overlayLayerId: 'ov-2', nativeStep: null },
    })
    const h = setupSync({ layers: [layer], selectedCatalogId: 'cat-img' })
    expect(h.sync.activeLayerGranularity.value).toBe('static')
    expect(h.sync.timelineSegments.value).toHaveLength(1)
  })

  it('天气图层走小时粒度与时钟段', () => {
    const layer = makeLayer({ catalogId: 'weather-temp' })
    workspaceCalls.isWeatherEngineLayer.mockReturnValue(true)
    const h = setupSync({ layers: [layer], selectedCatalogId: 'weather-temp' })
    expect(h.sync.activeLayerGranularity.value).toBe('hour')
    expect(h.sync.timelineSegments.value.length).toBeGreaterThan(0)
    expect(h.getLayerStatus).toHaveBeenCalledWith('weather-temp')
  })

  it('日粒度科学层带 ready 切片时生成对应时间段', () => {
    const layer = makeLayer({
      catalogId: 'cat-sci',
      dataState: 'imported',
      importedRaster: {
        overlayLayerId: 'ov-1',
        nativeStep: '8d',
        timeList: ['20260425_20260502'],
      },
    })
    const h = setupSync({ layers: [layer], selectedCatalogId: 'cat-sci' })
    const segments = h.sync.timelineSegments.value
    expect(segments.length).toBeGreaterThan(0)
    const readyish = segments.some((s) => s.state === 'ready' || s.state === 'fetchable')
    expect(readyish).toBe(true)
  })
})

// ── analysisFocusRequest ──────────────────────────────────────────────────────

describe('analysisFocusRequest', () => {
  it('请求到达时打开分析面板', async () => {
    const h = setupSync()
    h.uiStore.analysisFocusRequest = { kind: 'chart' }
    await nextTick()
    expect(h.showPanel).toHaveBeenCalled()
  })
})

// ── 事件时间轴（2026-08-25 用户反馈）：静态图层带事件时间 → 年刻度轴 ────────

describe('静态图层事件时间轴', () => {
  it('overlay meta 带事件 time_list → 生成事件年刻度（事件年 ready）', () => {
    const layer = makeLayer({
      catalogId: 'cat-era5-dwaa',
      dataState: 'imported',
      importedRaster: { overlayLayerId: 'ov-era5', nativeStep: null },
    })
    const h = setupSync({ layers: [layer], selectedCatalogId: 'cat-era5-dwaa' })
    h.overlayTimeStates.value = [
      {
        layerId: 'ov-era5',
        category: 'static',
        timeList: ['2020'],
        currentTime: null,
        palette: 'YlOrRd',
        vmin: 0,
        vmax: 10,
        unit: 'events',
        opacity: 0.8,
        bounds: [73, 15, 137, 59],
      },
    ]
    expect(h.sync.activeLayerGranularity.value).toBe('static')
    const segs = h.sync.timelineSegments.value
    // 事件年 2020 前后各留一年 → [2019, 2020, 2021]
    expect(segs.map((s) => s.label)).toEqual(['2019', '2020', '2021'])
    const eventSeg = segs.find((s) => s.label === '2020')
    expect(eventSeg?.state).toBe('ready')
    expect(eventSeg?.availabilityLabel).toContain('事件时间')
    expect(segs.find((s) => s.label === '2019')?.state).toBe('empty')
  })

  it('无事件 time_list → 保持原「静态」单段', () => {
    const layer = makeLayer({
      catalogId: 'cat-static-plain',
      dataState: 'imported',
      importedRaster: { overlayLayerId: 'ov-plain', nativeStep: null },
    })
    const h = setupSync({ layers: [layer], selectedCatalogId: 'cat-static-plain' })
    h.overlayTimeStates.value = [
      {
        layerId: 'ov-plain',
        category: 'static',
        timeList: [],
        currentTime: null,
        palette: 'viridis',
        vmin: null,
        vmax: null,
        unit: '',
        opacity: 0.7,
        bounds: [0, 0, 1, 1],
      },
    ]
    const segs = h.sync.timelineSegments.value
    expect(segs).toHaveLength(1)
    expect(segs[0].label).toBe('静态')
  })
})
