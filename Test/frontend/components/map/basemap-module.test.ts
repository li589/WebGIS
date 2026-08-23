import { describe, expect, it, vi } from "vitest";

import { createBasemapModule } from "@/components/map/basemap-module";

function createMapMock() {
  const sources = new Map<string, any>();
  const layerOrder: string[] = [];
  const layerSpecs = new Map<string, any>();
  const layers = {
    has: (id: string) => layerOrder.includes(id),
    add: (id: string) => {
      layerOrder.push(id);
    },
    delete: (id: string) => {
      const idx = layerOrder.indexOf(id);
      if (idx >= 0) layerOrder.splice(idx, 1);
    },
  };

  function insertAt(id: string, beforeId: string | undefined) {
    const idx = beforeId ? layerOrder.indexOf(beforeId) : -1;
    if (idx >= 0) layerOrder.splice(idx, 0, id);
    else layerOrder.push(id);
  }

  return {
    sources,
    layers,
    layerOrder,
    map: {
      getSource: (id: string) => sources.get(id),
      addSource: (id: string, source: any) => {
        sources.set(id, source);
      },
      removeSource: (id: string) => {
        sources.delete(id);
      },
      getStyle: () => ({
        layers: layerOrder.map((id) => layerSpecs.get(id) ?? { id }),
      }),
      getLayer: (id: string) => (layerOrder.includes(id) ? { id } : undefined),
      addLayer: (layer: { id: string; type?: string }, beforeId?: string) => {
        layerSpecs.set(layer.id, layer);
        insertAt(layer.id, beforeId);
      },
      moveLayer: (id: string, beforeId?: string) => {
        const from = layerOrder.indexOf(id);
        if (from >= 0) layerOrder.splice(from, 1);
        insertAt(id, beforeId);
      },
      removeLayer: (id: string) => {
        layers.delete(id);
      },
      setLayoutProperty: vi.fn(),
      setPaintProperty: vi.fn(),
      triggerRepaint: vi.fn(),
    } as any,
  };
}

describe("basemap-module", () => {
  it("debounces tile source switching and notifies after switch", () => {
    let timerId = 0;
    const scheduled = new Map<number, () => void>();
    const { map, layers, sources } = createMapMock();
    const setTileLoadFailed = vi.fn();
    const setTileFailedProvider = vi.fn();
    const setSourceTransitioning = vi.fn();
    const onAfterSourceSwitch = vi.fn();

    const module = createBasemapModule({
      map,
      getTileConfig: (sourceId) =>
        sourceId === "esri-street"
          ? {
              id: "esri-street",
              label: "Esri Street",
              provider: "Esri",
              style: "street",
              urlTemplate: "https://example.com/{z}/{x}/{y}.png",
              saturation: 0,
              brightness: 0,
              contrast: 0,
              isStandard: true,
              needsBackendTransform: false,
              authMode: "none",
            }
          : undefined,
      getCurrentTileSourceId: () => "esri-street",
      setTileLoadFailed,
      setTileFailedProvider,
      setSourceTransitioning,
      onAfterSourceSwitch,
      dependencies: {
        setTimeout: ((callback: () => void) => {
          timerId += 1;
          scheduled.set(timerId, callback);
          return timerId as unknown as ReturnType<typeof setTimeout>;
        }) as typeof setTimeout,
        clearTimeout: ((id: ReturnType<typeof setTimeout>) => {
          scheduled.delete(id as unknown as number);
        }) as typeof clearTimeout,
      },
    });

    module.scheduleTileSourceSwitch("esri-street");
    module.scheduleTileSourceSwitch("esri-street");

    expect(scheduled.size).toBe(1);
    scheduled.get(2)?.();

    expect(sources.has("tile-base")).toBe(true);
    expect(layers.has("tile-base-raster")).toBe(true);
    expect(setTileLoadFailed).toHaveBeenCalledWith(false);
    expect(setTileFailedProvider).toHaveBeenCalledWith(null);
    expect(setSourceTransitioning).toHaveBeenCalledWith(true);
    expect(onAfterSourceSwitch).toHaveBeenCalledTimes(1);
  });

  it("marks repeated tile failures and can retry current source", () => {
    const { map, sources } = createMapMock();
    const source = {
      type: "raster",
      setTiles: vi.fn(),
    };
    sources.set("tile-base", source);
    map.getLayer = () => ({ id: "tile-base-raster" });

    const setTileLoadFailed = vi.fn();
    const setTileFailedProvider = vi.fn();
    let now = 0;

    const module = createBasemapModule({
      map,
      getTileConfig: (sourceId) =>
        sourceId === "esri-street"
          ? {
              id: "esri-street",
              label: "Esri Street",
              provider: "Esri",
              style: "street",
              urlTemplate: "https://example.com/{z}/{x}/{y}.png",
              saturation: 0,
              brightness: 0,
              contrast: 0,
              isStandard: true,
              needsBackendTransform: false,
              authMode: "none",
            }
          : undefined,
      getCurrentTileSourceId: () => "esri-street",
      setTileLoadFailed,
      setTileFailedProvider,
      setSourceTransitioning: vi.fn(),
      // 本用例聚焦熔断+重试恢复路径；有候选时的故障转移见 failover 测试文件
      getFailoverCandidates: () => [],
      dependencies: {
        now: () => {
          now += 100;
          return now;
        },
      },
    });

    for (let index = 0; index < 16; index += 1) {
      module.handleTileError("Esri");
    }

    expect(setTileLoadFailed).toHaveBeenLastCalledWith(true);
    expect(setTileFailedProvider).toHaveBeenLastCalledWith("Esri");

    module.retryTileLoad();

    expect(setTileLoadFailed).toHaveBeenLastCalledWith(false);
    expect(setTileFailedProvider).toHaveBeenLastCalledWith(null);
    // 2026-08-24 修复：熔断/重试路径重建源（removeSource abort 全部挂起瓦片
    // 请求，立即释放同源连接池——/unified-tiles 代理与 API 同源，浏览器
    // HTTP/1.1 每源仅 6 条并发连接），不再走 setTiles（旧请求会继续占连接
    // 直到超时 = "切底图卡一段时间"根因）。
    expect(source.setTiles).not.toHaveBeenCalled();
    // 旧源已删除、新源以当前 urlTemplate 重建（瓦片命中 HTTP 缓存不重复下载）
    expect(sources.has("tile-base")).toBe(true);
    expect(sources.get("tile-base")).not.toBe(source);
    expect(sources.get("tile-base").tiles).toEqual([
      "https://example.com/{z}/{x}/{y}.png",
    ]);
    expect(map.triggerRepaint).toHaveBeenCalled();
    expect(map.setLayoutProperty).toHaveBeenCalledWith(
      "tile-base-raster",
      "visibility",
      "visible",
    );
  });

  it("switching away from a failing source recreates the source (aborts hanging requests)", () => {
    // 2026-08-24 复发报障：全部底图源经 /unified-tiles 代理（同源），浏览器
    // 每源 6 条并发连接。源 A 挂起时占满连接池，旧实现 setTiles 不中止挂
    // 请求 → 新源 B 的瓦片请求排在 A 的超时请求之后 → 切换"卡一段时间"。
    // 修复：异常态（熔断/错误窗口内/外来错误）切换必须 removeSource 重建
    // （abort 全部挂起请求、立即释放连接），健康切换保留 setTiles 平滑淡出。
    const { map, sources } = createMapMock();
    const source = { type: "raster", setTiles: vi.fn() };
    sources.set("tile-base", source);
    map.getLayer = () => ({ id: "tile-base-raster" });

    const module = createBasemapModule({
      map,
      getTileConfig: (sourceId) =>
        sourceId === "esri-street"
          ? {
              id: "esri-street",
              provider: "Esri",
              style: "street",
              urlTemplate: "https://esri.example/{z}/{x}/{y}.png",
            }
          : sourceId === "bing-road"
            ? {
                id: "bing-road",
                provider: "Bing",
                style: "street",
                urlTemplate: "https://bing.example/{z}/{x}/{y}.png",
              }
            : undefined,
      getCurrentTileSourceId: () => "bing-road",
      setTileLoadFailed: vi.fn(),
      setTileFailedProvider: vi.fn(),
      setSourceTransitioning: vi.fn(),
      getFailoverCandidates: () => [],
      dependencies: { now: () => 1000 },
    });

    // 旧源 Esri 请求失败（未到熔断阈值：仅 3 条错误进窗口）
    for (let index = 0; index < 3; index += 1) module.handleTileError("Esri");

    // 用户切到 bing-road：错误窗口非空 → 必须重建（abort 挂起请求）
    module.switchTileSource("bing-road");

    expect(source.setTiles).not.toHaveBeenCalled();
    expect(sources.get("tile-base")).not.toBe(source);
    expect(sources.get("tile-base").tiles).toEqual([
      "https://bing.example/{z}/{x}/{y}.png",
    ]);
  });

  it("switching between healthy sources keeps setTiles (smooth fade)", () => {
    const { map, sources } = createMapMock();
    const source = { type: "raster", setTiles: vi.fn() };
    sources.set("tile-base", source);
    map.getLayer = () => ({ id: "tile-base-raster" });

    const module = createBasemapModule({
      map,
      getTileConfig: (sourceId) =>
        sourceId === "esri-street"
          ? {
              id: "esri-street",
              provider: "Esri",
              style: "street",
              urlTemplate: "https://esri.example/{z}/{x}/{y}.png",
            }
          : sourceId === "bing-road"
            ? {
                id: "bing-road",
                provider: "Bing",
                style: "street",
                urlTemplate: "https://bing.example/{z}/{x}/{y}.png",
              }
            : undefined,
      getCurrentTileSourceId: () => "esri-street",
      setTileLoadFailed: vi.fn(),
      setTileFailedProvider: vi.fn(),
      setSourceTransitioning: vi.fn(),
      dependencies: { now: () => 1000 },
    });

    // 无任何错误：健康切换走 setTiles（旧瓦片平滑淡出到新瓦片）
    module.switchTileSource("bing-road");
    expect(source.setTiles).toHaveBeenCalledWith([
      "https://bing.example/{z}/{x}/{y}.png",
    ]);
    expect(sources.get("tile-base")).toBe(source);
  });

  it("foreign (old-provider) errors after switching also trigger recreate on next switch", () => {
    // 用户已切走后旧源迟到失败：归因检查跳过（不进熔断窗口），但证明旧
    // 请求挂起中——下一次切换仍须重建中止
    const { map, sources } = createMapMock();
    const source = { type: "raster", setTiles: vi.fn() };
    sources.set("tile-base", source);
    map.getLayer = () => ({ id: "tile-base-raster" });

    const module = createBasemapModule({
      map,
      getTileConfig: (sourceId) =>
        sourceId === "esri-street"
          ? {
              id: "esri-street",
              provider: "Esri",
              style: "street",
              urlTemplate: "https://esri.example/{z}/{x}/{y}.png",
            }
          : sourceId === "bing-road"
            ? {
                id: "bing-road",
                provider: "Bing",
                style: "street",
                urlTemplate: "https://bing.example/{z}/{x}/{y}.png",
              }
            : undefined,
      getCurrentTileSourceId: () => "bing-road",
      setTileLoadFailed: vi.fn(),
      setTileFailedProvider: vi.fn(),
      setSourceTransitioning: vi.fn(),
      dependencies: { now: () => 1000 },
    });

    // 旧源 Esri 迟到失败（当前已是 bing-road → 归因跳过）
    module.handleTileError("Esri");

    module.switchTileSource("esri-street");
    expect(source.setTiles).not.toHaveBeenCalled();
    expect(sources.get("tile-base")).not.toBe(source);
  });

  it("parses map error events for the managed tile source only", () => {
    const { map } = createMapMock();
    const setTileLoadFailed = vi.fn();
    const setTileFailedProvider = vi.fn();
    let now = 0;

    const module = createBasemapModule({
      map,
      getTileConfig: (sourceId) =>
        sourceId === "esri-street"
          ? {
              id: "esri-street",
              label: "Esri Street",
              provider: "Esri",
              style: "street",
              urlTemplate: "https://example.com/{z}/{x}/{y}.png",
              saturation: 0,
              brightness: 0,
              contrast: 0,
              isStandard: true,
              needsBackendTransform: false,
              authMode: "none",
            }
          : undefined,
      getCurrentTileSourceId: () => "esri-street",
      setTileLoadFailed,
      setTileFailedProvider,
      setSourceTransitioning: vi.fn(),
      // 本用例聚焦熔断路径；有候选时的故障转移见 failover 测试文件
      getFailoverCandidates: () => [],
      dependencies: {
        now: () => {
          now += 100;
          return now;
        },
      },
    });

    // 迟到失败指向其它底图：忽略，不进入失败态
    for (let index = 0; index < 16; index += 1) {
      module.handleMapErrorEvent({
        sourceId: "tile-base",
        error: {
          status: 403,
          url: "https://example.com/tiles/Gaode/1/2/3.png",
        },
      });
    }
    expect(setTileLoadFailed).not.toHaveBeenCalledWith(true);

    module.handleMapErrorEvent({
      sourceId: "other-source",
      error: {
        status: 403,
        url: "https://example.com/tiles/Esri/1/2/3.png",
      },
    });

    module.handleMapErrorEvent({
      sourceId: "tile-base",
      error: {
        status: 500,
        url: "https://example.com/tiles/Esri/1/2/3.png",
      },
    });

    // 当前底图连续失败：计入阈值
    for (let index = 0; index < 16; index += 1) {
      module.handleMapErrorEvent({
        sourceId: "tile-base",
        error: {
          status: 403,
          url: "https://example.com/tiles/Esri/1/2/3.png",
        },
      });
    }

    expect(setTileLoadFailed).toHaveBeenLastCalledWith(true);
    expect(setTileFailedProvider).toHaveBeenLastCalledWith("Esri");
  });

  it("adds annotation overlay when tile source provides overlayUrlTemplate", () => {
    const { map, layers, sources } = createMapMock();
    const module = createBasemapModule({
      map,
      getTileConfig: (sourceId) =>
        sourceId === "tianditu-vec"
          ? {
              id: "tianditu-vec",
              label: "天地图街道",
              provider: "Tianditu",
              style: "street",
              urlTemplate: "/unified-tiles/tianditu-vec/{z}/{x}/{y}",
              overlayUrlTemplate: "/unified-tiles/tianditu-cva/{z}/{x}/{y}",
              saturation: 0,
              brightness: 0,
              contrast: 0,
              isStandard: true,
              needsBackendTransform: false,
              authMode: "api-key",
            }
          : undefined,
      getCurrentTileSourceId: () => "tianditu-vec",
      setTileLoadFailed: vi.fn(),
      setTileFailedProvider: vi.fn(),
      setSourceTransitioning: vi.fn(),
    });

    module.switchTileSource("tianditu-vec");

    expect(sources.has("tile-base")).toBe(true);
    expect(sources.has("tile-base-overlay")).toBe(true);
    expect(layers.has("tile-base-raster")).toBe(true);
    expect(layers.has("tile-base-overlay-raster")).toBe(true);
    expect(sources.get("tile-base-overlay").tiles).toEqual([
      "/unified-tiles/tianditu-cva/{z}/{x}/{y}",
    ]);
  });

  it("hides basemap when switching to blank (none) without clearing tiles", () => {
    const { map, layers, sources } = createMapMock();
    const source = {
      type: "raster",
      tiles: ["https://example.com/gaode/{z}/{x}/{y}.png"],
      setTiles: vi.fn(function (this: { tiles: string[] }, next: string[]) {
        this.tiles = next;
      }),
    };
    sources.set("tile-base", source);
    layers.add("tile-base-raster");
    layers.add("tile-base-overlay-raster");
    sources.set("tile-base-overlay", {
      type: "raster",
      tiles: ["https://example.com/cva/{z}/{x}/{y}.png"],
    });

    const module = createBasemapModule({
      map,
      getTileConfig: () => undefined,
      getCurrentTileSourceId: () => "none",
      setTileLoadFailed: vi.fn(),
      setTileFailedProvider: vi.fn(),
      setSourceTransitioning: vi.fn(),
    });

    module.switchTileSource("none");

    expect(map.setLayoutProperty).toHaveBeenCalledWith(
      "tile-base-raster",
      "visibility",
      "none",
    );
    expect(map.setPaintProperty).toHaveBeenCalledWith(
      "tile-base-raster",
      "raster-opacity",
      0,
    );
    // 空白模式不清空 tiles：setTiles([]) 会触发 maplibre tile 状态机竞态
    // （painter texture.bind 读 undefined 持续崩溃），切回真实源必重设 tiles
    expect(source.setTiles).not.toHaveBeenCalled();
    expect(map.triggerRepaint).toHaveBeenCalled();
    expect(map.setLayoutProperty).toHaveBeenCalledWith(
      "tile-base-overlay-raster",
      "visibility",
      "none",
    );
    // overlay 源在空白模式下卸掉
    expect(sources.has("tile-base-overlay")).toBe(false);
    expect(layers.has("tile-base-overlay-raster")).toBe(false);
  });

  it("inserts base raster below existing overlay layers after blank-basemap start", () => {
    // 空白底图起步：数据叠加层先上图，底图层尚不存在
    const { layerOrder, map } = createMapMock();
    map.addLayer({ id: "data-overlay-1" });
    map.addLayer({ id: "data-overlay-2" });
    map.addLayer({ id: "admin-fill" });

    const module = createBasemapModule({
      map,
      getTileConfig: (sourceId) =>
        sourceId === "esri-street"
          ? {
              id: "esri-street",
              label: "Esri Street",
              provider: "Esri",
              style: "street",
              urlTemplate: "https://example.com/{z}/{x}/{y}.png",
              saturation: 0,
              brightness: 0,
              contrast: 0,
              isStandard: true,
              needsBackendTransform: false,
              authMode: "none",
            }
          : undefined,
      getCurrentTileSourceId: () => "esri-street",
      setTileLoadFailed: vi.fn(),
      setTileFailedProvider: vi.fn(),
      setSourceTransitioning: vi.fn(),
    });

    module.switchTileSource("esri-street");

    // 底图必须位于所有数据叠加层之下
    expect(layerOrder.indexOf("tile-base-raster")).toBe(0);
    expect(layerOrder.indexOf("tile-base-raster")).toBeLessThan(
      layerOrder.indexOf("data-overlay-1"),
    );
    expect(layerOrder.indexOf("tile-base-raster")).toBeLessThan(
      layerOrder.indexOf("admin-fill"),
    );
  });

  it("places annotation overlay directly above base raster and below data overlays", () => {
    const { layerOrder, map } = createMapMock();
    map.addLayer({ id: "data-overlay-1" });

    const module = createBasemapModule({
      map,
      getTileConfig: (sourceId) =>
        sourceId === "tianditu-vec"
          ? {
              id: "tianditu-vec",
              label: "天地图街道",
              provider: "Tianditu",
              style: "street",
              urlTemplate: "/unified-tiles/tianditu-vec/{z}/{x}/{y}",
              overlayUrlTemplate: "/unified-tiles/tianditu-cva/{z}/{x}/{y}",
              saturation: 0,
              brightness: 0,
              contrast: 0,
              isStandard: true,
              needsBackendTransform: false,
              authMode: "api-key",
            }
          : undefined,
      getCurrentTileSourceId: () => "tianditu-vec",
      setTileLoadFailed: vi.fn(),
      setTileFailedProvider: vi.fn(),
      setSourceTransitioning: vi.fn(),
    });

    module.switchTileSource("tianditu-vec");

    expect(layerOrder.indexOf("tile-base-raster")).toBe(0);
    expect(layerOrder.indexOf("tile-base-overlay-raster")).toBe(1);
    expect(layerOrder.indexOf("tile-base-overlay-raster")).toBeLessThan(
      layerOrder.indexOf("data-overlay-1"),
    );
  });

  it("repositions a misplaced base raster to the stack bottom on subsequent switches", () => {
    // 历史错位：底图层被追加到了栈顶
    const { layerOrder, map } = createMapMock();
    map.addLayer({ id: "data-overlay-1" });
    map.addLayer({ id: "tile-base-raster" });

    const module = createBasemapModule({
      map,
      getTileConfig: (sourceId) =>
        sourceId === "esri-street"
          ? {
              id: "esri-street",
              label: "Esri Street",
              provider: "Esri",
              style: "street",
              urlTemplate: "https://example.com/{z}/{x}/{y}.png",
              saturation: 0,
              brightness: 0,
              contrast: 0,
              isStandard: true,
              needsBackendTransform: false,
              authMode: "none",
            }
          : undefined,
      getCurrentTileSourceId: () => "esri-street",
      setTileLoadFailed: vi.fn(),
      setTileFailedProvider: vi.fn(),
      setSourceTransitioning: vi.fn(),
    });

    expect(layerOrder.indexOf("tile-base-raster")).toBe(1);
    module.switchTileSource("esri-street");
    expect(layerOrder.indexOf("tile-base-raster")).toBe(0);
  });

  it("keeps base raster above the style background layer on initial add", () => {
    // 真实 map 初始 style 仅含 background 层；底图必须落在其上，否则被背景色罩暗整图
    const { layerOrder, map } = createMapMock();
    map.addLayer({ id: "background", type: "background" });

    const module = createBasemapModule({
      map,
      getTileConfig: (sourceId) =>
        sourceId === "esri-street"
          ? {
              id: "esri-street",
              label: "Esri Street",
              provider: "Esri",
              style: "street",
              urlTemplate: "https://example.com/{z}/{x}/{y}.png",
              saturation: 0,
              brightness: 0,
              contrast: 0,
              isStandard: true,
              needsBackendTransform: false,
              authMode: "none",
            }
          : undefined,
      getCurrentTileSourceId: () => "esri-street",
      setTileLoadFailed: vi.fn(),
      setTileFailedProvider: vi.fn(),
      setSourceTransitioning: vi.fn(),
    });

    module.switchTileSource("esri-street");

    expect(layerOrder.indexOf("background")).toBe(0);
    expect(layerOrder.indexOf("tile-base-raster")).toBe(1);
  });

  it("lifts a base raster that sank below the background layer", () => {
    // bug 现场：底图沉到 background 之下被半透明背景色罩暗，画面整体发暗且与氛围遮罩开关无关
    const { layerOrder, map } = createMapMock();
    map.addLayer({ id: "tile-base-raster", type: "raster" });
    map.addLayer({ id: "background", type: "background" });
    map.addLayer({ id: "admin-fill", type: "fill" });

    const module = createBasemapModule({
      map,
      getTileConfig: (sourceId) =>
        sourceId === "esri-street"
          ? {
              id: "esri-street",
              label: "Esri Street",
              provider: "Esri",
              style: "street",
              urlTemplate: "https://example.com/{z}/{x}/{y}.png",
              saturation: 0,
              brightness: 0,
              contrast: 0,
              isStandard: true,
              needsBackendTransform: false,
              authMode: "none",
            }
          : undefined,
      getCurrentTileSourceId: () => "esri-street",
      setTileLoadFailed: vi.fn(),
      setTileFailedProvider: vi.fn(),
      setSourceTransitioning: vi.fn(),
    });

    expect(layerOrder.indexOf("tile-base-raster")).toBe(0);
    module.switchTileSource("esri-street");
    expect(layerOrder.indexOf("background")).toBe(0);
    expect(layerOrder.indexOf("tile-base-raster")).toBe(1);
    expect(layerOrder.indexOf("admin-fill")).toBe(2);
  });
});
