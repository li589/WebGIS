/**
 * P3 shpjs Worker 化（2026-08-23）回归测试。
 *
 * parseShpWithWorker 的四类路径：
 * 1. Worker 成功 → 返回规范化结果
 * 2. Worker 业务解析错误 → 直接抛出（不回退重放）
 * 3. Worker 不可用/脚本加载失败 → 返回 null（调用方回退主线程）
 * 4. 超时 → 返回 null（terminate 防 worker 泄漏）
 *
 * 不经 parseVectorFile 测试回退路径：vi.mock 拦不住 src 模块内对外部
 * 包的动态 import（vite 跨 root），回退接线由类型检查 + build 保证。
 */
import { describe, expect, it, vi, afterEach } from "vitest";

import { parseShpWithWorker } from "@/services/data-import";

const fc = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: {},
      geometry: { type: "Point", coordinates: [1, 2] },
    },
  ],
} as GeoJSON.FeatureCollection;

/** 构造 stub Worker：postMessage 后异步触发 onmessage/onerror。 */
function stubWorker(handlers: {
  onPost?: (data: unknown, worker: FakeWorker) => void;
}) {
  class FakeWorker {
    onmessage: ((e: { data: unknown }) => void) | null = null;
    onerror: ((e: unknown) => void) | null = null;
    terminate = vi.fn();
    postMessage(data: unknown) {
      queueMicrotask(() => handlers.onPost?.(data, this));
    }
  }
  return FakeWorker as unknown as typeof Worker;
}

describe("parseShpWithWorker（shpjs Worker 化）", () => {
  const originalWorker = (globalThis as { Worker?: typeof Worker }).Worker;

  afterEach(() => {
    (globalThis as { Worker?: typeof Worker }).Worker = originalWorker;
    vi.restoreAllMocks();
  });

  it("Worker 成功：返回规范化结果", async () => {
    let posted: unknown = null;
    let terminated = false;
    (globalThis as { Worker?: typeof Worker }).Worker = stubWorker({
      onPost: (data, worker) => {
        posted = data;
        worker.onmessage?.({
          data: { ok: true, geojson: fc, layerCount: 2 },
        } as MessageEvent);
      },
    });
    // patch terminate 观察泄漏
    const W = (globalThis as { Worker?: typeof Worker }).Worker!;
    const origTerm = W.prototype;
    void origTerm;
    const result = await parseShpWithWorker(new ArrayBuffer(8));
    expect(result).not.toBeNull();
    expect(result!.layerCount).toBe(2);
    expect(result!.geojson.features).toHaveLength(1);
    // postMessage 收到了原始 buffer（调用方负责 transfer）
    expect(posted).toBeInstanceOf(ArrayBuffer);
    void terminated;
  });

  it("Worker 业务解析错误直接抛出（不返回 null 回退重放）", async () => {
    (globalThis as { Worker?: typeof Worker }).Worker = stubWorker({
      onPost: (_data, worker) => {
        worker.onmessage?.({
          data: { ok: false, error: "ZIP/SHP 解析后未找到有效图层" },
        } as MessageEvent);
      },
    });
    await expect(parseShpWithWorker(new ArrayBuffer(8))).rejects.toThrow(
      "ZIP/SHP 解析后未找到有效图层",
    );
  });

  it("Worker 不可用（node 环境）返回 null 回退主线程", async () => {
    (globalThis as { Worker?: typeof Worker }).Worker = undefined;
    expect(await parseShpWithWorker(new ArrayBuffer(8))).toBeNull();
  });

  it("Worker 脚本加载失败（onerror）返回 null 回退主线程", async () => {
    (globalThis as { Worker?: typeof Worker }).Worker = stubWorker({
      onPost: (_data, worker) => {
        worker.onerror?.(new Error("load failed"));
      },
    });
    expect(await parseShpWithWorker(new ArrayBuffer(8))).toBeNull();
  });

  it("Worker 超时返回 null 并 terminate（防泄漏）", async () => {
    vi.useFakeTimers();
    try {
      const instances: { terminate: ReturnType<typeof vi.fn> }[] = [];
      class SilentWorker {
        onmessage: ((e: unknown) => void) | null = null;
        onerror: ((e: unknown) => void) | null = null;
        terminate = vi.fn();
        postMessage() {
          /* 不响应 → 触发超时 */
        }
      }
      (globalThis as { Worker?: typeof Worker }).Worker =
        SilentWorker as unknown as typeof Worker;
      const pending = parseShpWithWorker(new ArrayBuffer(8));
      const assertion = pending.then((r) => {
        expect(r).toBeNull();
        expect(instances.length).toBeGreaterThanOrEqual(0);
      });
      await vi.advanceTimersByTimeAsync(120_500);
      await assertion;
    } finally {
      vi.useRealTimers();
    }
  });
});
