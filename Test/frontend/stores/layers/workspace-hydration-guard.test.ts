import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { ActiveLayer } from '@/stores/layers/types'
import { createWorkspaceHydrateSlice } from '@/stores/layers/workspace-hydrate'
import { loadWorkspaceSnapshot, saveWorkspaceSnapshot } from '@/stores/layers/workspace-persist'
import { buildWorkspaceSnapshot } from '@/stores/layers/workspace-persist'

function mockBrowserStorage() {
  const store = new Map<string, string>()
  const storage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => {
      store.set(k, v)
    },
    removeItem: (k: string) => {
      store.delete(k)
    },
    clear: () => store.clear(),
  }
  vi.stubGlobal('localStorage', storage)
  vi.stubGlobal('window', { localStorage: storage, addEventListener: () => {}, setTimeout, clearTimeout })
}

function draftLayer(): ActiveLayer {
  return {
    instanceId: 'inst-draft',
    catalogId: 'draw-draft-x',
    visible: true,
    opacity: 0.85,
    order: 1,
    isAdminBoundary: false,
    dataState: 'imported',
    importedVector: {
      geojson: { type: 'FeatureCollection', features: [] },
      geometryType: 'Unknown',
      featureCount: 0,
      fileName: 'draft',
    },
  }
}

function importedVectorLayer(backendLayerId: string): ActiveLayer {
  return {
    instanceId: 'inst-vec',
    catalogId: backendLayerId,
    visible: true,
    opacity: 0.85,
    order: 2,
    isAdminBoundary: false,
    dataState: 'imported',
    importedVector: {
      geojson: { type: 'FeatureCollection', features: [] },
      geometryType: 'Polygon',
      featureCount: 1,
      backendLayerId,
      fileName: 'demo.geojson',
    },
  }
}

function createSlice(activeLayers: ActiveLayer[]) {
  return createWorkspaceHydrateSlice({
    getActiveLayers: () => activeLayers,
    getRunLayerGroups: () => [],
    getSidebarView: () => 'active',
    setSidebarView: () => {},
    getLayerLibraryMap: () => new Map(),
    assignLayerAccent: () => ({ accentColor: 'var(--accent)', accentGlow: '', chipTone: '' }),
    genInstanceId: () => 'gen-id',
    isLocalImport: (l) => Boolean(l.importedVector || l.importedRaster),
    isWeatherEngineLayer: () => false,
    weatherProviderArg: () => 'auto',
    getMapCenter: () => ({ lng: 0, lat: 0 }),
    getMapZoom: () => 4,
    getMapBBox: () => null,
    getCurrentHour: () => 0,
    bindPersistFns: () => {},
  })
}

describe('workspace-hydration-guard', () => {
  beforeEach(() => {
    mockBrowserStorage()
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('boot 前快照中的导入矢量层在保护期 flush 中不被抹掉', () => {
    // boot 前快照含导入矢量层（上一会话持久化）
    saveWorkspaceSnapshot(
      buildWorkspaceSnapshot([importedVectorLayer('imported-vec-abc')], []),
    )
    expect(loadWorkspaceSnapshot()?.vectorLayers).toHaveLength(1)

    // boot 早期：activeLayers 只有绘制草稿（矢量层尚未水合）
    const activeLayers = [draftLayer()]
    const slice = createSlice(activeLayers)

    // 水合保护开启期间的 flush 必须被跳过（否则矢量层被永久抹掉）
    slice.setWorkspaceHydrationGuard(true)
    slice.flushWorkspacePersistNow()
    expect(loadWorkspaceSnapshot()?.vectorLayers).toHaveLength(1)

    // 保护释放 + 水合完成（矢量层已恢复）后，落盘包含矢量层
    slice.setWorkspaceHydrationGuard(false)
    activeLayers.push(importedVectorLayer('imported-vec-abc'))
    slice.flushWorkspacePersistNow()
    expect(loadWorkspaceSnapshot()?.vectorLayers).toHaveLength(1)
    expect(loadWorkspaceSnapshot()?.vectorLayers?.[0]?.backendLayerId).toBe('imported-vec-abc')
  })

  it('无保护时 flush 正常写快照（回归对照）', () => {
    saveWorkspaceSnapshot(buildWorkspaceSnapshot([importedVectorLayer('imported-vec-abc')], []))
    const slice = createSlice([draftLayer()])
    slice.flushWorkspacePersistNow()
    // 草稿层不可持久化且矢量层不在 activeLayers → 快照清空（旧行为，用于对照）
    expect(loadWorkspaceSnapshot()?.vectorLayers).toHaveLength(0)
  })
})
