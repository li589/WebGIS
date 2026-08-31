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

import { computed, reactive, ref, isReactive, toRaw } from "vue";
import { buildImportedVectorPayload } from "@/stores/layers/imported-vector";
import type { ActiveLayer } from "@/stores/layers/types";

const fc: GeoJSON.FeatureCollection = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: { name: "p1" },
      geometry: { type: "Point", coordinates: [116, 39] },
    },
  ],
};

describe("D-4 importedVector geojson markRaw", () => {
  it("buildImportedVectorPayload 返回的 geojson 不被 proxy 化", () => {
    const payload = buildImportedVectorPayload(fc, "test.geojson");
    expect(isReactive(payload.geojson)).toBe(false);
    // markRaw 幂等：内容访问不受影响
    expect(payload.geojson.features.length).toBe(1);
    expect(payload.geojson.features[0].properties?.name).toBe("p1");
  });

  it("放入 reactive/ref 深响应式容器后 geojson 子树依然 raw", () => {
    const payload = buildImportedVectorPayload(fc, "test.geojson");
    const container = ref<{ items: { payload: typeof payload }[] }>({
      items: [{ payload }],
    });
    // 容器本身响应式，geojson 子树豁免（百万级 features 不建 Proxy）
    expect(isReactive(container.value.items[0].payload)).toBe(true);
    expect(isReactive(container.value.items[0].payload.geojson)).toBe(false);
  });

  it("geojson 引用替换触发响应（computed 重算）", () => {
    const payload = buildImportedVectorPayload(fc, "test.geojson");
    const layer = reactive<ActiveLayer>({
      instanceId: "i1",
      catalogId: "c1",
      name: "n",
      visible: true,
      opacity: 1,
      order: 1,
      isAdminBoundary: false,
      dataState: "imported",
      importedVector: payload,
    }) as ActiveLayer;

    const featureCounts: number[] = [];
    const derived = computed(() => {
      const geo = layer.importedVector?.geojson;
      featureCounts.push(geo ? geo.features.length : -1);
      return layer.importedVector?.revision ?? 0;
    });
    expect(derived.value).toBe(0);

    // 模拟 updateImportedVectorGeojson 的整体替换语义
    const fc2: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: [
        ...fc.features,
        {
          type: "Feature",
          properties: { name: "p2" },
          geometry: { type: "Point", coordinates: [117, 40] },
        },
      ],
    };
    layer.importedVector = {
      ...layer.importedVector!,
      geojson: fc2,
      featureCount: 2,
      revision: 1,
    };

    expect(derived.value).toBe(1);
    // 替换后 computed 重算读到了新数据
    expect(featureCounts[featureCounts.length - 1]).toBe(2);
  });

  it("payload 其他字段（style）仍深响应式", () => {
    const payload = buildImportedVectorPayload(fc, "test.geojson");
    const layer = reactive({ importedVector: payload });
    expect(isReactive(layer.importedVector)).toBe(true);
    expect(isReactive(layer.importedVector.style)).toBe(true);
  });

  it("toRaw 可取回原始 geojson（引用相等）", () => {
    const payload = buildImportedVectorPayload(fc, "test.geojson");
    const layer = reactive({ importedVector: payload });
    expect(toRaw(layer.importedVector.geojson)).toBe(payload.geojson);
    expect(layer.importedVector.geojson).toBe(fc); // markRaw 不复制对象
  });
});
