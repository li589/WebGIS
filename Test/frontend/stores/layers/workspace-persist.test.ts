import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ActiveLayer, ActiveRunLayerGroup } from '@/stores/layers/types'
import {
  buildWorkspaceSnapshot,
  isCatalogDismissed,
  isOverlayDismissed,
  isRunDismissed,
  isVectorDismissed,
  loadDismissedLayers,
  loadWorkspaceSnapshot,
  rememberDismissedLayer,
  saveWorkspaceSnapshot,
} from '@/stores/layers/workspace-persist'

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
  vi.stubGlobal('window', { localStorage: storage })
}

function rasterLayer(overlayLayerId: string, catalogId = overlayLayerId): ActiveLayer {
  return {
    instanceId: 'inst-raster',
    catalogId,
    visible: true,
    opacity: 0.8,
    order: 1,
    isAdminBoundary: false,
    dataState: 'imported',
    importedRaster: {
      overlayLayerId,
      fileName: 'demo.tif',
    },
  }
}

function catalogLayer(catalogId: string): ActiveLayer {
  return {
    instanceId: 'inst-cat',
    catalogId,
    visible: true,
    opacity: 1,
    order: 2,
    isAdminBoundary: false,
    dataState: 'catalog',
  }
}

function vectorLayer(backendLayerId: string): ActiveLayer {
  return {
    instanceId: 'inst-vec',
    catalogId: backendLayerId,
    visible: true,
    opacity: 0.85,
    order: 3,
    isAdminBoundary: false,
    dataState: 'imported',
    importedVector: {
      geojson: { type: 'FeatureCollection', features: [] },
      geometryType: 'Point',
      featureCount: 1,
      backendLayerId,
      fileName: 'demo.shp',
      style: { color: '#ff0000', width: 3 },
    },
  }
}

describe('workspace-persist', () => {
  beforeEach(() => {
    mockBrowserStorage()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('persists catalog layers for refresh restore', () => {
    const snap = buildWorkspaceSnapshot([catalogLayer('method-smap-omega-doy-dynamic')], [])
    expect(snap.catalogLayers).toHaveLength(1)
    expect(snap.catalogLayers?.[0]?.catalogId).toBe('method-smap-omega-doy-dynamic')
    saveWorkspaceSnapshot(snap)
    const loaded = loadWorkspaceSnapshot()
    expect(loaded?.catalogLayers).toHaveLength(1)
  })

  it('excludes dismissed overlay and catalog layers from snapshot', () => {
    rememberDismissedLayer({ overlayLayerId: 'ov-1', catalogId: 'cat-1' })
    const snap = buildWorkspaceSnapshot(
      [rasterLayer('ov-1', 'cat-r'), catalogLayer('cat-1')],
      [],
    )
    expect(snap.layers).toHaveLength(0)
    expect(snap.catalogLayers).toHaveLength(0)
  })

  it('tracks dismissed run ids', () => {
    rememberDismissedLayer({ runId: 'run-abc' })
    expect(isRunDismissed('run-abc')).toBe(true)
    expect(loadDismissedLayers().runIds).toContain('run-abc')
  })

  it('isOverlayDismissed and isCatalogDismissed', () => {
    rememberDismissedLayer({ overlayLayerId: 'x', catalogId: 'y' })
    expect(isOverlayDismissed('x')).toBe(true)
    expect(isCatalogDismissed('y')).toBe(true)
  })

  it('filters dismissed run from persisted groups', () => {
    rememberDismissedLayer({ runId: 'run-old' })
    const groups: ActiveRunLayerGroup[] = [
      {
        groupId: 'g1',
        runId: 'run-old',
        title: 't',
        status: 'ready',
        memberInstanceIds: ['inst-raster'],
        dissolvable: true,
      },
    ]
    const snap = buildWorkspaceSnapshot([rasterLayer('ov-2')], groups)
    expect(snap.groups).toHaveLength(0)
  })

  it('persists vector layers by backendLayerId without geojson', () => {
    const snap = buildWorkspaceSnapshot([vectorLayer('vec-layer-abc')], [])
    expect(snap.vectorLayers).toHaveLength(1)
    expect(snap.vectorLayers?.[0]?.backendLayerId).toBe('vec-layer-abc')
    expect(snap.vectorLayers?.[0]?.style?.color).toBe('#ff0000')
    expect(JSON.stringify(snap)).not.toContain('FeatureCollection')
  })

  it('excludes dismissed vector layers from snapshot', () => {
    rememberDismissedLayer({ vectorBackendLayerId: 'vec-gone' })
    const snap = buildWorkspaceSnapshot([vectorLayer('vec-gone')], [])
    expect(snap.vectorLayers).toHaveLength(0)
    expect(isVectorDismissed('vec-gone')).toBe(true)
  })

  it('persists computing run-group placeholders (locked, no overlay)', () => {
    const groupId = 'run-group-abc'
    const members: ActiveLayer[] = (['SM', 'VOD', 'OMEGA'] as const).map((tag, i) => ({
      instanceId: `inst-${tag.toLowerCase()}`,
      catalogId: `wf-run-${groupId}-${tag.toLowerCase()}`,
      name: tag,
      visible: true,
      opacity: 1,
      order: i,
      isAdminBoundary: false,
      dataState: 'catalog',
      runGroupId: groupId,
      runGroupProductTag: tag,
      runGroupLocked: true,
    }))
    const groups: ActiveRunLayerGroup[] = [
      {
        groupId,
        runId: 'run-live-1',
        title: 'SF 运行中',
        status: 'computing',
        memberInstanceIds: members.map((m) => m.instanceId),
        dissolvable: false,
        sourceLayerId: 'method-smap-omega-doy-dynamic',
        workflowId: 'omega_sf_fenkuai_smap_single',
      },
    ]
    const snap = buildWorkspaceSnapshot(members, groups)
    expect(snap.catalogLayers).toHaveLength(3)
    expect(snap.catalogLayers?.every((l) => l.runGroupLocked === true)).toBe(true)
    expect(snap.groups).toHaveLength(1)
    expect(snap.groups[0]?.status).toBe('computing')
    expect(snap.groups[0]?.dissolvable).toBe(false)
    expect(snap.groups[0]?.memberInstanceIds).toHaveLength(3)
  })

  it('keeps computing status when progressive overlay + placeholders mix', () => {
    const groupId = 'run-group-mix'
    const sm: ActiveLayer = {
      instanceId: 'inst-sm',
      catalogId: `wf-run-${groupId}-sm`,
      visible: true,
      opacity: 1,
      order: 2,
      isAdminBoundary: false,
      dataState: 'imported',
      runGroupId: groupId,
      runGroupProductTag: 'SM',
      runGroupLocked: true,
      importedRaster: { overlayLayerId: 'ov-sm', fileName: 'sm.tif', timeList: ['20251201'] },
    }
    const vod: ActiveLayer = {
      instanceId: 'inst-vod',
      catalogId: `wf-run-${groupId}-vod`,
      visible: true,
      opacity: 1,
      order: 1,
      isAdminBoundary: false,
      dataState: 'catalog',
      runGroupId: groupId,
      runGroupProductTag: 'VOD',
      runGroupLocked: true,
    }
    const groups: ActiveRunLayerGroup[] = [
      {
        groupId,
        runId: 'run-mix',
        title: '渐进',
        status: 'computing',
        memberInstanceIds: ['inst-sm', 'inst-vod'],
        dissolvable: false,
      },
    ]
    const snap = buildWorkspaceSnapshot([sm, vod], groups)
    expect(snap.layers).toHaveLength(1)
    expect(snap.layers[0]?.runGroupLocked).toBe(true)
    expect(snap.catalogLayers).toHaveLength(1)
    expect(snap.groups[0]?.status).toBe('computing')
    expect(snap.groups[0]?.memberInstanceIds).toEqual(['inst-sm', 'inst-vod'])
  })
})
