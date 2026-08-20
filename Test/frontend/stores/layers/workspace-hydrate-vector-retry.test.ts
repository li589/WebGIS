import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import type { ActiveLayer } from "@/stores/layers/types";
import { createWorkspaceHydrateSlice } from "@/stores/layers/workspace-hydrate";
import {
  buildWorkspaceSnapshot,
  loadWorkspaceSnapshot,
  saveWorkspaceSnapshot,
  type PersistedVectorLayer,
} from "@/stores/layers/workspace-persist";

/**
 * 矢量图层恢复失败重试（数据丢失 bug 2026-08-20 修复）：
 * hydrate 时 fetch 失败（网络抖动/后端重启）的条目必须保留在快照中
 * 待下次刷新重试——否则 guard 释放后首次 flush 以 activeLayers 重建
 * 快照，未恢复条目被永久抹除（且被同步推送放大到远端）。
 */

vi.mock("@/data-manager/core/api", () => ({
  fetchImportedLayerGeojson: vi.fn(),
  fetchImportedLayerMeta: vi.fn(),
}));

import {
  fetchImportedLayerGeojson,
  fetchImportedLayerMeta,
} from "@/data-manager/core/api";

function mockBrowserStorage() {
  const store = new Map<string, string>();
  const storage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
  };
  vi.stubGlobal("localStorage", storage);
  vi.stubGlobal("window", {
    localStorage: storage,
    addEventListener: () => {},
    setTimeout,
    clearTimeout,
  });
}

function importedVectorLayer(backendLayerId: string): ActiveLayer {
  return {
    instanceId: "inst-vec",
    catalogId: backendLayerId,
    visible: true,
    opacity: 0.85,
    order: 2,
    isAdminBoundary: false,
    dataState: "imported",
    importedVector: {
      geojson: { type: "FeatureCollection", features: [] },
      geometryType: "Polygon",
      featureCount: 1,
      backendLayerId,
      fileName: "demo.geojson",
    },
  };
}

function createSlice(activeLayers: ActiveLayer[]) {
  return createWorkspaceHydrateSlice({
    getActiveLayers: () => activeLayers,
    getRunLayerGroups: () => [],
    getSidebarView: () => "active",
    setSidebarView: () => {},
    getLayerLibraryMap: () => new Map(),
    assignLayerAccent: () => ({
      accentColor: "var(--accent)",
      accentGlow: "",
      chipTone: "",
    }),
    genInstanceId: () => "gen-id",
    isLocalImport: (l) => Boolean(l.importedVector || l.importedRaster),
    isWeatherEngineLayer: () => false,
    weatherProviderArg: () => "auto",
    getMapCenter: () => ({ lng: 0, lat: 0 }),
    getMapZoom: () => 4,
    getMapBBox: () => null,
    getCurrentHour: () => 0,
    bindPersistFns: () => {},
  });
}

function seedSnapshotWithVector(backendLayerId: string): PersistedVectorLayer {
  const snap = buildWorkspaceSnapshot(
    [importedVectorLayer(backendLayerId)],
    [],
  );
  saveWorkspaceSnapshot(snap);
  const saved = snap.vectorLayers?.[0];
  if (!saved) throw new Error("seed snapshot must contain vector layer");
  return saved;
}

describe("workspace-hydrate 矢量恢复失败重试", () => {
  beforeEach(() => {
    mockBrowserStorage();
    setActivePinia(createPinia());
    vi.mocked(fetchImportedLayerGeojson).mockReset();
    vi.mocked(fetchImportedLayerMeta).mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("hydrate fetch 失败 → guard 释放后 flush 快照仍保留该条目（下次刷新重试）", async () => {
    seedSnapshotWithVector("vec-fail-1");
    vi.mocked(fetchImportedLayerGeojson).mockRejectedValue(
      new Error("network down"),
    );
    vi.mocked(fetchImportedLayerMeta).mockResolvedValue(null);

    const activeLayers: ActiveLayer[] = [];
    const slice = createSlice(activeLayers);
    await slice.hydrateVectorLayersFromSnapshot(new Map());
    expect(activeLayers).toHaveLength(0); // 本轮未恢复

    // guard 释放后的首次 flush：以 activeLayers（空）重建快照——
    // 修复前条目被抹除；修复后保留待重试
    slice.setWorkspaceHydrationGuard(false);
    slice.flushWorkspacePersistNow();
    const snap = loadWorkspaceSnapshot();
    expect(snap?.vectorLayers).toHaveLength(1);
    expect(snap?.vectorLayers?.[0]?.backendLayerId).toBe("vec-fail-1");
  });

  it("条目成功恢复（backendLayerId 进入 activeLayers）后 flush 不重复保留", async () => {
    seedSnapshotWithVector("vec-ok-1");
    vi.mocked(fetchImportedLayerGeojson).mockRejectedValue(
      new Error("first boot fails"),
    );
    vi.mocked(fetchImportedLayerMeta).mockResolvedValue(null);

    const activeLayers: ActiveLayer[] = [];
    const slice = createSlice(activeLayers);
    await slice.hydrateVectorLayersFromSnapshot(new Map());

    // 模拟后续重试成功（图层进入 activeLayers）
    activeLayers.push(importedVectorLayer("vec-ok-1"));
    slice.flushWorkspacePersistNow();
    const snap = loadWorkspaceSnapshot();
    expect(snap?.vectorLayers).toHaveLength(1); // 不重复
    expect(snap?.vectorLayers?.[0]?.backendLayerId).toBe("vec-ok-1");
  });

  it("用户明确移除（dismissed 登记）后 flush 不再保留失败条目", async () => {
    seedSnapshotWithVector("vec-drop-1");
    vi.mocked(fetchImportedLayerGeojson).mockRejectedValue(
      new Error("network down"),
    );
    vi.mocked(fetchImportedLayerMeta).mockResolvedValue(null);

    const activeLayers: ActiveLayer[] = [];
    const slice = createSlice(activeLayers);
    await slice.hydrateVectorLayersFromSnapshot(new Map());

    // 用户在侧栏删除该层 → dismissed 登记
    const { rememberDismissedLayer } =
      await import("@/stores/layers/workspace-persist");
    rememberDismissedLayer({ vectorBackendLayerId: "vec-drop-1" });

    slice.flushWorkspacePersistNow();
    expect(loadWorkspaceSnapshot()?.vectorLayers ?? []).toHaveLength(0);
  });

  it("正常恢复路径不受影响（fetch 成功 → activeLayers 含层）", async () => {
    seedSnapshotWithVector("vec-normal-1");
    vi.mocked(fetchImportedLayerGeojson).mockResolvedValue({
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: {},
          geometry: {
            type: "Polygon",
            coordinates: [
              [
                [0, 0],
                [1, 0],
                [1, 1],
                [0, 0],
              ],
            ],
          },
        },
      ],
    });
    vi.mocked(fetchImportedLayerMeta).mockResolvedValue(null);

    const activeLayers: ActiveLayer[] = [];
    const slice = createSlice(activeLayers);
    await slice.hydrateVectorLayersFromSnapshot(new Map());

    expect(activeLayers).toHaveLength(1);
    slice.flushWorkspacePersistNow();
    expect(loadWorkspaceSnapshot()?.vectorLayers).toHaveLength(1);
  });
});
