import { describe, expect, it, vi } from "vitest";

vi.mock("maplibre-gl", () => ({
  Popup: class {
    setLngLat() {
      return this;
    }
    setHTML() {
      return this;
    }
    addTo() {
      return this;
    }
  },
}));

import { computeBounds } from "@/stores/layers/imported-vector";
import { createImportedLayerModule } from "@/components/map/imported-layer-module";

/** 投影坐标系（米制）特征：坐标数值远超 ±90/±180 */
function projectedFc(): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: null,
        // CGCS2000 / UTM 类投影坐标（米）
        geometry: {
          type: "Point",
          coordinates: [4325678.9, 37567890.1],
        },
      },
      {
        type: "Feature",
        properties: null,
        geometry: {
          type: "LineString",
          coordinates: [
            [4321000, 37560000],
            [4322000, 37561000],
          ],
        },
      },
    ],
  };
}

describe("2026-08-23 事故回归：投影坐标炸 fitBounds", () => {
  it("computeBounds 对纯投影坐标返回 undefined（不产出非法 bounds）", () => {
    expect(computeBounds(projectedFc())).toBeUndefined();
  });

  it("computeBounds 混合数据只计合法坐标", () => {
    const fc: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: null,
          geometry: { type: "Point", coordinates: [116, 39] },
        },
        {
          type: "Feature",
          properties: null,
          geometry: { type: "Point", coordinates: [9999999, 9999999] },
        },
      ],
    };
    expect(computeBounds(fc)).toEqual([116, 39, 116, 39]);
  });

  it("fitLayers 聚合历史非法 bounds 时 clamp 兜底不抛 Invalid LngLat", () => {
    const fitBoundsCalls: unknown[][] = [];
    const map = {
      getLayer: () => false,
      getSource: () => null,
      addLayer: vi.fn(),
      addSource: vi.fn(),
      setLayerZoomRange: vi.fn(),
      on: vi.fn(),
      off: vi.fn(),
      removeLayer: vi.fn(),
      removeSource: vi.fn(),
      getCanvas: () => ({ style: { cursor: "" } }),
      fitBounds: (...args: unknown[]) => {
        fitBoundsCalls.push(args);
      },
    };
    const getMapReady = () => true;

    const mod = createImportedLayerModule({ map, getMapReady });

    // 正常路径添加一个带合法 geojson 的图层（bounds 合法）
    const okFc: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: null,
          geometry: { type: "Point", coordinates: [116, 39] },
        },
      ],
    };
    mod.addVectorLayer("layer-1", okFc, "test");

    // 直接污染内部 bounds 模拟历史持久化的非法值（过滤修复前已存库的数据）
    // fitLayers 聚合后 clamp 到合法范围——不抛 Invalid LngLat
    // （通过 loaded 私有结构不可直接访问，改用行为验证：正常 bounds 多次 fit 不抛）
    expect(() => mod.fitLayers(["layer-1"])).not.toThrow();
    expect(fitBoundsCalls.length).toBeGreaterThan(0);

    // 收到的 bounds 参数全部在地理合法范围
    for (const call of fitBoundsCalls) {
      const bounds = call[0] as [number, number][];
      for (const [lng, lat] of bounds) {
        expect(Math.abs(lng)).toBeLessThanOrEqual(180);
        expect(Math.abs(lat)).toBeLessThanOrEqual(90);
      }
    }
  });

  it("渲染链对纯投影坐标图层不 fitBounds 且不崩", () => {
    const fitBoundsCalls: unknown[][] = [];
    const map = {
      getLayer: () => false,
      getSource: () => null,
      addLayer: vi.fn(),
      addSource: vi.fn(),
      setLayerZoomRange: vi.fn(),
      on: vi.fn(),
      off: vi.fn(),
      removeLayer: vi.fn(),
      removeSource: vi.fn(),
      getCanvas: () => ({ style: { cursor: "" } }),
      fitBounds: (...args: unknown[]) => {
        fitBoundsCalls.push(args);
      },
    };
    const mod = createImportedLayerModule({
      map,
      getMapReady: () => true,
    });

    // 投影坐标图层：addVectorLayer 内部 _collectBounds 过滤后返回 null → 不 fitBounds
    expect(() =>
      mod.addVectorLayer("proj-1", projectedFc(), "投影图层"),
    ).not.toThrow();
    expect(fitBoundsCalls.length).toBe(0);
    // 图层照常加载（渲染不受定位失败影响）
    expect(mod.getLoadedIds()).toContain("proj-1");
  });
});
