// @vitest-environment jsdom
/**
 * 条带化带序方向回归（2026-08-24 "条带样乱数据"修复）。
 *
 * 背景：addBandedImageSources 自 CSP 修复后首次真正渲染，暴露带序颠倒——
 * 图像自顶向下 = 自北向南（PNG row0=北），第 0 带（最北内容）此前被贴到
 * 最南带（lat0 = s + span*i/N），整图南北颠倒 + 逐带错位 = 条带样乱数据。
 *
 * 修复：lat1 = n - span*i/N（带上缘/北），lat0 = n - span*(i+1)/N（带下缘/南）。
 * 本测试断言：第 0 带的 coordinates 上缘 = bounds 北缘 n；末带上缘 > s 且
 * 下缘 = s；各带自北向南依序不重叠。
 */
import { describe, it, expect, vi } from "vitest";
import { addBandedImageSources } from "@/components/map/overlay-image-bands";

type AnyMap = Record<string, unknown>;

function makeMockMap() {
  const added: Array<{ id: string; spec: AnyMap }> = [];
  const layers = new Map<string, AnyMap>();
  const map = {
    getStyle: () => ({
      layers: [...layers.values()],
      sources: Object.fromEntries(added.map((a) => [a.id, a.spec])),
    }),
    getLayer: (id: string) => layers.get(id) ?? null,
    getSource: (id: string) => added.find((a) => a.id === id)?.spec ?? null,
    addLayer: (spec: AnyMap, before?: string) => {
      layers.set(String(spec.id), spec);
    },
    removeLayer: () => {},
    addSource: (id: string, spec: AnyMap) => {
      added.push({ id, spec });
    },
    removeSource: () => {},
    setLayoutProperty: () => {},
    setPaintProperty: () => {},
  };
  return { map, added };
}

/** stub Image + canvas 2d context + toBlob（jsdom 无 canvas 解码） */
function stubDom(naturalW: number, naturalH: number) {
  class FakeImage {
    crossOrigin = "";
    src = "";
    naturalWidth = naturalW;
    naturalHeight = naturalH;
    onload: (() => void) | null = null;
    constructor() {
      queueMicrotask(() => this.onload?.());
    }
  }
  const OrigImage = globalThis.Image;
  vi.stubGlobal("Image", FakeImage);

  // jsdom canvas.getContext('2d') 为 null：stub createElement 返回 fake canvas
  const origCreate = document.createElement.bind(document);
  const fakeCtx = { drawImage: () => {} };
  (document as unknown as { createElement: typeof document.createElement }).createElement =
    (tagName: string) => {
      if (String(tagName).toLowerCase() === "canvas") {
        const canvas = {
          tagName: "CANVAS",
          width: 0,
          height: 0,
          getContext: () => fakeCtx,
          toBlob: (cb: BlobCallback | null) => {
            cb?.(new Blob(["x"], { type: "image/png" }));
          },
        };
        return canvas as unknown as HTMLCanvasElement;
      }
      return origCreate(tagName);
    };

  const origUrl = URL.createObjectURL;
  URL.createObjectURL = () => "blob:fake-band-url";
  return () => {
    vi.stubGlobal("Image", OrigImage);
    document.createElement = origCreate;
    URL.createObjectURL = origUrl;
  };
}

describe("addBandedImageSources 带序方向（北带贴北）", () => {
  it("第 0 带上缘 = bounds 北缘 n，末带下缘 = 南缘 s，各带自北向南不重叠", async () => {
    const restore = stubDom(256, 176); // 等经纬中国区 176 行
    try {
      const { map, added } = makeMockMap();
      // 主 layer 占位（条带插它之前）
      (map as AnyMap).getLayer = (id: string) => ({ id } as AnyMap);
      const n = 59,
        s = 15,
        w = 73,
        e = 137;
      const created = await addBandedImageSources(
        map as never,
        "overlay-src-x",
        "overlay-raster-x",
        "http://x/img.png",
        [w, s, e, n],
        { opacity: 0.8 },
      );
      expect(created).toBeGreaterThan(0);
      expect(added.length).toBe(created);

      const coords = added.map(
        (a) => (a.spec as { coordinates: [number, number][] }).coordinates,
      );
      // 带 0：上缘（coordinates[0] 的 lat）= n（最北）
      expect(coords[0][0][1]).toBeCloseTo(n, 6);
      // 末带：下缘（coordinates[2] 的 lat）= s（最南）
      expect(coords[coords.length - 1][2][1]).toBeCloseTo(s, 6);
      // 各带自北向南依序：band i 的下缘 = band i+1 的上缘
      for (let i = 0; i + 1 < coords.length; i++) {
        expect(coords[i][2][1]).toBeCloseTo(coords[i + 1][0][1], 6);
        expect(coords[i][0][1]).toBeGreaterThan(coords[i][2][1]); // 带内上>下
      }
      // 经度：所有带左右缘一致
      for (const c of coords) {
        expect(c[0][0]).toBeCloseTo(w, 6);
        expect(c[1][0]).toBeCloseTo(e, 6);
      }
    } finally {
      restore();
    }
  });
});
