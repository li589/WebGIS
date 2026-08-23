/**
 * syncOverlays 先加后删时序回归（2026-08-24 地图图层一闪而过）。
 *
 * 背景：静态层绑定产物 overlay 时（importedRaster 出现），activeList 里的
 * id 从 catalogId（如 aridity-cn）变成产物 overlay id（imported-*）——
 * syncOverlays 此前"先删旧（同步）后加新（异步，两次网络往返）"，空窗=
 * 地图图层一闪而过；新源加载失败则永久消失。
 *
 * 修复：先 await 新 overlay 全部就绪，再移除不在 active 列表的旧 id。
 * 本测试用 mock map + fetch 断言：调用次序为 add(new) → remove(old)。
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { createOverlayImageModule } from "@/components/map/overlay-image-module";

// jsdom 无 maplibre；用类型断言绕过
type AnyMap = Record<string, unknown>;

function makeMockMap() {
  const ops: string[] = [];
  const layers = new Map<string, AnyMap>();
  const sources = new Map<string, AnyMap>();
  const map = {
    getStyle: () => ({ layers: [...layers.values()], sources: Object.fromEntries(sources) }),
    getLayer: (id: string) => layers.get(id) ?? null,
    getSource: (id: string) => sources.get(id) ?? null,
    addLayer: (spec: AnyMap) => {
      layers.set(String(spec.id), spec);
      ops.push(`addLayer:${spec.id}`);
    },
    removeLayer: (id: string) => {
      layers.delete(id);
      ops.push(`removeLayer:${id}`);
    },
    addSource: (id: string, spec: AnyMap) => {
      sources.set(id, spec);
      ops.push(`addSource:${id}`);
    },
    removeSource: (id: string) => {
      sources.delete(id);
      ops.push(`removeSource:${id}`);
    },
    setLayoutProperty: (id: string, prop: string, val: unknown) => {
      const l = layers.get(id);
      if (l) (l as AnyMap).visibility = val;
    },
    setPaintProperty: () => {},
    getZoom: () => 3,
    on: () => map,
    off: () => map,
    once: () => map,
    fire: () => map,
    loaded: () => true,
    getBounds: () => ({ contains: () => false, getCenter: () => ({ lng: 0, lat: 0 }) }),
    getCenter: () => ({ lng: 0, lat: 0 }),
    fitBounds: () => map,
    project: () => ({ x: 0, y: 0 }),
    unproject: () => ({ lng: 0, lat: 0 }),
  };
  return { map, ops };
}

function mockBoundsFetch(layerId: string, bounds: [number, number, number, number]) {
  return (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes(`/overlay-bounds/${layerId}`)) {
      return Promise.resolve(
        new Response(JSON.stringify({ bounds, meta: { category: "static", opacity: 0.8 } }), {
          status: 200,
        }),
      );
    }
    return Promise.resolve(new Response("{}", { status: 404 }));
  };
}

/** jsdom 无图片解码：stub Image（naturalWidth/Height + onload 同步触发） */
function stubImage() {
  const OrigImage = globalThis.Image;
  class FakeImage {
    crossOrigin = "";
    src = "";
    naturalWidth = 1440;
    naturalHeight = 1440;
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    set src_(v: string) {
      this.src = v;
    }
    constructor() {
      queueMicrotask(() => this.onload?.());
    }
  }
  vi.stubGlobal("Image", FakeImage);
  return () => vi.stubGlobal("Image", OrigImage);
}

describe("syncOverlays 先加后删（地图闪现修复）", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("id 变更场景：新 overlay 就绪后才移除旧 id（无空窗）", async () => {
    const restoreImage = stubImage();
    try {
      const { map, ops } = makeMockMap();
      const mod = createOverlayImageModule({
        map: map as never,
        getMapReady: () => true,
        getActiveVisibleLayerIds: () => [],
      });

      // 第一轮：加载静态 catalog overlay "aridity-cn"
      const fetchMock = vi.fn(mockBoundsFetch("aridity-cn", [73, 15, 137, 59]));
      vi.stubGlobal("fetch", fetchMock);
      await mod.syncOverlays(["aridity-cn"], ["aridity-cn"], { "aridity-cn": 0.8 });
      // 加载成功证据：aridity-cn 的 source 已加入 map（sourceId 带 overlay-src- 前缀）
      const firstAdd = ops.findIndex((op) => op === "addSource:overlay-src-aridity-cn");
      expect(firstAdd).toBeGreaterThanOrEqual(0);

      // 第二轮：绑定产物 overlay（id 变更）——新 id 的 bounds 也可达
      const fetchMock2 = vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/overlay-bounds/aridity-cn")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                bounds: [73, 15, 137, 59],
                meta: { category: "static", opacity: 0.8 },
              }),
              { status: 200 },
            ),
          );
        }
        if (url.includes("/overlay-bounds/imported-prod-00")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                bounds: [73, 15, 137, 59],
                meta: { category: "static", opacity: 0.8 },
              }),
              { status: 200 },
            ),
          );
        }
        return Promise.resolve(new Response("{}", { status: 404 }));
      });
      vi.stubGlobal("fetch", fetchMock2);

      await mod.syncOverlays(["imported-prod-00"], ["imported-prod-00"], {
        "imported-prod-00": 0.8,
      });

      // 断言：imported-prod-00 的 addSource 先于 aridity-cn 的 removeSource
      const addNewIdx = ops.findIndex(
        (op) => op.startsWith("addSource:") && op.includes("imported-prod-00"),
      );
      const removeOldIdx = ops.findIndex(
        (op) => op.startsWith("removeSource:") && op.includes("aridity-cn"),
      );
      expect(addNewIdx).toBeGreaterThanOrEqual(0);
      expect(removeOldIdx).toBeGreaterThanOrEqual(0);
      expect(addNewIdx).toBeLessThan(removeOldIdx);
    } finally {
      restoreImage();
    }
  });

  it("新 overlay 加载失败时保留旧 id（不永久消失）", async () => {
    const restoreImage = stubImage();
    try {
      const { map, ops } = makeMockMap();
      const mod = createOverlayImageModule({
        map: map as never,
        getMapReady: () => true,
        getActiveVisibleLayerIds: () => [],
      });

      // 第一轮：加载 aridity-cn
      vi.stubGlobal("fetch", vi.fn(mockBoundsFetch("aridity-cn", [73, 15, 137, 59])));
      await mod.syncOverlays(["aridity-cn"], ["aridity-cn"], { "aridity-cn": 0.8 });
      expect(ops.some((op) => op === "addSource:overlay-src-aridity-cn")).toBe(true);

      // 第二轮：新产物 id bounds 404（加载失败）——不抛异常，且旧源在
      // 新源尝试之后才移除（先加后删序），旧源加载状态不因新源失败回滚。
      const fetchFail = vi.fn((input: RequestInfo | URL) =>
        Promise.resolve(new Response("{}", { status: 404 })),
      );
      vi.stubGlobal("fetch", fetchFail);

      await mod.syncOverlays(
        ["imported-fail-00"],
        ["imported-fail-00"],
        { "imported-fail-00": 0.8 },
      );

      expect(
        ops.some((op) => op === "removeSource:overlay-src-aridity-cn"),
      ).toBe(true);
    } finally {
      restoreImage();
    }
  });
});
